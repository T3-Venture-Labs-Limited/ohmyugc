"""fal: queue API (submit, poll the status URL, fetch the result) and CDN uploads."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from oh_my_ugc import config
from oh_my_ugc.errors import OmuError
from oh_my_ugc.providers import base
from oh_my_ugc.providers.base import Http, Output, PollResult, Provider, Submission, plain_error, redact

QUEUE = "https://queue.fal.run"
REST = "https://rest.fal.ai"
FILE_KEYS = ("video", "audio", "image", "images", "audio_file", "file", "files", "video_file")


class Fal(Provider):
    name = "fal"
    display = "fal"

    def __init__(self) -> None:
        self.http = Http("fal", QUEUE, lambda: {"Authorization": f"Key {self.key()}"})

    def check_key(self) -> str:
        # Starting an upload is authenticated and free; nothing is stored.
        self.http.request(
            "POST",
            f"{REST}/storage/upload/initiate",
            params={"storage_type": "fal-cdn-v3"},
            json={"file_name": "ping.txt", "content_type": "text/plain"},
            retries=1,
        )
        return "connected"

    def upload(self, path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        init = self.http.json(
            "POST",
            f"{REST}/storage/upload/initiate",
            params={"storage_type": "fal-cdn-v3"},
            json={"file_name": path.name, "content_type": mime},
        )
        try:
            with httpx.Client(timeout=300, transport=base.transport) as client:
                put = client.put(
                    init["upload_url"], content=path.read_bytes(), headers={"Content-Type": mime}
                )
        except httpx.HTTPError as exc:
            raise OmuError("Could not upload a file to fal.", detail=redact(str(exc))) from exc
        if put.status_code >= 400:
            raise plain_error("fal", put.status_code, put.text)
        return init["file_url"]

    def submit(self, model: str, inputs: dict[str, Any], *, version: str | None = None) -> Submission:
        data = self.http.json("POST", f"/{model}", json=inputs)
        ref = {k: data.get(k) for k in ("request_id", "status_url", "response_url", "cancel_url")}
        return Submission(job_id=json.dumps(ref))

    def poll(self, job_id: str) -> PollResult:
        ref = json.loads(job_id)
        status = self.http.json("GET", ref["status_url"]).get("status", "")
        if status == "IN_QUEUE":
            return PollResult("queued")
        if status != "COMPLETED":
            return PollResult("running")
        try:
            result = self.http.json("GET", ref["response_url"])
        except OmuError as exc:
            return PollResult("failed", error=exc.message)
        return self._result(result)

    def cancel(self, job_id: str) -> None:
        try:
            self.http.request("PUT", json.loads(job_id)["cancel_url"], retries=0)
        except Exception:
            pass

    @staticmethod
    def _result(result: dict) -> PollResult:
        if not isinstance(result, dict):
            return PollResult("failed", error="fal returned an unexpected result.")
        if result.get("detail") and not any(k in result for k in FILE_KEYS):
            return PollResult("failed", error=f"fal said: {str(result['detail'])[:240]}")
        urls: list[Output] = []
        for key in FILE_KEYS:
            value = result.get(key)
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, dict) and item.get("url"):
                    urls.append(Output(url=item["url"]))
        meta = {k: result[k] for k in ("duration", "timestamps", "description") if k in result}
        if not urls:
            return PollResult("failed", error="fal finished but returned no file.", meta=meta)
        return PollResult("succeeded", urls, meta=meta)


def configured() -> bool:
    return bool(config.get_key("fal"))
