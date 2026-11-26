"""OpenRouter: chat (language and vision models), image generation and video generation."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from oh_my_ugc.errors import OmuError
from oh_my_ugc.providers.base import Http, Output, PollResult, Provider, Submission, data_uri

API = "https://openrouter.ai/api/v1"


class OpenRouter(Provider):
    name = "openrouter"
    display = "OpenRouter"

    def __init__(self) -> None:
        self.http = Http(
            "openrouter",
            API,
            lambda: {"Authorization": f"Bearer {self.key()}", "X-Title": "oh-my-ugc"},
            timeout=300,
        )

    def check_key(self) -> str:
        self.http.request("GET", "/key", retries=1)
        return "connected"

    def balance(self) -> dict:
        return self.http.json("GET", "/key").get("data", {})

    def upload(self, path: Path) -> str:
        return data_uri(path)  # OpenRouter takes images as URLs or data URIs

    # ── chat ─────────────────────────────────────────────────────────────────

    def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        schema: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, float | None]:
        """(text, billed cost in dollars)."""
        body: dict[str, Any] = {"model": model, "messages": messages, "usage": {"include": True}}
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens:
            body["max_tokens"] = max_tokens
        data = self.http.json("POST", "/chat/completions", json=body)
        if data.get("error"):
            raise OmuError(f"OpenRouter said: {str(data['error'].get('message', data['error']))[:240]}.")
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise OmuError("OpenRouter returned an empty answer. Try again or pick another model.") from exc
        return text, (data.get("usage") or {}).get("cost")

    # ── jobs (images are synchronous, videos are polled) ─────────────────────

    def submit(self, model: str, inputs: dict[str, Any], *, version: str | None = None) -> Submission:
        kind = inputs.pop("__kind", "video")
        if kind == "image":
            return Submission("", self._image(model, inputs))
        data = self.http.json("POST", "/videos", json={"model": model, **inputs})
        return Submission(job_id=data["id"])

    def _image(self, model: str, inputs: dict[str, Any]) -> PollResult:
        data = self.http.json("POST", "/images", json={"model": model, "n": 1, **inputs})
        outputs = []
        for item in data.get("data", []):
            if item.get("b64_json"):
                ext = (item.get("media_type") or "image/png").split("/")[-1].replace("jpeg", "jpg")
                outputs.append(Output(data=base64.b64decode(item["b64_json"]), ext=ext))
            elif item.get("url"):
                outputs.append(Output(url=item["url"]))
        if not outputs:
            return PollResult("failed", error="OpenRouter returned no image.")
        return PollResult("succeeded", outputs, cost=(data.get("usage") or {}).get("cost"))

    def poll(self, job_id: str) -> PollResult:
        data = self.http.json("GET", f"/videos/{job_id}")
        status = data.get("status", "")
        if status == "completed":
            cost = (data.get("usage") or {}).get("cost")
            urls = data.get("unsigned_urls") or [f"{API}/videos/{job_id}/content?index=0"]
            auth = {"Authorization": f"Bearer {self.key()}"}
            return PollResult(
                "succeeded", [Output(url=u, ext="mp4", headers=auth) for u in urls[:1]], cost=cost
            )
        if status in ("failed", "cancelled", "expired"):
            return PollResult("failed", error=str(data.get("error") or f"The video job {status}."))
        return PollResult("queued" if status == "pending" else "running")

    def cancel(self, job_id: str) -> None:
        return None

    # ── discovery ────────────────────────────────────────────────────────────

    def list_models(self, kind: str) -> list[dict]:
        path = {"video": "/videos/models", "image": "/images/models", "llm": "/models"}[kind]
        return self.http.json("GET", path).get("data", [])


def parse_json(text: str) -> Any:
    """JSON from a model reply, tolerating a code fence around it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except ValueError as exc:
        raise OmuError(
            "The language model did not return valid JSON. Try again or pick another model.",
            detail=text[:300],
        ) from exc
