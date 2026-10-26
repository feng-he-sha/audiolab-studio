"""AudioSet tagging with AST (MIT/ast-finetuned-audioset-10-10-0.4593).

The model is loaded lazily and only when available; any failure returns an empty
list so tagging never blocks analysis.  Probabilities are reduced to the
categories the fusion step cares about (Music / Speech / Singing) plus a handful
of useful sub-labels.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from audiolab import config

__all__ = ["analyze", "available", "MODEL_ID", "clear_cache", "model_dir_has_weights"]

MODEL_ID = "MIT/ast-finetuned-audioset-10-10-0.4593"
_MODEL_CACHE: dict[str, Any] = {}

# Categories exposed to the API / fusion.  ``Music``/``Speech``/``Singing`` are
# aggregates; the rest are individual AudioSet labels kept for display.
_AGGREGATE = {
    "Music": ("Music",),
    "Speech": ("Speech",),
    "Singing": (
        "Singing",
        "Male singing",
        "Female singing",
        "Child singing",
        "Synthetic singing",
    ),
}
_EXTRA_KEYWORDS = (
    "singing",
    "vocal",
    "rapping",
    "humming",
    "whistling",
    "musical instrument",
    "acoustic environment",
    "silence",
)


def _resolve_dir(model_dir: str | Path | None) -> Path:
    if model_dir:
        return Path(model_dir)
    try:
        return Path(config.models_dir()) / "hf"
    except Exception:
        return Path(config.MODELS) / "hf"


def model_dir_has_weights(model_dir: str | Path | None = None) -> bool:
    """True when an AST snapshot already exists under ``model_dir``."""
    root = _resolve_dir(model_dir)
    if not root.exists():
        return False
    direct = root / "config.json"
    if direct.is_file():
        return True
    named = [
        root / "models--MIT--ast-finetuned-audioset-10-10-0.4593",
        root / "ast-finetuned-audioset-10-10-0.4593",
    ]
    if any(path.exists() for path in named):
        return True
    try:
        for child in root.iterdir():
            name = child.name.lower()
            if child.is_dir() and "ast" in name and "audioset" in name:
                return True
    except OSError:
        return False
    return False


def available(model_dir: str | Path | None = None) -> bool:
    """Whether tagging can run without downloading 350 MB of weights."""
    if model_dir_has_weights(model_dir):
        return True
    # Explicit opt-in for online machines / first run.
    return os.environ.get("AUDIOLAB_ALLOW_MODEL_DOWNLOAD", "").strip().lower() in {"1", "true", "yes"}


def clear_cache() -> None:
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


def _load(model_dir: Path, device: str) -> tuple[Any, Any, dict[int, str]]:
    key = f"{model_dir}|{device}"
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    import torch  # local import: never at module import time
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    local_only = model_dir_has_weights(model_dir)
    kwargs: dict[str, Any] = {"cache_dir": str(model_dir)}
    if local_only:
        kwargs["local_files_only"] = True
    # NOTE: HF_ENDPOINT (mirror) is read directly from the environment by
    # huggingface_hub; config.load_settings() already exports it when configured.

    feature_extractor = AutoFeatureExtractor.from_pretrained(MODEL_ID, **kwargs)
    net = AutoModelForAudioClassification.from_pretrained(MODEL_ID, **kwargs)
    net.eval()
    net.to(device if device == "cuda" else "cpu")
    id2label = {int(k): str(v) for k, v in getattr(net.config, "id2label", {}).items()}
    _MODEL_CACHE[key] = (feature_extractor, net, id2label)
    return _MODEL_CACHE[key]


def _resample(wav: np.ndarray, sr: int) -> np.ndarray:
    sr = int(sr) if sr else 16000
    if sr == 16000:
        return np.ascontiguousarray(wav, dtype=np.float32)
    from audiolab.core.media import resample

    return resample(np.asarray(wav, dtype=np.float32), sr, 16000)


def _reduce_probs(probs: np.ndarray, id2label: dict[int, str]) -> dict[str, float]:
    """Reduce full AudioSet probabilities to display/fusion categories."""
    by_label = {id2label.get(i, str(i)).strip().lower(): float(p) for i, p in enumerate(probs)}
    out: dict[str, float] = {}

    for aggregate, names in _AGGREGATE.items():
        value = max((by_label.get(name.lower(), 0.0) for name in names), default=0.0)
        if value > 0.0:
            out[aggregate] = round(value, 4)

    extras: list[tuple[str, float]] = []
    for label, value in by_label.items():
        if value < 0.08:
            continue
        if any(label == name.lower() for names in _AGGREGATE.values() for name in names):
            continue
        if any(keyword in label for keyword in _EXTRA_KEYWORDS):
            extras.append((label, value))
    for label, value in sorted(extras, key=lambda kv: kv[1], reverse=True)[:6]:
        out[label] = round(value, 4)
    return out


def analyze(
    wav: np.ndarray,
    sr: int = 16000,
    model_dir: str | Path | None = None,
    device: str = "cpu",
    window: float = 10.0,
    hop: float = 5.0,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Slide a 10 s AST window over ``wav`` and return tagged windows.

    Result: ``[{"start": float, "stop": float, "probs": {label: prob}}, ...]``.
    Returns ``[]`` (and never raises) when the model or transformers is missing.
    """
    arr = np.asarray(wav, dtype=np.float32).ravel()
    if arr.size == 0:
        return []
    direction = _resolve_dir(model_dir)
    try:
        import torch
    except Exception as exc:
        if warnings is not None:
            warnings.append(f"标签模型不可用（{exc}）")
        return []
    if not available(direction):
        if warnings is not None:
            warnings.append("未找到 AST 标签模型，已跳过标签（可让后端下载到 models/hf）")
        return []

    window = max(2.0, float(window or 10.0))
    hop = max(0.5, float(hop or 5.0))
    sr = int(sr) if sr else 16000
    arr = _resample(arr, sr)
    sr = 16000
    total = arr.size / sr
    win_n = int(round(window * sr))
    hop_n = max(1, int(round(hop * sr)))

    starts: list[int] = list(range(0, max(1, arr.size - win_n + 1), hop_n))
    if not starts:
        starts = [0]
    if arr.size > win_n and (arr.size - win_n) not in starts:
        starts.append(arr.size - win_n)

    try:
        resolved_device = _resolve_device(device)
        feature_extractor, net, id2label = _load(direction, resolved_device)
    except Exception as exc:
        if warnings is not None:
            warnings.append(f"AST 标签模型加载失败，已跳过标签：{exc}")
        return []

    results: list[dict[str, Any]] = []
    batch_size = 4 if resolved_device == "cuda" else 2
    torch_device = resolved_device
    with torch.no_grad():
        for batch_start in range(0, len(starts), batch_size):
            batch_starts = starts[batch_start : batch_start + batch_size]
            chunks = []
            for offset in batch_starts:
                chunk = arr[offset : offset + win_n]
                if chunk.size < win_n:
                    chunk = np.pad(chunk, (0, win_n - chunk.size))
                chunks.append(chunk)
            try:
                inputs = feature_extractor(
                    [c.astype(np.float32) for c in chunks],
                    sampling_rate=sr,
                    return_tensors="pt",
                )
                inputs = {k: v.to(torch_device) for k, v in inputs.items()}
                logits = net(**inputs).logits
                probs = torch.sigmoid(logits).cpu().numpy() if logits.shape[-1] == 527 else torch.softmax(logits, dim=-1).cpu().numpy()
            except Exception as exc:  # pragma: no cover - model specific
                if warnings is not None:
                    warnings.append(f"AST 推理失败，已停止标签：{exc}")
                return results
            for row, offset in zip(probs, batch_starts):
                start = offset / sr
                stop = min(total, (offset + win_n) / sr)
                reduced = _reduce_probs(row, id2label)
                if not reduced:
                    continue
                results.append(
                    {
                        "start": round(float(start), 3),
                        "stop": round(float(stop), 3),
                        "probs": reduced,
                    }
                )
    return results
