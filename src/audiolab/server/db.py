"""SQLite persistence for AudioLab Studio.

Small, dependency-free repository layer. One connection per operation keeps it
safe across FastAPI thread-pool requests and the worker subprocess (WAL mode).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from audiolab import config
from audiolab.core.schemas import (
    MediaInfo,
    Segment,
    Timeline,
    TimbreCluster,
    TimbreClip,
    TimbreFeatures,
    TimbreResult,
)

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex[:12]
    return f"{prefix}{value}" if prefix else value


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    db_file = config.db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_file), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_hash TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'imported',
                media_json TEXT DEFAULT '',
                tags_json TEXT DEFAULT '[]',
                summary_json TEXT DEFAULT '{}',
                result_dir TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_hash
                ON projects(source_hash) WHERE source_hash != '';

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'done',
                params_json TEXT DEFAULT '{}',
                result_dir TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                finished_at TEXT DEFAULT '',
                error TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);

            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                run_id TEXT DEFAULT '',
                idx INTEGER NOT NULL DEFAULT 0,
                start REAL NOT NULL,
                stop REAL NOT NULL,
                label TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                tags_json TEXT DEFAULT '{}',
                user_label TEXT DEFAULT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_segments_project ON segments(project_id, idx);

            CREATE TABLE IF NOT EXISTS clusters (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                run_id TEXT DEFAULT '',
                idx INTEGER NOT NULL,
                label TEXT NOT NULL,
                color TEXT DEFAULT '',
                features_json TEXT DEFAULT '{}',
                user_label TEXT DEFAULT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_clusters_project ON clusters(project_id, idx);

            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                clip_id TEXT NOT NULL,
                path TEXT DEFAULT '',
                start REAL DEFAULT 0,
                stop REAL DEFAULT 0,
                duration REAL DEFAULT 0,
                features_json TEXT DEFAULT '{}',
                is_representative INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_clips_project ON clips(project_id);

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT DEFAULT '',
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT DEFAULT '',
                progress REAL DEFAULT 0,
                message TEXT DEFAULT '',
                params_json TEXT DEFAULT '{}',
                log_path TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT DEFAULT '',
                finished_at TEXT DEFAULT '',
                error TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);

            CREATE TABLE IF NOT EXISTS models (
                id TEXT PRIMARY KEY,
                engine TEXT DEFAULT '',
                filename TEXT DEFAULT '',
                label TEXT DEFAULT '',
                size INTEGER DEFAULT 0,
                path TEXT DEFAULT '',
                status TEXT DEFAULT 'missing',
                license TEXT DEFAULT '',
                source TEXT DEFAULT '',
                sha256 TEXT DEFAULT '',
                error TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            """
        )
        row = con.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            con.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        elif int(row["version"]) < SCHEMA_VERSION:
            con.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------


