"""Shared data contracts between the pipeline, API and frontend.

All JSON emitted by the backend uses snake_case. The frontend consumes these
shapes directly. Keep this module free of heavy imports: it is imported by the
API process, the worker subprocess and tests.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Label = Literal["vocals", "music", "vocals+music", "other"]


class MediaInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    filename: str
    duration: float
    sample_rate: int = 0
    channels: int = 0
    codec: str = ""
    bit_rate: int = 0
    size: int = 0
    sha256: str = ""
    has_video: bool = False
    video_width: int | None = None
    video_height: int | None = None
    has_audio: bool = True
    audio_track: int = 0


class Segment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = 0
    start: float
    stop: float
    label: Label
    confidence: float = 0.0
    tags: dict[str, float] = Field(default_factory=dict)
    user_label: str | None = None

    @property
    def effective_label(self) -> str:
        return self.user_label or self.label


class Timeline(BaseModel):
    model_config = ConfigDict(extra="ignore")

    duration: float
    frame_hop: float = 0.02
    segments: list[Segment] = Field(default_factory=list)
    summary: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class TimbreFeatures(BaseModel):
    model_config = ConfigDict(extra="ignore")

    f0_median: float | None = None
    f0_mean: float | None = None
    f0_std: float | None = None
    voiced_ratio: float = 0.0
    centroid_mean: float = 0.0
    centroid_std: float = 0.0
    rolloff_mean: float = 0.0
    flatness_mean: float = 0.0
    zcr_mean: float = 0.0
    harmonic_ratio: float = 0.0
    rms_db: float = -120.0
    duration: float = 0.0

    def as_flat(self) -> dict[str, Any]:
        return self.model_dump()


class TimbreClip(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    path: str
    url: str = ""
    start: float
    stop: float
    duration: float
    cluster: int = 0
    features: TimbreFeatures = Field(default_factory=TimbreFeatures)
    is_representative: bool = False


class TimbreCluster(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    index: int
    label: str
    color: str
    n_clips: int = 0
    total_duration: float = 0.0
    features: TimbreFeatures = Field(default_factory=TimbreFeatures)
    clips: list[TimbreClip] = Field(default_factory=list)
    representative: list[str] = Field(default_factory=list)
    user_label: str | None = None


class TimbreResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    backend: str = "colorsplitter"
    clusters: list[TimbreCluster] = Field(default_factory=list)
    points: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Artifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str
    label: str
    path: str
    url: str
    duration: float = 0.0
    size: int = 0
    mime: str = ""


class Loudness(BaseModel):
    model_config = ConfigDict(extra="ignore")

    integrated_lufs: float | None = None
    true_peak_dbtp: float | None = None
    lra: float | None = None


class ProcessResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset: str
    output_path: str
    output_url: str
    format: str
    duration: float = 0.0
    loudness: Loudness = Field(default_factory=Loudness)
    warnings: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str = ""
    media: MediaInfo
    timeline: Timeline
    timbre: TimbreResult
    artifacts: list[Artifact] = Field(default_factory=list)
    report_url: str = ""
    warnings: list[str] = Field(default_factory=list)


class EngineSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str
    label: str
    version: str = ""
    license: str = ""
    description: str = ""
    model_ids: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    params_schema: dict[str, Any] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    engine: str
    filename: str
    label: str
    size: int = 0
    status: Literal["missing", "downloading", "ready", "error"] = "missing"
    path: str = ""
    license: str = ""
    source: str = ""
    sha256: str = ""
    error: str = ""


class JobInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    project_id: str = ""
    kind: str
    status: str
    stage: str = ""
    progress: float = 0.0
    message: str = ""
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    error: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class ProjectInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    source_path: str
    status: str = "imported"
    media: MediaInfo | None = None
    tags: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    result_dir: str = ""
    created_at: str = ""
    updated_at: str = ""
    error: str = ""


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_dir: str = ""
    models_dir: str = ""
    device: str = "auto"
    hf_endpoint: str = ""
    preview_quality: int = 32
    max_gpu_jobs: int = 1
    theme: str = "dark"
    language: str = "zh-CN"
    auto_open_report: bool = False
