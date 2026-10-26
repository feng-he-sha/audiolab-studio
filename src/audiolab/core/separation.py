"""Stem separation through ``audio-separator`` with automatic model fallbacks.

Primary model: BS-Roformer (``model_bs_roformer_ep_317_sdr_12.9755.ckpt``).
Fallback: MDX-Net ONNX (``UVR-MDX-NET-Inst_HQ_4.onnx``; ``HQ_3`` is unsupported by
audio-separator 0.47.1 and is remapped by :func:`resolve_fallback`), which is CPU
friendly and covers GPU OOM / model-load failures.

Outputs are always normalised to ``<out_dir>/vocals.wav`` and
``<out_dir>/instrumental.wav`` (48 kHz stereo PCM).  Missing models are fetched
from the Hugging Face mirror (``HF_ENDPOINT`` honoured) and, as a last resort,
by audio-separator's own verified downloader.
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from typing import Any, Callable

from audiolab import config
from audiolab.core import media
from audiolab.core.media import MediaError

__all__ = [
    "SeparateError",
    "separate",
    "ensure_model_file",
    "available",
    "resolve_fallback",
    "MODEL_REPO",
    "MODEL_REPOS",
    "DEFAULT_MODEL",
    "DEFAULT_FALLBACK",
    "FALLBACK_CANDIDATES",
]

ProgressFn = Callable[[str, float, str], None]

MODEL_REPO = "lainlives/audio-separator-models"
MODEL_REPOS = ("lainlives/audio-separator-models", "nomadkaraoke/audio-separator-models")
DEFAULT_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
# audio-separator 0.47.1 no longer ships UVR metadata for
# ``UVR-MDX-NET-Inst_HQ_3.onnx`` (it fails with "Unsupported Model File"), so the
# default fallback is HQ_4, which that version supports and can auto-download.
DEFAULT_FALLBACK = "UVR-MDX-NET-Inst_HQ_4.onnx"
FALLBACK_CANDIDATES = (
    "UVR-MDX-NET-Inst_HQ_4.onnx",
    "UVR-MDX-NET-Inst_HQ_1.onnx",
    "Kim_Inst.onnx",
)
TARGET_SR = 48000


class SeparateError(MediaError):
    """Raised when every separation attempt fails."""


def _emit(progress: ProgressFn | None, stage: str, pct: float, message: str) -> None:
    if progress is None:
        return
    try:
        progress(stage, float(pct), message)
    except Exception:
        pass


def _settings_hf_endpoint() -> str:
    try:
        return config.load_settings().hf_endpoint or ""
    except Exception:
        return ""


def _model_dir(model_dir: str | Path | None) -> Path:
    if model_dir:
        return Path(model_dir)
    try:
        return Path(config.models_dir()) / "separator"
    except Exception:
        return Path(config.MODELS) / "separator"


def _find_local(filename: str | Path, model_dir: Path) -> Path | None:
    candidate = Path(filename)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    for path in (model_dir / candidate.name, Path.cwd() / candidate, model_dir / candidate):
        if path.is_file() and path.stat().st_size > 1024:
            return path
    return None


def ensure_model_file(
    filename: str | Path,
    model_dir: str | Path | None = None,
    *,
    allow_download: bool = True,
) -> Path | None:
    """Return a local path for ``filename``, downloading it when necessary.

    ``None`` means "could not fetch" — callers should fall back / fail clearly.
    With ``allow_download=False`` this only checks the local model directory.
    """
    directory = _model_dir(model_dir)
    directory.mkdir(parents=True, exist_ok=True)
    found = _find_local(filename, directory)
    if found is not None:
        return found
    if not allow_download:
        return None

    endpoint = os.environ.get("HF_ENDPOINT") or _settings_hf_endpoint()
    if endpoint and not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = endpoint
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return None

    name = Path(filename).name
    last_error: Exception | None = None
    for repo in MODEL_REPOS:
        try:
            path = hf_hub_download(repo_id=repo, filename=name, local_dir=str(directory))
            resolved = Path(path)
            if resolved.is_file() and resolved.stat().st_size > 1024:
                return resolved
        except Exception as exc:  # network / 404
            last_error = exc
            continue
    if last_error is not None:
        logging.getLogger(__name__).warning("模型下载失败 %s: %s", name, last_error)
    return None


def available(filename: str, model_dir: str | Path | None = None) -> bool:
    """Whether a separator model file is present locally."""
    return _find_local(filename, _model_dir(model_dir)) is not None


def resolve_fallback(
    requested: str | Path | None = None,
    model_dir: str | Path | None = None,
) -> str:
    """Return an ``audio-separator``-supported MDX fallback filename.

    The configured fallback (``UVR-MDX-NET-Inst_HQ_3.onnx`` in older settings) may
    be unsupported by the installed audio-separator version.  Preference order:
    locally present supported model, then HQ_4 (auto-downloadable), then the
    requested name when it is a supported candidate.
    """
    directory = _model_dir(model_dir)
    requested_name = Path(requested).name if requested else None
    candidates = list(FALLBACK_CANDIDATES)
    if requested_name and requested_name in candidates:
        candidates.remove(requested_name)
        candidates.insert(0, requested_name)
    for name in candidates:
        if _find_local(name, directory) is not None:
            return name
    return candidates[0] if candidates else DEFAULT_FALLBACK


# ---------------------------------------------------------------------------
# audio-separator wiring
# ---------------------------------------------------------------------------

def _arch_kwargs(filename: str, overlap: float | None = None) -> dict[str, Any]:
    """Map a model file to the matching ``audio-separator`` architecture params."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".ckpt":
        params: dict[str, Any] = {}
        if overlap is not None:
            # MDXC overlap is expressed in windows (2-50); default is 8.
            params["overlap"] = max(2, min(50, int(round(float(overlap)))))
        return {"mdxc_params": params} if params else {}
    if suffix in {".onnx", ".mdx"}:
        # NOTE: audio-separator 0.47.1 converts MDX ONNX models to PyTorch and
        # crashes when ``mdx_params`` is supplied ("unsupported operand type(s)
        # for -: 'NoneType' and 'int'"), so MDX models always use their defaults.
        return {}
    if suffix == ".pth":
        params = {}
        if overlap is not None:
            value = float(overlap)
            params["batch_size"] = max(1, min(16, int(round(value))))
        return {"vr_params": params} if params else {}
    return {}


