from __future__ import annotations

import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from audiolab.server.app import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _wav(path) -> None:
    sr = 16000
    t = np.arange(sr * 3) / sr
    wav = (0.15 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(path, wav, sr)


def test_health_and_doctor(client) -> None:
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert "device" in health
    doctor = client.get("/api/doctor").json()
    assert "checks" in doctor and doctor["checks"]


def test_import_and_fake_analyze(client, tmp_path) -> None:
    source = tmp_path / "api_sample.wav"
    _wav(source)
    response = client.post("/api/projects/import", json={"paths": [str(source)]})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["errors"] == []
    project = payload["projects"][0]
    pid = project["id"]
    assert project["media"]["duration"] > 2.5

    response = client.post(f"/api/projects/{pid}/analyze", json={"quality": "fast", "skip_tagging": True})
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]

    job = None
    for _ in range(80):
        time.sleep(0.5)
        jobs = client.get("/api/jobs").json()["items"]
        found = [j for j in jobs if j["id"] == job_id]
        if found:
            job = found[0]
            if job["status"] in {"done", "failed", "canceled"}:
                break
    assert job is not None
    assert job["status"] == "done", job

    project = client.get(f"/api/projects/{pid}").json()
    assert project["status"] == "analyzed"
    timeline = client.get(f"/api/projects/{pid}/timeline").json()
    assert timeline["segments"]
    assert timeline["duration"] > 0
    timbre = client.get(f"/api/projects/{pid}/timbre").json()
    assert "clusters" in timbre
    artifacts = client.get(f"/api/projects/{pid}/artifacts").json()["artifacts"]
    assert any(a["kind"] == "original" for a in artifacts)
    report = client.get(f"/api/projects/{pid}/report")
    assert report.status_code == 200
    assert "<base href=\"/api/files/" in report.text
    assert client.get(f"/api/projects/{pid}/export?format=json").status_code == 200
    csv_export = client.get(f"/api/projects/{pid}/export?format=csv")
    assert csv_export.status_code == 200
    assert "auto_label" in csv_export.text

    # manual label override
    segment = timeline["segments"][0]
    response = client.patch(f"/api/projects/{pid}/segments/{segment['id']}", json={"user_label": "music"})
    assert response.status_code == 200
    assert response.json()["segments"][0]["user_label"] == "music"

    # settings are readable; PATCH is covered manually to avoid persisting the
    # temporary test workspace into the user's settings.json.
    settings = client.get("/api/settings").json()
    assert "device" in settings and "models_dir" in settings

    # models list is always available
    models = client.get("/api/models").json()["models"]
    assert isinstance(models, list) and models