def _row_to_project(row: sqlite3.Row) -> dict[str, Any]:
    media = None
    if row["media_json"]:
        try:
            media = MediaInfo.model_validate(json.loads(row["media_json"]))
        except Exception:
            media = None
    return {
        "id": row["id"],
        "name": row["name"],
        "source_path": row["source_path"],
        "status": row["status"],
        "media": media,
        "tags": json.loads(row["tags_json"] or "[]"),
        "summary": json.loads(row["summary_json"] or "{}"),
        "result_dir": row["result_dir"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "error": row["error"],
    }


def project_by_hash(source_hash: str) -> dict[str, Any] | None:
    if not source_hash:
        return None
    with connect() as con:
        row = con.execute("SELECT * FROM projects WHERE source_hash=?", (source_hash,)).fetchone()
        return _row_to_project(row) if row else None


def create_project(
    name: str,
    source_path: str,
    media: MediaInfo,
    result_dir: str,
    status: str = "imported",
) -> dict[str, Any]:
    pid = new_id("p_")
    ts = now_iso()
    with connect() as con:
        con.execute(
            """INSERT INTO projects
               (id,name,source_path,source_hash,status,media_json,tags_json,summary_json,
                result_dir,error,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pid,
                name,
                source_path,
                media.sha256 or "",
                status,
                media.model_dump_json(),
                "[]",
                "{}",
                result_dir,
                "",
                ts,
                ts,
            ),
        )
        row = con.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return _row_to_project(row)


def get_project(project_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return _row_to_project(row) if row else None


def list_projects(
    query: str = "", status: str = "", page: int = 1, page_size: int = 50
) -> tuple[list[dict[str, Any]], int]:
    page = max(1, int(page))
    page_size = max(1, min(200, int(page_size)))
    where: list[str] = []
    params: list[Any] = []
    if query:
        where.append("(name LIKE ? OR source_path LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like])
    if status:
        where.append("status=?")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with connect() as con:
        total = int(con.execute(f"SELECT COUNT(*) AS n FROM projects{clause}", params).fetchone()["n"])
        rows = con.execute(
            f"SELECT * FROM projects{clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        return [_row_to_project(r) for r in rows], total


def update_project(project_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "name",
        "status",
        "media",
        "tags",
        "summary",
        "result_dir",
        "error",
        "source_hash",
    }
    columns = {"media": "media_json", "tags": "tags_json", "summary": "summary_json"}
    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "media" and isinstance(value, MediaInfo):
            value = value.model_dump_json()
        elif key in {"tags", "summary"}:
            value = json.dumps(value, ensure_ascii=False)
        sets.append(f"{columns.get(key, key)}=?")
        values.append(value)
    if not sets:
        return get_project(project_id)
    sets.append("updated_at=?")
    values.append(now_iso())
    values.append(project_id)
    with connect() as con:
        con.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", values)
    return get_project(project_id)


def delete_project(project_id: str, delete_outputs: bool = True) -> None:
    project = get_project(project_id)
    with connect() as con:
        for table in ("segments", "clusters", "clips", "runs", "jobs"):
            con.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
        con.execute("DELETE FROM projects WHERE id=?", (project_id,))
    if delete_outputs and project and project.get("result_dir"):
        shutil.rmtree(project["result_dir"], ignore_errors=True)


def stats() -> dict[str, Any]:
    with connect() as con:
        projects = int(con.execute("SELECT COUNT(*) n FROM projects").fetchone()["n"])
        analyzed = int(
            con.execute("SELECT COUNT(*) n FROM projects WHERE status IN ('analyzed','ready')").fetchone()["n"]
        )
        jobs = int(con.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"])
        return {"projects": projects, "analyzed": analyzed, "jobs": jobs}


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


def save_run(
    project_id: str,
    kind: str,
    status: str,
    params: dict[str, Any],
    result_dir: str,
    started_at: str = "",
    finished_at: str = "",
    error: str = "",
    run_id: str | None = None,
) -> str:
    rid = run_id or new_id("r_")
    with connect() as con:
        con.execute(
            """INSERT OR REPLACE INTO runs
               (id,project_id,kind,status,params_json,result_dir,started_at,finished_at,error)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                project_id,
                kind,
                status,
                json.dumps(params, ensure_ascii=False),
                result_dir,
                started_at,
                finished_at,
                error,
            ),
        )
    return rid


def latest_run(project_id: str, kind: str | None = None) -> dict[str, Any] | None:
    sql = "SELECT * FROM runs WHERE project_id=?"
    params: list[Any] = [project_id]
    if kind:
        sql += " AND kind=?"
        params.append(kind)
    sql += " ORDER BY finished_at DESC, started_at DESC LIMIT 1"
    with connect() as con:
        row = con.execute(sql, params).fetchone()
        if not row:
            return None
        data = dict(row)
        data["params"] = json.loads(data.pop("params_json") or "{}")
        return data


# ---------------------------------------------------------------------------
# timeline / segments
# ---------------------------------------------------------------------------


