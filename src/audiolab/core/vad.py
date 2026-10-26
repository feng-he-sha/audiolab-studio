"""Voice activity detection with Silero VAD (ONNX preferred, JIT fallback).

Silero is loaded lazily so importing this module never initialises torch/CUDA.
If neither ONNX nor JIT weights are usable the module degrades to an
energy + spectral-flatness heuristic and reports a warning, which keeps the
rest of the pipeline running on machines without the model.

Singing is frequently missed by speech-trained VADs, so :func:`vocal_mask`
additionally ORs in a vocal-stem energy gate (RMS above the noise floor + 6 dB
and above -40 dBFS).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from audiolab import config
from audiolab.core.fusion import frame_rms_db, mask_from_segments

__all__ = [
    "speech_segments",
    "vocal_mask",
    "silero_available",
    "silero_model_path",
    "clear_cache",
    "SAMPLE_RATE",
]

SAMPLE_RATE = 16000
_MODEL_CACHE: dict[str, Any] = {}
_LAST_BACKEND: dict[str, str] = {"backend": "unknown"}


# ---------------------------------------------------------------------------
# Model discovery / loading
# ---------------------------------------------------------------------------

def silero_model_path(model_path: str | Path | None = None) -> Path | None:
    """Return the ONNX VAD path when it exists on disk."""
    candidates: list[Path] = []
    if model_path:
        candidates.append(Path(model_path))
    try:
        candidates.append(Path(config.models_dir()) / "silero" / "silero_vad.onnx")
    except Exception:
        pass
    candidates.append(Path(config.MODELS) / "silero" / "silero_vad.onnx")
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 1024:
            return candidate
    return None


def silero_available(model_path: str | Path | None = None) -> bool:
    """Best-effort check that a usable Silero implementation is importable."""
    try:
        import silero_vad  # noqa: F401
    except Exception:
        return False
    return True


def clear_cache() -> None:
    """Drop cached VAD models (tests / device changes)."""
    _MODEL_CACHE.clear()


def _resolve_device(device: str) -> str:
    requested = (device or "cpu").lower()
    if requested != "cuda":
        return "cpu"
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _load_onnx(path: Path, device: str) -> Any:
    """Load the ONNX VAD wrapper, tolerating small API differences."""
    import onnxruntime  # noqa: F401  (required by the ONNX wrapper)

    try:
        from silero_vad.utils_vad import OnnxWrapper

        try:
            return OnnxWrapper(str(path), force_onnx_cpu=(device != "cuda"))
        except TypeError:
            return OnnxWrapper(str(path))
    except Exception:
        pass
    from silero_vad import load_silero_vad

    for kwargs in (
        {"onnx": True, "model_path": str(path)},
        {"onnx": True},
    ):
        try:
            return load_silero_vad(**kwargs)
        except TypeError:
            continue
    raise RuntimeError("无法加载 Silero ONNX 模型")


def _load_jit(device: str) -> Any:
    try:
        from silero_vad import load_silero_vad

        model = load_silero_vad(onnx=False)
    except Exception:
        import torch

        model, _utils = torch.hub.load(
            "snakers4/silero-vad", "silero_vad", trust_repo=True, verbose=False
        )
    try:
        model.to(device)
    except Exception:
        pass
    return model


def _load_silero(model_path: str | Path | None = None, device: str = "cpu") -> tuple[Any, str]:
    """Return ``(model, backend)`` where backend is ``onnx`` or ``jit``."""
    device = _resolve_device(device)
    onnx_path = silero_model_path(model_path)
    key = f"{onnx_path if onnx_path else 'jit'}|{device}"
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key], ("onnx" if onnx_path else "jit")

    errors: list[str] = []
    if onnx_path is not None:
        try:
            model = _load_onnx(onnx_path, device)
            _MODEL_CACHE[key] = model
            return model, "onnx"
        except Exception as exc:  # pragma: no cover - depends on local install
            errors.append(f"ONNX: {exc}")
    try:
        model = _load_jit(device)
        _MODEL_CACHE[key] = model
        return model, "jit"
    except Exception as exc:  # pragma: no cover - depends on local install
        errors.append(f"JIT: {exc}")
    raise RuntimeError("；".join(errors) or "Silero VAD 不可用")


# ---------------------------------------------------------------------------
# Probability / segmentation core
# ---------------------------------------------------------------------------

def _frame_probs(wav: np.ndarray, sr: int, model: Any) -> np.ndarray:
    """Run the VAD sequentially and return one probability per 32 ms window."""
    import torch

    window = 512 if int(sr) == 16000 else 256
    n = int(wav.size) // window
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    chunks = np.ascontiguousarray(wav[: n * window], dtype=np.float32).reshape(n, window)
    try:
        model.reset_states()
    except Exception:
        pass
    probs = np.zeros(n, dtype=np.float32)
    with torch.no_grad():
        for i in range(n):
            tensor = torch.from_numpy(chunks[i].copy())
            out = model(tensor, int(sr))
            if hasattr(out, "item"):
                probs[i] = float(out.item())
            else:  # pragma: no cover - defensive
                probs[i] = float(np.asarray(out).reshape(-1)[0])
    return probs


def _smooth_probs(probs: np.ndarray, size: int = 3) -> np.ndarray:
    if probs.size < 3 or size < 2:
        return probs
    if size % 2 == 0:
        size += 1
    pad = size // 2
    padded = np.pad(probs, pad, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, size)
    return np.median(windows, axis=-1).astype(np.float32)


def _mask_from_probs(probs: np.ndarray, frame_hop: float, total: float, threshold: float) -> np.ndarray:
    """Hysteresis-free frame mask from probabilities (threshold only)."""
    if probs.size == 0:
        return np.zeros(0, dtype=bool)
    return probs >= float(threshold)


def _segments_from_mask(
    active: np.ndarray,
    probs: np.ndarray,
    frame_hop: float,
    total: float,
    min_speech_ms: float,
    min_silence_ms: float,
    pad_ms: float,
) -> list[tuple[float, float, float]]:
    """Apply min speech/silence/padding rules to a boolean frame mask."""
    if active.size == 0:
        return []
    min_speech_frames = max(1, int(round((min_speech_ms / 1000.0) / frame_hop)))
    min_silence_frames = max(1, int(round((min_silence_ms / 1000.0) / frame_hop)))
    pad_frames = max(0, int(round((pad_ms / 1000.0) / frame_hop)))

    change = np.flatnonzero(np.diff(active.astype(np.int8)) != 0) + 1
    bounds = [0, *change.tolist(), int(active.size)]
    runs = [
        [bounds[i], bounds[i + 1]]
        for i in range(len(bounds) - 1)
        if active[bounds[i]]
    ]
    runs = [run for run in runs if run[1] - run[0] >= min_speech_frames]
    if not runs:
        return []

    merged: list[list[int]] = []
    for start, end in runs:
        if merged and start - merged[-1][1] < min_silence_frames:
            merged[-1][1] = end
        else:
            merged.append([start, end])

    segments: list[tuple[float, float, float]] = []
    for start, end in merged:
        start = max(0, start - pad_frames)
        end = min(int(active.size), end + pad_frames)
        if end <= start:
            continue
        confidence = float(np.mean(probs[start:end])) if probs.size else 0.0
        confidence = min(0.99, max(0.05, confidence))
        segments.append((round(start * frame_hop, 3), round(min(total, end * frame_hop), 3), round(confidence, 3)))

    # Merge overlaps introduced by padding.
    if len(segments) > 1:
        combined: list[tuple[float, float, float]] = [segments[0]]
        for start, stop, conf in segments[1:]:
            prev = combined[-1]
            if start <= prev[1] + 1e-6:
                combined[-1] = (prev[0], max(prev[1], stop), round(max(prev[2], conf), 3))
            else:
                combined.append((start, stop, conf))
        segments = combined
    return segments


def _energy_probs(wav: np.ndarray, sr: int, hop: float) -> np.ndarray:
    """Fallback voice-likelihood from energy + spectral flatness."""
    from audiolab.core.fusion import _frame_flatness  # local import: private helper

    rms_db = frame_rms_db(wav, sr, hop)
    if rms_db.size == 0:
        return rms_db
    try:
        flatness = _frame_flatness(np.asarray(wav, dtype=np.float32), sr, hop)
        flatness = np.resize(flatness, rms_db.size)
    except Exception:
        flatness = np.full(rms_db.size, 0.2, dtype=np.float32)
    floor = float(np.percentile(rms_db, 15))
    gate = max(floor + 6.0, -40.0)
    energy = np.clip((rms_db - (gate - 6.0)) / 12.0, 0.0, 1.0)
    tonal = np.clip(1.0 - flatness * 2.0, 0.0, 1.0)
    # Speech is broadband: prefer moderate flatness over pure tones.
    speechiness = 0.65 + 0.35 * (1.0 - tonal)
    return (energy * speechiness).astype(np.float32)


def _to_mono16k(wav: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    arr = np.asarray(wav, dtype=np.float32).ravel()
    sr = int(sr) if sr else SAMPLE_RATE
    if sr not in (8000, 16000):
        from audiolab.core.media import resample

        arr = resample(arr, sr, SAMPLE_RATE)
        sr = SAMPLE_RATE
    return np.ascontiguousarray(arr, dtype=np.float32), sr


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speech_segments(
    wav: np.ndarray,
    sr: int = SAMPLE_RATE,
    model_path: str | Path | None = None,
    device: str = "cpu",
    threshold: float = 0.5,
    min_speech_ms: float = 250,
    min_silence_ms: float = 200,
    pad_ms: float = 100,
    warnings: list[str] | None = None,
) -> list[tuple[float, float, float]]:
    """Detect speech/singing regions.

    Returns ``[(start, stop, confidence), ...]`` in seconds.  Falls back to an
    energy heuristic when Silero cannot be loaded (a message is appended to
    ``warnings`` when provided).
    """
    arr, sr = _to_mono16k(np.asarray(wav, dtype=np.float32), sr)
    total = arr.size / float(sr) if sr else 0.0
    if total <= 0:
        return []
    hop = 512.0 / float(sr)
    try:
        model, backend = _load_silero(model_path, device)
        probs = _frame_probs(arr, sr, model)
        probs = _smooth_probs(probs, 3)
        _LAST_BACKEND["backend"] = backend
        active = _mask_from_probs(probs, hop, total, threshold)
        return _segments_from_mask(active, probs, hop, total, min_speech_ms, min_silence_ms, pad_ms)
    except Exception as exc:
        _LAST_BACKEND["backend"] = "energy"
        if warnings is not None:
            warnings.append(f"Silero VAD 不可用，已使用能量+谱平坦度回退（{exc}）")
        probs = _energy_probs(arr, sr, hop)
        probs = _smooth_probs(probs, 3)
        active = _mask_from_probs(probs, hop, total, max(0.35, threshold * 0.7))
        return _segments_from_mask(active, probs, hop, total, min_speech_ms, min_silence_ms, pad_ms)


def vocal_mask(
    wav: np.ndarray,
    sr: int,
    duration: float,
    hop: float = 0.02,
    segments: Sequence[tuple[float, float, float]] | None = None,
    warnings: list[str] | None = None,
) -> np.ndarray:
    """Frame-level 0/1 vocal mask (``ceil(duration / hop)`` frames).

    VAD boundaries come from Silero when available; a vocal-stem energy gate is
    ORed in afterwards so singing that the speech model misses still counts.
    """
    hop = float(hop) if hop and hop > 0 else 0.02
    duration = max(0.0, float(duration or 0.0))
    n_frames = max(0, int(math.ceil(duration / hop))) if duration > 0 else 0
    if n_frames == 0:
        return np.zeros(0, dtype=np.int8)

    arr = np.asarray(wav, dtype=np.float32).ravel()
    if segments is None:
        segments = speech_segments(arr, sr, warnings=warnings)
    mask = mask_from_segments(segments, duration, hop)

    # Singing supplement: loud vocal-stem frames the VAD did not flag.
    if arr.size:
        rms_db = frame_rms_db(arr, int(sr), hop)
        rms_db = np.resize(rms_db, n_frames)
        floor = float(np.percentile(rms_db, 15))
        gate = max(floor + 6.0, -40.0)
        mask = np.maximum(mask, (rms_db > gate).astype(np.int8))
    return mask.astype(np.int8)
