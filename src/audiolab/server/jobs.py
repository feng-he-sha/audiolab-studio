"""Job queue: one GPU-ish worker, subprocess isolation, live events."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from audiolab import config
from audiolab.server import db
from audiolab.server.events import HUB


class JobManager:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._running = False
        self._current: str | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            db.init_db()
            recovered = db.mark_interrupted_jobs()
            for job in db.queued_jobs():
                self._queue.put(job["id"])
            self._thread = threading.Thread(target=self._run_loop, name="audiolab-jobs", daemon=True)
            self._thread.start()
            if recovered:
                HUB.publish({"type": "log", "job_id": "", "line": f"启动恢复：{recovered} 个中断任务已标记"})

    def shutdown(self) -> None:
        with self._lock:
            self._running = False
            procs = list(self._processes.values())
        for proc in procs:
            self._terminate(proc)
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    # -- public API --------------------------------------------------------

    def submit(self, kind: str, project_id: str = "", params: dict[str, Any] | None = None) -> dict[str, Any]:
        job = db.create_job(kind, project_id, params or {})
        HUB.publish({"type": "job", "job": self._public_job(job)})
        self._queue.put(job["id"])
        return job

    def cancel(self, job_id: str) -> bool:
        job = db.get_job(job_id)
        if not job:
            return False
        if job["status"] == "queued":
            db.update_job(job_id, status="canceled", finished_at=db.now_iso(), message="已取消")
            HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or job)})
            return True
        with self._lock:
            proc = self._processes.get(job_id)
        if proc:
            self._terminate(proc)
            db.update_job(job_id, status="canceled", finished_at=db.now_iso(), message="已取消")
            HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or job)})
            return True
        return False

    def retry(self, job_id: str) -> dict[str, Any] | None:
        job = db.get_job(job_id)
        if not job:
            return None
        return self.submit(job["kind"], job["project_id"], job["params"])

    def current_job_id(self) -> str | None:
        return self._current

    # -- worker loop -------------------------------------------------------

    def _run_loop(self) -> None:
        while self._running:
            try:
                job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not self._running:
                break
            job = db.get_job(job_id)
            if not job or job["status"] != "queued":
                continue
            self._current = job_id
            try:
                self._execute(job)
            except Exception as exc:
                db.update_job(
                    job_id,
                    status="failed",
                    finished_at=db.now_iso(),
                    error=f"任务管理器异常: {exc}",
                    message="失败",
                )
                HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or job)})
            finally:
                self._current = None
                self._queue.task_done()

    def _execute(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        log_path = Path(job.get("log_path") or config.logs_dir() / f"job-{job_id}.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = db.now_iso()
        db.update_job(
            job_id,
            status="running",
            started_at=started,
            progress=0.0,
            stage="启动",
            message="任务启动",
        )
        HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or job)})

        cmd = [config.python_exe(), "-m", "audiolab.jobs.worker", "--job-id", job_id]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(config.SRC) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("HF_HOME", str(Path(config.load_settings().models_dir) / "hf"))
        endpoint = config.load_settings().hf_endpoint
        if endpoint:
            env.setdefault("HF_ENDPOINT", endpoint)
        if config.load_settings().device:
            env.setdefault("AUDIOLAB_DEVICE", config.load_settings().device)

        done = False
        error_msg = ""
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            log.write(f"\n=== job {job_id} {job['kind']} {started} ===\n")
            log.flush()
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(config.ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as exc:
                db.update_job(
                    job_id,
                    status="failed",
                    finished_at=db.now_iso(),
                    error=f"无法启动 worker: {exc}",
                    message="启动失败",
                )
                HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or job)})
                return
            with self._lock:
                self._processes[job_id] = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                log.write(line + "\n")
                log.flush()
                if line.startswith("{"):
                    try:
                        event = json.loads(line)
                    except Exception:
                        event = None
                    if isinstance(event, dict):
                        done, error_msg = self._handle_event(job_id, event, done, error_msg)
                        continue
                HUB.publish({"type": "log", "job_id": job_id, "line": line})
            proc.wait()
            with self._lock:
                self._processes.pop(job_id, None)

        current = db.get_job(job_id)
        if current and current["status"] == "canceled":
            db.update_job(job_id, finished_at=db.now_iso(), message="已取消")
        elif done:
            db.update_job(job_id, status="done", progress=100.0, finished_at=db.now_iso(), message="完成")
        else:
            db.update_job(
                job_id,
                status="failed",
                finished_at=db.now_iso(),
                error=error_msg or f"worker 退出码 {proc.returncode}",
                message="失败",
            )
        HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or job)})

    def _handle_event(
        self, job_id: str, event: dict[str, Any], done: bool, error_msg: str
    ) -> tuple[bool, str]:
        kind = event.get("type")
        if kind == "stage":
            db.update_job(
                job_id,
                stage=str(event.get("stage", "")),
                progress=float(event.get("progress", 0)),
                message=str(event.get("message", "")),
            )
            HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or {})})
        elif kind == "progress":
            db.update_job(
                job_id,
                progress=float(event.get("progress", 0)),
                message=str(event.get("message", "")),
                stage=str(event.get("stage", "")),
            )
            HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or {})})
        elif kind == "log":
            HUB.publish({"type": "log", "job_id": job_id, "line": str(event.get("line", ""))})
        elif kind == "done":
            done = True
            HUB.publish(
                {
                    "type": "job",
                    "job": self._public_job(db.get_job(job_id) or {}),
                }
            )
        elif kind == "error":
            error_msg = str(event.get("message", "任务失败"))
            db.update_job(job_id, status="failed", error=error_msg, message="失败")
            HUB.publish({"type": "job", "job": self._public_job(db.get_job(job_id) or {})})
        return done, error_msg

    def _terminate(self, proc: subprocess.Popen[str]) -> None:
        try:
            import psutil

            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.terminate()
                except Exception:
                    pass
            parent.terminate()
            try:
                parent.wait(timeout=5)
            except Exception:
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                parent.kill()
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": job.get("id", ""),
            "project_id": job.get("project_id", ""),
            "kind": job.get("kind", ""),
            "status": job.get("status", ""),
            "stage": job.get("stage", ""),
            "progress": job.get("progress", 0),
            "message": job.get("message", ""),
            "created_at": job.get("created_at", ""),
            "started_at": job.get("started_at", ""),
            "finished_at": job.get("finished_at", ""),
            "error": job.get("error", ""),
            "params": job.get("params", {}),
        }


JOB_MANAGER = JobManager()
