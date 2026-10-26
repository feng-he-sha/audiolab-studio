"""SenseVoice speech-to-text via sherpa-onnx.

The model is a local SenseVoiceSmall int8 ONNX bundle (``model.int8.onnx`` +
``tokens.txt``). It is intentionally loaded lazily so importing AudioLab does not
require sherpa-onnx or the model files.

Default model discovery order:
1. explicit ``model_dir`` / ``settings.asr_model_dir`` / ``AUDIOLAB_SENSEVOICE_DIR``
2. ``<models>/sensevoice`` and ``<models>/sensevoice-onnx``
3. ``~/.dsh/speech-to-text/sensevoice/models/sensevoice-onnx`` (existing DSH install)
"""

from __future__ import annotations

import importlib.util
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from audiolab import config
from audiolab.core import media
from audiolab.core.schemas import Timeline, TranscriptResult, TranscriptSegment

ProgressFn = Callable[[str, float, str], None]
_CACHE: dict[tuple[str, str], Any] = {}

_LANG_NAMES = {
    "zh": "中文",
    "en": "英文",
    "ja": "日文",
    "ko": "韩文",
    "yue": "粤语",
}


class ASRError(RuntimeError):
    pass


def model_candidates(explicit: str | Path | None = None) -> list[Path]:
    values: list[Any] = [
        explicit,
        config.load_settings().asr_model_dir,
        os.environ.get("AUDIOLAB_SENSEVOICE_DIR"),
        config.MODELS / "sensevoice",
        config.MODELS / "sensevoice-onnx",
        config.MODELS / "asr" / "sensevoice",
        Path.home() / ".dsh" / "speech-to-text" / "sensevoice" / "models" / "sensevoice-onnx",
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        path = Path(value).expanduser()
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def resolve_model_dir(explicit: str | Path | None = None) -> Path | None:
    for path in model_candidates(explicit):
        if not path.is_dir():
            continue
        has_model = (path / "model.int8.onnx").is_file() or (path / "model.onnx").is_file()
        if has_model and (path / "tokens.txt").is_file():
            return path
    return None


def available(explicit: str | Path | None = None) -> bool:
    return resolve_model_dir(explicit) is not None and importlib.util.find_spec("sherpa_onnx") is not None


def _strip_tags(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"<\|.*?\|>", "", value).strip()


def _tag_value(value: str | None) -> str:
    """Extract ``<|zh|>`` -> ``zh`` without dropping the value."""
    if not value:
        return ""
    match = re.search(r"<\|([^|]+)\|>", value)
    return (match.group(1) if match else value).strip()


def _load_recognizer(model_dir: Path, language: str):
    key = (str(model_dir), language)
    if key in _CACHE:
        return _CACHE[key]
    try:
        import sherpa_onnx
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise ASRError("sherpa-onnx 未安装：pip install sherpa-onnx") from exc

    model_path = model_dir / "model.int8.onnx"
    if not model_path.is_file():
        model_path = model_dir / "model.onnx"
    tokens = model_dir / "tokens.txt"
    lang = "" if (language or "auto").lower() == "auto" else language.lower()
    started = time.time()
    try:
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_path),
            tokens=str(tokens),
            num_threads=4,
            use_itn=True,
            language=lang,
            provider="cpu",
            debug=False,
        )
    except Exception as exc:
        raise ASRError(f"SenseVoice 模型加载失败：{exc}") from exc
    _CACHE[key] = recognizer
    _CACHE[("__load_seconds__", key[0])] = time.time() - started
    return recognizer


