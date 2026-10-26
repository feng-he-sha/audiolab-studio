"""Declarative engine/model registry.

The workbench never hard-codes an upstream project in the UI. Every capability
is described here and every model file is listed with source, size and license
so the models panel can download/verify/delete it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiolab import config
from audiolab.core.schemas import EngineSpec, ModelInfo

HF_SEPARATOR_REPO = "lainlives/audio-separator-models"
HF_SEPARATOR_BASE = f"https://huggingface.co/{HF_SEPARATOR_REPO}/resolve/main"
GITHUB_RAW = "https://raw.githubusercontent.com"
COLORSPLITTER_COMMIT = "50c9616dbb82f179af0d432f53d5014857e7f9a5"
SENSEVOICE_REPO = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
SENSEVOICE_BASE = f"https://huggingface.co/{SENSEVOICE_REPO}/resolve/main"


@dataclass
class ModelFile:
    filename: str
    size: int = 0
    sha256: str = ""
    url: str = ""
    subdir: str = ""
    optional: bool = False


@dataclass
class ModelSpec:
    id: str
    engine: str
    label: str
    files: list[ModelFile]
    license: str = "见 docs/licenses.md"
    source: str = ""
    kind: str = "file"  # file | hf_snapshot
    repo_id: str = ""
    note: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


MODEL_SPECS: list[ModelSpec] = [
    ModelSpec(
        id="separation.bs_roformer",
        engine="separation",
        label="BS-Roformer 人声/伴奏分离 (HQ)",
        kind="file",
        source=HF_SEPARATOR_BASE,
        license="UVR 社区模型权重，商用前请确认上游许可",
        note="默认分离模型，639MB，RTX 4060 8GB 可用；OOM 时自动降级 MDX。",
        files=[
            ModelFile(
                filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt",
                size=639331213,
                subdir="separator",
                url=f"{HF_SEPARATOR_BASE}/model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            ),
            ModelFile(
                filename="model_bs_roformer_ep_317_sdr_12.9755.yaml",
                size=2273,
                subdir="separator",
                url=f"{HF_SEPARATOR_BASE}/model_bs_roformer_ep_317_sdr_12.9755.yaml",
            ),
        ],
        tags=["vocals", "instrumental", "gpu", "hq"],
    ),
    ModelSpec(
        id="separation.mdx_fast",
        engine="separation",
        label="UVR-MDX-NET Inst HQ 4 (快速/兜底)",
        kind="file",
        source=HF_SEPARATOR_BASE,
        license="UVR 社区模型权重，商用前请确认上游许可",
        note="59MB，CPU 也能跑，作为 8GB 显存不足时的兜底。",
        files=[
            ModelFile(
                filename="UVR-MDX-NET-Inst_HQ_4.onnx",
                size=59074342,
                subdir="separator",
                url=f"{HF_SEPARATOR_BASE}/UVR-MDX-NET-Inst_HQ_4.onnx",
            )
        ],
        tags=["vocals", "instrumental", "cpu", "fast"],
    ),
    ModelSpec(
        id="timbre.colorsplitter",
        engine="timbre",
        label="ColorSplitter timbre-v1 音色编码器",
        kind="file",
        source=f"{GITHUB_RAW}/KakaruHayate/ColorSplitter/{COLORSPLITTER_COMMIT}/pretrain/timbre-v1.pt",
        license="MIT (ColorSplitter)",
        note="17MB，按音色聚类；失败时自动降级 MFCC。",
        files=[
            ModelFile(
                filename="timbre-v1.pt",
                size=17100415,
                sha256="7e975269badb2325bea04d2cec58218901d791aeb6b8d622f0136d45282a3cac",
                subdir="colorsplitter",
                url=f"{GITHUB_RAW}/KakaruHayate/ColorSplitter/{COLORSPLITTER_COMMIT}/pretrain/timbre-v1.pt",
            )
        ],
        tags=["timbre", "clustering", "gpu"],
    ),
    ModelSpec(
        id="vad.silero",
        engine="vad",
        label="Silero VAD ONNX",
        kind="file",
        source=f"{GITHUB_RAW}/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx",
        license="MIT (Silero)",
        note="约 1.9MB，人声活动检测；缺失时用能量门限降级。",
        files=[
            ModelFile(
                filename="silero_vad.onnx",
                size=1888608,
                subdir="silero",
                url=f"{GITHUB_RAW}/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx",
            )
        ],
        tags=["vad", "speech"],
    ),
    ModelSpec(
        id="tagging.ast",
        engine="tagging",
        label="AST AudioSet 场景标签",
        kind="hf_snapshot",
        repo_id="MIT/ast-finetuned-audioset-10-10-0.4593",
        source="https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593",
        license="BSD-3-Clause (AST)",
        note="约 350MB，识别 Music/Speech/Singing/Sound effect 等；可跳过。",
        files=[],
        tags=["tagging", "music", "speech", "gpu"],
    ),
    ModelSpec(
        id="asr.sensevoice",
        engine="asr",
        label="SenseVoiceSmall 语音转写 (ONNX int8)",
        kind="file",
        source=SENSEVOICE_BASE,
        license="MIT (SenseVoice / FunASR)",
        note="239MB，中/英/日/韩/粤语转写与情绪/事件标签；缺失时跳过转写。本机已有模型可直接复用。",
        files=[
            ModelFile(
                filename="model.int8.onnx",
                size=239233841,
                subdir="sensevoice",
                url=f"{SENSEVOICE_BASE}/model.int8.onnx",
            ),
            ModelFile(
                filename="tokens.txt",
                size=315894,
                subdir="sensevoice",
                url=f"{SENSEVOICE_BASE}/tokens.txt",
            ),
        ],
        tags=["asr", "speech", "subtitle", "cpu", "optional"],
    ),
]

MODEL_BY_ID = {m.id: m for m in MODEL_SPECS}


ENGINE_SPECS: list[EngineSpec] = [
    EngineSpec(
        id="separation.bs_roformer",
        kind="separation",
        label="BS-Roformer HQ",
        version="317 / SDR 12.98",
        license="见 docs/licenses.md",
        description="高质量人声/伴奏分离，GPU 推荐。",
        model_ids=["separation.bs_roformer", "separation.mdx_fast"],
        capabilities=["vocals", "instrumental", "gpu", "cpu_fallback"],
        params_schema={
            "model": {
                "type": "select",
                "options": ["model_bs_roformer_ep_317_sdr_12.9755.ckpt", "UVR-MDX-NET-Inst_HQ_4.onnx"],
                "default": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            },
            "segment_size": {"type": "int", "default": 256, "min": 64, "max": 512},
        },
    ),
    EngineSpec(
        id="vad.silero",
        kind="vad",
        label="Silero VAD",
        version="6.2.3",
        license="MIT",
        description="语音活动检测，配合人声能量门限补歌唱漏检。",
        model_ids=["vad.silero"],
        capabilities=["speech", "singing_fallback"],
    ),
    EngineSpec(
        id="tagging.ast",
        kind="tagging",
        label="AST AudioSet",
        version="10-10-0.4593",
        license="BSD-3-Clause",
        description="10 秒窗场景标签，用于 Music/Speech/音效区分。",
        model_ids=["tagging.ast"],
        capabilities=["music", "speech", "singing", "sound_effect"],
    ),
    EngineSpec(
        id="timbre.colorsplitter",
        kind="timbre",
        label="ColorSplitter timbre-v1",
        version="v1",
        license="MIT",
        description="按音色嵌入聚类；短片段/失败时降级 MFCC。",
        model_ids=["timbre.colorsplitter"],
        capabilities=["timbre", "clustering", "gpu"],
    ),
    EngineSpec(
        id="asr.sensevoice",
        kind="asr",
        label="SenseVoiceSmall",
        version="2024-07-17 / ONNX int8",
        license="MIT",
        description="本地语音转写，输出全文、分段时间、语言、情绪和事件标签。",
        model_ids=["asr.sensevoice"],
        capabilities=["transcription", "subtitle", "language_id", "emotion", "event"],
    ),
    EngineSpec(
        id="processing.ffmpeg",
        kind="processing",
        label="ffmpeg 处理链",
        version="9.x",
        license="LGPL/GPL（取决于 ffmpeg 构建）",
        description="响度、降噪、静音裁剪、淡入淡出、BGM 闪避、视频回贴。",
        capabilities=["loudnorm", "denoise", "trim", "duck", "mux"],
    ),
]


def model_dir_for(spec: ModelSpec) -> Path:
    base = Path(config.load_settings().models_dir)
    sub = spec.files[0].subdir if spec.files else ""
    return base / sub if sub else base


def model_file_path(spec: ModelSpec, file: ModelFile) -> Path:
    return Path(config.load_settings().models_dir) / file.subdir / file.filename


def ast_snapshot_dir() -> Path:
    return Path(config.load_settings().models_dir) / "hf" / "models--MIT--ast-finetuned-audioset-10-10-0.4593"


def model_status(spec: ModelSpec) -> tuple[str, str]:
    """Return (status, detail_path_or_error)."""
    if spec.id == "asr.sensevoice":
        # The user may already have a SenseVoice bundle outside models/ (e.g.
        # the DSH speech-to-text cache); report it as ready without copying it.
        try:
            from audiolab.core import asr

            local = asr.resolve_model_dir()
            if local is not None:
                return "ready", str(local)
        except Exception:
            pass
    if spec.kind == "hf_snapshot":
        snap = ast_snapshot_dir()
        if snap.exists() and any(snap.glob("snapshots/*/config.json")):
            return "ready", str(snap)
        return "missing", str(snap)
    missing: list[str] = []
    for file in spec.files:
        path = model_file_path(spec, file)
        expected = max(1024, int(file.size * 0.98)) if file.size else 1024
        if not path.exists() or path.stat().st_size < expected:
            missing.append(path.name)
    if missing:
        return "missing", ", ".join(missing)
    return "ready", str(model_file_path(spec, spec.files[0]).parent)


def refresh_model_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in MODEL_SPECS:
        status, detail = model_status(spec)
        path = detail if status == "ready" else ""
        rows.append(
            {
                "id": spec.id,
                "engine": spec.engine,
                "filename": spec.files[0].filename if spec.files else spec.repo_id,
                "label": spec.label,
                "size": spec.total_size,
                "path": path,
                "status": status,
                "license": spec.license,
                "source": spec.source,
                "sha256": spec.files[0].sha256 if spec.files else "",
                "error": "" if status == "ready" else detail,
            }
        )
    return rows


def engine_list() -> list[EngineSpec]:
    return ENGINE_SPECS


def model_info_list() -> list[ModelInfo]:
    return [ModelInfo(**row) for row in refresh_model_rows()]
