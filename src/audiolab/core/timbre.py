"""Vocal timbre analysis: clip extraction, speaker-style embeddings, clustering.

Pipeline: vocal segments -> 1.5-10 s clips (split on internal pauses) -> embeddings
(vendored Resemblyzer-style voice encoder, MFCC fallback) -> agglomerative
clustering (cosine distance) -> perceptual features (F0, centroid, rolloff,
flatness, ZCR, harmonic ratio, RMS) -> Chinese labels / colours / PCA scatter.

The encoder implementation lives in ``audiolab.core.timbre_encoder`` (vendored by
the Lead) and its weights in ``models/colorsplitter/timbre-v1.pt``.  When either
is missing the module falls back to MFCC embeddings and records a warning instead
of failing analysis.  ``backend`` keeps the API-contract values
(``"colorsplitter"`` / ``"mfcc"``) for compatibility with the frontend.
"""

from __future__ import annotations

import math
import logging
import os
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from audiolab import config
from audiolab.core import media
from audiolab.core.schemas import TimbreClip, TimbreCluster, TimbreFeatures, TimbreResult, Timeline

__all__ = ["analyze", "available", "backend_available", "clip_features", "cluster_labels"]

ProgressFn = Callable[[str, float, str], None]

SAMPLE_RATE = 16000
CLIP_MIN_SECONDS = 1.5
CLIP_MAX_SECONDS = 10.0
MAX_CLIPS = int(os.environ.get("AUDIOLAB_TIMBRE_MAX_CLIPS", "80"))
PALETTE = [
    "#60a5fa", "#34d399", "#a78bfa", "#fbbf24", "#f87171", "#38bdf8",
    "#f472b6", "#4ade80", "#fb923c", "#c084fc", "#2dd4bf", "#facc15",
]
VOICE_LABELS = ("vocals", "vocals+music")


def _emit(progress: ProgressFn | None, stage: str, pct: float, message: str) -> None:
    if progress is None:
        return
    try:
        progress(stage, float(pct), message)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Paths / availability
# ---------------------------------------------------------------------------

def _models_root(model_dir: str | Path | None) -> list[Path]:
    roots: list[Path] = []
    if model_dir:
        roots.append(Path(model_dir))
    try:
        roots.append(Path(config.models_dir()))
    except Exception:
        pass
    roots.append(Path(config.MODELS))
    return roots


def _weights_path(model_dir: str | Path | None = None, filename: str = "timbre-v1.pt") -> Path | None:
    candidates: list[Path] = []
    for root in _models_root(model_dir):
        candidates.extend([root / filename, root / "colorsplitter" / filename])
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 1024:
            return candidate
    return None


def backend_available(backend: str = "colorsplitter", model_dir: str | Path | None = None) -> bool:
    """Whether the requested timbre backend can actually run."""
    if (backend or "").lower() == "mfcc":
        try:
            import librosa  # noqa: F401

            return True
        except Exception:
            return False
    if _weights_path(model_dir) is None:
        return False
    try:
        from audiolab.core.timbre_encoder import VoiceEncoder  # noqa: F401,PLC0415
    except Exception:
        return False
    return True


def available(model_dir: str | Path | None = None, backend: str = "colorsplitter") -> bool:
    return backend_available(backend, model_dir)


# ---------------------------------------------------------------------------
# Clip extraction
# ---------------------------------------------------------------------------

def _frame_rms_db(y: np.ndarray, sr: int, hop: float = 0.02) -> np.ndarray:
    from audiolab.core.fusion import frame_rms_db

    return frame_rms_db(y, sr, hop)


