"""FFmpeg / ffprobe wrappers for AudioLab Studio.

This module is the single place that shells out to media tooling.  It never
imports torch and only imports numpy/soundfile/librosa *inside* functions, so
importing :mod:`audiolab.core.media` from the API process stays cheap.

All subprocess calls use argument lists (never ``shell=True``), UTF-8 decoding
and a hidden console window on Windows, which makes paths with spaces or
Chinese characters safe.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from audiolab import config
from audiolab.core.schemas import MediaInfo

__all__ = [
    "MediaError",
    "AUDIO_EXTS",
    "VIDEO_EXTS",
    "MEDIA_EXTS",
    "probe",
    "extract_audio",
    "decode_mono",
    "decode_stereo",
    "duration",
    "sha256_file",
    "make_preview",
    "compute_peaks",
    "write_wav",
    "mux_video",
    "run",
    "ffmpeg_path",
    "ffprobe_path",
    "is_media_file",
    "resample",
]

AUDIO_EXTS = {
    ".wav", ".wave", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".aiff", ".aif", ".ape", ".alac", ".caf", ".amr",
}
VIDEO_EXTS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".wmv", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp",
}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_STDERR_TAIL = 1600


class MediaError(RuntimeError):
    """Raised when ffmpeg/ffprobe fails or a media file is unusable."""


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------

def _find_tool(env_key: str, name: str) -> str:
    """Locate ffmpeg/ffprobe: env override -> PATH -> bundled vendor dir."""
    override = os.environ.get(env_key)
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    exe_name = f"{name}.exe" if sys.platform == "win32" else name
    for base in (config.ROOT / "vendor" / "ffmpeg" / "bin", config.ROOT / "tools" / "ffmpeg" / "bin"):
        candidate = base / exe_name
        if candidate.exists():
            return str(candidate)
    return name  # let run() raise a clear MediaError


def ffmpeg_path() -> str:
    return _find_tool("AUDIOLAB_FFMPEG", config.ffmpeg_exe())


def ffprobe_path() -> str:
    return _find_tool("AUDIOLAB_FFPROBE", config.ffprobe_exe())


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def run(cmd: Sequence[str | Path], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command as an argument list and return its completed process.

    ``stdout`` / ``stderr`` are decoded UTF-8 strings.  Raises :class:`MediaError`
    with the tail of stderr on a non-zero exit, a missing executable or timeout.
    """
    args = [str(c) for c in cmd]
    if not args:
        raise MediaError("空命令")
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise MediaError(
            f"找不到可执行文件：{args[0]}。请安装 ffmpeg 并加入 PATH，"
            f"或设置环境变量 AUDIOLAB_FFMPEG / AUDIOLAB_FFPROBE。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"命令超时（{timeout}s）：{os.path.basename(args[0])}") from exc
    except OSError as exc:  # pragma: no cover - platform specific
        raise MediaError(f"无法启动命令 {args[0]}：{exc}") from exc

    if proc.returncode != 0:
        tail = _tail(proc.stderr) or _tail(proc.stdout) or "(无输出)"
        raise MediaError(f"命令失败（退出码 {proc.returncode}）：{os.path.basename(args[0])}\n{tail}")
    return proc


def _tail(text: str | None, limit: int = _STDERR_TAIL) -> str:
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def _run_bytes(cmd: Sequence[str | Path], timeout: float | None = None) -> bytes:
    """Run a command returning raw stdout bytes (used for PCM piping)."""
    args = [str(c) for c in cmd]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise MediaError(f"找不到可执行文件：{args[0]}。请安装 ffmpeg 并加入 PATH。") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"命令超时（{timeout}s）：{os.path.basename(args[0])}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        raise MediaError(f"命令失败（退出码 {proc.returncode}）：\n{_tail(err)}")
    return proc.stdout


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out and abs(out) != float("inf") else 0.0


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def ffprobe_json(path: str | Path) -> dict[str, Any]:
    """Return the raw ``ffprobe -show_format -show_streams`` JSON."""
    p = Path(path)
    if not p.exists():
        raise MediaError(f"文件不存在：{p}")
    cmd = [
        ffprobe_path(), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(p),
    ]
    out = run(cmd).stdout
    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise MediaError(f"无法解析 ffprobe 输出：{p.name}") from exc
    if not isinstance(data, dict):
        raise MediaError(f"无法解析 ffprobe 输出：{p.name}")
    return data


def _split_streams(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    streams = data.get("streams") or []
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [
        s for s in streams
        if s.get("codec_type") == "video"
        and not (s.get("disposition") or {}).get("attached_pic")
    ]
    return audio, video


def _duration_from(data: dict[str, Any], audio: list[dict[str, Any]], video: list[dict[str, Any]]) -> float:
    fmt = data.get("format") or {}
    dur = _to_float(fmt.get("duration"))
    if dur <= 0:
        for stream in (*audio, *video):
            dur = max(dur, _to_float(stream.get("duration")))
    return round(dur, 4)


def probe(
    path: str | Path,
    audio_track: int = 0,
    *,
    compute_sha256: bool = False,
) -> MediaInfo:
    """Inspect a media file and return a :class:`MediaInfo` description.

    ``audio_track`` selects the n-th audio stream (0-based).  ``sha256`` is empty
    unless ``compute_sha256`` is true because hashing large files is expensive;
    call :func:`sha256_file` (or pass the flag) when de-duplicating imports.
    """
    p = Path(path)
    if not p.exists():
        raise MediaError(f"文件不存在：{p}")
    if p.is_dir():
        raise MediaError(f"这是一个目录，不是媒体文件：{p}")
    data = ffprobe_json(p)
    audio, video = _split_streams(data)
    if not audio and not video:
        raise MediaError(f"不是可识别的音频/视频文件：{p.name}")
    fmt = data.get("format") or {}

    has_audio = bool(audio)
    idx = 0
    if has_audio:
        idx = max(0, min(int(audio_track), len(audio) - 1))
    stream = audio[idx] if has_audio else {}
    bit_rate = _to_int(stream.get("bit_rate")) or _to_int(fmt.get("bit_rate"))
    size = _to_int(fmt.get("size")) or p.stat().st_size
    first_video = video[0] if video else {}

    return MediaInfo(
        path=str(p.resolve()),
        filename=p.name,
        duration=_duration_from(data, audio, video),
        sample_rate=_to_int(stream.get("sample_rate")),
        channels=_to_int(stream.get("channels")),
        codec=str(stream.get("codec_name") or ""),
        bit_rate=bit_rate,
        size=size,
        sha256=sha256_file(p) if compute_sha256 else "",
        has_video=bool(video),
        video_width=_to_int(first_video.get("width")) or None if video else None,
        video_height=_to_int(first_video.get("height")) or None if video else None,
        has_audio=has_audio,
        audio_track=idx,
    )


def duration(path: str | Path) -> float:
    """Return the duration in seconds (0.0 when unknown)."""
    p = Path(path)
    if not p.exists():
        raise MediaError(f"文件不存在：{p}")
    cmd = [
        ffprobe_path(), "-v", "error",
        "-show_entries", "format=duration:stream=duration",
        "-print_format", "json", str(p),
    ]
    try:
        data = json.loads(run(cmd).stdout or "{}")
    except MediaError:
        return probe(p).duration
    dur = _to_float((data.get("format") or {}).get("duration"))
    if dur <= 0:
        for stream in data.get("streams") or []:
            dur = max(dur, _to_float(stream.get("duration")))
    return round(dur, 4)


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    """Streaming SHA256 of a file."""
    p = Path(path)
    if not p.exists():
        raise MediaError(f"文件不存在：{p}")
    digest = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_media_file(path: str | Path) -> bool:
    p = Path(path)
    return p.suffix.lower() in MEDIA_EXTS


# ---------------------------------------------------------------------------
# Audio extraction / decoding
# ---------------------------------------------------------------------------

_CODEC_BY_SUFFIX = {
    ".wav": "pcm_s16le",
    ".wave": "pcm_s16le",
    ".flac": "flac",
    ".mp3": "libmp3lame",
    ".m4a": "aac",
    ".aac": "aac",
    ".mp4": "aac",
    ".ogg": "libvorbis",
    ".opus": "libopus",
}


def _audio_codec_for(path: Path) -> str:
    return _CODEC_BY_SUFFIX.get(path.suffix.lower(), "pcm_s16le")


def extract_audio(
    src: str | Path,
    dst: str | Path,
    sample_rate: int = 48000,
    channels: int = 2,
    audio_track: int = 0,
) -> Path:
    """Extract one audio track to ``dst`` at the requested rate/channels.

    Raises :class:`MediaError` when the source has no audio track at all (e.g. a
    silent video) or when ffmpeg cannot map the requested track.
    """
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise MediaError(f"文件不存在：{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    data = ffprobe_json(src)
    audio, video = _split_streams(data)
    if not audio:
        kind = "视频文件" if video else "文件"
        raise MediaError(f"{kind}没有音频轨道：{src.name}")
    track = max(0, min(int(audio_track), len(audio) - 1))

    prefix = [
        ffmpeg_path(), "-y", "-hide_banner", "-nostdin", "-v", "error",
        "-i", str(src), "-vn",
    ]
    tail = [
        "-ac", str(int(channels)), "-ar", str(int(sample_rate)),
        "-c:a", _audio_codec_for(dst),
    ]
    target = dst
    try:
        run([*prefix, "-map", f"0:a:{track}", *tail, str(target)])
    except MediaError:
        if track == 0:
            raise
        # Some containers report odd stream indexes; retry with the first track.
        run([*prefix, "-map", "0:a:0", *tail, str(target)])
    if not target.exists() or target.stat().st_size == 0:
        raise MediaError(f"音频抽取失败（输出为空）：{target.name}")
    return target


def _ffmpeg_decode_pcm(path: str | Path, sample_rate: int, channels: int = 1) -> bytes:
    cmd = [
        ffmpeg_path(), "-v", "error", "-nostdin", "-i", str(path),
        "-vn", "-ac", str(int(channels)), "-ar", str(int(sample_rate)),
        "-f", "f32le", "-acodec", "pcm_f32le", "-",
    ]
    return _run_bytes(cmd)


def resample(wav, orig_sr: int, target_sr: int):
    """Resample a mono/stereo float array using librosa -> scipy -> numpy."""
    import numpy as np

    arr = np.asarray(wav, dtype=np.float32)
    if orig_sr == target_sr or arr.size == 0:
        return arr
    try:
        import librosa

        out = librosa.resample(arr, orig_sr=orig_sr, target_sr=target_sr, axis=0)
        return np.ascontiguousarray(out, dtype=np.float32)
    except Exception:
        pass
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(int(orig_sr), int(target_sr))
        out = resample_poly(arr, target_sr // g, orig_sr // g, axis=0)
        return np.ascontiguousarray(out, dtype=np.float32)
    except Exception:
        n_out = int(round(arr.shape[0] * float(target_sr) / float(orig_sr)))
        if n_out <= 1:
            return arr
        old = np.linspace(0.0, 1.0, arr.shape[0], endpoint=False)
        new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        if arr.ndim == 1:
            return np.interp(new, old, arr).astype(np.float32)
        return np.stack([np.interp(new, old, arr[:, c]) for c in range(arr.shape[1])], axis=1).astype(
            np.float32
        )


def decode_mono(path: str | Path, sr: int = 16000):
    """Decode any media file to a mono float32 numpy array at ``sr``."""
    import numpy as np

    p = Path(path)
    if not p.exists():
        raise MediaError(f"文件不存在：{p}")

    mono = None
    orig_sr = 0
    try:
        import soundfile as sf

        data, orig_sr = sf.read(str(p), dtype="float32", always_2d=True)
        if data.size:
            mono = data.mean(axis=1)
    except Exception:
        mono = None

    if mono is None:
        try:
            raw = _ffmpeg_decode_pcm(p, sr)
            mono = np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=False)
            return np.ascontiguousarray(mono)
        except MediaError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise MediaError(f"无法解码音频：{p.name}：{exc}") from exc

    if orig_sr and int(orig_sr) != int(sr):
        mono = resample(mono, int(orig_sr), int(sr))
    return np.ascontiguousarray(np.asarray(mono, dtype=np.float32))


def decode_stereo(path: str | Path, sr: int = 48000):
    """Decode to float32 ``(n, 2)`` stereo at ``sr`` (used for stem math)."""
    import numpy as np

    raw = _ffmpeg_decode_pcm(path, sr, channels=2)
    data = np.frombuffer(raw, dtype="<f4")
    data = data[: (data.size // 2) * 2].reshape(-1, 2)
    return np.ascontiguousarray(data.astype(np.float32, copy=False))


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _run_with_input(
    cmd: Sequence[str | Path],
    stdin_bytes: bytes,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a command feeding raw bytes to stdin (used for PCM piping)."""
    args = [str(c) for c in cmd]
    try:
        proc = subprocess.run(
            args,
            input=stdin_bytes,
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise MediaError(f"找不到可执行文件：{args[0]}。请安装 ffmpeg 并加入 PATH。") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"命令超时（{timeout}s）：{os.path.basename(args[0])}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        raise MediaError(f"命令失败（退出码 {proc.returncode}）：\n{_tail(err)}")
    return proc


def write_wav(path: str | Path, wav, sr: int) -> Path:
    """Write float audio as 16-bit PCM WAV.

    Tries soundfile, then scipy, then an ffmpeg raw-pipe fallback so the
    pipeline still works in minimal environments.
    """
    import numpy as np

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim > 2:
        arr = arr.reshape(arr.shape[0], -1)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    arr = np.clip(arr, -1.0, 1.0)
    try:
        import soundfile as sf

        sf.write(str(p), arr, int(sr), subtype="PCM_16")
        return p
    except Exception:
        pass
    try:
        from scipy.io import wavfile

        wavfile.write(str(p), int(sr), (arr * 32767.0).astype(np.int16))
        return p
    except Exception:
        pass
    channels = 1 if arr.ndim == 1 else int(arr.shape[1])
    interleaved = np.ascontiguousarray(arr, dtype="<f4")
    cmd = [
        ffmpeg_path(), "-y", "-hide_banner", "-nostdin", "-v", "error",
        "-f", "f32le", "-ar", str(int(sr)), "-ac", str(channels), "-i", "-",
        "-c:a", "pcm_s16le", str(p),
    ]
    try:
        _run_with_input(cmd, interleaved.tobytes())
    except MediaError as exc:
        raise MediaError(f"写入 WAV 失败：{p.name}：{exc}") from exc
    return p


# ---------------------------------------------------------------------------
# Preview / peaks / mux
# ---------------------------------------------------------------------------

def make_preview(
    src: str | Path,
    dst: str | Path,
    sample_rate: int = 32000,
    bitrate: str = "96k",
) -> Path:
    """Create a small AAC/M4A preview; falls back to WAV on encoder failure."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.suffix.lower() not in {".m4a", ".mp4", ".aac"}:
        dst = dst.with_suffix(".m4a")
    cmd = [
        ffmpeg_path(), "-y", "-hide_banner", "-nostdin", "-v", "error",
        "-i", str(src), "-vn", "-ac", "2", "-ar", str(int(sample_rate)),
        "-c:a", "aac", "-b:a", str(bitrate), "-movflags", "+faststart", str(dst),
    ]
    try:
        run(cmd)
        if dst.exists() and dst.stat().st_size > 0:
            return dst
    except MediaError:
        pass
    fallback = dst.with_suffix(".wav")
    run([
        ffmpeg_path(), "-y", "-hide_banner", "-nostdin", "-v", "error",
        "-i", str(src), "-vn", "-ac", "2", "-ar", str(int(sample_rate)),
        "-c:a", "pcm_s16le", str(fallback),
    ])
    return fallback


def compute_peaks(src: str | Path, buckets: int = 2000) -> dict[str, Any]:
    """Compute visual min/max peaks for a waveform canvas.

    Decodes through ffmpeg to 4 kHz mono float32 (fast even for long videos) and
    reduces to ``buckets`` pairs.  Returns ``{"duration": float,
    "peaks": [[min, max], ...]}`` with values in [-1, 1].
    """
    import numpy as np

    p = Path(src)
    if not p.exists():
        raise MediaError(f"文件不存在：{p}")
    buckets = max(1, int(buckets))
    total = duration(p)
    try:
        raw = _ffmpeg_decode_pcm(p, 4000, channels=1)
    except MediaError:
        raw = _ffmpeg_decode_pcm(p, 8000, channels=1)
    data = np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=False)
    if data.size == 0:
        return {"duration": round(float(total), 3), "peaks": []}
    n_buckets = min(buckets, data.size)
    per = max(1, data.size // n_buckets)
    usable = (data.size // per) * per
    trimmed = data[:usable].reshape(-1, per)
    if trimmed.shape[0] > n_buckets:
        trimmed = trimmed[:n_buckets]
    mins = trimmed.min(axis=1)
    maxs = trimmed.max(axis=1)
    np.clip(mins, -1.0, 1.0, out=mins)
    np.clip(maxs, -1.0, 1.0, out=maxs)
    peaks = [
        [round(float(lo), 4), round(float(hi), 4)]
        for lo, hi in zip(mins.tolist(), maxs.tolist())
    ]
    if total <= 0:
        total = data.size / 4000.0
    return {"duration": round(float(total), 3), "peaks": peaks}


def mux_video(video: str | Path, audio: str | Path, out: str | Path) -> Path:
    """Put an audio track back onto a video, copying the video stream."""
    video, audio, out = Path(video), Path(audio), Path(out)
    if not video.exists():
        raise MediaError(f"视频文件不存在：{video}")
    if not audio.exists():
        raise MediaError(f"音频文件不存在：{audio}")
    out.parent.mkdir(parents=True, exist_ok=True)
    suffix = out.suffix.lower()
    if suffix in {".mp4", ".mov", ".m4v"}:
        acodec = ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    elif suffix == ".webm":
        acodec = ["-c:a", "libopus", "-b:a", "160k"]
    elif suffix == ".mkv":
        acodec = ["-c:a", "aac", "-b:a", "192k"]
    else:
        acodec = ["-c:a", "aac", "-b:a", "192k"]
    cmd = [
        ffmpeg_path(), "-y", "-hide_banner", "-nostdin", "-v", "error",
        "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        *acodec, "-shortest", str(out),
    ]
    run(cmd)
    if not out.exists() or out.stat().st_size == 0:
        raise MediaError(f"视频合成失败（输出为空）：{out.name}")
    return out
