"""Replicate: predictions API. Official models run by name; community models need a version id."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from oh_my_ugc.providers.base import Http, Output, PollResult, Provider, Submission

API = "https://api.replicate.com/v1"


class Replicate(Provider):
    name = "replicate"
    display = "Replicate"

    def __init__(self) -> None:
        self.http = Http("replicate", API, lambda: {"Authorization": f"Bearer {self.key()}"})
        self._models: dict[str, dict] = {}

    def check_key(self) -> str:
        self.http.request("GET", "/account", retries=1)
        return "connected"

    def upload(self, path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle:
            response = self.http.request(
                "POST", "/files", files={"content": (path.name, handle, mime)}, timeout=300
            )
        return response.json()["urls"]["get"]

    def model_info(self, model: str) -> dict:
        if model not in self._models:
            self._models[model] = self.http.json("GET", f"/models/{model}")
        return self._models[model]

    def submit(self, model: str, inputs: dict[str, Any], *, version: str | None = None) -> Submission:
        if version:
            url, body = "/predictions", {"version": version, "input": inputs}
        else:
            info = self.model_info(model)
            if info.get("is_official"):
                url, body = f"/models/{model}/predictions", {"input": inputs}
            else:  # community models are addressed by their latest version id
                latest = (info.get("latest_version") or {}).get("id")
                url, body = "/predictions", {"version": latest, "input": inputs}
        data = self.http.json("POST", url, json=body)
        return Submission(
            job_id=data["id"],
            result=self._result(data) if data.get("status") in ("succeeded", "failed", "canceled") else None,
        )

    def poll(self, job_id: str) -> PollResult:
        return self._result(self.http.json("GET", f"/predictions/{job_id}"))

    def cancel(self, job_id: str) -> None:
        try:
            self.http.request("POST", f"/predictions/{job_id}/cancel", retries=0)
        except Exception:
            pass

    @staticmethod
    def _result(data: dict) -> PollResult:
        status = data.get("status", "")
        meta = dict(data.get("metrics") or {})
        if status == "succeeded":
            out = data.get("output")
            urls = out if isinstance(out, list) else [out] if out else []
            flat = [u for u in urls if isinstance(u, str)]
            return PollResult("succeeded", [Output(url=u) for u in flat], meta=meta)
        if status in ("failed", "canceled"):
            return PollResult(
                "failed" if status == "failed" else "canceled",
                error=str(data.get("error") or "The model failed."),
                meta=meta,
            )
        return PollResult("queued" if status == "starting" else "running", meta=meta)
