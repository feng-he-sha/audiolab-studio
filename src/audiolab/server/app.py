"""FastAPI application for AudioLab Studio."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from audiolab import __version__, config
from audiolab.core.schemas import (
    AnalysisResult,
    Artifact,
    EngineSpec,
    MediaInfo,
    ModelInfo,
    ProjectInfo,
    SettingsModel,
    Timeline,
    TimbreResult,
)
from audiolab.engines import models as model_downloads
from audiolab.engines.registry import (
    MODEL_BY_ID,
    engine_list,
    model_info_list,
    refresh_model_rows,
)
from audiolab.server import db
from audiolab.server.events import HUB
from audiolab.server.jobs import JOB_MANAGER

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wma",
    ".aiff",
    ".aif",
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
}


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------


class ImportRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    quality: str = "balanced"
    separation_model: str | None = None
    skip_tagging: bool | None = None
    clusters: int | None = None
    timbre_threshold: float | None = None
    timbre_backend: str | None = None
    force: bool = False
    audio_track: int = 0


class RefuseRequest(BaseModel):
    min_segment: float | None = None
    smooth_frames: int | None = None
    min_music: float | None = None
    min_gap: float | None = None


class ProcessRequest(BaseModel):
    preset: str = "douyin"
    params: dict[str, Any] = Field(default_factory=dict)
    mux_video: bool = False
    output_format: str | None = None


class SegmentPatch(BaseModel):
    user_label: str | None = None


class SegmentsMerge(BaseModel):
    segment_ids: list[int] = Field(default_factory=list)


class SegmentSplit(BaseModel):
    segment_id: int
    at: float


class ClusterPatch(BaseModel):
    user_label: str | None = None


class ClustersMerge(BaseModel):
    cluster_ids: list[str] = Field(default_factory=list)


class SettingsPatch(BaseModel):
    workspace_dir: str | None = None
    models_dir: str | None = None
    device: str | None = None
    hf_endpoint: str | None = None
    preview_quality: int | None = None
    max_gpu_jobs: int | None = None
    theme: str | None = None
    language: str | None = None
    auto_open_report: bool | None = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _safe_name(value: str, limit: int = 60) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return (value[:limit] or "project")


def _project_dir(project: dict[str, Any]) -> Path:
    result_dir = str(project.get("result_dir") or "").strip()
    if result_dir in {"", "."}:
        result_dir = str(config.outputs_dir() / f"{_safe_name(project['name'])}_{project['id']}")
        db.update_project(project["id"], result_dir=result_dir)
        project["result_dir"] = result_dir
    path = Path(result_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _rel_url(project_id: str, result_dir: Path, value: str | Path) -> str:
    path = Path(value)
    try:
        rel = path.resolve().relative_to(result_dir.resolve())
    except Exception:
        rel = Path(path.name)
    return f"/api/files/{project_id}/{quote(rel.as_posix())}"


def _media_duration(project: dict[str, Any] | None) -> float:
    if not project:
        return 0.0
    media = project.get("media")
    if media is None:
        return 0.0
    return float(getattr(media, "duration", 0.0) or 0.0)


def _save_upload(upload: UploadFile) -> Path:
    name = _safe_name(Path(upload.filename or "upload.wav").name, 120)
    folder = config.imports_dir() / db.new_id("u_")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    with target.open("wb") as out:
        shutil.copyfileobj(upload.file, out, length=1024 * 1024)
    return target


def _iter_media(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in AUDIO_EXTENSIONS else []
    found: list[Path] = []
    for child in path.rglob("*"):
        if child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS:
            found.append(child)
    return sorted(found, key=lambda p: str(p).lower())


def _import_one(path: Path) -> dict[str, Any]:
    from audiolab.core import media as media_mod

    path = path.resolve()
    info = media_mod.probe(path)
    if not info.sha256:
        info.sha256 = media_mod.sha256_file(path)
    existing = db.project_by_hash(info.sha256)
    if existing:
        existing["reused"] = True
        return existing
    project = db.create_project(path.stem, str(path), info, result_dir="", status="imported")
    out_dir = _project_dir(project)
    project = db.update_project(project["id"], result_dir=str(out_dir)) or project
    return project


def _active_job_for(project_id: str, kind: str) -> dict[str, Any] | None:
    for job in db.list_jobs(active_only=True):
        if job.get("project_id") == project_id and job.get("kind") == kind:
            return job
    return None


def _load_timbre_payload(project: dict[str, Any]) -> TimbreResult:
    pid = project["id"]
    out_dir = _project_dir(project)
    db_result = db.get_timbre(pid)
    json_payload: TimbreResult | None = None
    json_path = out_dir / "timbre.json"
    if json_path.exists():
        try:
            json_payload = TimbreResult.model_validate(
                __import__("json").loads(json_path.read_text(encoding="utf-8"))
            )
        except Exception:
            json_payload = None

    points = json_payload.points if json_payload else []
    backend = (json_payload.backend if json_payload else "") or "colorsplitter"
    json_representative = {
        c.id.split(":")[-1]: c.representative for c in json_payload.clusters
    } if json_payload else {}

    def fill_cluster(cluster, short_id: str) -> None:
        cluster.id = f"{pid}:{short_id}"
        cluster.n_clips = len(cluster.clips)
        cluster.total_duration = round(sum(c.duration for c in cluster.clips), 3)
        for clip in cluster.clips:
            clip.url = _rel_url(pid, out_dir, clip.path)
            if not clip.duration:
                clip.duration = max(0.0, clip.stop - clip.start)
        reps = json_representative.get(short_id, [])
        if not reps:
            reps = [c.id for c in cluster.clips if c.is_representative]
        cluster.representative = reps

    if db_result.clusters:
        for cluster in db_result.clusters:
            fill_cluster(cluster, cluster.id.split(":")[-1])
        db_result.points = points
        db_result.backend = backend
        return db_result

    if json_payload and json_payload.clusters:
        for cluster in json_payload.clusters:
            fill_cluster(cluster, cluster.id.split(":")[-1])
        json_payload.points = points
        json_payload.backend = backend
        return json_payload
    db_result.backend = backend
    db_result.points = points
    return db_result


def _artifact_file(out_dir: Path, artifact_id: str) -> Path | None:
    mapping = {
        "original": out_dir / "audio" / "original.wav",
        "vocals": out_dir / "stems" / "vocals.wav",
        "instrumental": out_dir / "stems" / "instrumental.wav",
    }
    if artifact_id in mapping:
        return mapping[artifact_id] if mapping[artifact_id].exists() else None
    if artifact_id.startswith("preview_"):
        name = artifact_id.replace("preview_", "", 1)
        candidate = out_dir / "preview" / f"{name}.m4a"
        if candidate.exists():
            return candidate
        candidate = out_dir / "preview" / f"{name}.wav"
        return candidate if candidate.exists() else None
    if artifact_id.startswith("processed_"):
        name = artifact_id.replace("processed_", "", 1)
        for ext in (".mp3", ".m4a", ".wav", ".flac"):
            candidate = out_dir / "processed" / f"{name}{ext}"
            if candidate.exists():
                return candidate
    return None


def _list_artifacts(project: dict[str, Any]) -> list[Artifact]:
    pid = project["id"]
    out_dir = _project_dir(project)
    duration = _media_duration(project)
    items: list[Artifact] = []

    def add(aid: str, kind: str, label: str, rel: str, mime: str = "") -> None:
        path = out_dir / rel
        if not path.exists():
            return
        mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        items.append(
            Artifact(
                id=aid,
                kind=kind,
                label=label,
                path=str(path),
                url=_rel_url(pid, out_dir, path),
                duration=duration,
                size=path.stat().st_size,
                mime=mime,
            )
        )

    add("original", "original", "原声", "audio/original.wav")
    add("vocals", "vocals", "人声", "stems/vocals.wav")
    add("instrumental", "instrumental", "伴奏", "stems/instrumental.wav")
    for stem in ("original", "vocals", "instrumental"):
        for ext in (".m4a", ".wav"):
            if (out_dir / "preview" / f"{stem}{ext}").exists():
                add(f"preview_{stem}", "preview", f"{stem} 预览", f"preview/{stem}{ext}")
                break
    processed_dir = out_dir / "processed"
    if processed_dir.exists():
        for file in sorted(processed_dir.iterdir()):
            if file.is_file() and file.suffix.lower() in {".mp3", ".m4a", ".wav", ".flac", ".mp4"}:
                add(f"processed_{file.stem}", "processed", f"处理结果 · {file.stem}", f"processed/{file.name}")
    if (out_dir / "report.html").exists():
        add("report", "report", "报告", "report.html", "text/html")
    return items


def _doctor() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, hint: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "hint": hint})

    add("Python", True, os.sys.version.split()[0])
    try:
        out = subprocess.run([config.ffmpeg_exe(), "-version"], capture_output=True, text=True, timeout=15)
        first = (out.stdout or out.stderr).splitlines()[0] if (out.stdout or out.stderr) else ""
        add("ffmpeg", out.returncode == 0, first or "未找到", "安装 ffmpeg 并加入 PATH")
    except Exception as exc:
        add("ffmpeg", False, str(exc), "安装 ffmpeg 并加入 PATH")
    try:
        import torch

        detail = f"torch {torch.__version__}"
        cuda = bool(torch.cuda.is_available())
        if cuda:
            detail += f" · CUDA {torch.version.cuda} · {torch.cuda.get_device_name(0)}"
        add("PyTorch / CUDA", True, detail, "GPU 不可用时会自动使用 CPU，速度较慢")
    except Exception as exc:
        add("PyTorch / CUDA", False, str(exc), "重新运行 setup.ps1 安装 CUDA torch")
    try:
        import audio_separator  # noqa: F401

        add("audio-separator", True, "已安装")
    except Exception as exc:
        add("audio-separator", False, str(exc), "pip install audio-separator[cpu]")
    try:
        import transformers  # noqa: F401

        add("transformers", True, f"transformers {transformers.__version__}")
    except Exception as exc:
        add("transformers", False, str(exc), "pip install transformers")
    add("前端构建", (config.WEB_DIST / "index.html").exists(), str(config.WEB_DIST), "运行 pnpm --dir web build")
    ready = [m for m in refresh_model_rows() if m["status"] == "ready"]
    add(
        "模型",
        bool(ready),
        f"{len(ready)}/{len(MODEL_BY_ID)} 个模型就绪",
        "在模型页下载，或运行 python scripts/fetch_models.py",
    )
    try:
        free = shutil.disk_usage(config.workspace_dir()).free / (1024**3)
        add("磁盘", free > 2, f"剩余 {free:.1f} GB")
    except Exception as exc:
        add("磁盘", False, str(exc))
    try:
        probe = config.workspace_dir() / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        add("工作区权限", True, str(config.workspace_dir()))
    except Exception as exc:
        add("工作区权限", False, str(exc))
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "version": __version__}


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------


def _sync_models() -> None:
    for row in refresh_model_rows():
        existing = db.get_model(row["id"])
        if existing and existing.get("status") == "downloading" and row["status"] != "ready":
            row["status"] = "downloading"
        db.upsert_model(row)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    db.init_db()
    _sync_models()
    HUB.attach_loop(asyncio.get_running_loop())
    JOB_MANAGER.start()
    try:
        yield
    finally:
        JOB_MANAGER.shutdown()


app = FastAPI(title="AudioLab Studio", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:7860", "http://localhost:7860"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- system -----------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    device = "cpu"
    cuda = False
    try:
        import torch

        cuda = bool(torch.cuda.is_available())
        device = "cuda" if cuda else "cpu"
    except Exception:
        pass
    ffmpeg_ok = shutil.which(config.ffmpeg_exe()) is not None
    return {
        "ok": True,
        "version": __version__,
        "device": device,
        "cuda": cuda,
        "ffmpeg": ffmpeg_ok,
        "web": (config.WEB_DIST / "index.html").exists(),
        "fake": os.environ.get("AUDIOLAB_FAKE") == "1",
    }


@app.get("/api/doctor")
def doctor() -> dict[str, Any]:
    return _doctor()


# -- projects ---------------------------------------------------------------


@app.get("/api/projects")
def list_projects(query: str = "", status: str = "", page: int = 1, page_size: int = 50):
    items, total = db.list_projects(query, status, page, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/api/projects/import")
def import_projects(req: ImportRequest):
    projects: list[dict[str, Any]] = []
    errors: list[str] = []
    files: list[Path] = []
    for raw in req.paths:
        path = Path(raw).expanduser()
        if not path.exists():
            errors.append(f"路径不存在: {raw}")
            continue
        found = _iter_media(path)
        if not found:
            errors.append(f"没有支持的音视频文件: {raw}")
            continue
        files.extend(found)
    for file in files:
        try:
            projects.append(_import_one(file))
        except Exception as exc:
            errors.append(f"{file.name}: {exc}")
    return {"projects": projects, "errors": errors}


@app.post("/api/projects/upload")
def upload_projects(files: list[UploadFile] = File(...)):
    projects: list[dict[str, Any]] = []
    errors: list[str] = []
    for upload in files:
        try:
            target = _save_upload(upload)
            projects.append(_import_one(target))
        except Exception as exc:
            errors.append(f"{upload.filename}: {exc}")
    return {"projects": projects, "errors": errors}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, payload: dict[str, Any]):
    if not db.get_project(project_id):
        raise HTTPException(404, "项目不存在")
    fields = {k: v for k, v in payload.items() if k in {"name", "tags"}}
    return db.update_project(project_id, **fields)


@app.delete("/api/projects/{project_id}")
def remove_project(project_id: str, delete_outputs: bool = True):
    if not db.get_project(project_id):
        raise HTTPException(404, "项目不存在")
    db.delete_project(project_id, delete_outputs=delete_outputs)
    return {"ok": True}


# -- analysis / processing --------------------------------------------------


@app.post("/api/projects/{project_id}/analyze")
def analyze(project_id: str, req: AnalyzeRequest):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    active = _active_job_for(project_id, "analyze")
    if active:
        return {"job_id": active["id"], "existing": True}
    params = req.model_dump(exclude_none=True)
    job = JOB_MANAGER.submit("analyze", project_id, params)
    db.update_project(project_id, status="analyzing", error="")
    return {"job_id": job["id"], "existing": False}


@app.post("/api/projects/{project_id}/refuse")
def refuse(project_id: str, req: RefuseRequest):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    params = req.model_dump(exclude_none=True)
    job = JOB_MANAGER.submit("refuse", project_id, params)
    return {"job_id": job["id"]}


@app.post("/api/projects/{project_id}/process")
def process(project_id: str, req: ProcessRequest):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    active = _active_job_for(project_id, "process")
    if active:
        return {"job_id": active["id"], "existing": True}
    if req.preset not in {"douyin", "podcast", "movie", "music", "clean"}:
        raise HTTPException(400, "未知处理预设")
    params = {"preset": req.preset, "params": req.params, "mux_video": req.mux_video}
    if req.output_format:
        params["output_format"] = req.output_format
    job = JOB_MANAGER.submit("process", project_id, params)
    db.update_project(project_id, status="processing")
    return {"job_id": job["id"], "existing": False}


@app.get("/api/projects/{project_id}/timeline", response_model=Timeline)
def timeline(project_id: str):
    if not db.get_project(project_id):
        raise HTTPException(404, "项目不存在")
    return db.get_timeline(project_id)


@app.get("/api/projects/{project_id}/timbre", response_model=TimbreResult)
def timbre(project_id: str):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    return _load_timbre_payload(project)


@app.get("/api/projects/{project_id}/artifacts")
def artifacts(project_id: str):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    return {"artifacts": _list_artifacts(project)}


@app.get("/api/projects/{project_id}/peaks/{artifact_id}")
def peaks(project_id: str, artifact_id: str):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    out_dir = _project_dir(project)
    cache = out_dir / "peaks" / f"{artifact_id}.json"
    if cache.exists():
        return JSONResponse(__import__("json").loads(cache.read_text(encoding="utf-8")))
    source = _artifact_file(out_dir, artifact_id)
    if not source:
        raise HTTPException(404, "音频产物不存在")
    from audiolab.core import media as media_mod

    data = media_mod.compute_peaks(source)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(__import__("json").dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


@app.patch("/api/projects/{project_id}/segments/{segment_id}")
def patch_segment(project_id: str, segment_id: int, req: SegmentPatch):
    if not db.get_project(project_id):
        raise HTTPException(404, "项目不存在")
    try:
        return db.update_segment_label(project_id, segment_id, req.user_label)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/projects/{project_id}/segments/merge")
def merge_segments(project_id: str, req: SegmentsMerge):
    if not db.get_project(project_id):
        raise HTTPException(404, "项目不存在")
    try:
        return db.merge_segments(project_id, req.segment_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/projects/{project_id}/segments/split")
def split_segment(project_id: str, req: SegmentSplit):
    if not db.get_project(project_id):
        raise HTTPException(404, "项目不存在")
    return db.split_segment(project_id, req.segment_id, req.at)


@app.patch("/api/clusters/{cluster_id}")
def patch_cluster(cluster_id: str, req: ClusterPatch):
    project_id, _, short = cluster_id.partition(":")
    project = db.get_project(project_id) if project_id else None
    if not project or not short:
        raise HTTPException(404, "项目不存在；cluster_id 需要 <project_id>:<V1> 形式")
    db.update_cluster_label(project_id, short, req.user_label)
    return _load_timbre_payload(project)


@app.post("/api/projects/{project_id}/clusters/merge")
def merge_clusters(project_id: str, req: ClustersMerge):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    current = _load_timbre_payload(project)
    selected = [c for c in current.clusters if c.id in set(req.cluster_ids)]
    if len(selected) < 2:
        return current
    base = selected[0]
    base.clips = [clip for cluster in selected for clip in cluster.clips]
    base.n_clips = len(base.clips)
    base.total_duration = round(sum(c.duration for c in base.clips), 3)
    base.label = f"{base.label}（合并）"
    base.id = base.id
    merged = [c for c in current.clusters if c.id not in set(req.cluster_ids)]
    merged.append(base)
    merged.sort(key=lambda c: c.index)
    current.clusters = merged
    db.save_timbre(project_id, "", current)
    return _load_timbre_payload(project)


# -- files / report / export ------------------------------------------------


@app.get("/api/projects/{project_id}/report")
def report(project_id: str):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    path = _project_dir(project) / "report.html"
    if not path.exists():
        raise HTTPException(404, "报告尚未生成")
    # The stored report uses relative asset paths so it also works when opened
    # from disk. When served over HTTP, add a <base> so audio/clip URLs resolve
    # through the range-enabled /api/files endpoint.
    html_text = path.read_text(encoding="utf-8", errors="replace")
    base = f'<base href="/api/files/{quote(project_id)}/">'
    if "<base " not in html_text:
        html_text = html_text.replace("<head>", f"<head>{base}", 1)
    return HTMLResponse(html_text)


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str, format: str = "zip"):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    out_dir = _project_dir(project)
    if not out_dir.exists():
        raise HTTPException(404, "没有可导出的结果")
    fmt = (format or "zip").lower()
    # Keep Content-Disposition ASCII-only (HTTP headers are latin-1); the UI
    # supplies the user-facing Chinese filename via its download anchor.
    filename = f"audiolab_{project_id}"
    if fmt in {"json", "csv"}:
        from fastapi.encoders import jsonable_encoder

        timeline = db.get_timeline(project_id)
        if fmt == "json":
            payload = {
                "project": jsonable_encoder(project),
                "timeline": timeline.model_dump(),
                "timbre": _load_timbre_payload(project).model_dump(),
                "artifacts": [a.model_dump() for a in _list_artifacts(project)],
            }
            body = __import__("json").dumps(payload, ensure_ascii=False, indent=2)
            return Response(
                content=body,
                media_type="application/json; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
            )
        import csv
        import io

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "start", "stop", "duration", "auto_label", "final_label", "confidence", "tags"])
        for seg in timeline.segments:
            writer.writerow(
                [
                    seg.id,
                    f"{seg.start:.3f}",
                    f"{seg.stop:.3f}",
                    f"{seg.stop - seg.start:.3f}",
                    seg.label,
                    seg.user_label or seg.label,
                    f"{seg.confidence:.3f}",
                    __import__("json").dumps(seg.tags, ensure_ascii=False),
                ]
            )
        return Response(
            content="\ufeff" + buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    if fmt != "zip":
        raise HTTPException(400, "format 必须是 zip/json/csv")
    fd, temp_name = tempfile.mkstemp(suffix=".zip", dir=str(config.workspace_dir()))
    os.close(fd)
    temp = Path(temp_name)
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in out_dir.rglob("*"):
            if file.is_file() and not file.name.endswith(".part"):
                zf.write(file, file.relative_to(out_dir))
    from starlette.background import BackgroundTask

    return FileResponse(
        temp,
        filename=f"audiolab_{project_id}.zip",
        media_type="application/zip",
        background=BackgroundTask(temp.unlink, missing_ok=True),
    )


def _range_response(request: Request, path: Path) -> Response:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type)
    match = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not match:
        return FileResponse(path, media_type=media_type)
    start = int(match.group(1) or 0)
    end = int(match.group(2) or size - 1)
    start = max(0, min(start, size - 1))
    end = max(start, min(end, size - 1))
    length = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        data = f.read(length)
    return Response(
        content=data,
        status_code=206,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Cache-Control": "no-store",
        },
        media_type=media_type,
    )


@app.get("/api/files/{project_id}/{path:path}")
def serve_file(project_id: str, path: str, request: Request):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    out_dir = _project_dir(project).resolve()
    candidate = (out_dir / path).resolve()
    if not candidate.is_relative_to(out_dir) or not candidate.is_file():
        raise HTTPException(404, "文件不存在")
    return _range_response(request, candidate)


# -- jobs / engines / models / settings -------------------------------------


@app.get("/api/jobs")
def jobs(active: bool = False):
    items = db.list_jobs(active_only=active)
    return {"items": items}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return {"ok": JOB_MANAGER.cancel(job_id)}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    job = JOB_MANAGER.retry(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return {"job_id": job["id"]}


@app.get("/api/jobs/{job_id}/log")
def job_log(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    path = Path(job.get("log_path") or "")
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    return {"lines": lines}


@app.get("/api/engines")
def engines():
    return {"engines": [e.model_dump() for e in engine_list()]}


@app.get("/api/models")
def models():
    _sync_models()
    return {"models": db.list_models()}


@app.post("/api/models/{model_id}/download")
def download_model(model_id: str):
    if model_id not in MODEL_BY_ID:
        raise HTTPException(404, "未知模型")
    db.set_model_status(model_id, "downloading")
    job = JOB_MANAGER.submit("download", "", {"model_id": model_id})
    return {"job_id": job["id"]}


@app.delete("/api/models/{model_id}")
def delete_model(model_id: str):
    if model_id not in MODEL_BY_ID:
        raise HTTPException(404, "未知模型")
    model_downloads.delete_model_files(model_id)
    db.delete_model(model_id)
    _sync_models()
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return config.load_settings().to_dict()


@app.patch("/api/settings")
def patch_settings(req: SettingsPatch):
    settings = config.load_settings()
    for key, value in req.model_dump(exclude_none=True).items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    config.save_settings(settings)
    config.ensure_dirs()
    return settings.to_dict()


# -- websocket --------------------------------------------------------------


@app.websocket("/api/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    queue = HUB.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        HUB.unsubscribe(queue)


# -- static frontend --------------------------------------------------------

if (config.WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(config.WEB_DIST / "assets")), name="assets")


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    dist = config.WEB_DIST
    candidate = (dist / full_path).resolve() if full_path else dist / "index.html"
    if full_path and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
        return FileResponse(candidate)
    index = dist / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html; charset=utf-8")
    return HTMLResponse(
        """<!doctype html><meta charset="utf-8"><title>AudioLab Studio</title>
        <body style="background:#0b0e14;color:#e6edf7;font-family:system-ui;padding:40px">
        <h1>AudioLab Studio 后端已启动</h1>
        <p>前端尚未构建。运行 <code>pnpm --dir web install &amp;&amp; pnpm --dir web build</code> 后刷新。</p>
        <p>API 文档：<a style="color:#5eead4" href="/docs">/docs</a></p></body>""",
        status_code=200,
    )


def create_app() -> FastAPI:
    return app
