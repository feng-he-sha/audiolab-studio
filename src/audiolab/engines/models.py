"""Model download / verification / deletion."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Callable

from audiolab import config
from audiolab.engines.registry import (
    MODEL_BY_ID,
    ModelFile,
    ModelSpec,
    ast_snapshot_dir,
    model_file_path,
    model_status,
)

Progress = Callable[[float, str], None]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _candidate_urls(url: str) -> list[str]:
    urls = [url]
    if "huggingface.co" in url:
        mirror = os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com"
        if mirror:
            urls.append(url.replace("https://huggingface.co", mirror.rstrip("/")))
    return urls


def _download_file(file: ModelFile, dest: Path, progress: Progress | None = None) -> Path:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size >= max(1024, file.size * 0.98 if file.size else 1024):
        if not file.sha256 or _sha256(dest) == file.sha256:
            return dest
    part = dest.with_suffix(dest.suffix + ".part")
    last_error: Exception | None = None
    for url in _candidate_urls(file.url):
        try:
            headers = {"User-Agent": "AudioLab-Studio/0.1"}
            with requests.get(url, stream=True, timeout=(30, 180), headers=headers) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or file.size or 0)
                done = 0
                started = time.time()
                with part.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            elapsed = max(0.001, time.time() - started)
                            speed = done / elapsed / (1024 * 1024)
                            progress(
                                min(99.0, done / total * 100.0),
                                f"{dest.name} {done / 1048576:.0f}/{total / 1048576:.0f} MB · {speed:.1f} MB/s",
                            )
            if file.size and part.stat().st_size < file.size * 0.98:
                raise RuntimeError(f"下载不完整: {part.stat().st_size}/{file.size}")
            if file.sha256:
                if progress:
                    progress(99.0, f"校验 {dest.name} ...")
                if _sha256(part) != file.sha256:
                    raise RuntimeError(f"SHA256 校验失败: {dest.name}")
            part.replace(dest)
            return dest
        except Exception as exc:  # try mirror
            last_error = exc
            part.unlink(missing_ok=True)
            continue
    raise RuntimeError(f"模型下载失败: {file.filename}: {last_error}")


def download_model(
    model_id: str,
    progress: Progress | None = None,
    force: bool = False,
) -> dict:
    spec: ModelSpec | None = MODEL_BY_ID.get(model_id)
    if not spec:
        raise KeyError(f"unknown model: {model_id}")
    if force:
        delete_model_files(model_id)

    if spec.kind == "hf_snapshot":
        if progress:
            progress(1.0, f"下载 {spec.label} (Hugging Face)")
        os.environ.setdefault("HF_HOME", str(Path(config.load_settings().models_dir) / "hf"))
        endpoint = config.load_settings().hf_endpoint
        if endpoint:
            os.environ["HF_ENDPOINT"] = endpoint
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=spec.repo_id,
            cache_dir=str(Path(config.load_settings().models_dir) / "hf"),
            allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"],
            ignore_patterns=["*.bin", "*.h5", "*.msgpack", "*.ot"],
        )
        if progress:
            progress(100.0, f"{spec.label} 就绪")
        return {"id": model_id, "status": "ready"}

    total_files = len(spec.files)
    for idx, file in enumerate(spec.files):
        dest = model_file_path(spec, file)
        base = idx / total_files * 100.0
        span = 100.0 / total_files

        def sub_progress(pct: float, msg: str, _base=base, _span=span) -> None:
            if progress:
                progress(_base + pct * _span / 100.0, msg)

        _download_file(file, dest, sub_progress)
    if progress:
        progress(100.0, f"{spec.label} 就绪")
    return {"id": model_id, "status": "ready"}


def delete_model_files(model_id: str) -> None:
    spec = MODEL_BY_ID.get(model_id)
    if not spec:
        return
    if spec.kind == "hf_snapshot":
        shutil.rmtree(ast_snapshot_dir(), ignore_errors=True)
        return
    for file in spec.files:
        path = model_file_path(spec, file)
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".part").unlink(missing_ok=True)


def ensure_model(model_id: str, progress: Progress | None = None) -> bool:
    spec = MODEL_BY_ID.get(model_id)
    if not spec:
        return False
    status, _ = model_status(spec)
    if status == "ready":
        return True
    try:
        download_model(model_id, progress)
        return True
    except Exception:
        return False


def download_all(progress: Progress | None = None) -> dict[str, str]:
    results: dict[str, str] = {}
    for model_id in MODEL_BY_ID:
        spec = MODEL_BY_ID[model_id]
        status, _ = model_status(spec)
        if status == "ready":
            results[model_id] = "ready"
            continue
        try:
            download_model(model_id, progress)
            results[model_id] = "ready"
        except Exception as exc:
            results[model_id] = f"error: {exc}"
    return results