def _split_on_pauses(y: np.ndarray, sr: int, hop: float = 0.02, min_pause: float = 0.25) -> list[tuple[int, int]]:
    """Split a mono segment at internal silences; returns sample ranges.

    Short fragments are merged into their neighbour (so a 2 s segment with one
    pause still yields a single 2 s clip) and very long fragments are divided
    into ~8 s pieces.
    """
    if y.size == 0:
        return []
    hop_n = max(1, int(round(hop * sr)))
    min_samples = int(CLIP_MIN_SECONDS * sr)
    rms_db = _frame_rms_db(y, sr, hop)
    if rms_db.size == 0:
        return [(0, int(y.size))]
    floor = float(np.percentile(rms_db, 15))
    gate = max(floor + 8.0, -40.0)
    silent = rms_db < gate
    min_pause_frames = max(1, int(round(min_pause / hop)))

    cuts: list[int] = []
    start = None
    for idx, flag in enumerate(silent.tolist()):
        if flag and start is None:
            start = idx
        elif not flag and start is not None:
            if idx - start >= min_pause_frames:
                cuts.append(int((start + idx) / 2))
            start = None
    if start is not None and silent.size - start >= min_pause_frames:
        cuts.append(int((start + silent.size) / 2))

    boundaries = [0, *sorted({c * hop_n for c in cuts if 0 < c * hop_n < y.size}), int(y.size)]

    # Merge fragments shorter than the minimum clip length into a neighbour.
    merged: list[list[int]] = []
    for lo, hi in zip(boundaries[:-1], boundaries[1:]):
        if hi <= lo:
            continue
        if merged and (hi - lo) < min_samples:
            merged[-1][1] = hi
        elif merged and (merged[-1][1] - merged[-1][0]) < min_samples:
            merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    if len(merged) > 1 and (merged[0][1] - merged[0][0]) < min_samples:
        merged[1][0] = merged[0][0]
        merged.pop(0)

    ranges: list[tuple[int, int]] = []
    for lo, hi in merged:
        if hi - lo < min_samples:
            continue
        duration = (hi - lo) / sr
        if duration <= CLIP_MAX_SECONDS:
            ranges.append((lo, hi))
        else:
            parts = max(2, int(math.ceil(duration / 8.0)))
            step = (hi - lo) / parts
            for i in range(parts):
                a = int(lo + i * step)
                b = int(lo + (i + 1) * step)
                if (b - a) / sr >= CLIP_MIN_SECONDS:
                    ranges.append((a, b))
    return ranges


def _voiced_ratio(y: np.ndarray, sr: int) -> float:
    """Fraction of frames that are loud relative to the clip's own speech level.

    A vocal clip may have no true digital silence, so the gate is derived from
    the clip's own 90th percentile RMS (peak-relative) with an absolute floor.
    """
    rms_db = _frame_rms_db(y, sr, 0.02)
    if rms_db.size == 0:
        return 0.0
    loud_level = float(np.percentile(rms_db, 90))
    gate = max(-50.0, loud_level - 20.0)
    return float(np.mean(rms_db > gate))


