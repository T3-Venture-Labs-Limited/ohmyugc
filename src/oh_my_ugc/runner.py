"""Run one paid model call: cache, budget, upload, submit, poll, download, ledger (design D2–D4, D7).

Every provider call goes through :func:`call`. It is safe to run again after a crash: the
``calls`` table remembers the provider's job id, so a restart resumes polling instead of paying
for a second submission.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oh_my_ugc import config, costs, db, providers, store
from oh_my_ugc.catalog.mapping import build_inputs, resolve_files
from oh_my_ugc.catalog.schema import Entry
from oh_my_ugc.errors import OmuError
from oh_my_ugc.providers import base

# Tests make polling instant.
sleep: Callable[[float], None] = time.sleep
POLL_START, POLL_MAX = 2.0, 6.0

_semaphores: dict[tuple[str, int], threading.BoundedSemaphore] = {}
_sem_lock = threading.Lock()
_ctx = threading.local()


class Cancelled(OmuError):
    def __init__(self) -> None:
        super().__init__("Cancelled.")


def semaphore(provider: str) -> threading.BoundedSemaphore:
    limit = config.concurrency(provider)
    with _sem_lock:
        return _semaphores.setdefault((provider, limit), threading.BoundedSemaphore(limit))


def set_context(
    job_id: str | None, project_id: str | None = None, cancel: threading.Event | None = None
) -> None:
    _ctx.job_id, _ctx.project_id, _ctx.cancel = job_id, project_id, cancel


def current_job() -> str | None:
    return getattr(_ctx, "job_id", None)


def stage(text: str) -> None:
    """Show what the current job is doing (best effort)."""
    job_id = current_job()
    if job_id:
        db.run("UPDATE jobs SET stage = ?, updated_at = ? WHERE id = ?", (text, db.now(), job_id))


@dataclass(slots=True)
class CallResult:
    media: list[str]
    meta: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    cached: bool = False

    @property
    def paths(self) -> list[Path]:
        return [store.path(m) for m in self.media]

    @property
    def path(self) -> Path:
        return store.path(self.media[0])


def _check_cancel() -> None:
    cancel = getattr(_ctx, "cancel", None)
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def _wait_hook(provider: str, seconds: float) -> None:
    stage(f"Waiting for {base.DISPLAY.get(provider, provider)} rate limit ({int(seconds)} s)")


def call(
    entry: Entry,
    slots: dict[str, Any],
    *,
    project_id: str | None = None,
    step: str = "",
    take: int = 0,
    quantities: dict[str, Any] | None = None,
) -> CallResult:
    quantities = quantities or {}
    project_id = project_id or getattr(_ctx, "project_id", None)
    inputs = build_inputs(entry, slots)
    key = costs.cache_key(entry, inputs, take)
    hit = costs.cache_get(key)
    if hit:
        return CallResult(hit["outputs"], hit["meta"], 0.0, cached=True)

    est = costs.estimate(entry, **quantities)
    reservation = costs.reserve(project_id, est.amount or 0.0)
    previous_hook, base.on_wait = base.on_wait, _wait_hook
    try:
        result = _run(entry, inputs, key)
    except Cancelled:
        raise
    except OmuError as exc:
        db.run(
            "UPDATE calls SET status = 'failed', error = ?, updated_at = ? WHERE key = ?",
            (exc.message, db.now(), key),
        )
        costs.record(
            project_id=project_id,
            job_id=current_job(),
            step=step,
            entry=entry,
            units=json.dumps(quantities),
            estimated=est.amount or 0.0,
            actual=0.0,
            status="failed",
        )
        raise
    finally:
        base.on_wait = previous_hook
        costs.release(reservation)
    media = _download(entry, result)
    actual = result.cost
    computed = False
    if actual is None:
        actual, computed = costs.actual_cost(entry, result.meta, quantities)
    costs.record(
        project_id=project_id,
        job_id=current_job(),
        step=step,
        entry=entry,
        units=json.dumps(quantities),
        estimated=est.amount or 0.0,
        actual=actual,
        computed=computed,
    )
    cost = actual if actual is not None else (est.amount or 0.0)
    meta = {
        k: v for k, v in result.meta.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))
    }
    costs.cache_put(key, media, meta, cost)
    db.run(
        "UPDATE calls SET status = 'done', outputs = ?, meta = ?, actual = ?, updated_at = ? WHERE key = ?",
        (json.dumps(media), json.dumps(meta), actual, db.now(), key),
    )
    return CallResult(media, meta, cost)


def _run(entry: Entry, inputs: dict[str, Any], key: str) -> base.PollResult:
    provider = providers.get(entry.provider)
    row = db.one("SELECT * FROM calls WHERE key = ?", (key,))
    job_id = row["provider_job_id"] if row and row["status"] == "running" and row["provider_job_id"] else None
    if job_id:
        stage(f"Resuming {provider.display} job")
    else:
        with semaphore(entry.provider):
            stage(f"Uploading to {provider.display}")
            payload = resolve_files(inputs, provider.upload)
            _check_cancel()
            stage(f"Submitting to {provider.display}")
            submission = provider.submit(entry.model, dict(payload), version=entry.version)
        if submission.result is not None and submission.result.status == "succeeded":
            return submission.result
        if submission.result is not None:
            raise OmuError(_plain_failure(provider.display, submission.result.error))
        job_id = submission.job_id
        if row:
            db.update(
                "calls",
                key,
                {"provider_job_id": job_id, "status": "running", "updated_at": db.now()},
                key="key",
            )
        else:
            db.insert(
                "calls",
                {
                    "key": key,
                    "provider": entry.provider,
                    "model": entry.model,
                    "provider_job_id": job_id,
                    "status": "running",
                    "created_at": db.now(),
                    "updated_at": db.now(),
                },
            )
    deadline = time.monotonic() + entry.timeout_minutes * 60
    interval = POLL_START
    while True:
        _check_cancel()
        result = provider.poll(job_id)
        if result.status == "succeeded":
            return result
        if result.status in ("failed", "canceled"):
            raise OmuError(_plain_failure(provider.display, result.error))
        stage(f"{provider.display}: {'in the queue' if result.status == 'queued' else 'generating'}")
        if time.monotonic() > deadline:
            provider.cancel(job_id)
            raise OmuError(
                f"{provider.display} did not finish in {entry.timeout_minutes} minutes. Try again or pick another model."
            )
        sleep(interval)
        interval = min(POLL_MAX, interval * 1.3)


def _plain_failure(display: str, error: str) -> str:
    error = base.redact((error or "").strip())
    if not error:
        return f"{display} could not make this. Try again or pick another model."
    sentence = error[:240].rstrip(".")
    return f"{display} could not make this: {sentence}."


def _download(entry: Entry, result: base.PollResult) -> list[str]:
    provider = providers.get(entry.provider)
    media = []
    stage("Saving the result")
    for output in result.outputs:
        data, ext = provider.download(output)
        media.append(store.put_bytes(data, ext))
    if not media:
        raise OmuError(f"{provider.display} finished but returned no file.")
    return media
