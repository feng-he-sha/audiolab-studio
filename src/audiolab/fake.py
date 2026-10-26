"""Fast synthetic results for UI development and E2E tests.

Enabled with AUDIOLAB_FAKE=1. It still creates real (copied) audio artifacts so
the workbench can play and export something without downloading models.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from audiolab import config
from audiolab.core.schemas import (
    AnalysisResult,
    Artifact,
    MediaInfo,
    Segment,
    Timeline,
    TimbreCluster,
    TimbreFeatures,
    TimbreResult,
)
from audiolab.server import db


def _duration(source: str) -> float:
    try:
        from audiolab.core.media import probe

        return probe(source).duration
    except Exception:
        return 30.0


def _gen_timeline(duration: float) -> Timeline:
    pattern = [
        (0.00, 0.18, "vocals+music", 0.92),
        (0.18, 0.34, "vocals", 0.88),
        (0.34, 0.58, "music", 0.90),
        (0.58, 0.74, "vocals+music", 0.84),
        (0.74, 0.86, "vocals", 0.80),
        (0.86, 1.00, "other", 0.72),
    ]
    segments: list[Segment] = []
    for start_ratio, stop_ratio, label, conf in pattern:
        start = round(duration * start_ratio, 2)
        stop = round(duration * stop_ratio, 2)
        if stop - start < 0.2:
            continue
        tags = (
            {"Music": 0.91, "Speech": 0.76, "Singing": 0.31}
            if label in {"music", "vocals+music"}
            else {"Speech": 0.93, "Music": 0.12}
        )
        segments.append(
            Segment(start=start, stop=stop, label=label, confidence=conf, tags=tags)  # type: ignore[arg-type]
        )
    summary: dict[str, float] = {}
    for seg in segments:
        summary[seg.label] = round(summary.get(seg.label, 0.0) + seg.stop - seg.start, 2)
    return Timeline(duration=duration, segments=segments, summary=summary)


def _gen_timbre(duration: float) -> TimbreResult:
    clusters = [
        TimbreCluster(
            id="V1",
            index=0,
            label="中音 · 明亮 · 自然",
            color="#60a5fa",
            n_clips=3,
            total_duration=round(duration * 0.25, 2),
            features=TimbreFeatures(
                f0_median=178.0,
                f0_mean=181.0,
                f0_std=18.0,
                voiced_ratio=0.78,
                centroid_mean=2140.0,
                centroid_std=380.0,
                rolloff_mean=3920.0,
                flatness_mean=0.06,
                zcr_mean=0.08,
                harmonic_ratio=0.72,
                rms_db=-25.0,
                duration=round(duration * 0.25, 2),
            ),
        ),
        TimbreCluster(
            id="V2",
            index=1,
            label="低音 · 温暖 · 圆润",
            color="#34d399",
            n_clips=2,
            total_duration=round(duration * 0.18, 2),
            features=TimbreFeatures(
                f0_median=112.0,
                f0_mean=116.0,
                f0_std=12.0,
                voiced_ratio=0.71,
                centroid_mean=1480.0,
                centroid_std=260.0,
                rolloff_mean=2450.0,
                flatness_mean=0.045,
                zcr_mean=0.045,
                harmonic_ratio=0.81,
                rms_db=-23.0,
                duration=round(duration * 0.18, 2),
            ),
        ),
    ]
    points = [
        {"x": -0.62, "y": 0.35, "cluster": 0, "clip_id": "c1"},
        {"x": -0.51, "y": 0.48, "cluster": 0, "clip_id": "c2"},
        {"x": -0.70, "y": 0.22, "cluster": 0, "clip_id": "c3"},
        {"x": 0.58, "y": -0.42, "cluster": 1, "clip_id": "c4"},
        {"x": 0.66, "y": -0.30, "cluster": 1, "clip_id": "c5"},
    ]
    return TimbreResult(backend="colorsplitter", clusters=clusters, points=points, warnings=[])


def _copy_audio(source: str, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        cmd = [config.ffmpeg_exe(), "-y", "-v", "error", "-i", source, "-vn", "-ac", "2", "-ar", "48000", str(target)]
        subprocess.run(cmd, check=True, timeout=300, capture_output=True)
        return True
    except Exception:
        return False


def _make_preview(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                config.ffmpeg_exe(), "-y", "-v", "error", "-i", str(source),
                "-vn", "-ac", "2", "-ar", "32000", "-c:a", "aac", "-b:a", "96k", str(target),
            ],
            check=True,
            timeout=300,
            capture_output=True,
        )
    except Exception:
        pass


def _write_report(out_dir: Path, timeline: Timeline, timbre: TimbreResult) -> Path:
    try:
        from audiolab.core.report import build

        media = MediaInfo(path="", filename="demo", duration=timeline.duration)
        result = AnalysisResult(
            media=media,
            timeline=timeline,
            timbre=timbre,
            warnings=["AUDIOLAB_FAKE=1 演示数据"],
        )
        return build(result, out_dir / "report.html", "AudioLab Demo")
    except Exception:
        html = f"""<!doctype html><meta charset="utf-8"><title>Demo</title>
        <body style="background:#0b0e14;color:#e6edf7;font-family:sans-serif;padding:32px">
        <h1>AudioLab Studio · 演示报告</h1>
        <p>时长 {timeline.duration:.1f}s，{len(timeline.segments)} 个分段，{len(timbre.clusters)} 个音色簇。</p>
        </body>"""
        path = out_dir / "report.html"
        path.write_text(html, encoding="utf-8")
        return path


def _artifacts(project_id: str, out_dir: Path, duration: float) -> list[Artifact]:
    def art(aid: str, kind: str, label: str, rel: str, mime: str = "audio/wav") -> Artifact:
        path = out_dir / rel
        return Artifact(
            id=aid,
            kind=kind,
            label=label,
            path=str(path),
            url=f"/api/files/{project_id}/{rel}",
            duration=duration,
            size=path.stat().st_size if path.exists() else 0,
            mime=mime,
        )

    items = [art("original", "original", "原声", "audio/original.wav")]
    if (out_dir / "stems" / "vocals.wav").exists():
        items.append(art("vocals", "vocals", "人声", "stems/vocals.wav"))
    if (out_dir / "stems" / "instrumental.wav").exists():
        items.append(art("instrumental", "instrumental", "伴奏", "stems/instrumental.wav"))
    if (out_dir / "preview" / "original.m4a").exists():
        items.append(art("preview_original", "preview", "试听", "preview/original.m4a", "audio/mp4"))
    return items


def run(job: dict[str, Any], project: dict[str, Any], progress) -> None:
    kind = job["kind"]
    out_dir = Path(project.get("result_dir") or config.outputs_dir() / f"demo_{project['id']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    source = project["source_path"]
    duration = _duration(source)
    if kind == "process":
        progress("render", 20, "演示模式：复制音频")
        target = out_dir / "processed" / "demo.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_audio(source, target)
        progress("render", 100, "演示处理完成")
        summary = dict(project.get("summary") or {})
        summary["last_process"] = {
            "preset": (job.get("params") or {}).get("preset", "douyin"),
            "path": str(target),
            "url": f"/api/files/{project['id']}/processed/demo.wav",
            "format": "wav",
            "loudness": {"integrated_lufs": -14.0},
        }
        db.update_project(project["id"], summary=summary, status="analyzed")
        return

    progress("extract", 10, "演示模式：生成原声")
    original = out_dir / "audio" / "original.wav"
    _copy_audio(source, original)
    vocals = out_dir / "stems" / "vocals.wav"
    instrumental = out_dir / "stems" / "instrumental.wav"
    _copy_audio(source, vocals)
    _copy_audio(source, instrumental)
    progress("separation", 35, "演示模式：假分离")
    _make_preview(original, out_dir / "preview" / "original.m4a")
    _make_preview(vocals, out_dir / "preview" / "vocals.m4a")
    _make_preview(instrumental, out_dir / "preview" / "instrumental.m4a")
    progress("fusion", 60, "演示模式：假分段")
    timeline = _gen_timeline(duration)
    timbre = _gen_timbre(duration)
    progress("timbre", 80, "演示模式：假音色簇")
    report = _write_report(out_dir, timeline, timbre)
    result = AnalysisResult(
        project_id=project["id"],
        media=MediaInfo(path=source, filename=Path(source).name, duration=duration),
        timeline=timeline,
        timbre=timbre,
        artifacts=_artifacts(project["id"], out_dir, duration),
        report_url=f"/api/projects/{project['id']}/report",
        warnings=["AUDIOLAB_FAKE=1 演示数据，非真实分析结果"],
    )
    (out_dir / "analysis.json").write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "timeline.json").write_text(
        json.dumps(timeline.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "timbre.json").write_text(
        json.dumps(timbre.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    run_id = db.new_id("r_")
    db.save_timeline(project["id"], run_id, timeline)
    db.save_timbre(project["id"], run_id, timbre)
    db.save_run(project["id"], "analyze", "done", job.get("params") or {}, str(out_dir), run_id=run_id)
    summary = dict(timeline.summary)
    summary.update({"clusters": len(timbre.clusters), "duration": duration, "fake": True, "report_url": result.report_url})
    db.update_project(project["id"], status="analyzed", summary=summary, error="")
    progress("report", 100, f"演示报告已生成: {report.name}")
