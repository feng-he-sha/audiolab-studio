from __future__ import annotations

import json

import pytest

from audiolab.core.schemas import MediaInfo, Segment, Timeline
from audiolab.server import db


def make_project(name: str = "unit-test") -> dict:
    db.init_db()
    media = MediaInfo(path="C:/tmp/test.wav", filename="test.wav", duration=12.0, sample_rate=48000, channels=2)
    project = db.create_project(name, "C:/tmp/test.wav", media, result_dir="C:/tmp/out", status="imported")
    return project


def test_project_crud_and_summary() -> None:
    project = make_project("db-crud")
    pid = project["id"]
    assert db.get_project(pid)["name"] == "db-crud"
    updated = db.update_project(pid, tags=["a"], summary={"vocals": 3.0})
    assert json.loads(json.dumps(updated["summary"])) == {"vocals": 3.0}
    items, total = db.list_projects(query="db-crud")
    assert total >= 1
    db.delete_project(pid, delete_outputs=False)
    assert db.get_project(pid) is None


def test_timeline_edits() -> None:
    project = make_project("db-timeline")
    pid = project["id"]
    timeline = Timeline(
        duration=12.0,
        segments=[
            Segment(start=0, stop=4, label="vocals", confidence=0.9),
            Segment(start=4, stop=8, label="music", confidence=0.8),
            Segment(start=8, stop=12, label="other", confidence=0.7),
        ],
    )
    saved = db.save_timeline(pid, "run1", timeline)
    assert len(saved.segments) == 3
    assert saved.summary["vocals"] == 4.0
    sid = saved.segments[0].id
    assert db.update_segment_label(pid, sid, "vocals+music").summary["vocals+music"] == 4.0
    merged = db.merge_segments(pid, [saved.segments[1].id, saved.segments[2].id])
    assert len(merged.segments) == 2
    split = db.split_segment(pid, merged.segments[1].id, 10.0)
    assert len(split.segments) == 3
    db.delete_project(pid, delete_outputs=False)


def test_jobs() -> None:
    job = db.create_job("analyze", "", {"quality": "fast"})
    assert job["status"] == "queued"
    updated = db.update_job(job["id"], status="running", progress=25, stage="probe")
    assert updated["progress"] == 25
    assert any(j["id"] == job["id"] for j in db.list_jobs())
