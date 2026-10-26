"""Runtime paths and settings for AudioLab Studio."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
WEB_DIST = ROOT / "web" / "dist"
WORKSPACE = ROOT / "workspace"
MODELS = ROOT / "models"
OUTPUTS = WORKSPACE / "outputs"
CACHE = WORKSPACE / "cache"
IMPORTS = WORKSPACE / "imports"
LOGS = WORKSPACE / "logs"
DB_PATH = WORKSPACE / "audiolab.db"
SETTINGS_PATH = WORKSPACE / "settings.json"


@dataclass
class Settings:
    workspace_dir: str = str(WORKSPACE)
    models_dir: str = str(MODELS)
    device: str = "auto"  # auto | cuda | cpu
    hf_endpoint: str = ""
    preview_quality: int = 32  # preview sample rate in kHz
    max_gpu_jobs: int = 1
    theme: str = "dark"
    language: str = "zh-CN"
    auto_open_report: bool = False
    separation_model: str = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
    separation_fallback: str = "UVR-MDX-NET-Inst_HQ_4.onnx"
    timbre_backend: str = "colorsplitter"  # colorsplitter | mfcc
    enable_tagging: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ensure_dirs() -> None:
    for p in (WORKSPACE, OUTPUTS, CACHE, IMPORTS, LOGS, MODELS):
        p.mkdir(parents=True, exist_ok=True)
    (MODELS / "separator").mkdir(parents=True, exist_ok=True)
    (MODELS / "colorsplitter").mkdir(parents=True, exist_ok=True)
    (MODELS / "silero").mkdir(parents=True, exist_ok=True)
    (MODELS / "hf").mkdir(parents=True, exist_ok=True)
    WEB_DIST.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    ensure_dirs()
    data: dict[str, Any] = {}
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    known = {f for f in Settings.__dataclass_fields__}
    filtered = {k: v for k, v in data.items() if k in known}
    settings = Settings(**filtered)
    # Environment overrides useful for tests / headless runs.
    if os.environ.get("AUDIOLAB_WORKSPACE"):
        settings.workspace_dir = os.environ["AUDIOLAB_WORKSPACE"]
    if os.environ.get("AUDIOLAB_MODELS"):
        settings.models_dir = os.environ["AUDIOLAB_MODELS"]
    if os.environ.get("AUDIOLAB_DEVICE"):
        settings.device = os.environ["AUDIOLAB_DEVICE"]
    if os.environ.get("HF_ENDPOINT"):
        settings.hf_endpoint = os.environ["HF_ENDPOINT"]
    return settings


def save_settings(settings: Settings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_PATH)


def resolve_device(requested: str | None = None) -> str:
    requested = (requested or load_settings().device or "auto").lower()
    if requested in {"cpu", "cuda"}:
        return requested
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def models_dir() -> Path:
    return Path(load_settings().models_dir)


def workspace_dir() -> Path:
    return Path(load_settings().workspace_dir)


def outputs_dir() -> Path:
    d = workspace_dir() / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = workspace_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = workspace_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def imports_dir() -> Path:
    d = workspace_dir() / "imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return workspace_dir() / "audiolab.db"


def python_exe() -> str:
    return sys.executable


def ffmpeg_exe() -> str:
    return os.environ.get("AUDIOLAB_FFMPEG", "ffmpeg")


def ffprobe_exe() -> str:
    return os.environ.get("AUDIOLAB_FFPROBE", "ffprobe")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
