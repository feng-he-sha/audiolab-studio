"""Preset-based audio processing with two-pass EBU R128 loudness normalisation.

Rendering is pure ffmpeg: filter graphs are passed as argument lists, so paths
with spaces or Chinese characters are safe.  Two-pass ``loudnorm`` measures the
signal first and then applies a linear gain correction; if measurement fails the
render falls back to a single-pass loudnorm and records a warning.

Presets match the API contract: ``douyin``, ``podcast``, ``movie``, ``music``,
``clean``.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Sequence

from audiolab.core import media
from audiolab.core.media import MediaError

__all__ = [
    "PRESETS",
    "PRESET_IDS",
    "presets",
    "get_preset",
    "render",
    "measure_loudness",
    "mux_video",
    "ProcessError",
]

ProgressFn = Callable[[str, float, str], None]

mux_video = media.mux_video  # re-exported for pipeline convenience


class ProcessError(RuntimeError):
    """Raised when processing cannot be completed."""


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict[str, Any]] = {
    "douyin": {
        "id": "douyin",
        "label": "抖音短视频",
        "description": "削低频 + 轻降噪 + -14 LUFS，适配抖音/视频号上传。",
        "capabilities": ["highpass", "denoise", "loudnorm", "fade"],
        "defaults": {
            "target_lufs": -14.0,
            "true_peak": -1.5,
            "lra": 11.0,
            "highpass": 70,
            "denoise": True,
            "fade_in": 0.05,
            "fade_out": 0.1,
        },
        "params_schema": {
            "target_lufs": {"type": "number", "label": "目标响度 (LUFS)", "min": -30.0, "max": -5.0, "step": 0.5, "default": -14.0},
            "true_peak": {"type": "number", "label": "真峰值上限 (dBTP)", "min": -6.0, "max": 0.0, "step": 0.1, "default": -1.5},
            "highpass": {"type": "number", "label": "高通滤波 (Hz)", "min": 0, "max": 200, "step": 5, "default": 70},
            "denoise": {"type": "boolean", "label": "轻度降噪", "default": True},
            "fade_in": {"type": "number", "label": "淡入 (秒)", "min": 0.0, "max": 3.0, "step": 0.01, "default": 0.05},
            "fade_out": {"type": "number", "label": "淡出 (秒)", "min": 0.0, "max": 5.0, "step": 0.01, "default": 0.1},
        },
    },
    "podcast": {
        "id": "podcast",
        "label": "播客口播",
        "description": "降噪 + 高通 + 首尾静音裁剪 + -16 LUFS，适合长口播。",
        "capabilities": ["denoise", "highpass", "silenceremove", "loudnorm"],
        "defaults": {
            "target_lufs": -16.0,
            "true_peak": -1.5,
            "lra": 11.0,
            "highpass": 80,
            "denoise": True,
            "silence": True,
            "fade_in": 0.02,
            "fade_out": 0.05,
        },
        "params_schema": {
            "target_lufs": {"type": "number", "label": "目标响度 (LUFS)", "min": -30.0, "max": -5.0, "step": 0.5, "default": -16.0},
            "highpass": {"type": "number", "label": "高通滤波 (Hz)", "min": 0, "max": 200, "step": 5, "default": 80},
            "denoise": {"type": "boolean", "label": "降噪", "default": True},
            "silence": {"type": "boolean", "label": "裁剪首尾静音", "default": True},
            "fade_in": {"type": "number", "label": "淡入 (秒)", "min": 0.0, "max": 3.0, "step": 0.01, "default": 0.02},
            "fade_out": {"type": "number", "label": "淡出 (秒)", "min": 0.0, "max": 5.0, "step": 0.01, "default": 0.05},
        },
    },
    "movie": {
        "id": "movie",
        "label": "影视混剪",
        "description": "人声触发伴奏闪避（sidechain duck）+ 混音 + -16 LUFS。",
        "capabilities": ["stem_mix", "sidechain_duck", "loudnorm"],
        "defaults": {
            "target_lufs": -16.0,
            "true_peak": -1.5,
            "lra": 11.0,
            "duck_threshold": 0.03,
            "duck_ratio": 8.0,
            "duck_attack": 20,
            "duck_release": 400,
            "vocals_gain": 0.0,
            "instrumental_gain": 0.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
        },
        "params_schema": {
            "target_lufs": {"type": "number", "label": "目标响度 (LUFS)", "min": -30.0, "max": -5.0, "step": 0.5, "default": -16.0},
            "duck_threshold": {"type": "number", "label": "闪避阈值", "min": 0.001, "max": 0.5, "step": 0.001, "default": 0.03},
            "duck_ratio": {"type": "number", "label": "闪避压缩比", "min": 1.0, "max": 20.0, "step": 0.5, "default": 8.0},
            "duck_attack": {"type": "number", "label": "启动时间 (ms)", "min": 1, "max": 200, "step": 1, "default": 20},
            "duck_release": {"type": "number", "label": "释放时间 (ms)", "min": 50, "max": 2000, "step": 10, "default": 400},
            "vocals_gain": {"type": "number", "label": "人声增益 (dB)", "min": -12.0, "max": 12.0, "step": 0.5, "default": 0.0},
            "instrumental_gain": {"type": "number", "label": "伴奏增益 (dB)", "min": -12.0, "max": 12.0, "step": 0.5, "default": 0.0},
        },
    },
    "music": {
        "id": "music",
        "label": "音乐混音",
        "description": "按分离音轨增益混合人声与伴奏（默认 +2 / -1 dB）+ -14 LUFS。",
        "capabilities": ["stem_mix", "loudnorm"],
        "defaults": {
            "target_lufs": -14.0,
            "true_peak": -1.5,
            "lra": 11.0,
            "vocals_gain": 2.0,
            "instrumental_gain": -1.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
        },
        "params_schema": {
            "target_lufs": {"type": "number", "label": "目标响度 (LUFS)", "min": -30.0, "max": -5.0, "step": 0.5, "default": -14.0},
            "vocals_gain": {"type": "number", "label": "人声增益 (dB)", "min": -12.0, "max": 12.0, "step": 0.5, "default": 2.0},
            "instrumental_gain": {"type": "number", "label": "伴奏增益 (dB)", "min": -12.0, "max": 12.0, "step": 0.5, "default": -1.0},
        },
    },
    "clean": {
        "id": "clean",
        "label": "基础清理",
        "description": "裁剪首尾静音 + 淡入淡出 + -14 LUFS，无降噪不改音色。",
        "capabilities": ["silenceremove", "fade", "loudnorm"],
        "defaults": {
            "target_lufs": -14.0,
            "true_peak": -1.5,
            "lra": 11.0,
            "silence": True,
            "highpass": 0,
            "denoise": False,
            "fade_in": 0.05,
            "fade_out": 0.1,
        },
        "params_schema": {
            "target_lufs": {"type": "number", "label": "目标响度 (LUFS)", "min": -30.0, "max": -5.0, "step": 0.5, "default": -14.0},
            "silence": {"type": "boolean", "label": "裁剪首尾静音", "default": True},
            "fade_in": {"type": "number", "label": "淡入 (秒)", "min": 0.0, "max": 3.0, "step": 0.01, "default": 0.05},
            "fade_out": {"type": "number", "label": "淡出 (秒)", "min": 0.0, "max": 5.0, "step": 0.01, "default": 0.1},
        },
    },
}
PRESET_IDS = tuple(PRESETS)


def presets() -> list[dict[str, Any]]:
    """Preset metadata list for ``/api/engines``-style endpoints."""
    return [PRESETS[key] for key in PRESET_IDS]


def get_preset(preset: str) -> dict[str, Any]:
    key = (preset or "").strip().lower()
    if key not in PRESETS:
        raise ProcessError(f"未知预设 {preset!r}，可选：{', '.join(PRESET_IDS)}")
    return PRESETS[key]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _emit(progress: ProgressFn | None, stage: str, pct: float, message: str) -> None:
    if progress is None:
        return
    try:
        progress(stage, float(pct), message)
    except Exception:
        pass


def _num(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _db(value: Any, default: float = 0.0) -> str:
    gain = _num(value, default)
    return f"{gain:+.2f}"


def _suffix_format(path: Path) -> tuple[str, list[str], str]:
    """Return ``(format_name, codec_args, mime)`` for an output path."""
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "mp3", ["-c:a", "libmp3lame", "-b:a", "192k"], "audio/mpeg"
    if suffix in {".m4a", ".aac", ".mp4"}:
        return "m4a", ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"], "audio/mp4"
    if suffix == ".flac":
        return "flac", ["-c:a", "flac"], "audio/flac"
    if suffix == ".ogg":
        return "ogg", ["-c:a", "libvorbis", "-q:a", "5"], "audio/ogg"
    return "wav", ["-c:a", "pcm_s16le"], "audio/wav"


_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def _parse_loudnorm_json(text: str | None) -> dict[str, str] | None:
    if not text:
        return None
    for match in reversed(_LOUDNORM_JSON.findall(text)):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "input_i" in data:
            return {str(k): str(v) for k, v in data.items()}
    return None


def _valid_measurement(data: dict[str, str]) -> bool:
    try:
        if float(data.get("input_i", "-inf")) <= -70.0:
            return False
        float(data.get("input_tp", "-inf"))
        float(data.get("input_lra", "0"))
        float(data.get("input_thresh", "-inf"))
        float(data.get("target_offset", "0"))
    except (TypeError, ValueError):
        return False
    return True


def _loudnorm_filter(target_lufs: float, true_peak: float, lra: float, measured: dict[str, str] | None) -> str:
    base = f"loudnorm=I={target_lufs:.1f}:TP={true_peak:.1f}:LRA={lra:.1f}"
    if measured is None:
        return base + ":print_format=json"
    return (
        base
        + f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        + f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        + f":offset={measured.get('target_offset', '0')}:linear=true:print_format=summary"
    )


def _silence_filter() -> str:
    # Trim leading/trailing silence only (conservative for podcasts).
    return (
        "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB:"
        "stop_periods=1:stop_duration=0.3:stop_threshold=-50dB"
    )


def _build_base_graph(
    preset: str,
    cfg: dict[str, Any],
    duration: float,
    has_stems: bool,
    has_vocals: bool,
    warnings: list[str],
) -> tuple[str, int]:
    """Build the pre-loudnorm filter graph, ending in the ``[mix]`` label.

    Returns ``(complex_filter, input_count)``.
    """
    filters: list[str] = []
    if bool(cfg.get("silence")):
        filters.append(_silence_filter())
    highpass = _num(cfg.get("highpass"), 0.0)
    if highpass > 0:
        filters.append(f"highpass=f={int(round(highpass))}")
    if bool(cfg.get("denoise")):
        filters.append("afftdn=nf=-30")

    if preset == "movie" and has_stems and has_vocals:
        threshold = min(0.95, max(0.001, _num(cfg.get("duck_threshold"), 0.03)))
        ratio = min(20.0, max(1.0, _num(cfg.get("duck_ratio"), 8.0)))
        attack = min(2000.0, max(0.01, _num(cfg.get("duck_attack"), 20.0)))
        release = min(9000.0, max(10.0, _num(cfg.get("duck_release"), 400.0)))
        inst_gain = _db(cfg.get("instrumental_gain"), 0.0)
        voc_gain = _db(cfg.get("vocals_gain"), 0.0)
        graph = ";".join(
            [
                f"[0:a]volume={inst_gain}dB[main]",
                f"[1:a]volume={voc_gain}dB,asplit=2[sc][voc]",
                f"[main][sc]sidechaincompress=threshold={threshold:.4f}:ratio={ratio:.2f}"
                f":attack={attack:.0f}:release={release:.0f}:makeup=1[ducked]",
                "[ducked][voc]amix=inputs=2:duration=longest:normalize=0[mix]",
            ]
        )
        return graph, 2

    if preset == "music" and has_stems:
        inst_gain = _db(cfg.get("instrumental_gain"), -1.0)
        voc_gain = _db(cfg.get("vocals_gain"), 2.0)
        graph = ";".join(
            [
                f"[0:a]volume={inst_gain}dB[inst]",
                f"[1:a]volume={voc_gain}dB[voc]",
                "[inst][voc]amix=inputs=2:duration=longest:normalize=0[mix]",
            ]
        )
        return graph, 2

    if has_stems:
        warnings.append("该预设为单轨处理，已把分离音轨混合后处理")
        graph = (
            "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0[mix]"
        )
        return graph, 2

    chain = ",".join(filters) if filters else "anull"
    return f"[0:a]{chain}[mix]", 1


def _build_command(
    inputs: Sequence[Path],
    graph: str,
    post_filters: Sequence[str],
    out: Path,
    codec_args: Sequence[str],
    sample_rate: int,
    pass1: bool,
) -> list[str]:
    filters = list(post_filters)
    if pass1:
        cmd = [
            media.ffmpeg_path(), "-y", "-hide_banner", "-nostdin", "-v", "info",
        ]
        for item in inputs:
            cmd += ["-i", str(item)]
        cmd += ["-filter_complex", f"{graph};[mix]{','.join(filters)}[out]", "-map", "[out]", "-f", "null", "-"]
        return cmd
    # second pass appends measured loudnorm via `filters`
    cmd = [
        media.ffmpeg_path(), "-y", "-hide_banner", "-nostdin", "-v", "error",
    ]
    for item in inputs:
        cmd += ["-i", str(item)]
    cmd += [
        "-filter_complex", f"{graph};[mix]{','.join(filters)}[out]",
        "-map", "[out]", "-ar", str(int(sample_rate)), "-ac", "2",
        *codec_args, "-vn", str(out),
    ]
    return cmd


def _format_for_output(path: Path) -> tuple[str, list[str], str]:
    return _suffix_format(path)


def _resolve_stems(
    stems: dict[str, Any] | None,
    warnings: list[str],
) -> tuple[Path | None, Path | None]:
    if not stems:
        return None, None
    vocals = stems.get("vocals")
    instrumental = stems.get("instrumental")
    vocals_path = Path(vocals) if vocals else None
    inst_path = Path(instrumental) if instrumental else None
    if vocals_path is not None and not vocals_path.is_file():
        warnings.append(f"人声音轨不存在：{vocals_path}")
        vocals_path = None
    if inst_path is not None and not inst_path.is_file():
        warnings.append(f"伴奏音轨不存在：{inst_path}")
        inst_path = None
    return vocals_path, inst_path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def measure_loudness(path: str | Path) -> Any:
    """Measure integrated loudness / true peak / LRA with ffmpeg loudnorm."""
    from audiolab.core.schemas import Loudness

    p = Path(path)
    if not p.exists():
        return Loudness()
    cmd = [
        media.ffmpeg_path(), "-hide_banner", "-nostdin", "-v", "info",
        "-i", str(p), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    try:
        completed = media.run(cmd)
    except MediaError:
        return Loudness()
    data = _parse_loudnorm_json(completed.stderr)

    def value(key: str) -> float | None:
        if not data:
            return None
        try:
            out = float(data.get(key, "nan"))
        except (TypeError, ValueError):
            return None
        return None if not math.isfinite(out) else round(out, 2)

    if data is None:
        return Loudness()
    return Loudness(
        integrated_lufs=value("input_i"),
        true_peak_dbtp=value("input_tp"),
        lra=value("input_lra"),
    )


def render(
    input_path: str | Path | None,
    output_path: str | Path,
    preset: str,
    params: dict[str, Any] | None = None,
    stems: dict[str, Any] | None = None,
    progress: ProgressFn | None = None,
) -> Any:
    """Render an audio file with the given preset.

    ``stems`` may contain ``{"vocals": path, "instrumental": path}``; the
    ``movie`` and ``music`` presets use them directly, other presets fall back to
    a stem mix.  Returns :class:`~audiolab.core.schemas.ProcessResult` with
    ``output_url`` left empty (the pipeline fills the API URL).
    """
    from audiolab.core.schemas import ProcessResult

    meta = get_preset(preset)
    preset_id = str(meta["id"])
    cfg: dict[str, Any] = dict(meta["defaults"])
    if params:
        cfg.update({key: value for key, value in params.items() if value is not None})
    cfg["target_lufs"] = _num(cfg.get("target_lufs"), -14.0)
    cfg["true_peak"] = _num(cfg.get("true_peak"), -1.5)
    cfg["lra"] = _num(cfg.get("lra"), 11.0)
    sample_rate = int(_num(cfg.get("sample_rate"), 48000.0))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt, codec_args, _mime = _format_for_output(out)
    warnings: list[str] = []

    vocals_path, instrumental_path = _resolve_stems(stems, warnings)
    input_file = Path(input_path) if input_path else None
    if input_file is not None and not input_file.is_file():
        warnings.append(f"输入文件不存在：{input_file}")
        input_file = None

    # Decide inputs.
    use_stems = False
    if preset_id == "movie":
        if instrumental_path is not None and vocals_path is not None:
            inputs = [instrumental_path, vocals_path]
            use_stems = True
        elif instrumental_path is not None:
            inputs = [instrumental_path]
            warnings.append("未提供人声音轨，已跳过闪避处理")
        elif vocals_path is not None:
            inputs = [vocals_path]
            warnings.append("未提供伴奏音轨，仅处理人声")
        elif input_file is not None:
            inputs = [input_file]
            warnings.append("无分离音轨，闪避已跳过，使用原始混音")
        else:
            raise ProcessError("没有可处理的音频输入")
    elif preset_id == "music":
        if instrumental_path is not None and vocals_path is not None:
            inputs = [instrumental_path, vocals_path]
            use_stems = True
        elif input_file is not None:
            inputs = [input_file]
            warnings.append("无分离音轨，仅对原始混音做响度处理")
        elif instrumental_path is not None or vocals_path is not None:
            inputs = [instrumental_path or vocals_path]
            warnings.append("仅有单条音轨，直接处理该音轨")
        else:
            raise ProcessError("没有可处理的音频输入")
    else:
        if input_file is not None:
            inputs = [input_file]
            if instrumental_path is not None and vocals_path is not None:
                # Prefer the full mix; stems are intentionally ignored here.
                pass
        elif instrumental_path is not None and vocals_path is not None:
            inputs = [instrumental_path, vocals_path]
            use_stems = True
            warnings.append("缺少原始混音，已使用分离音轨混合")
        elif input_file is None:
            raise ProcessError("没有可处理的音频输入")

    if out.suffix.lower() == "":
        out = out.with_suffix(".wav")
        fmt, codec_args, _mime = _format_for_output(out)
    if input_file is not None and input_file.resolve() == out.resolve():
        raise ProcessError("输出路径不能与输入路径相同")

    # Duration for fades (max over inputs).
    duration = 0.0
    for item in inputs:
        try:
            duration = max(duration, float(media.duration(item)))
        except Exception:
            continue

    _emit(progress, "processing", 5, "构建处理滤镜")
    graph, _count = _build_base_graph(
        preset_id,
        cfg,
        duration,
        has_stems=use_stems or len(inputs) == 2,
        has_vocals=vocals_path is not None,
        warnings=warnings,
    )

    post_filters: list[str] = []
    fade_in = _num(cfg.get("fade_in"), 0.0)
    fade_out = _num(cfg.get("fade_out"), 0.0)
    if fade_in > 0:
        post_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0 and duration > 0:
        start = max(0.0, duration - fade_out)
        post_filters.append(f"afade=t=out:st={start:.3f}:d={fade_out:.3f}")

    loudnorm = _loudnorm_filter(cfg["target_lufs"], cfg["true_peak"], cfg["lra"], None)

    # ---- Pass 1: measure -------------------------------------------------
    _emit(progress, "processing", 15, "响度测量（第一遍）")
    measured: dict[str, str] | None = None
    try:
        pass1 = media.run(_build_command(inputs, graph, [*post_filters, loudnorm], out, codec_args, sample_rate, pass1=True))
        measured = _parse_loudnorm_json(pass1.stderr)
        if measured is not None and not _valid_measurement(measured):
            warnings.append("音频过轻或接近静音，已跳过线性响度校正")
            measured = None
    except MediaError as exc:
        warnings.append(f"两遍 loudnorm 测量失败，退回单遍：{exc}")

    if measured is None:
        measured_filter = _loudnorm_filter(cfg["target_lufs"], cfg["true_peak"], cfg["lra"], None)
        warnings.append("使用单遍 loudnorm（动态模式）")
    else:
        measured_filter = _loudnorm_filter(cfg["target_lufs"], cfg["true_peak"], cfg["lra"], measured)

    _emit(progress, "processing", 55, "渲染输出（第二遍）")
    final_filters = [*post_filters, measured_filter]
    cmd = _build_command(inputs, graph, final_filters, out, codec_args, sample_rate, pass1=False)
    try:
        media.run(cmd)
    except MediaError as exc:
        raise ProcessError(f"渲染失败：{exc}") from exc
    if not out.exists() or out.stat().st_size == 0:
        raise ProcessError(f"渲染输出为空：{out.name}")

    _emit(progress, "processing", 88, "复测响度")
    loudness = measure_loudness(out)
    try:
        out_duration = float(media.duration(out))
    except Exception:
        out_duration = duration

    _emit(progress, "processing", 100, "处理完成")
    return ProcessResult(
        preset=preset_id,
        output_path=str(out.resolve()),
        output_url="",
        format=fmt,
        duration=round(out_duration, 3),
        loudness=loudness,
        warnings=warnings,
    )