def _segments(timeline: Timeline | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(timeline, Timeline):
        return [s.model_dump() for s in timeline.segments]
    return list(timeline.get("segments") or [])


def transcribe(
    vocals_path: str | Path,
    timeline: Timeline | dict[str, Any],
    model_dir: str | Path | None = None,
    language: str = "auto",
    max_segments: int = 200,
    progress: ProgressFn | None = None,
) -> TranscriptResult:
    """Transcribe vocal/mixed timeline segments with SenseVoice."""
    resolved = resolve_model_dir(model_dir)
    if not resolved:
        raise ASRError(
            "未找到 SenseVoice 模型。请在本机准备 model.int8.onnx + tokens.txt，"
            "或在设置里填写 ASR 模型目录。"
        )
    if importlib.util.find_spec("sherpa_onnx") is None:
        raise ASRError("sherpa-onnx 未安装：pip install sherpa-onnx")

    vocals_path = Path(vocals_path)
    wav = media.decode_mono(vocals_path, 16000)
    if wav.size == 0:
        raise ASRError("人声音轨为空，无法转写")
    duration = float(wav.size / 16000)
    recognizer = _load_recognizer(resolved, language)

    candidates: list[dict[str, Any]] = []
    for seg in _segments(timeline):
        label = seg.get("user_label") or seg.get("label") or ""
        start = float(seg.get("start") or 0.0)
        stop = float(seg.get("stop") or 0.0)
        if label not in {"vocals", "vocals+music"}:
            continue
        if stop - start < 0.25:
            continue
        candidates.append({"start": start, "stop": stop})
    if not candidates:
        return TranscriptResult(
            backend="sensevoice",
            model_dir=str(resolved),
            language=language,
            text="",
            segments=[],
            duration=duration,
            warnings=["没有检测到可转写的人声分段"],
        )

    warnings: list[str] = []
    if len(candidates) > max_segments:
        warnings.append(f"人声分段过多（{len(candidates)}），仅转写前 {max_segments} 段")
        candidates = candidates[:max_segments]

    segments: list[TranscriptSegment] = []
    started = time.time()
    for index, candidate in enumerate(candidates):
        # Decode with a little context, but keep the subtitle timestamps on the
        # original segment boundaries so adjacent cues never overlap.
        start = float(candidate["start"])
        stop = float(candidate["stop"])
        audio_start = max(0.0, start - 0.15)
        audio_stop = min(duration, stop + 0.15)
        chunk = wav[int(audio_start * 16000) : int(audio_stop * 16000)]
        if chunk.size < 1600:
            continue
        try:
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, np.asarray(chunk, dtype=np.float32))
            recognizer.decode_stream(stream)
            result = stream.result
            text = _strip_tags(getattr(result, "text", ""))
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    id=index + 1,
                    start=round(start, 3),
                    stop=round(stop, 3),
                    text=text,
                    language=_tag_value(getattr(result, "lang", "")),
                    emotion=_tag_value(getattr(result, "emotion", "")),
                    event=_tag_value(getattr(result, "event", "")),
                )
            )
        except Exception as exc:
            warnings.append(f"第 {index + 1} 段转写失败：{exc}")
        if progress:
            progress("asr", 100.0 * (index + 1) / len(candidates), f"转写 {index + 1}/{len(candidates)} 段")

    if not segments:
        warnings.append("SenseVoice 没有返回文本（可能全是音乐/静音）")
    full_text = "".join(s.text for s in segments) if _is_cjk(segments) else " ".join(s.text for s in segments)
    languages = [s.language for s in segments if s.language]
    aggregate_lang = max(set(languages), key=languages.count) if languages else (language or "auto")
    elapsed = time.time() - started
    return TranscriptResult(
        backend="sensevoice",
        model_dir=str(resolved),
        language=aggregate_lang,
        text=full_text.strip(),
        segments=segments,
        duration=duration,
        elapsed=round(elapsed, 3),
        warnings=warnings,
    )


def _is_cjk(segments: list[TranscriptSegment]) -> bool:
    if not segments:
        return True
    sample = "".join(s.text for s in segments[:8])
    cjk = len(re.findall(r"[\u4e00-\u9fff]", sample))
    return cjk > max(3, len(sample) * 0.15)


# ---------------------------------------------------------------------------
# Subtitle export
# ---------------------------------------------------------------------------


def _timestamp(seconds: float, sep: str = ",") -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        secs += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millis:03d}"


def to_srt(result: TranscriptResult) -> str:
    lines: list[str] = []
    for index, seg in enumerate(result.segments, start=1):
        lines.extend([str(index), f"{_timestamp(seg.start)} --> {_timestamp(seg.stop)}", seg.text, ""])
    return "\n".join(lines)


def to_vtt(result: TranscriptResult) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for seg in result.segments:
        lines.extend([f"{_timestamp(seg.start, '.')} --> {_timestamp(seg.stop, '.')}", seg.text, ""])
    return "\n".join(lines)


def to_txt(result: TranscriptResult) -> str:
    if result.segments:
        return "\n".join(f"[{_timestamp(s.start, '.')[:8]}] {s.text}" for s in result.segments)
    return result.text


def language_name(code: str) -> str:
    return _LANG_NAMES.get((code or "").strip("<>|"), code or "")