def _new_separator(
    model_dir: Path,
    work_dir: Path,
    arch_kwargs: dict[str, Any],
    progress: ProgressFn | None = None,
) -> Any:
    from audio_separator.separator import Separator

    kwargs: dict[str, Any] = {
        "model_file_dir": str(model_dir),
        "output_dir": str(work_dir),
        "output_format": "WAV",
        "sample_rate": TARGET_SR,
        "log_level": logging.WARNING,
        "use_soundfile": False,
        "use_autocast": False,
        **arch_kwargs,
    }
    try:
        signature = inspect.signature(Separator.__init__)
        accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
        if not accepts_var_kw:
            kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
    except (TypeError, ValueError):  # pragma: no cover - defensive
        pass
    _emit(progress, "separation", 5, "初始化分离器")
    return Separator(**kwargs)


def _call_separate(separator: Any, input_wav: Path, work_dir: Path) -> list[str]:
    """Call ``separator.separate`` across API variants and return output paths."""
    names = {"Vocals": "vocals", "Instrumental": "instrumental"}
    attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = [
        ((str(input_wav), names), {}),
        ((str(input_wav),), {"custom_output_names": names}),
        ((str(input_wav),), {"output_names": names}),
        ((str(input_wav),), {}),
    ]
    last_error: Exception | None = None
    for args, kwargs in attempts:
        try:
            result = separator.separate(*args, **kwargs)
            if result:
                return [str(item) for item in result]
        except TypeError as exc:
            last_error = exc
            continue
        except (SystemExit, Exception) as exc:  # SystemExit: audio-separator calls sys.exit
            raise SeparateError(f"分离执行失败：{exc}") from exc
    if last_error is not None:
        raise SeparateError(f"分离执行失败（接口或推理错误）：{last_error}")
    return []


def _classify(path: Path) -> str | None:
    name = path.stem.lower()
    if "vocal" in name:
        return "vocals"
    if "instrument" in name or "inst" in name or "karaoke" in name or "other" in name:
        return "instrumental"
    return None


def _resolve_output(item: str, work_dir: Path) -> Path | None:
    candidate = Path(item)
    if not candidate.is_absolute():
        candidate = work_dir / candidate
    if candidate.is_file():
        return candidate
    matches = list(work_dir.glob(f"*{Path(item).stem}*"))
    for match in matches:
        if match.is_file():
            return match
    return None