def _collect_clips(
    wav: np.ndarray,
    sr: int,
    segments: Sequence[dict[str, Any]],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Build candidate clips from vocal segments."""
    candidates: list[dict[str, Any]] = []
    wav = np.asarray(wav, dtype=np.float32).ravel()
    for segment in segments:
        label = str(segment.get("label", "vocals"))
        if label not in VOICE_LABELS:
            continue
        start = max(0.0, float(segment.get("start", 0.0)))
        stop = min(wav.size / sr, float(segment.get("stop", 0.0)))
        if stop - start < CLIP_MIN_SECONDS:
            continue
        i0 = int(round(start * sr))
        i1 = int(round(stop * sr))
        chunk = wav[i0:i1]
        for lo, hi in _split_on_pauses(chunk, sr):
            piece = chunk[lo:hi]
            duration = piece.size / sr
            if duration < CLIP_MIN_SECONDS or duration > CLIP_MAX_SECONDS:
                continue
            voiced = _voiced_ratio(piece, sr)
            if voiced < 0.5:
                continue
            peak = float(np.max(np.abs(piece))) if piece.size else 0.0
            if peak < 1e-4:
                continue
            candidates.append(
                {
                    "start": round(start + lo / sr, 3),
                    "stop": round(start + hi / sr, 3),
                    "duration": round(duration, 3),
                    "voiced_ratio": round(voiced, 3),
                    "segment_label": label,
                    "audio": piece,
                }
            )

    if not candidates:
        warnings.append("没有找到符合条件的人声音色片段（1.5–10 秒、有效发声≥50%）")
        return []

    if len(candidates) > MAX_CLIPS:
        order = sorted(range(len(candidates)), key=lambda i: candidates[i]["start"])
        keep = np.linspace(0, len(order) - 1, MAX_CLIPS).round().astype(int)
        selected = {order[int(i)] for i in keep}
        candidates = [c for i, c in enumerate(candidates) if i in selected]
        warnings.append(f"音色片段过多，已均匀抽取 {len(candidates)} 条")
    candidates.sort(key=lambda c: c["start"])
    return candidates


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def _empty_features(duration: float = 0.0) -> TimbreFeatures:
    return TimbreFeatures(duration=round(float(duration), 3))


def clip_features(y: np.ndarray, sr: int = SAMPLE_RATE) -> TimbreFeatures:
    """Perceptual timbre features for one clip (librosa)."""
    y = np.asarray(y, dtype=np.float32).ravel()
    duration = y.size / sr if sr else 0.0
    if y.size < 512 or duration <= 0:
        return _empty_features(duration)
    try:
        import librosa
    except Exception:
        return _empty_features(duration)

    f0_median = f0_mean = f0_std = None
    voiced_ratio = 0.0
    try:
        f0, voiced_flag, _voiced_prob = librosa.pyin(
            y,
            fmin=55.0,
            fmax=1100.0,
            sr=sr,
            frame_length=1024,
            hop_length=256,
            fill_na=np.nan,
        )
        valid = f0[~np.isnan(f0)]
        if valid.size:
            f0_median = round(float(np.median(valid)), 2)
            f0_mean = round(float(np.mean(valid)), 2)
            f0_std = round(float(np.std(valid)), 2)
        if voiced_flag is not None:
            voiced_ratio = float(np.mean(np.asarray(voiced_flag, dtype=np.float32)))
    except Exception:
        try:
            import librosa as _lr

            f0 = _lr.yin(y, fmin=55.0, fmax=1100.0, sr=sr, frame_length=1024, hop_length=256)
            valid = f0[np.isfinite(f0) & (f0 > 0)]
            if valid.size:
                f0_median = round(float(np.median(valid)), 2)
                f0_mean = round(float(np.mean(valid)), 2)
                f0_std = round(float(np.std(valid)), 2)
        except Exception:
            pass

    try:
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, roll_percent=0.85)[0]
        flatness = librosa.feature.spectral_flatness(y=y)[0]
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        rms = librosa.feature.rms(y=y)[0]
    except Exception:
        return _empty_features(duration)

    rms_mean = float(np.mean(rms)) if rms.size else 0.0
    rms_db = round(20.0 * math.log10(max(rms_mean, 1e-7)), 2)
    harmonic_ratio = 0.5
    try:
        harmonic, percussive = librosa.effects.hpss(y)
        h_energy = float(np.sum(harmonic.astype(np.float64) ** 2))
        p_energy = float(np.sum(percussive.astype(np.float64) ** 2))
        if h_energy + p_energy > 0:
            harmonic_ratio = h_energy / (h_energy + p_energy)
    except Exception:
        pass

    if voiced_ratio == 0.0:
        voiced_ratio = float(np.mean(rms > 1e-3)) if rms.size else 0.0
    return TimbreFeatures(
        f0_median=f0_median,
        f0_mean=f0_mean,
        f0_std=f0_std,
        voiced_ratio=round(min(1.0, max(0.0, voiced_ratio)), 3),
        centroid_mean=round(float(np.mean(centroid)), 2),
        centroid_std=round(float(np.std(centroid)), 2),
        rolloff_mean=round(float(np.mean(rolloff)), 2),
        flatness_mean=round(float(np.mean(flatness)), 4),
        zcr_mean=round(float(np.mean(zcr)), 4),
        harmonic_ratio=round(float(harmonic_ratio), 4),
        rms_db=rms_db,
        duration=round(duration, 3),
    )


def _aggregate_features(features: Sequence[TimbreFeatures]) -> TimbreFeatures:
    if not features:
        return _empty_features()
    valid_f0 = [f.f0_median for f in features if f.f0_median is not None]

    def mean(key: str) -> float:
        values = [getattr(f, key) for f in features if getattr(f, key) is not None]
        return round(float(np.mean(values)), 4) if values else 0.0

    has_f0 = bool(valid_f0)
    return TimbreFeatures(
        f0_median=round(float(np.median(valid_f0)), 2) if has_f0 else None,
        f0_mean=mean("f0_mean") if has_f0 else None,
        f0_std=mean("f0_std") if has_f0 else None,
        voiced_ratio=mean("voiced_ratio"),
        centroid_mean=mean("centroid_mean"),
        centroid_std=mean("centroid_std"),
        rolloff_mean=mean("rolloff_mean"),
        flatness_mean=mean("flatness_mean"),
        zcr_mean=mean("zcr_mean"),
        harmonic_ratio=mean("harmonic_ratio"),
        rms_db=mean("rms_db"),
        duration=round(sum(f.duration for f in features), 3),
    )


def _pitch_label(f0_median: float | None) -> str:
    if f0_median is None or f0_median <= 0:
        return "未知音域"
    if f0_median < 165.0:
        return "低音"
    if f0_median < 255.0:
        return "中音"
    return "高音"


def _brightness_label(centroid: float, rolloff: float) -> str:
    score = centroid * 0.7 + rolloff * 0.3
    if score < 1900.0:
        return "暗"
    if score < 3200.0:
        return "中"
    return "亮"


def _texture_label(features: TimbreFeatures) -> str:
    if features.harmonic_ratio >= 0.62 and features.flatness_mean < 0.08:
        return "圆润"
    if features.flatness_mean >= 0.08 and features.harmonic_ratio < 0.5:
        return "气声"
    return "自然"


def cluster_labels(features: TimbreFeatures) -> str:
    """Chinese perceptual label: 音域 · 明暗 · 质感."""
    return "·".join(
        (
            _pitch_label(features.f0_median),
            _brightness_label(features.centroid_mean, features.rolloff_mean),
            _texture_label(features),
        )
    )


# ---------------------------------------------------------------------------
# Embeddings / clustering
# ---------------------------------------------------------------------------

def _load_voice_encoder(model_dir: str | Path | None, device: str) -> tuple[Any, Any, str]:
    """Load the vendored Resemblyzer-style encoder.

    The encoder implementation lives in ``audiolab.core.timbre_encoder`` (vendored
    by the Lead because the upstream ColorSplitter git dependency is unavailable).
    ``colorsplitter`` is intentionally *not* imported.  Raises on missing module
    or weights so the caller can fall back to MFCC.
    """
    import torch

    weights = _weights_path(model_dir)
    if weights is None:
        raise FileNotFoundError("未找到音色编码器权重 models/colorsplitter/timbre-v1.pt")
    try:
        from audiolab.core.timbre_encoder import VoiceEncoder, preprocess_wav
    except Exception as exc:
        raise ImportError(f"音色编码器模块不可用（timbre_encoder）：{exc}") from exc

    resolved = "cuda" if device == "cuda" and torch.cuda.is_available() else "cpu"
    try:
        # Current vendored API: the constructor loads the checkpoint itself.
        encoder = VoiceEncoder(device=resolved, weights_fpath=str(weights))
    except TypeError:
        # Older/alternate signature: instantiate and load weights manually.
        encoder = VoiceEncoder()
        state = torch.load(str(weights), map_location="cpu")
        if isinstance(state, dict):
            for key in ("state_dict", "model", "encoder", "model_state_dict"):
                if key in state and isinstance(state[key], dict):
                    state = state[key]
                    break
        missing, _unexpected = encoder.load_state_dict(state, strict=False)
        if missing:
            raise RuntimeError(f"音色编码器权重不匹配（缺少 {len(missing)} 个参数）")
        try:
            encoder.to(resolved)
        except Exception:
            pass
    try:
        encoder.eval()
    except Exception:
        pass
    return encoder, preprocess_wav, resolved


def _embed_timbre_encoder(
    clip_paths: Sequence[Path],
    model_dir: str | Path | None,
    device: str,
) -> tuple[np.ndarray, str]:
    """Embed clips with the vendored encoder (batch API when available)."""
    encoder, preprocess_wav, resolved = _load_voice_encoder(model_dir, device)
    import torch

    waves = []
    for path in clip_paths:
        try:
            waves.append(preprocess_wav(str(path), trim_silences=False))
        except TypeError:
            try:
                waves.append(preprocess_wav(str(path)))
            except Exception as exc:
                raise RuntimeError(f"预处理音色片段失败（{path.name}）：{exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"预处理音色片段失败（{path.name}）：{exc}") from exc

    with torch.no_grad():
        embeddings = None
        if hasattr(encoder, "embed_utterances"):
            for kwargs in ({"batch_size": 32}, {}):
                try:
                    embeddings = encoder.embed_utterances(waves, **kwargs)
                    break
                except TypeError:
                    continue
                except Exception:
                    embeddings = None
                    break
        if embeddings is None:
            embeddings = [encoder.embed_utterance(wave) for wave in waves]
    rows = [np.asarray(item, dtype=np.float32).reshape(-1) for item in embeddings]
    if not rows:
        raise RuntimeError("音色编码器未生成任何嵌入")
    return np.vstack(rows), resolved


def _embed_mfcc(clip_paths: Sequence[Path], warnings: list[str]) -> np.ndarray:
    import librosa

    rows: list[np.ndarray] = []
    for path in clip_paths:
        y, sr = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
        if y.size < 512:
            rows.append(np.zeros(80, dtype=np.float32))
            continue
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        rows.append(np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1)]).astype(np.float32))
    matrix = np.vstack(rows) if rows else np.zeros((0, 80), dtype=np.float32)
    # Reduce dimensionality before cosine clustering (spec: MFCC + PCA).
    if matrix.shape[0] >= 3 and matrix.shape[1] > 20:
        try:
            from sklearn.decomposition import PCA

            n_components = int(min(20, matrix.shape[0] - 1, matrix.shape[1]))
            matrix = PCA(n_components=n_components, random_state=0).fit_transform(matrix)
            warnings.append(f"MFCC 回退：{n_components} 维 PCA 嵌入")
        except Exception:
            pass
    return np.asarray(matrix, dtype=np.float32)


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _compact_labels(labels: np.ndarray) -> np.ndarray:
    """Relabel clusters 0..k-1 ordered by size (largest first)."""
    unique, counts = np.unique(labels, return_counts=True)
    order = unique[np.argsort(-counts)]
    remap = {int(old): int(new) for new, old in enumerate(order.tolist())}
    return np.array([remap[int(value)] for value in labels], dtype=np.int32)


def _merge_small_clusters(
    normalized: np.ndarray,
    labels: np.ndarray,
    warnings: list[str],
    min_size: int = 2,
) -> np.ndarray:
    """Merge single-clip clusters into the most similar remaining cluster.

    MFCC/PCA embeddings are noisy enough that average-linkage clustering can
    produce one-clip clusters; those are useless in the UI, so they are folded
    into their nearest centroid (auto mode only).
    """
    labels = labels.copy()
    merged_any = False
    guard = 0
    while guard < 64:
        guard += 1
        unique, counts = np.unique(labels, return_counts=True)
        if unique.size <= 1:
            break
        small = unique[counts < min_size]
        if small.size == 0:
            break
        target = int(small[0])
        members = labels == target
        centroids: dict[int, np.ndarray] = {}
        for cluster_id in unique.tolist():
            if int(cluster_id) == target:
                continue
            centroids[int(cluster_id)] = normalized[labels == cluster_id].mean(axis=0)
        vec = normalized[members].mean(axis=0)
        norm = float(np.linalg.norm(vec)) or 1.0
        vec = vec / norm
        best_id = max(
            centroids,
            key=lambda cid: float(np.dot(vec, centroids[cid] / (float(np.linalg.norm(centroids[cid])) or 1.0))),
        )
        labels[members] = best_id
        merged_any = True
    if merged_any:
        warnings.append("已将只含 1 条片段的音色簇合并到最相近的簇")
    return _compact_labels(labels)


def _cluster(matrix: np.ndarray, clusters: int | None, threshold: float, warnings: list[str]) -> np.ndarray:
    n = matrix.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int32)
    if n < 3:
        return np.zeros(n, dtype=np.int32)
    normalized = _normalize_rows(matrix)
    auto_mode = not (clusters and int(clusters) >= 2)
    try:
        from sklearn.cluster import AgglomerativeClustering

        if auto_mode:
            model = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=max(0.01, float(threshold)),
                metric="cosine",
                linkage="average",
            )
        else:
            model = AgglomerativeClustering(
                n_clusters=min(int(clusters), n),
                metric="cosine",
                linkage="average",
            )
        labels = model.fit_predict(normalized).astype(np.int32)
    except Exception as exc:
        warnings.append(f"聚类失败，已归为单簇：{exc}")
        return np.zeros(n, dtype=np.int32)

    unique = np.unique(labels)
    if unique.size > 8:
        # Keep the result readable for the UI: merge down to 8 clusters.
        try:
            from sklearn.cluster import AgglomerativeClustering

            labels = AgglomerativeClustering(n_clusters=8, metric="cosine", linkage="average").fit_predict(
                normalized
            ).astype(np.int32)
            warnings.append("聚类过多，已合并到 8 个音色簇")
        except Exception:
            pass
    if auto_mode and np.unique(labels).size > 1:
        return _merge_small_clusters(normalized, labels, warnings)
    return _compact_labels(labels)


def _pca_points(matrix: np.ndarray, labels: np.ndarray, clip_ids: Sequence[str]) -> list[dict[str, float]]:
    n = matrix.shape[0]
    if n == 0:
        return []
    if n == 1:
        return [{"x": 0.0, "y": 0.0, "cluster": int(labels[0]) if labels.size else 0, "clip_id": clip_ids[0]}]
    coords = None
    try:
        from sklearn.decomposition import PCA

        coords = PCA(n_components=2, random_state=0).fit_transform(_normalize_rows(matrix))
    except Exception:
        centered = matrix - matrix.mean(axis=0, keepdims=True)
        try:
            u, s, _vt = np.linalg.svd(centered, full_matrices=False)
            coords = u[:, :2] * s[:2]
        except Exception:
            coords = np.zeros((n, 2), dtype=np.float32)
    points: list[dict[str, float]] = []
    for i in range(n):
        points.append(
            {
                "x": round(float(coords[i, 0]), 4),
                "y": round(float(coords[i, 1]), 4),
                "cluster": int(labels[i]) if labels.size else 0,
                "clip_id": clip_ids[i],
            }
        )
    return points


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze(
    vocals_path: str | Path,
    timeline: Timeline | dict[str, Any],
    out_dir: str | Path,
    model_dir: str | Path | None = None,
    device: str = "cuda",
    clusters: int | None = None,
    threshold: float = 0.35,
    backend: str = "colorsplitter",
    progress: ProgressFn | None = None,
) -> TimbreResult:
    """Analyse vocal timbre and cluster the singer's voices.

    ``clip.url`` is intentionally left empty; the pipeline fills it with
    ``/api/files/{project_id}/<relative path>``.
    """
    warnings: list[str] = []
    vocals_path = Path(vocals_path)
    out_dir = Path(out_dir)
    clips_dir = out_dir / "timbre" / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    if not vocals_path.exists():
        return TimbreResult(backend=backend, clusters=[], points=[], warnings=[f"人声文件不存在：{vocals_path}"])

    # Normalise the timeline input.
    if isinstance(timeline, Timeline):
        duration = float(timeline.duration or 0.0)
        segments = [segment.model_dump() for segment in timeline.segments]
    elif isinstance(timeline, dict):
        duration = float(timeline.get("duration") or 0.0)
        segments = list(timeline.get("segments") or [])
    else:  # pragma: no cover - defensive
        duration = 0.0
        segments = []
    if duration <= 0:
        try:
            duration = media.duration(vocals_path)
        except Exception:
            duration = 0.0

    _emit(progress, "timbre", 4, "解码人声")
    try:
        wav = media.decode_mono(vocals_path, SAMPLE_RATE)
    except Exception as exc:
        return TimbreResult(backend=backend, clusters=[], points=[], warnings=[f"无法解码人声：{exc}"])
    if duration <= 0:
        duration = wav.size / SAMPLE_RATE

    _emit(progress, "timbre", 12, "切分音色片段")
    candidates = _collect_clips(wav, SAMPLE_RATE, segments, warnings)
    if not candidates:
        _emit(progress, "timbre", 100, "没有可分析的人声片段")
        return TimbreResult(backend=backend, clusters=[], points=[], warnings=warnings)

    clip_paths: list[Path] = []
    features: list[TimbreFeatures] = []
    for index, candidate in enumerate(candidates):
        clip_path = clips_dir / f"clip_{index:04d}.wav"
        media.write_wav(clip_path, candidate["audio"], SAMPLE_RATE)
        clip_paths.append(clip_path)
        features.append(clip_features(candidate["audio"], SAMPLE_RATE))
    _emit(progress, "timbre", 35, f"已提取 {len(clip_paths)} 条片段特征")

    requested_backend = (backend or "colorsplitter").lower()
    used_backend = "mfcc"
    matrix: np.ndarray | None = None
    if requested_backend == "colorsplitter":
        try:
            matrix, _device = _embed_timbre_encoder(clip_paths, model_dir, device)
            used_backend = "colorsplitter"
            _emit(progress, "timbre", 55, "音色编码器嵌入完成")
        except Exception as exc:
            warnings.append(f"音色编码器不可用，已回退 MFCC：{exc}")
    if matrix is None:
        _emit(progress, "timbre", 50, "提取 MFCC 音色嵌入")
        try:
            matrix = _embed_mfcc(clip_paths, warnings)
        except Exception as exc:
            warnings.append(f"音色嵌入失败：{exc}")
            return TimbreResult(backend="mfcc", clusters=[], points=[], warnings=warnings)
        used_backend = "mfcc"

    if matrix.shape[0] != len(clip_paths):
        warnings.append("嵌入数量与片段数量不一致，已按最小值对齐")
        size = min(matrix.shape[0], len(clip_paths))
        matrix = matrix[:size]
        clip_paths = clip_paths[:size]
        features = features[:size]
    if matrix.size == 0:
        return TimbreResult(backend=used_backend, clusters=[], points=[], warnings=warnings)

    _emit(progress, "timbre", 65, "聚类音色")
    labels = _cluster(matrix, clusters, threshold, warnings)
    points = _pca_points(matrix, labels, [path.stem for path in clip_paths])
    normalized = _normalize_rows(matrix)

    clip_models: list[TimbreClip] = []
    for index, (path, feat, cluster_id) in enumerate(zip(clip_paths, features, labels.tolist())):
        candidate = candidates[index]
        clip_models.append(
            TimbreClip(
                id=f"clip_{index:04d}",
                path=str(path.resolve()),
                url="",
                start=float(candidate["start"]),
                stop=float(candidate["stop"]),
                duration=float(candidate["duration"]),
                cluster=int(cluster_id),
                features=feat,
                is_representative=False,
            )
        )

    montage_dir = out_dir / "timbre"
    montage_dir.mkdir(parents=True, exist_ok=True)
    timbre_clusters: list[TimbreCluster] = []
    for cluster_id in sorted(set(labels.tolist())):
        indices = [i for i, value in enumerate(labels.tolist()) if value == cluster_id]
        cluster_features = _aggregate_features([features[i] for i in indices])
        centroid = normalized[indices].mean(axis=0)
        centroid_norm = np.linalg.norm(centroid)
        if centroid_norm > 0:
            centroid = centroid / centroid_norm
        similarity = normalized[indices] @ centroid
        ranked = [indices[i] for i in np.argsort(-similarity)]
        representative = ranked[:3]
        for i in representative:
            clip_models[i].is_representative = True

        # Montage of the representative clips (best effort, useful for audition).
        try:
            pieces = []
            for i in representative:
                pieces.append(np.asarray(candidates[i]["audio"], dtype=np.float32))
                pieces.append(np.zeros(int(0.1 * SAMPLE_RATE), dtype=np.float32))
            if pieces:
                media.write_wav(montage_dir / f"cluster_{int(cluster_id):02d}_montage.wav", np.concatenate(pieces), SAMPLE_RATE)
        except Exception:
            pass

        timbre_clusters.append(
            TimbreCluster(
                id=f"cluster_{int(cluster_id)}",
                index=int(cluster_id),
                label=cluster_labels(cluster_features),
                color=PALETTE[int(cluster_id) % len(PALETTE)],
                n_clips=len(indices),
                total_duration=round(sum(features[i].duration for i in indices), 2),
                features=cluster_features,
                clips=[clip_models[i] for i in indices],
                representative=[clip_models[i].id for i in representative],
            )
        )

    _emit(progress, "timbre", 100, f"音色分析完成：{len(timbre_clusters)} 个簇")
    try:
        return TimbreResult(backend=used_backend, clusters=timbre_clusters, points=points, warnings=warnings)
    except Exception as exc:
        # schemas.TimbreResult.points is list[dict[str, float]], which cannot hold
        # the string clip_id required by the API contract.  Degrade to numeric
        # points instead of failing the whole analysis; the Lead has been asked
        # to widen the schema to dict[str, Any].
        numeric_points = [
            {
                "x": float(point.get("x", 0.0)),
                "y": float(point.get("y", 0.0)),
                "cluster": float(point.get("cluster", 0)),
            }
            for point in points
        ]
        warnings.append(
            "散点数据已省略 clip_id（schemas.TimbreResult.points 仅支持数值，建议改为 dict[str, Any]）"
        )
        logging.getLogger(__name__).debug("TimbreResult points fallback: %s", exc)
        return TimbreResult(
            backend=used_backend,
            clusters=timbre_clusters,
            points=numeric_points,
            warnings=warnings,
        )
