"""Evidence fusion: turn 20 ms vocal/music masks into a labelled :class:`Timeline`.

This module is deliberately pure: numpy only, no I/O and no heavy model imports,
so it can be unit-tested and reused by ``pipeline.refuse`` when the UI changes
fusion thresholds without re-running the models.

Frame label rules (per 20 ms frame)::

    vocal & music -> vocals+music
    vocal only    -> vocals
    music only    -> music
    neither       -> other

After the raw labels are built the evidence masks are median-smoothed, micro gaps
are merged, tiny segment fragments are absorbed, and boundaries are snapped to
the frame grid.  AST window probabilities are advisory: they can promote
weak-energy music and demote frames the classifier is confident are not music.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np

from audiolab.core.schemas import Segment, Timeline

__all__ = [
    "LABELS",
    "LABEL_COLORS",
    "mask_from_segments",
    "music_mask_from_energy",
    "frame_rms_db",
    "fuse",
]

LABELS: tuple[str, ...] = ("other", "vocals", "music", "vocals+music")
_LABEL_CODES = {name: idx for idx, name in enumerate(LABELS)}
LABEL_COLORS = {
    "vocals": "#60a5fa",
    "music": "#34d399",
    "vocals+music": "#a78bfa",
    "other": "#94a3b8",
}
_ASCII_KEYS = ("Music", "Speech", "Singing")


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------

def _as_float_array(values: Any) -> np.ndarray:
    return np.asarray(values if values is not None else [], dtype=np.float32).ravel()


def _fit_frames(values: Any, n_frames: int) -> np.ndarray:
    """Nearest-neighbour resample/pad a 1-D mask or probability array."""
    arr = _as_float_array(values)
    if n_frames <= 0:
        return np.zeros(0, dtype=np.float32)
    if arr.size == n_frames:
        return arr.copy()
    if arr.size == 0:
        return np.zeros(n_frames, dtype=np.float32)
    idx = (np.arange(n_frames, dtype=np.int64) * arr.size // n_frames).clip(0, arr.size - 1)
    return arr[idx].astype(np.float32, copy=True)


def _median_filter(values: np.ndarray, size: int) -> np.ndarray:
    """Median filter with edge padding (categorical/boolean friendly)."""
    if size <= 1 or values.size == 0:
        return values
    if size % 2 == 0:
        size += 1
    if values.size < 3 or size >= values.size * 2 + 1:
        return values
    pad = size // 2
    padded = np.pad(values, pad, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, size)
    return np.median(windows, axis=-1)


def _runs(codes: np.ndarray) -> list[list[int]]:
    """Return ``[[code, start_frame, end_frame), ...]`` runs."""
    if codes.size == 0:
        return []
    change = np.flatnonzero(np.diff(codes) != 0) + 1
    boundaries = [0, *change.tolist(), codes.size]
    return [[int(codes[boundaries[i]]), boundaries[i], boundaries[i + 1]] for i in range(len(boundaries) - 1)]


def _merge_runs(runs: list[list[int]]) -> list[list[int]]:
    if not runs:
        return []
    merged = [list(runs[0])]
    for code, start, end in runs[1:]:
        if merged[-1][0] == code:
            merged[-1][2] = end
        else:
            merged.append([code, start, end])
    return merged


# ---------------------------------------------------------------------------
# Mask builders
# ---------------------------------------------------------------------------

def mask_from_segments(
    segments: Iterable[Any] | None,
    duration: float,
    hop: float = 0.02,
) -> np.ndarray:
    """Rasterise ``[(start, stop, confidence), ...]`` (or dicts) into a 0/1 mask."""
    hop = float(hop) if hop and hop > 0 else 0.02
    n_frames = max(0, int(math.ceil(max(0.0, float(duration)) / hop)))
    mask = np.zeros(n_frames, dtype=np.int8)
    if not segments or n_frames == 0:
        return mask
    for segment in segments:
        if isinstance(segment, dict):
            start = float(segment.get("start", 0.0))
            stop = float(segment.get("stop", segment.get("end", 0.0)))
        else:
            try:
                start, stop = float(segment[0]), float(segment[1])
            except (TypeError, IndexError, ValueError):
                continue
        i0 = max(0, min(n_frames, int(math.floor(start / hop))))
        i1 = max(0, min(n_frames, int(math.ceil(stop / hop))))
        if i1 > i0:
            mask[i0:i1] = 1
    return mask


def _frame_rms_db(wav: np.ndarray, sr: int, hop: float = 0.02) -> np.ndarray:
    """Per-frame RMS in dBFS (frames centred on hop grid)."""
    hop_n = max(1, int(round(float(hop) * int(sr))))
    win_n = max(hop_n * 2, 256)
    n = int(wav.size)
    n_frames = max(0, int(math.ceil(n / hop_n))) if n else 0
    if n_frames == 0:
        return np.zeros(0, dtype=np.float32)
    half = win_n // 2
    padded = np.pad(np.asarray(wav, dtype=np.float32), (half, win_n + hop_n), mode="constant")
    rms_db = np.full(n_frames, -120.0, dtype=np.float32)
    window = np.hanning(win_n).astype(np.float32)
    block = 4096
    for start in range(0, n_frames, block):
        stop = min(n_frames, start + block)
        offsets = np.arange(start, stop, dtype=np.int64) * hop_n
        frames = padded[offsets[:, None] + np.arange(win_n, dtype=np.int64)[None, :]]
        frames = frames * window
        rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
        rms_db[start:stop] = 20.0 * np.log10(np.maximum(rms, 1e-7))
    return rms_db


def frame_rms_db(wav: np.ndarray, sr: int, hop: float = 0.02) -> np.ndarray:
    """Public wrapper around the frame RMS helper."""
    return _frame_rms_db(np.asarray(wav, dtype=np.float32), sr, hop)


def _harmonic_ratio_frames(wav: np.ndarray, sr: int, hop: float = 0.02, block_seconds: float = 60.0) -> np.ndarray:
    """Estimate per-frame harmonic ratio with block-wise HPSS.

    Falls back to a spectral-flatness proxy when librosa is unavailable.  The
    signal is processed in blocks so that hour-long files stay within memory.
    """
    wav = np.asarray(wav, dtype=np.float32)
    n_frames = max(0, int(math.ceil(wav.size / max(1, int(round(hop * sr))))) if wav.size else 0)
    if n_frames == 0:
        return np.zeros(0, dtype=np.float32)
    block_n = max(1, int(block_seconds * sr))
    out = np.zeros(n_frames, dtype=np.float32)
    hop_n = max(1, int(round(float(hop) * int(sr))))
    try:
        import librosa
    except Exception:  # pragma: no cover - librosa is a hard dependency
        return np.full(n_frames, 0.5, dtype=np.float32)

    n_fft = 2048
    hop_stft = max(64, int(round(hop * sr)))
    pad = n_fft
    for block_start in range(0, wav.size, block_n):
        block_stop = min(wav.size, block_start + block_n + pad)
        chunk = wav[block_start:block_stop]
        if chunk.size < 1024:
            continue
        try:
            harmonic, percussive = librosa.effects.hpss(chunk, n_fft=n_fft, hop_length=hop_stft)
        except Exception:
            flat = _frame_flatness(chunk, sr, hop, block_frames=8192)
            out[: flat.size] = np.maximum(out[: flat.size], 1.0 - flat)
            continue
        total = np.abs(harmonic) + np.abs(percussive)
        frame_i0 = block_start // hop_n
        n_local = int(math.ceil(chunk.size / hop_n))
        idx_end = min(n_frames, frame_i0 + n_local)
        if idx_end <= frame_i0:
            continue
        # Project per-sample energy onto the hop grid.
        frames = np.arange(idx_end - frame_i0, dtype=np.int64) * hop_n
        sample_idx = block_start + frames + n_fft // 2
        sample_idx = np.clip(sample_idx, 0, max(0, chunk.size - 1))
        # Use a short window around each frame centre for the ratio.
        half = max(1, hop_n)
        lo = np.clip(sample_idx - half, 0, chunk.size - 1)
        hi = np.clip(sample_idx + half, 1, chunk.size)
        ratios = np.empty(idx_end - frame_i0, dtype=np.float32)
        for i, (a, b) in enumerate(zip(lo.tolist(), hi.tolist())):
            h = float(np.mean(np.abs(harmonic[a:b]))) if b > a else 0.0
            p = float(np.mean(np.abs(percussive[a:b]))) if b > a else 0.0
            ratios[i] = h / (h + p + 1e-6)
        out[frame_i0:idx_end] = ratios[: idx_end - frame_i0]
    return out


def _frame_flatness(wav: np.ndarray, sr: int, hop: float, block_frames: int = 4096) -> np.ndarray:
    """Per-frame spectral flatness (0 = tonal, 1 = noisy)."""
    hop_n = max(1, int(round(float(hop) * int(sr))))
    win_n = max(hop_n * 2, 512)
    n_frames = max(0, int(math.ceil(wav.size / hop_n))) if wav.size else 0
    flat = np.zeros(n_frames, dtype=np.float32)
    if n_frames == 0:
        return flat
    half = win_n // 2
    padded = np.pad(np.asarray(wav, dtype=np.float32), (half, win_n + hop_n), mode="constant")
    window = np.hanning(win_n).astype(np.float32)
    for start in range(0, n_frames, block_frames):
        stop = min(n_frames, start + block_frames)
        offsets = np.arange(start, stop, dtype=np.int64) * hop_n
        frames = padded[offsets[:, None] + np.arange(win_n, dtype=np.int64)[None, :]] * window
        spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2 + 1e-10
        log_mean = np.mean(np.log(spec), axis=1)
        mean = np.mean(spec, axis=1)
        flat[start:stop] = np.exp(log_mean) / (mean + 1e-10)
    return flat


def _ast_prob(windows: Sequence[dict[str, Any]] | None, duration: float, hop: float, keys: Sequence[str]) -> np.ndarray | None:
    """Rasterise AST probabilities for the first matching key to the frame grid."""
    if not windows:
        return None
    hop = float(hop) if hop and hop > 0 else 0.02
    n_frames = max(0, int(math.ceil(max(0.0, float(duration)) / hop)))
    if n_frames == 0:
        return None
    acc = np.zeros(n_frames, dtype=np.float32)
    seen = np.zeros(n_frames, dtype=bool)
    for window in windows:
        if not isinstance(window, dict):
            continue
        probs = window.get("probs") if isinstance(window.get("probs"), dict) else window
        value = None
        for key in keys:
            if key in probs:
                try:
                    value = float(probs[key])
                except (TypeError, ValueError):
                    value = None
                if value is not None:
                    break
        if value is None:
            continue
        start = float(window.get("start", 0.0))
        stop = float(window.get("stop", start + 10.0))
        i0 = max(0, min(n_frames, int(math.floor(start / hop))))
        i1 = max(0, min(n_frames, int(math.ceil(stop / hop))))
        if i1 <= i0:
            continue
        acc[i0:i1] = np.maximum(acc[i0:i1], value)
        seen[i0:i1] = True
    if not seen.any():
        return None
    # Unknown regions are neutral (0.5) rather than "definitely not music".
    acc[~seen] = 0.5
    return acc


def music_mask_from_energy(
    instrumental_wav: Any,
    sr: int,
    duration: float,
    hop: float = 0.02,
    ast_windows: Sequence[dict[str, Any]] | None = None,
) -> np.ndarray:
    """Adaptive energy + harmonic-ratio (+AST) music presence mask.

    ``instrumental_wav`` is the separated instrumental track (numpy array; a
    path is also accepted for convenience).  A frame counts as music when its
    RMS is at least 6 dB above the track noise floor and above -40 dBFS *and*
    the content is predominantly harmonic.  AST ``Music`` probability can fill
    low-energy holes, and confident speech windows can suppress speech-only
    babbling that leaked into the instrumental stem.
    """
    if isinstance(instrumental_wav, (str, bytes)) or hasattr(instrumental_wav, "__fspath__"):
        from audiolab.core import media

        wav = media.decode_mono(instrumental_wav, sr=sr)
    else:
        wav = np.asarray(instrumental_wav, dtype=np.float32).ravel()

    hop = float(hop) if hop and hop > 0 else 0.02
    n_frames = max(0, int(math.ceil(max(0.0, float(duration)) / hop)))
    if n_frames == 0 or wav.size == 0:
        return np.zeros(n_frames, dtype=np.int8)

    rms_db = _fit_frames(_frame_rms_db(wav, sr, hop), n_frames)
    harm = _fit_frames(_harmonic_ratio_frames(wav, sr, hop), n_frames)
    floor = float(np.percentile(rms_db, 15)) if rms_db.size else -120.0
    gate = max(floor + 6.0, -40.0)
    mask = (rms_db > gate) & (harm > 0.33)

    ast_music = _ast_prob(ast_windows, duration, hop, ("Music", "Music (score)"))
    if ast_music is not None:
        ast_speech = _ast_prob(ast_windows, duration, hop, ("Speech",))
        ast_singing = _ast_prob(ast_windows, duration, hop, ("Singing",))
        weak = rms_db > (gate - 6.0)
        mask |= (ast_music >= 0.5) & weak
        if ast_speech is not None:
            speech_like = ast_speech >= 0.6
            if ast_singing is not None:
                speech_like &= ast_singing < 0.25
            mask &= ~(speech_like & (ast_music < 0.25))
    return mask.astype(np.int8)


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def _ast_tags(windows: Sequence[dict[str, Any]] | None, start: float, stop: float, limit: int = 4) -> dict[str, float]:
    """Average AST probabilities over the windows overlapping a segment."""
    if not windows:
        return {}
    acc: dict[str, float] = {}
    weight = 0.0
    for window in windows:
        if not isinstance(window, dict):
            continue
        w_start = float(window.get("start", 0.0))
        w_stop = float(window.get("stop", w_start + 10.0))
        overlap = min(stop, w_stop) - max(start, w_start)
        if overlap <= 0:
            continue
        probs = window.get("probs") if isinstance(window.get("probs"), dict) else window
        for key, value in probs.items():
            if not isinstance(key, str):
                continue
            try:
                acc[key] = acc.get(key, 0.0) + float(value) * overlap
            except (TypeError, ValueError):
                continue
        weight += overlap
    if weight <= 0 or not acc:
        return {}
    averaged = {key: value / weight for key, value in acc.items() if value / weight >= 0.05}
    top = sorted(averaged.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {key: round(value, 3) for key, value in top}


def _labels_to_codes(vocal: np.ndarray, music: np.ndarray) -> np.ndarray:
    v = vocal > 0.5
    m = music > 0.5
    codes = np.zeros(v.size, dtype=np.int8)
    codes[v] = _LABEL_CODES["vocals"]
    codes[m] = _LABEL_CODES["music"]
    codes[v & m] = _LABEL_CODES["vocals+music"]
    return codes


def _confidence(
    label: str,
    v_density: float,
    m_density: float,
    ast_music: np.ndarray | None,
    ast_speech: np.ndarray | None,
    ast_singing: np.ndarray | None,
    i0: int,
    i1: int,
) -> float:
    def mean(arr: np.ndarray | None) -> float | None:
        if arr is None or i1 <= i0:
            return None
        return float(np.mean(arr[i0:i1]))

    music_p = mean(ast_music)
    speech_p = mean(ast_speech)
    singing_p = mean(ast_singing)
    vocal_p = None
    candidates = [p for p in (speech_p, singing_p) if p is not None]
    if candidates:
        vocal_p = max(candidates)

    if label == "vocals":
        conf = 0.55 + 0.45 * v_density
        if vocal_p is not None:
            conf = 0.5 * conf + 0.5 * vocal_p
    elif label == "music":
        conf = 0.45 + 0.55 * m_density
        if music_p is not None:
            conf = 0.5 * conf + 0.5 * music_p
    elif label == "vocals+music":
        conf = 0.7 * min(1.0, v_density + m_density) / 2.0 + 0.3
        if vocal_p is not None or music_p is not None:
            mixed_ast = np.mean([p for p in (vocal_p, music_p) if p is not None])
            conf = 0.55 * conf + 0.45 * mixed_ast
    else:
        conf = 0.55 - 0.25 * max(v_density, m_density)
        if vocal_p is not None or music_p is not None:
            conf = 0.6 * conf + 0.4 * (1.0 - max([p for p in (vocal_p, music_p) if p is not None]))
    return round(float(min(0.99, max(0.05, conf))), 3)


def fuse(
    duration: float,
    vocal_mask: Any,
    music_mask: Any,
    ast_windows: Sequence[dict[str, Any]] | None = None,
    orig_rms_db: Any = None,
    hop: float = 0.02,
    smooth_frames: int = 5,
    min_segment: float = 0.3,
    min_music: float = 0.5,
    min_gap: float = 0.25,
) -> Timeline:
    """Fuse vocal/music evidence into a labelled timeline.

    Parameters mirror the tunables exposed in the UI so ``pipeline.refuse`` can
    re-run only this function.  ``orig_rms_db`` may be a scalar or a per-frame
    array; frames quieter than -55 dBFS are forced to ``other``.
    """
    hop = float(hop) if hop and hop > 0 else 0.02
    duration = max(0.0, float(duration or 0.0))
    n_frames = max(0, int(math.ceil(duration / hop))) if duration > 0 else 0
    warnings: list[str] = []
    if n_frames == 0:
        return Timeline(duration=0.0, frame_hop=hop, segments=[], summary={}, warnings=["音频时长为 0"])

    vocal = _fit_frames(vocal_mask, n_frames)
    music = _fit_frames(music_mask, n_frames)
    vocal = (vocal > 0.5).astype(np.float32)
    music = (music > 0.5).astype(np.float32)

    # Median smoothing of the evidence (categorical labels are rebuilt after).
    if smooth_frames and smooth_frames > 1:
        vocal = (_median_filter(vocal, int(smooth_frames)) > 0.5).astype(np.float32)
        music = (_median_filter(music, int(smooth_frames)) > 0.5).astype(np.float32)

    # Absolute silence always wins.
    silence_db = -55.0
    if orig_rms_db is not None and np.size(orig_rms_db):
        rms = _fit_frames(orig_rms_db, n_frames)
    else:
        rms = None
    if rms is not None:
        quiet = rms < silence_db
        vocal[quiet] = 0.0
        music[quiet] = 0.0

    # AST advisory pass: promote weak music, demote confident non-music.
    ast_music = _ast_prob(ast_windows, duration, hop, ("Music", "Music (score)"))
    ast_speech = _ast_prob(ast_windows, duration, hop, ("Speech",))
    ast_singing = _ast_prob(ast_windows, duration, hop, ("Singing",))
    if ast_music is not None:
        threshold = max(0.05, float(min_music))
        promote = (ast_music >= threshold) & (music < 0.5)
        if rms is not None:
            promote &= rms > silence_db
        music[promote] = 1.0
        demote = (ast_music < threshold * 0.6) & (music > 0.5)
        if ast_speech is not None:
            demote &= ast_speech > 0.5
        music[demote] = 0.0
    else:
        warnings.append("无 AST 标签证据，音乐判定仅依赖能量与谐波比")

    codes = _labels_to_codes(vocal, music)
    if not vocal.any():
        warnings.append("未检测到人声证据")

    runs = _merge_runs(_runs(codes))

    # 1) Merge micro gaps: short runs take the label of their longer neighbour.
    min_gap = max(0.0, float(min_gap))
    if min_gap > 0 and len(runs) > 1:
        changed = True
        guard = 0
        while changed and guard < 12:
            changed = False
            guard += 1
            merged: list[list[int]] = []
            for pos, run in enumerate(runs):
                code, start, end = run
                if (end - start) * hop < min_gap:
                    left_code = runs[pos - 1][0] if pos > 0 else None
                    right_code = runs[pos + 1][0] if pos + 1 < len(runs) else None
                    if left_code is not None and (right_code is None or left_code == right_code):
                        new_code = left_code
                    elif right_code is not None and left_code is None:
                        new_code = right_code
                    elif left_code is not None and right_code is not None:
                        left_len = runs[pos - 1][2] - runs[pos - 1][1]
                        right_len = runs[pos + 1][2] - runs[pos + 1][1]
                        new_code = left_code if left_len >= right_len else right_code
                    else:
                        new_code = code
                    if new_code != code:
                        changed = True
                        code = new_code
                if merged and merged[-1][0] == code:
                    merged[-1][2] = end
                else:
                    merged.append([code, start, end])
            runs = _merge_runs(merged)

    # 2) Absorb segments shorter than min_segment into the longer neighbour.
    min_segment = max(0.0, float(min_segment))
    if min_segment > 0 and len(runs) > 1:
        guard = 0
        while len(runs) > 1 and guard < 512:
            guard += 1
            idx = min(range(len(runs)), key=lambda i: runs[i][2] - runs[i][1])
            code, start, end = runs[idx]
            if (end - start) * hop >= min_segment:
                break
            if idx == 0:
                runs[1][1] = start
                runs.pop(0)
            elif idx == len(runs) - 1:
                runs[-2][2] = end
                runs.pop()
            else:
                left_len = runs[idx - 1][2] - runs[idx - 1][1]
                right_len = runs[idx + 1][2] - runs[idx + 1][1]
                if left_len >= right_len:
                    runs[idx - 1][2] = end
                else:
                    runs[idx + 1][1] = start
                runs.pop(idx)
            runs = _merge_runs(runs)

    # 3) Build schema segments with confidence + AST tags.
    segments: list[Segment] = []
    for code, start_frame, end_frame in runs:
        start = round(start_frame * hop, 3)
        stop = round(min(duration, end_frame * hop), 3)
        if stop <= start:
            continue
        label = LABELS[int(code)]
        v_density = float(np.mean(vocal[start_frame:end_frame])) if end_frame > start_frame else 0.0
        m_density = float(np.mean(music[start_frame:end_frame])) if end_frame > start_frame else 0.0
        confidence = _confidence(label, v_density, m_density, ast_music, ast_speech, ast_singing, start_frame, end_frame)
        segments.append(
            Segment(
                start=start,
                stop=stop,
                label=label,  # type: ignore[arg-type]
                confidence=confidence,
                tags=_ast_tags(ast_windows, start, stop),
            )
        )
    if segments:
        segments[0].start = 0.0
        segments[-1].stop = round(duration, 3)
    # Keep coverage contiguous and sorted after rounding.
    for i in range(1, len(segments)):
        if segments[i].start < segments[i - 1].stop:
            segments[i].start = segments[i - 1].stop
    segments = [seg for seg in segments if seg.stop > seg.start]

    summary: dict[str, float] = {}
    for segment in segments:
        key = segment.label
        summary[key] = round(summary.get(key, 0.0) + (segment.stop - segment.start), 2)
    summary["total"] = round(sum(summary.values()), 2)
    return Timeline(duration=round(duration, 3), frame_hop=hop, segments=segments, summary=summary, warnings=warnings)