def _timeline_summary(segments: list[Segment]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for seg in segments:
        label = seg.user_label or seg.label
        summary[label] = summary.get(label, 0.0) + max(0.0, seg.stop - seg.start)
    return {k: round(v, 3) for k, v in summary.items()}


def save_timeline(project_id: str, run_id: str, timeline: Timeline) -> Timeline:
    with connect() as con:
        con.execute("DELETE FROM segments WHERE project_id=?", (project_id,))
        for idx, seg in enumerate(timeline.segments):
            con.execute(
                """INSERT INTO segments
                   (project_id,run_id,idx,start,stop,label,confidence,tags_json,user_label)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    project_id,
                    run_id,
                    idx,
                    float(seg.start),
                    float(seg.stop),
                    seg.label,
                    float(seg.confidence),
                    json.dumps(seg.tags, ensure_ascii=False),
                    seg.user_label,
                ),
            )
        con.execute(
            "UPDATE projects SET summary_json=?, updated_at=? WHERE id=?",
            (
                json.dumps(_timeline_summary(timeline.segments), ensure_ascii=False),
                now_iso(),
                project_id,
            ),
        )
    return get_timeline(project_id)


def get_timeline(project_id: str) -> Timeline:
    project = get_project(project_id)
    duration = project["media"].duration if project and project.get("media") else 0.0
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM segments WHERE project_id=? ORDER BY idx ASC", (project_id,)
        ).fetchall()
    segments = [
        Segment(
            id=int(r["id"]),
            start=float(r["start"]),
            stop=float(r["stop"]),
            label=r["label"],
            confidence=float(r["confidence"] or 0),
            tags=json.loads(r["tags_json"] or "{}"),
            user_label=r["user_label"],
        )
        for r in rows
    ]
    return Timeline(
        duration=duration,
        segments=segments,
        summary=_timeline_summary(segments),
        warnings=[],
    )


def get_segment(project_id: str, segment_id: int) -> Segment | None:
    timeline = get_timeline(project_id)
    for seg in timeline.segments:
        if seg.id == segment_id:
            return seg
    return None


def update_segment_label(project_id: str, segment_id: int, user_label: str | None) -> Timeline:
    if user_label not in (None, "vocals", "music", "vocals+music", "other"):
        raise ValueError("invalid label")
    with connect() as con:
        con.execute(
            "UPDATE segments SET user_label=? WHERE id=? AND project_id=?",
            (user_label, segment_id, project_id),
        )
        con.execute("UPDATE projects SET updated_at=? WHERE id=?", (now_iso(), project_id))
    return get_timeline(project_id)


def merge_segments(project_id: str, segment_ids: list[int], label: str | None = None) -> Timeline:
    timeline = get_timeline(project_id)
    chosen = [s for s in timeline.segments if s.id in set(segment_ids)]
    if len(chosen) < 2:
        return timeline
    positions = [i for i, s in enumerate(timeline.segments) if s.id in set(segment_ids)]
    if positions != list(range(min(positions), max(positions) + 1)):
        raise ValueError("只能合并连续的分段")
    start = min(s.start for s in chosen)
    stop = max(s.stop for s in chosen)
    total = max(1e-6, sum(s.stop - s.start for s in chosen))
    confidence = sum(s.confidence * (s.stop - s.start) for s in chosen) / total
    merged_label = label or chosen[0].user_label or chosen[0].label
    merged = Segment(
        start=start,
        stop=stop,
        label=merged_label,  # type: ignore[arg-type]
        confidence=confidence,
        tags=chosen[0].tags,
        user_label=label,
    )
    rest = [s for s in timeline.segments if s.id not in set(segment_ids)]
    rest.append(merged)
    rest.sort(key=lambda s: s.start)
    return save_timeline(project_id, "", Timeline(duration=timeline.duration, segments=rest))


def split_segment(project_id: str, segment_id: int, at: float) -> Timeline:
    timeline = get_timeline(project_id)
    out: list[Segment] = []
    for seg in timeline.segments:
        if seg.id == segment_id and seg.start + 0.05 < at < seg.stop - 0.05:
            left = seg.model_copy(update={"id": 0, "stop": at})
            right = seg.model_copy(update={"id": 0, "start": at})
            out.extend([left, right])
        else:
            out.append(seg.model_copy(update={"id": 0}))
    return save_timeline(project_id, "", Timeline(duration=timeline.duration, segments=out))


# ---------------------------------------------------------------------------
# timbre
# ---------------------------------------------------------------------------


def save_timbre(project_id: str, run_id: str, result: TimbreResult) -> TimbreResult:
    with connect() as con:
        con.execute("DELETE FROM clips WHERE project_id=?", (project_id,))
        con.execute("DELETE FROM clusters WHERE project_id=?", (project_id,))
        for cluster in result.clusters:
            short = cluster.id.split(":")[-1]
            key = f"{project_id}:{short}"
            con.execute(
                """INSERT OR REPLACE INTO clusters
                   (id,project_id,run_id,idx,label,color,features_json,user_label)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    key,
                    project_id,
                    run_id,
                    cluster.index,
                    cluster.label,
                    cluster.color,
                    cluster.features.model_dump_json(),
                    cluster.user_label,
                ),
            )
            for clip in cluster.clips:
                con.execute(
                    """INSERT INTO clips
                       (project_id,cluster_id,clip_id,path,start,stop,duration,features_json,is_representative)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        project_id,
                        key,
                        clip.id,
                        clip.path,
                        clip.start,
                        clip.stop,
                        clip.duration,
                        clip.features.model_dump_json(),
                        1 if clip.is_representative else 0,
                    ),
                )
    return get_timbre(project_id)


def get_timbre(project_id: str) -> TimbreResult:
    with connect() as con:
        cluster_rows = con.execute(
            "SELECT * FROM clusters WHERE project_id=? ORDER BY idx ASC", (project_id,)
        ).fetchall()
        clip_rows = con.execute(
            "SELECT * FROM clips WHERE project_id=? ORDER BY id ASC", (project_id,)
        ).fetchall()
    clips_by_cluster: dict[str, list[TimbreClip]] = {}
    for r in clip_rows:
        cluster_key = r["cluster_id"]
        try:
            features = TimbreFeatures.model_validate(json.loads(r["features_json"] or "{}"))
        except Exception:
            features = TimbreFeatures()
        clip = TimbreClip(
            id=r["clip_id"],
            path=r["path"],
            url="",
            start=float(r["start"] or 0),
            stop=float(r["stop"] or 0),
            duration=float(r["duration"] or 0),
            features=features,
            is_representative=bool(r["is_representative"]),
        )
        clips_by_cluster.setdefault(cluster_key, []).append(clip)
    clusters: list[TimbreCluster] = []
    points: list[dict[str, float]] = []
    for r in cluster_rows:
        key = r["id"]
        short_id = key.split(":")[-1]
        try:
            features = TimbreFeatures.model_validate(json.loads(r["features_json"] or "{}"))
        except Exception:
            features = TimbreFeatures()
        cluster = TimbreCluster(
            id=short_id,
            index=int(r["idx"]),
            label=r["label"],
            color=r["color"] or "#94a3b8",
            n_clips=len(clips_by_cluster.get(key, [])),
            total_duration=sum(c.duration for c in clips_by_cluster.get(key, [])),
            features=features,
            clips=clips_by_cluster.get(key, []),
            representative=[],
            user_label=r["user_label"],
        )
        clusters.append(cluster)
    return TimbreResult(backend="", clusters=clusters, points=points, warnings=[])


def update_cluster_label(project_id: str, cluster_id: str, user_label: str | None) -> TimbreResult:
    with connect() as con:
        con.execute(
            "UPDATE clusters SET user_label=? WHERE id=?",
            (user_label, f"{project_id}:{cluster_id}"),
        )
    return get_timbre(project_id)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


def create_job(
    kind: str, project_id: str = "", params: dict[str, Any] | None = None, status: str = "queued"
) -> dict[str, Any]:
    jid = new_id("j_")
    ts = now_iso()
    log_path = str(config.logs_dir() / f"job-{jid}.log")
    with connect() as con:
        con.execute(
            """INSERT INTO jobs
               (id,project_id,kind,status,stage,progress,message,params_json,log_path,
                created_at,started_at,finished_at,error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                jid,
                project_id,
                kind,
                status,
                "",
                0.0,
                "等待中",
                json.dumps(params or {}, ensure_ascii=False),
                log_path,
                ts,
                "",
                "",
                "",
            ),
        )
    return get_job(jid)  # type: ignore[return-value]


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "kind": row["kind"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": float(row["progress"] or 0),
        "message": row["message"],
        "params": json.loads(row["params_json"] or "{}"),
        "log_path": row["log_path"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"],
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "status",
        "stage",
        "progress",
        "message",
        "started_at",
        "finished_at",
        "error",
        "params",
    }
    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "params":
            value = json.dumps(value, ensure_ascii=False)
        sets.append(f"{key}=?")
        values.append(value)
    if not sets:
        return get_job(job_id)
    values.append(job_id)
    with connect() as con:
        con.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", values)
    return get_job(job_id)


def list_jobs(active_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT * FROM jobs"
    params: list[Any] = []
    if active_only:
        sql += " WHERE status IN ('queued','running')"
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(500, limit)))
    with connect() as con:
        return [_row_to_job(r) for r in con.execute(sql, params).fetchall()]