def _normalize(src: Path, dst: Path) -> Path:
    """Convert any stem to 48 kHz stereo PCM WAV."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    media.run([
        media.ffmpeg_path(), "-y", "-hide_banner", "-nostdin", "-v", "error",
        "-i", str(src), "-vn", "-ac", "2", "-ar", str(TARGET_SR),
        "-c:a", "pcm_s16le", str(dst),
    ])
    return dst


def _derive_stem(original: Path, known: Path, dst: Path) -> Path:
    """Recover a missing stem by subtracting the known one from the mix."""
    import numpy as np

    orig = media.decode_stereo(original, TARGET_SR)
    other = media.decode_stereo(known, TARGET_SR)
    n = min(orig.shape[0], other.shape[0])
    derived = np.clip(orig[:n] - other[:n], -1.0, 1.0)
    media.write_wav(dst, derived, TARGET_SR)
    return dst


def _finalize(
    found: dict[str, Path],
    input_wav: Path,
    out_dir: Path,
    progress: ProgressFn | None,
) -> dict[str, Path]:
    _emit(progress, "separation", 88, "整理分离音轨")
    vocals = out_dir / "vocals.wav"
    instrumental = out_dir / "instrumental.wav"
    if "vocals" in found and "instrumental" in found:
        _normalize(found["vocals"], vocals)
        _normalize(found["instrumental"], instrumental)
    elif "instrumental" in found:
        _normalize(found["instrumental"], instrumental)
        _derive_stem(input_wav, instrumental, vocals)
    elif "vocals" in found:
        _normalize(found["vocals"], vocals)
        _derive_stem(input_wav, vocals, instrumental)
    else:  # pragma: no cover - defensive
        raise SeparateError("分离器没有输出可识别的音轨（vocals/instrumental）")
    if not (vocals.exists() and instrumental.exists()):
        raise SeparateError("分离输出整理失败")
    return {"vocals": vocals, "instrumental": instrumental}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def separate(
    input_wav: str | Path,
    out_dir: str | Path,
    model_dir: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    fallback: str = DEFAULT_FALLBACK,
    device: str = "cuda",
    progress: ProgressFn | None = None,
    overlap: float | None = None,
    shifts: int | None = None,
    allow_download: bool = True,
) -> dict[str, Path]:
    """Separate ``input_wav`` into vocals + instrumental.

    ``overlap``/``shifts`` are best-effort quality knobs forwarded to the
    architecture parameters (MDXC overlap / Demucs shifts) when supported.
    ``allow_download=False`` restricts separation to models already on disk
    (useful for tests and offline machines).  GPU OOM, model-load failures and
    ``SystemExit`` from audio-separator all trigger the next attempt; the last
    failure is raised as :class:`SeparateError`.
    """
    input_path = Path(input_wav)
    if not input_path.exists():
        raise SeparateError(f"待分离音频不存在：{input_path}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "_sep_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    directory = _model_dir(model_dir)
    directory.mkdir(parents=True, exist_ok=True)
    resolved_device = config.resolve_device(device)
    _emit(progress, "separation", 2, f"分离设备：{resolved_device}")

    main_overlap = overlap if overlap is not None else None
    resolved_fallback = resolve_fallback(fallback, directory)
    attempts: list[tuple[str, float | None]] = [(model, main_overlap)]
    if resolved_fallback and Path(resolved_fallback).name != Path(model).name:
        attempts.append(
            (resolved_fallback, 0.5 if overlap is None else min(0.6, float(overlap)))
        )

    errors: list[str] = []
    for index, (filename, arch_overlap) in enumerate(attempts):
        label = Path(filename).name
        try:
            local = ensure_model_file(filename, directory, allow_download=allow_download)
            if local is None:
                if not allow_download:
                    _emit(progress, "separation", 6, f"模型缺失：{label}")
                    raise SeparateError(
                        f"分离模型缺失且自动下载被禁用：{label}。"
                        f"请把模型放到 {directory}，或配置 HF_ENDPOINT 镜像后重试。"
                    )
                # audio-separator knows its own model repo/hashes: let it fetch
                # the model rather than failing here.
                _emit(progress, "separation", 6, f"本地缺少 {label}，交由 audio-separator 自动下载")
            arch_kwargs = _arch_kwargs(filename, arch_overlap)
            separator = _new_separator(directory, work_dir, arch_kwargs, progress)
            _emit(progress, "separation", 12, f"加载模型 {label}")
            separator.load_model(model_filename=Path(filename).name)
            _emit(progress, "separation", 30, f"正在分离音轨（{label}）")
            outputs = _call_separate(separator, input_path, work_dir)
            found: dict[str, Path] = {}
            for item in outputs:
                path = _resolve_output(item, work_dir)
                if path is None:
                    continue
                kind = _classify(path)
                if kind and kind not in found:
                    found[kind] = path
            if not found:
                raise SeparateError("分离器返回了空结果")
            _emit(progress, "separation", 70, "分离完成，正在整理输出")
            result = _finalize(found, input_path, out_dir, progress)
            # Best-effort cleanup of intermediate stem files.
            for path in outputs:
                resolved = _resolve_output(path, work_dir)
                if resolved is not None and resolved.parent == work_dir:
                    try:
                        resolved.unlink()
                    except OSError:
                        pass
            _emit(progress, "separation", 100, f"分离完成（{label}）")
            return result
        except (SystemExit, Exception) as exc:  # noqa: BLE001 - deliberate catch-all
            message = f"{label}: {exc}"
            errors.append(message)
            is_oom = "out of memory" in str(exc).lower() or "cuda" in str(exc).lower()
            reason = "显存不足/GPU 不可用" if is_oom else "模型加载或推理失败"
            if index + 1 < len(attempts):
                _emit(progress, "separation", 15, f"{reason}，降级到备用模型")
            logging.getLogger(__name__).warning("分离失败：%s", message)

    raise SeparateError("音频分离失败（已尝试全部模型）：\n" + "\n".join(errors))
