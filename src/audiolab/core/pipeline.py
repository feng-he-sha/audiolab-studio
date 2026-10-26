"""End-to-end orchestration: analysis, fusion re-runs and preset processing.

Layout written under ``out_dir`` (the project ``result_dir``)::

    audio/original.wav         48 kHz stereo, extracted from the source
    audio/analysis_16k.wav     16 kHz mono (AST / diagnostics)
    stems/vocals.wav           separated vocals (48 kHz stereo)
    stems/instrumental.wav     separated instrumental
    preview/*.m4a              AAC previews (WAV fallback)
    peaks/*.json               waveform peaks for the canvas
    timbre/clips/*.wav         16 kHz mono timbre clips
    evidence.npz               fusion evidence (vocal/music masks)
    timeline.json  timbre.json  analysis.json
    report.html
    processed/<preset>.<ext>   render output

The module never touches the database or the API server; callers pass callbacks
for progress.  Every stage is idempotent and individual stages are re-run when
their output files are missing.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from audiolab import config
from audiolab.core import fusion, media, processing, report, separation, tagging, timbre, vad
from audiolab.core import schemas
from audiolab.core.media import MediaError
from audiolab.core.schemas import (
    AnalysisResult,
    Artifact,
    ProcessResult,
    Timeline,
    TimbreResult,
)

__all__ = [
    "PipelineError",
    "analyze",
    "process",
    "refuse",
    "load_analysis",
    "load_timeline",
    "load_timbre",
    "artifacts_from_result",
    "HOP",
    "QUALITY_PRESETS",
]

ProgressFn = Callable[[str, float, str], None]

HOP = 0.02
EVIDENCE_NAME = "evidence.npz"

QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "fast": {
        "label": "快速",
        "skip_tagging": True,
        "timbre_backend": "mfcc",
        "overlap": None,
        "description": "MDX 分离 + 能量融合 + MFCC 音色，最快出结果",
    },
    "balanced": {
        "label": "均衡",
        "skip_tagging": False,
        "timbre_backend": "colorsplitter",
        "overlap": None,
        "description": "BS-Roformer 分离 + AST 标签 + ColorSplitter 音色",
    },
    "hq": {
        "label": "高质量",
        "skip_tagging": False,
        "timbre_backend": "colorsplitter",
        "overlap": 16.0,
        "description": "与均衡相同，但分离重叠窗口更高（更慢更好）",
    },
}


class PipelineError(RuntimeError):
    """Raised when a pipeline stage fails; ``stage`` names the failing stage."""

    def __init__(self, message: str, stage: str = "") -> None:
        self.stage = stage
        super().__init__(f"[{stage}] {message}" if stage else message)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _emit(progress: ProgressFn | None, stage: str, pct: float, message: str) -> None:
    if progress is None:
        return
    try:
        progress(stage, max(0.0, min(100.0, float(pct))), message)
    except Exception:
        pass


def _settings(settings: Any = None) -> config.Settings:
    if isinstance(settings, config.Settings):
        return settings
    if settings is None:
        try:
            return config.load_settings()
        except Exception:
            return config.Settings()
    if isinstance(settings, dict):
        known = set(config.Settings.__dataclass_fields__)
        filtered = {key: value for key, value in settings.items() if key in known}
        try:
            return config.Settings(**filtered)
        except TypeError:
            base = config.Settings()
            for key, value in filtered.items():
                setattr(base, key, value)
            return base
    return config.Settings()


def _models_root(settings: config.Settings) -> Path:
    root = Path(settings.models_dir) if settings.models_dir else config.MODELS
    return root


def _api_url(project_id: str, path: Path, out_dir: Path) -> str:
    try:
        relative = path.resolve().relative_to(out_dir.resolve()).as_posix()
    except ValueError:
        relative = path.name
    return f"/api/files/{quote(project_id)}/{quote(relative, safe='/')}"


def _rel(path: Path, out_dir: Path) -> str:
    try:
        return path.resolve().relative_to(out_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _normalize_params(params: dict[str, Any] | None, settings: config.Settings) -> dict[str, Any]:
    raw = dict(params or {})
    quality = str(raw.get("quality") or "balanced").strip().lower()
    if quality not in QUALITY_PRESETS:
        quality = "balanced"
    quality_cfg = QUALITY_PRESETS[quality]

    def pick(key: str, default: Any) -> Any:
        value = raw.get(key)
        return default if value is None else value

    base_model = pick("separation_model", settings.separation_model)
    if quality == "fast":
        # MDX-Net fallback: resolve away unsupported legacy filenames (HQ_3).
        base_model = pick("separation_model", separation.resolve_fallback(settings.separation_fallback))
    clusters = pick("clusters", None)
    try:
        clusters = int(clusters) if clusters not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        clusters = None
    threshold = float(pick("timbre_threshold", 0.35))
    return {
        "quality": quality,
        "device": pick("device", None),
        "separation_model": str(base_model),
        "separation_fallback": str(pick("separation_fallback", settings.separation_fallback)),
        "separation_overlap": quality_cfg["overlap"] if raw.get("separation_overlap") is None else raw.get("separation_overlap"),
        "skip_tagging": bool(pick("skip_tagging", quality_cfg["skip_tagging"])),
        "timbre_backend": str(pick("timbre_backend", quality_cfg["timbre_backend"] or settings.timbre_backend)),
        "clusters": clusters,
        "timbre_threshold": max(0.05, min(0.95, threshold)),
        "force": bool(pick("force", False)),
        "allow_model_download": bool(pick("allow_model_download", True)),
        "audio_track": int(pick("audio_track", 0)),
        "hop": HOP,
        "smooth_frames": int(pick("smooth_frames", 5)),
        "min_segment": float(pick("min_segment", 0.3)),
        "min_music": float(pick("min_music", 0.5)),
        "min_gap": float(pick("min_gap", 0.25)),
    }


def _dirs(out_dir: Path) -> dict[str, Path]:
    paths = {
        "root": out_dir,
        "audio": out_dir / "audio",
        "stems": out_dir / "stems",
        "preview": out_dir / "preview",
        "peaks": out_dir / "peaks",
        "timbre": out_dir / "timbre",
        "clips": out_dir / "timbre" / "clips",
        "processed": out_dir / "processed",
    }
    for key, path in paths.items():
        if key != "root":
            path.mkdir(parents=True, exist_ok=True)
    return paths


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: Any) -> None:
    config.write_json(path, data)


def _load_cached(out_dir: Path, media_info: schemas.MediaInfo) -> AnalysisResult | None:
    path = out_dir / "analysis.json"
    if not path.is_file():
        return None
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    try:
        result = AnalysisResult.model_validate(data)
    except Exception:
        return None
    if not result.media:
        return None
    cached = result.media
    if abs(float(cached.duration) - float(media_info.duration)) > max(0.5, float(media_info.duration) * 0.01):
        return None
    if cached.sha256 and media_info.sha256 and cached.sha256 != media_info.sha256:
        return None
    if not (out_dir / "stems" / "vocals.wav").is_file():
        return None
    return result


def _ensure_cached_side_files(out_dir: Path, result: AnalysisResult, project_title: str) -> None:
    paths = _dirs(out_dir)
    if not (out_dir / "timeline.json").is_file():
        _write_json(out_dir / "timeline.json", result.timeline.model_dump())
    if not (out_dir / "timbre.json").is_file():
        _write_json(out_dir / "timbre.json", result.timbre.model_dump())
    report_path = out_dir / "report.html"
    if not report_path.is_file():
        report.build(result, report_path, project_title)


def _fill_clip_urls(timbre_result: TimbreResult, project_id: str, out_dir: Path) -> None:
    for cluster in timbre_result.clusters:
        for clip in cluster.clips:
            if not clip.url:
                clip.url = _api_url(project_id, Path(clip.path), out_dir)


def _write_evidence(
    out_dir: Path,
    vocal_mask: Any,
    music_mask: Any,
    orig_rms_db: Any,
    hop: float,
    duration: float,
    ast_windows: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    import numpy as np

    np.savez_compressed(
        out_dir / EVIDENCE_NAME,
        vocal_mask=np.asarray(vocal_mask, dtype=np.int8),
        music_mask=np.asarray(music_mask, dtype=np.int8),
        orig_rms_db=np.asarray(orig_rms_db, dtype=np.float32),
        hop=np.float32(hop),
        duration=np.float32(duration),
        ast_json=np.array(json.dumps(ast_windows, ensure_ascii=False)),
        warnings_json=np.array(json.dumps(warnings, ensure_ascii=False)),
    )


def _read_evidence(out_dir: Path) -> dict[str, Any]:
    import numpy as np

    path = out_dir / EVIDENCE_NAME
    if not path.is_file():
        raise PipelineError("缺少融合证据 (evidence.npz)，请先运行分析", "refuse")
    try:
        with np.load(path, allow_pickle=False) as data:
            payload: dict[str, Any] = {key: data[key] for key in data.files}
    except Exception as exc:
        raise PipelineError(f"融合证据损坏：{exc}", "refuse") from exc
    for key in ("vocal_mask", "music_mask"):
        if key not in payload:
            raise PipelineError(f"融合证据缺少 {key}", "refuse")
    for key in ("ast_json", "warnings_json"):
        if key in payload:
            try:
                payload[key] = json.loads(str(payload[key]))
            except Exception:
                payload[key] = [] if key.endswith("json") else None
    return payload


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(
    project_id: str,
    source_path: str | Path,
    out_dir: str | Path,
    params: dict[str, Any] | None = None,
    progress: ProgressFn | None = None,
    settings: Any = None,
) -> AnalysisResult:
    """Run the full analysis pipeline for one project.

    ``params`` supports ``quality`` (fast/balanced/hq), ``separation_model``,
    ``skip_tagging``, ``clusters``, ``timbre_threshold``, ``timbre_backend``,
    ``force``, ``audio_track`` (plus optional fusion tunables).
    Results are cached: an existing ``analysis.json`` is returned when the media
    duration/hash still matches and ``force`` is false.
    """
    started = time.time()
    settings_obj = _settings(settings)
    params_norm = _normalize_params(params, settings_obj)
    source = Path(source_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = _dirs(out_dir)
    models_root = _models_root(settings_obj)
    device = config.resolve_device(params_norm.get("device") or settings_obj.device)
    hop = float(params_norm["hop"])
    warnings: list[str] = []
    timings: dict[str, float] = {}
    _last_mark = [started]

    def lap(name: str) -> None:
        now = time.time()
        timings[name] = round(now - _last_mark[0], 3)
        _last_mark[0] = now

    if not source.exists():
        raise PipelineError(f"源文件不存在：{source}", "probe")

    # Prefer the fast MDX model when the primary Roformer weights are absent and
    # the caller did not explicitly pin a model (avoids a slow 639 MB download).
    explicit_model = bool((params or {}).get("separation_model"))
    if not explicit_model:
        primary = str(params_norm["separation_model"])
        fallback = separation.resolve_fallback(params_norm["separation_fallback"], models_root / "separator")
        params_norm["separation_fallback"] = fallback
        if not separation.available(primary, models_root / "separator"):
            params_norm["separation_model"] = fallback
            if separation.available(fallback, models_root / "separator"):
                warnings.append(f"主分离模型缺失，已自动改用备用模型 {fallback}")
            else:
                warnings.append(
                    f"主分离模型 {Path(primary).name} 缺失，已切换 MDX 备用模型 {fallback}"
                    f"（本地不存在时会自动下载）"
                )

    # ---- Stage: probe ------------------------------------------------------
    _emit(progress, "probe", 1, "读取媒体信息")
    try:
        media_info = media.probe(source, audio_track=int(params_norm["audio_track"]), compute_sha256=True)
    except MediaError as exc:
        raise PipelineError(str(exc), "probe") from exc
    if media_info.duration <= 0:
        raise PipelineError("无法读取音频时长（文件可能损坏）", "probe")
    duration = float(media_info.duration)
    _emit(progress, "probe", 3, f"时长 {duration:.1f}s · {media_info.codec or '未知编码'}")
    lap("probe")

    # ---- Cache -------------------------------------------------------------
    if not params_norm["force"]:
        cached = _load_cached(out_dir, media_info)
        if cached is not None:
            _emit(progress, "cache", 100, "命中分析缓存，直接返回")
            _ensure_cached_side_files(out_dir, cached, media_info.filename)
            return cached

    # ---- Stage: extract ----------------------------------------------------
    original = paths["audio"] / "original.wav"
    need_extract = params_norm["force"] or not original.is_file()
    if not need_extract:
        try:
            need_extract = abs(media.duration(original) - duration) > max(1.0, duration * 0.01)
        except Exception:
            need_extract = True
    if need_extract:
        _emit(progress, "extract", 5, "抽取音轨（48kHz 立体声）")
        try:
            media.extract_audio(
                source,
                original,
                sample_rate=48000,
                channels=2,
                audio_track=int(params_norm["audio_track"]),
            )
        except MediaError as exc:
            raise PipelineError(str(exc), "extract") from exc
    duration = media.duration(original) or duration
    original_info = media.probe(original)

    analysis_16k = paths["audio"] / "analysis_16k.wav"
    if params_norm["force"] or not analysis_16k.is_file():
        _emit(progress, "extract", 8, "生成 16kHz 分析音频")
        try:
            mono = media.decode_mono(original, 16000)
            media.write_wav(analysis_16k, mono, 16000)
        except MediaError as exc:
            raise PipelineError(f"生成分析音频失败：{exc}", "extract") from exc
    try:
        mix16 = media.decode_mono(analysis_16k, 16000)
    except MediaError as exc:
        raise PipelineError(f"解码分析音频失败：{exc}", "extract") from exc
    lap("extract")

    # ---- Stage: separation -------------------------------------------------
    vocals_48 = paths["stems"] / "vocals.wav"
    inst_48 = paths["stems"] / "instrumental.wav"
    stems_ready = vocals_48.is_file() and inst_48.is_file()
    if params_norm["force"] or not stems_ready:
        _emit(progress, "separation", 10, f"分离音轨（{params_norm['quality']}）")
        try:
            separation.separate(
                original,
                paths["stems"],
                models_root / "separator",
                model=str(params_norm["separation_model"]),
                fallback=str(params_norm["separation_fallback"]),
                device=device,
                progress=progress,
                overlap=params_norm["separation_overlap"],
                allow_download=bool(params_norm["allow_model_download"]),
            )
        except separation.SeparateError as exc:
            raise PipelineError(f"音轨分离失败：{exc}", "separation") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise PipelineError(f"音轨分离异常：{exc}", "separation") from exc
    if not (vocals_48.is_file() and inst_48.is_file()):
        raise PipelineError("分离未生成 vocals.wav / instrumental.wav", "separation")
    lap("separation")

    # ---- Stage: VAD + masks ------------------------------------------------
    _emit(progress, "vad", 40, "人声检测（Silero VAD）")
    try:
        vocals16 = media.decode_mono(vocals_48, 16000)
        inst16 = media.decode_mono(inst_48, 16000)
    except MediaError as exc:
        raise PipelineError(f"解码分离音轨失败：{exc}", "vad") from exc
    vad_warnings: list[str] = []
    try:
        speech = vad.speech_segments(
            vocals16,
            16000,
            model_path=models_root / "silero" / "silero_vad.onnx",
            device=device,
            threshold=0.5,
            min_speech_ms=250,
            min_silence_ms=200,
            pad_ms=100,
            warnings=vad_warnings,
        )
        vocal_mask = vad.vocal_mask(vocals16, 16000, duration, hop, speech, warnings=vad_warnings)
    except Exception as exc:
        raise PipelineError(f"人声检测失败：{exc}", "vad") from exc
    warnings.extend(vad_warnings)
    lap("vad")

    # ---- Stage: tagging (optional) ----------------------------------------
    ast_windows: list[dict[str, Any]] = []
    if params_norm["skip_tagging"]:
        _emit(progress, "tagging", 50, "已按参数跳过 AST 标签")
    else:
        _emit(progress, "tagging", 50, "AST 音频标签（10s 滑窗）")
        tagging_warnings: list[str] = []
        try:
            ast_windows = tagging.analyze(
                mix16,
                16000,
                models_root / "hf",
                device=device,
                warnings=tagging_warnings,
            )
        except Exception as exc:  # tagging must never break the pipeline
            tagging_warnings.append(f"AST 标签失败，已跳过：{exc}")
            ast_windows = []
        warnings.extend(tagging_warnings)
        if not ast_windows and not any("AST" in item for item in warnings):
            warnings.append("未获得 AST 标签，音乐判定仅依赖能量/谐波比")
    lap("tagging")

    # ---- Stage: fusion -----------------------------------------------------
    _emit(progress, "fusion", 58, "融合人声/音乐证据")
    try:
        music_mask = fusion.music_mask_from_energy(inst16, 16000, duration, hop, ast_windows)
        orig_rms = fusion.frame_rms_db(mix16, 16000, hop)
        timeline = fusion.fuse(
            duration,
            vocal_mask,
            music_mask,
            ast_windows=ast_windows,
            orig_rms_db=orig_rms,
            hop=hop,
            smooth_frames=int(params_norm["smooth_frames"]),
            min_segment=float(params_norm["min_segment"]),
            min_music=float(params_norm["min_music"]),
            min_gap=float(params_norm["min_gap"]),
        )
    except Exception as exc:
        raise PipelineError(f"证据融合失败：{exc}", "fusion") from exc
    warnings.extend(timeline.warnings)
    _write_json(out_dir / "timeline.json", timeline.model_dump())
    try:
        _write_evidence(
            out_dir,
            vocal_mask,
            music_mask,
            orig_rms,
            hop,
            duration,
            ast_windows,
            [item for item in warnings if item],
        )
    except Exception as exc:
        warnings.append(f"融合证据保存失败（refuse 将不可用）：{exc}")
    lap("fusion")

    # ---- Stage: timbre -----------------------------------------------------
    _emit(progress, "timbre", 65, "音色分析")
    timbre_result = TimbreResult(backend=str(params_norm["timbre_backend"]), clusters=[], points=[], warnings=[])
    try:
        timbre_result = timbre.analyze(
            vocals_48,
            timeline,
            out_dir,
            models_root,
            device=device,
            clusters=params_norm["clusters"],
            threshold=float(params_norm["timbre_threshold"]),
            backend=str(params_norm["timbre_backend"]),
            progress=progress,
        )
    except Exception as exc:  # timbre degrades, never blocks
        timbre_result = TimbreResult(
            backend=str(params_norm["timbre_backend"]),
            clusters=[],
            points=[],
            warnings=[f"音色分析失败，已跳过：{exc}"],
        )
    warnings.extend(timbre_result.warnings)
    _fill_clip_urls(timbre_result, project_id, out_dir)
    _write_json(out_dir / "timbre.json", timbre_result.model_dump())
    lap("timbre")

    # ---- Stage: previews / peaks ------------------------------------------
    _emit(progress, "preview", 84, "生成预览与波形峰值")
    preview_sr = int(settings_obj.preview_quality or 32) * 1000
    sources = [("original", original), ("vocals", vocals_48), ("instrumental", inst_48)]
    preview_paths: dict[str, Path] = {}
    for name, src in sources:
        if not src.is_file():
            continue
        preview_path = paths["preview"] / f"{name}.m4a"
        if params_norm["force"] or not preview_path.is_file():
            try:
                preview_paths[name] = media.make_preview(src, preview_path, sample_rate=preview_sr, bitrate="96k")
            except MediaError as exc:
                warnings.append(f"预览生成失败（{name}）：{exc}")
                continue
        else:
            preview_paths[name] = preview_path
        peaks_path = paths["peaks"] / f"{name}.json"
        if params_norm["force"] or not peaks_path.is_file():
            try:
                _write_json(peaks_path, media.compute_peaks(src, buckets=2000))
            except MediaError as exc:
                warnings.append(f"波形峰值生成失败（{name}）：{exc}")
    lap("preview")

    # ---- Artifacts ---------------------------------------------------------
    artifacts: list[Artifact] = []

    def add_artifact(key: str, kind: str, label: str, path: Path, mime: str) -> None:
        if not path.is_file():
            return
        try:
            dur = media.duration(path)
        except Exception:
            dur = 0.0
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        artifacts.append(
            Artifact(
                id=key,
                kind=kind,
                label=label,
                path=str(path.resolve()),
                url=_api_url(project_id, path, out_dir),
                duration=round(float(dur), 3),
                size=int(size),
                mime=mime,
            )
        )

    add_artifact("original", "original", "原始音频", original, "audio/wav")
    add_artifact("vocals", "vocals", "人声", vocals_48, "audio/wav")
    add_artifact("instrumental", "instrumental", "伴奏", inst_48, "audio/wav")
    for name, path in preview_paths.items():
        mime = "audio/mp4" if path.suffix.lower() in {".m4a", ".mp4", ".aac"} else "audio/wav"
        add_artifact(f"preview_{name}", "preview", f"{name} 预览", path, mime)

    result = AnalysisResult(
        project_id=project_id,
        media=media_info,
        timeline=timeline,
        timbre=timbre_result,
        artifacts=artifacts,
        report_url=f"/api/projects/{quote(project_id)}/report",
        warnings=_dedupe(warnings),
    )

    # ---- Stage: report -----------------------------------------------------
    # Write provisional meta first so the report can show model/timing rows.
    elapsed_so_far = time.time() - started
    meta = {
        "project_id": project_id,
        "source_path": str(source),
        "quality": params_norm["quality"],
        "device": device,
        "duration": round(float(result.timeline.duration), 3),
        "separation_model": str(params_norm["separation_model"]),
        "separation_fallback": str(params_norm["separation_fallback"]),
        "timbre_backend": result.timbre.backend,
        "skip_tagging": bool(params_norm["skip_tagging"]),
        "frame_hop": hop,
        "elapsed_seconds": round(elapsed_so_far, 3),
        "stages": dict(timings),
        "warnings": len([item for item in result.warnings if item]),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write_json(out_dir / "meta.json", meta)

    _emit(progress, "report", 93, "生成 HTML 报告")
    report_path = out_dir / "report.html"
    try:
        report.build(result, report_path, media_info.filename)
        add_artifact("report", "report", "分析报告", report_path, "text/html")
        result.artifacts = artifacts
    except Exception as exc:
        result.warnings = _dedupe([*result.warnings, f"报告生成失败：{exc}"])
    lap("report")

    # ---- Persist -----------------------------------------------------------
    _emit(progress, "save", 98, "写入分析结果")
    elapsed = time.time() - started
    meta.update({"elapsed_seconds": round(elapsed, 3), "stages": dict(timings)})
    _write_json(out_dir / "meta.json", meta)
    _write_json(out_dir / "analysis.json", result.model_dump())
    _emit(progress, "done", 100, f"分析完成，用时 {elapsed:.1f}s")
    return result


# ---------------------------------------------------------------------------
# Fusion-only re-run (UI threshold tuning)
# ---------------------------------------------------------------------------

def refuse(
    project_id: str,
    out_dir: str | Path,
    params: dict[str, Any] | None = None,
    progress: ProgressFn | None = None,
    settings: Any = None,
) -> Timeline:
    """Re-run only the fusion stage using cached evidence (fast threshold tuning)."""
    out_dir = Path(out_dir)
    raw = dict(params or {})
    _emit(progress, "refuse", 5, "读取融合证据")
    evidence = _read_evidence(out_dir)
    hop = float(evidence.get("hop", HOP))
    duration = float(evidence.get("duration", 0.0))
    if duration <= 0:
        path = out_dir / "timeline.json"
        cached = _read_json(path)
        duration = float((cached or {}).get("duration", 0.0) or 0.0)

    def pick(key: str, default: Any) -> Any:
        value = raw.get(key)
        return default if value is None else value

    _emit(progress, "refuse", 40, "重新融合分段")
    try:
        timeline = fusion.fuse(
            duration,
            evidence["vocal_mask"],
            evidence["music_mask"],
            ast_windows=evidence.get("ast_json") or [],
            orig_rms_db=evidence.get("orig_rms_db"),
            hop=hop,
            smooth_frames=int(pick("smooth_frames", 5)),
            min_segment=float(pick("min_segment", 0.3)),
            min_music=float(pick("min_music", 0.5)),
            min_gap=float(pick("min_gap", 0.25)),
        )
    except Exception as exc:
        raise PipelineError(f"重新融合失败：{exc}", "refuse") from exc
    _write_json(out_dir / "timeline.json", timeline.model_dump())

    analysis_path = out_dir / "analysis.json"
    data = _read_json(analysis_path)
    if isinstance(data, dict):
        data["timeline"] = timeline.model_dump()
        data["warnings"] = _dedupe([*data.get("warnings", []), *timeline.warnings])
        _write_json(analysis_path, data)
        try:
            result = AnalysisResult.model_validate(data)
            report.build(result, out_dir / "report.html", result.media.filename)
        except Exception:
            pass
    _emit(progress, "refuse", 100, f"已重新分段：{len(timeline.segments)} 段")
    return timeline


# ---------------------------------------------------------------------------
# Preset processing
# ---------------------------------------------------------------------------

def process(
    project_id: str,
    source_path: str | Path,
    out_dir: str | Path,
    preset: str,
    params: dict[str, Any] | None = None,
    progress: ProgressFn | None = None,
    settings: Any = None,
) -> ProcessResult:
    """Render a project with a preset.  Uses separated stems when available."""
    settings_obj = _settings(settings)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = _dirs(out_dir)
    raw = dict(params or {})
    source = Path(source_path)

    vocal_stem = paths["stems"] / "vocals.wav"
    inst_stem = paths["stems"] / "instrumental.wav"
    stems = None
    if vocal_stem.is_file() and inst_stem.is_file():
        stems = {"vocals": vocal_stem, "instrumental": inst_stem}

    output_format = str(raw.get("output_format") or "m4a").lower().lstrip(".")
    if output_format not in {"wav", "mp3", "m4a", "flac", "aac"}:
        output_format = "m4a"

    _emit(progress, "processing", 2, f"准备 {preset} 处理")
    render_params = {key: value for key, value in raw.items() if key not in {"output_format", "mux_video", "format"}}

    mux_requested = bool(raw.get("mux_video"))
    has_video = False
    if mux_requested:
        try:
            has_video = media.probe(source).has_video
        except MediaError:
            has_video = False

    audio_out = paths["processed"] / f"{preset}.{output_format}"
    try:
        result = processing.render(
            source if source.exists() else None,
            audio_out,
            preset,
            params=render_params,
            stems=stems,
            progress=progress,
        )
    except processing.ProcessError as exc:
        raise PipelineError(str(exc), "processing") from exc
    except MediaError as exc:
        raise PipelineError(f"处理失败：{exc}", "processing") from exc

    final_path = Path(result.output_path)
    if mux_requested and has_video:
        _emit(progress, "processing", 96, "回贴视频")
        try:
            muxed = media.mux_video(source, final_path, paths["processed"] / f"{preset}.mp4")
            result.output_path = str(muxed.resolve())
            result.output_url = _api_url(project_id, muxed, out_dir)
            result.format = "mp4"
            result.warnings = _dedupe([*result.warnings, "已把处理后音频回贴到原视频"])
            final_path = muxed
        except MediaError as exc:
            result.warnings = _dedupe([*result.warnings, f"视频回贴失败，保留音频输出：{exc}"])
            result.output_url = _api_url(project_id, final_path, out_dir)
    else:
        if mux_requested and not has_video:
            result.warnings = _dedupe([*result.warnings, "源文件不是视频，已跳过视频回贴"])
        result.output_url = _api_url(project_id, final_path, out_dir)

    try:
        result.duration = round(float(media.duration(final_path)), 3)
        result.loudness = processing.measure_loudness(final_path)
    except Exception:
        pass
    _emit(progress, "processing", 100, "处理完成")
    return result


# ---------------------------------------------------------------------------
# Read-back helpers for the API layer
# ---------------------------------------------------------------------------

def load_analysis(out_dir: str | Path) -> AnalysisResult | None:
    data = _read_json(Path(out_dir) / "analysis.json")
    if not isinstance(data, dict):
        return None
    try:
        return AnalysisResult.model_validate(data)
    except Exception:
        return None


def load_timeline(out_dir: str | Path) -> Timeline | None:
    data = _read_json(Path(out_dir) / "timeline.json")
    if isinstance(data, dict):
        try:
            return Timeline.model_validate(data)
        except Exception:
            return None
    cached = load_analysis(out_dir)
    return cached.timeline if cached else None


def load_timbre(out_dir: str | Path) -> TimbreResult | None:
    data = _read_json(Path(out_dir) / "timbre.json")
    if isinstance(data, dict):
        try:
            return TimbreResult.model_validate(data)
        except Exception:
            return None
    cached = load_analysis(out_dir)
    return cached.timbre if cached else None


def artifacts_from_result(result: AnalysisResult) -> list[Artifact]:
    return list(result.artifacts)