def retry_job(job_id: str) -> dict[str, Any] | None:
    job = get_job(job_id)
    if not job:
        return None
    return create_job(job["kind"], job["project_id"], job["params"])


def mark_interrupted_jobs() -> int:
    with connect() as con:
        cur = con.execute(
            "UPDATE jobs SET status='interrupted', finished_at=?, error='应用重启时任务仍在运行' "
            "WHERE status='running'",
            (now_iso(),),
        )
        return int(cur.rowcount or 0)


def queued_jobs() -> list[dict[str, Any]]:
    with connect() as con:
        return [
            _row_to_job(r)
            for r in con.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at ASC"
            ).fetchall()
        ]


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


def upsert_model(data: dict[str, Any]) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO models (id,engine,filename,label,size,path,status,license,source,sha256,error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 engine=excluded.engine, filename=excluded.filename, label=excluded.label,
                 size=excluded.size, path=excluded.path, status=excluded.status,
                 license=excluded.license, source=excluded.source, sha256=excluded.sha256,
                 error=excluded.error""",
            (
                data["id"],
                data.get("engine", ""),
                data.get("filename", ""),
                data.get("label", ""),
                int(data.get("size", 0)),
                data.get("path", ""),
                data.get("status", "missing"),
                data.get("license", ""),
                data.get("source", ""),
                data.get("sha256", ""),
                data.get("error", ""),
            ),
        )


def list_models() -> list[dict[str, Any]]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM models ORDER BY engine, label").fetchall()]


def get_model(model_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        return dict(row) if row else None


def delete_model(model_id: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM models WHERE id=?", (model_id,))


def set_model_status(model_id: str, status: str, path: str = "", error: str = "") -> None:
    with connect() as con:
        con.execute(
            "UPDATE models SET status=?, path=COALESCE(NULLIF(?, ''), path), error=? WHERE id=?",
            (status, path, error, model_id),
        )
