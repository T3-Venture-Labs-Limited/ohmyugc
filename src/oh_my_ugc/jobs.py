"""Durable background jobs (design D3).

A job is a unit of user-visible work (render a shot, generate frames, assemble an ad). Jobs live
in SQLite so the browser can close and the app can restart. Provider-level durability is in
``runner.call``: a re-run job resumes the provider job it had already submitted.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from oh_my_ugc import config, db, runner
from oh_my_ugc.errors import OmuError

logger = logging.getLogger(__name__)

HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {}
_cancels: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


def register(kind: str):
    def wrap(fn):
        HANDLERS[kind] = fn
        return fn

    return wrap


def enqueue(
    kind: str, *, project_id: str | None = None, shot_id: str | None = None, payload: dict | None = None
) -> str:
    return db.insert(
        "jobs",
        {
            "kind": kind,
            "project_id": project_id,
            "shot_id": shot_id,
            "status": "queued",
            "stage": "Queued",
            "payload": payload or {},
            "created_at": db.now(),
            "updated_at": db.now(),
        },
    )


def get(job_id: str) -> dict[str, Any]:
    from oh_my_ugc.errors import NotFound

    job = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job:
        raise NotFound("That job")
    return public(job)


def public(job: dict[str, Any]) -> dict[str, Any]:
    status = job["status"]
    stage = job.get("stage") or ""
    display = status
    if status == "queued" and "rate limit" in stage.lower():
        display = "waiting"
    if status == "running" and stage.lower().startswith("waiting for") and "rate limit" in stage.lower():
        display = "waiting"
    if status == "running" and stage.lower().startswith("checking"):
        display = "checking"
    started = job.get("started_at")
    return {**job, "display": display, "started_at": started}


def listing(project_id: str | None = None, shot_id: str | None = None, limit: int = 100) -> list[dict]:
    clauses, params = [], []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if shot_id:
        clauses.append("shot_id = ?")
        params.append(shot_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return [
        public(j)
        for j in db.many(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC, rowid DESC LIMIT {int(limit)}", params
        )
    ]


def active(project_id: str) -> list[dict]:
    return [
        public(j)
        for j in db.many(
            "SELECT * FROM jobs WHERE project_id = ? AND status IN ('queued','running') ORDER BY created_at",
            (project_id,),
        )
    ]


def cancel(job_id: str) -> dict[str, Any]:
    job = get(job_id)
    if job["status"] == "queued":
        db.update("jobs", job_id, {"status": "canceled", "stage": "Canceled", "updated_at": db.now()})
    elif job["status"] == "running":
        with _cancel_lock:
            event = _cancels.get(job_id)
        if event:
            event.set()
    return get(job_id)


def requeue_interrupted() -> int:
    """Jobs that were running when the app stopped go back in the queue; their provider jobs resume."""
    rows = db.many("SELECT id FROM jobs WHERE status = 'running'")
    for r in rows:
        db.update("jobs", r["id"], {"status": "queued", "stage": "Resuming", "updated_at": db.now()})
    return len(rows)


def claim() -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute(
        "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at, rowid LIMIT 1"
    ).fetchone()
    if not row:
        return None
    cur = conn.execute(
        "UPDATE jobs SET status = 'running', started_at = ?, updated_at = ? WHERE id = ? AND status = 'queued'",
        (db.now(), db.now(), row["id"]),
    )
    if cur.rowcount != 1:
        return None
    return db.one("SELECT * FROM jobs WHERE id = ?", (row["id"],))


def run_job(job: dict[str, Any]) -> None:
    handler = HANDLERS.get(job["kind"])
    event = threading.Event()
    with _cancel_lock:
        _cancels[job["id"]] = event
    runner.set_context(job["id"], job.get("project_id"), event)
    try:
        if handler is None:
            raise OmuError(f"Unknown job kind '{job['kind']}'.")
        result = handler({**job, "cancel": event}) or {}
        db.update(
            "jobs",
            job["id"],
            {"status": "done", "stage": "Done", "result": result, "error": None, "updated_at": db.now()},
        )
    except runner.Cancelled:
        db.update("jobs", job["id"], {"status": "canceled", "stage": "Canceled", "updated_at": db.now()})
    except OmuError as exc:
        logger.info("job %s failed: %s", job["id"], exc.message)
        db.update(
            "jobs",
            job["id"],
            {"status": "failed", "stage": "Failed", "error": exc.message, "updated_at": db.now()},
        )
    except Exception as exc:  # a bug: say so plainly, keep the detail in the log
        logger.exception("job %s crashed", job["id"])
        db.update(
            "jobs",
            job["id"],
            {
                "status": "failed",
                "stage": "Failed",
                "error": f"Something went wrong: {type(exc).__name__}. Try again, and report it if it keeps happening.",
                "updated_at": db.now(),
            },
        )
    finally:
        runner.set_context(None)
        with _cancel_lock:
            _cancels.pop(job["id"], None)


def run_pending() -> int:
    """Run queued jobs on this thread until none remain (used by tests and the CLI)."""
    n = 0
    while (job := claim()) is not None:
        run_job(job)
        n += 1
    return n


def wait(job_id: str, timeout: float = 3600, poll: float = 0.5) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = get(job_id)
        if job["status"] in ("done", "failed", "canceled"):
            return job
        time.sleep(poll)
    return get(job_id)


class Worker:
    """A pool of threads that run queued jobs."""

    def __init__(self, threads: int = 6, idle_seconds: float = 0.5) -> None:
        self.idle_seconds = idle_seconds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads = [
            threading.Thread(target=self._loop, name=f"omu-worker-{i}", daemon=True) for i in range(threads)
        ]

    def start(self) -> None:
        requeue_interrupted()
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = claim()
            except Exception:
                logger.exception("worker error")
                job = None
            if job is None:
                self._wake.wait(self.idle_seconds)
                self._wake.clear()
            else:
                run_job(job)


# ── background worker for the CLI ────────────────────────────────────────────


def _pidfile():
    return config.home() / "worker.pid"


def worker_alive() -> bool:
    try:
        pid = int(_pidfile().read_text())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def claim_pidfile() -> None:
    _pidfile().write_text(str(os.getpid()))


def ensure_worker() -> None:
    """Start a detached worker (``omu worker``) if no server or worker is processing jobs."""
    if worker_alive():
        return
    subprocess.Popen(
        [sys.executable, "-m", "oh_my_ugc.cli", "worker"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ},
    )
