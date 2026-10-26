"""Subprocess entry point for one job.

The GUI never runs models in the API process. The job manager starts this module
so an OOM/crash is isolated; progress is streamed as JSON lines on stdout and
also persisted to SQLite.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from audiolab import config
from audiolab.server import db


def emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def make_progress(job_id: str):
    last = 0.0

    def progress(stage: str, pct: float, message: str = "") -> None:
        nonlocal last
        pct = max(last, min(100.0, float(pct)))
        last = pct
        db.update_job(job_id, stage=stage, progress=pct, message=message or stage)
        emit({"type": "progress", "stage": stage, "progress": pct, "message": message or stage})

    return progress


def project_dir(project: dict[str, Any]) -> Path:
    result_dir = project.get("result_dir") or ""
    if not result_dir:
        safe = "".join(c for c in project["name"] if c.isalnum() or c in "-_ ")[:40].strip() or "project"
        result_dir = str(config.outputs_dir() / f"{safe}_{project['id']}")
        db.update_project(project["id"], result_dir=result_dir)
    path = Path(result_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_analyze(job: dict[str, Any], project: dict[str, Any], progress) -> None:
    from audiolab.core.pipeline import analyze

    out_dir = project_dir(project)
    params = job.get("params") or {}
    result = analyze(
        project_id=project["id"],
        source_path=project["source_path"],
        out_dir=out_dir,
        params=params,
        progress=progress,
    )
    run_id = db.new_id("r_")
    timeline = db.save_timeline(project["id"], run_id, result.timeline)
    timbre = db.save_timbre(project["id"], run_id, result.timbre)
    summary = dict(result.timeline.summary)
    summary.update(
        {
            "clusters": len(timbre.clusters),
            "timbre_backend": result.timbre.backend,
            "transcript_segments": len(result.transcript.segments) if result.transcript else 0,
            "asr_backend": result.transcript.backend if result.transcript else "",
            "asr_language": result.transcript.language if result.transcript else "",
            "duration": result.media.duration,
            "report_url": result.report_url,
            "warnings": len(result.warnings),
        }
    )
    db.save_run(
        project["id"],
        "analyze",
        "done",
        params,
        str(out_dir),
        started_at=job.get("started_at", ""),
        finished_at=db.now_iso(),
        run_id=run_id,
    )
    db.update_project(project["id"], status="analyzed", summary=summary, error="")
    emit({"type": "done", "stage": "report", "progress": 100, "message": "分析完成", "summary": summary})


def run_refuse(job: dict[str, Any], project: dict[str, Any], progress) -> None:
    from audiolab.core.pipeline import refuse

    out_dir = project_dir(project)
    previous = dict((db.get_project(project["id"]) or project).get("summary") or {})
    timeline = refuse(project["id"], out_dir, job.get("params") or {}, progress)
    db.save_timeline(project["id"], "", timeline)
    merged = dict(previous)
    merged.update(timeline.summary)
    db.update_project(project["id"], summary=merged, status="analyzed")
    emit({"type": "done", "stage": "fusion", "progress": 100, "message": "重新融合完成"})


def run_process(job: dict[str, Any], project: dict[str, Any], progress) -> None:
    from audiolab.core.pipeline import process

    out_dir = project_dir(project)
    params = job.get("params") or {}
    preset = params.get("preset", "douyin")
    result = process(
        project_id=project["id"],
        source_path=project["source_path"],
        out_dir=out_dir,
        preset=preset,
        params=params,
        progress=progress,
    )
    db.save_run(
        project["id"],
        "process",
        "done",
        params,
        str(out_dir),
        started_at=job.get("started_at", ""),
        finished_at=db.now_iso(),
    )
    project_now = db.get_project(project["id"]) or project
    summary = dict(project_now.get("summary") or {})
    summary["last_process"] = {
        "preset": result.preset,
        "path": result.output_path,
        "url": result.output_url,
        "format": result.format,
        "loudness": result.loudness.model_dump(),
    }
    db.update_project(project["id"], summary=summary, status="analyzed")
    emit(
        {
            "type": "done",
            "stage": "render",
            "progress": 100,
            "message": f"处理完成: {result.output_path}",
            "output": result.output_path,
        }
    )


def run_download(job: dict[str, Any], progress) -> None:
    from audiolab.engines import models
    from audiolab.engines.registry import MODEL_BY_ID

    params = job.get("params") or {}
    model_id = params.get("model_id", "")
    if not model_id and params.get("all"):
        results = models.download_all(lambda pct, msg: progress("download", pct, msg))
        emit({"type": "done", "stage": "download", "progress": 100, "results": results})
        return
    spec = MODEL_BY_ID.get(model_id)
    if not spec:
        raise KeyError(f"未知模型: {model_id}")
    db.set_model_status(model_id, "downloading")
    try:
        models.download_model(model_id, lambda pct, msg: progress("download", pct, msg))
        db.set_model_status(model_id, "ready", path=str(spec.files[0].subdir if spec.files else ""))
    except Exception:
        db.set_model_status(model_id, "error", error="下载失败")
        raise
    emit({"type": "done", "stage": "download", "progress": 100, "message": f"{spec.label} 下载完成"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    job = db.get_job(args.job_id)
    if not job:
        emit({"type": "error", "message": f"任务不存在: {args.job_id}"})
        return 1
    db.init_db()
    progress = make_progress(args.job_id)
    project: dict[str, Any] | None = None
    if job.get("project_id"):
        project = db.get_project(job["project_id"])
        if not project:
            emit({"type": "error", "message": f"项目不存在: {job['project_id']}"})
            return 1
    emit({"type": "stage", "stage": "启动", "progress": 0, "message": "worker 已启动"})

    try:
        started = time.time()
        if os.environ.get("AUDIOLAB_FAKE") == "1" and job["kind"] in {"analyze", "refuse", "process"}:
            from audiolab import fake

            fake.run(job, project, progress)
            emit({"type": "done", "stage": "fake", "progress": 100, "message": "演示数据已生成"})
        elif job["kind"] == "analyze":
            assert project is not None
            run_analyze(job, project, progress)
        elif job["kind"] == "refuse":
            assert project is not None
            run_refuse(job, project, progress)
        elif job["kind"] == "process":
            assert project is not None
            run_process(job, project, progress)
        elif job["kind"] == "download":
            run_download(job, progress)
        else:
            raise ValueError(f"未知任务类型: {job['kind']}")
        emit({"type": "log", "line": f"耗时 {time.time() - started:.1f}s"})
        return 0
    except Exception as exc:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        db.update_job(args.job_id, status="failed", error=f"{type(exc).__name__}: {exc}", message="失败")
        if project and job.get("kind") == "analyze":
            db.update_project(project["id"], status="error", error=f"{type(exc).__name__}: {exc}")
        elif project:
            db.update_project(project["id"], error=f"{type(exc).__name__}: {exc}")
        emit({"type": "error", "message": f"{type(exc).__name__}: {exc}", "traceback": tb[-4000:]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
