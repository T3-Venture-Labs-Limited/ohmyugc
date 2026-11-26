"""The shared HTTP layer and the job protocol every provider adapter implements.

Retry policy (design D2): HTTP 429 waits for the provider's retry time and tries again;
5xx and network errors back off and retry up to three times; 400/401/402/403/404/422 are
never retried and become one plain sentence.
"""

from __future__ import annotations

import base64
import mimetypes
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from oh_my_ugc import config
from oh_my_ugc.errors import OmuError, OutOfCredit

DISPLAY = {
    "replicate": "Replicate",
    "fal": "fal",
    "openrouter": "OpenRouter",
    "elevenlabs": "ElevenLabs",
    "fish": "Fish Audio",
}

# Tests swap these in; production leaves them alone.
transport: httpx.BaseTransport | None = None
sleep: Callable[[float], None] = time.sleep
MAX_RATE_WAITS = 20
# Called with (provider, seconds) while a call waits out a rate limit.
on_wait: Callable[[str, float], None] | None = None

_KEY_SHAPES = re.compile(
    r"(Bearer|Key|Token)\s+[A-Za-z0-9._\-:]{8,}|r8_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9_\-]{12,}"
)


def redact(text: str) -> str:
    """Remove anything that looks like an API key, and every key the user has stored."""
    out = _KEY_SHAPES.sub("[redacted]", str(text))
    for provider in config.PROVIDERS:
        try:
            secret = config.get_key(provider)
        except Exception:
            secret = ""
        if len(secret) >= 8:
            out = out.replace(secret, "[redacted]")
    return out


@dataclass(slots=True)
class Output:
    """One file a job produced: a URL to download, or bytes already in hand."""

    url: str = ""
    data: bytes | None = None
    ext: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class PollResult:
    status: str  # queued | running | succeeded | failed | canceled
    outputs: list[Output] = field(default_factory=list)
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    cost: float | None = None  # billed amount when the provider reports it


@dataclass(slots=True)
class Submission:
    job_id: str
    result: PollResult | None = None  # set when the provider finished synchronously


def plain_error(provider: str, status: int, body: str) -> OmuError:
    """One sentence a person can act on, naming the provider."""
    name = DISPLAY.get(provider, provider)
    message = _message(body)
    lowered = message.lower()
    if status in (401, 403) and "credit" not in lowered:
        return OmuError(
            f"{name} rejected the API key. Check it in Settings.", detail=redact(body), status=401
        )
    if status == 402 or "insufficient credit" in lowered or "out of credit" in lowered or "quota" in lowered:
        return OutOfCredit(
            f"Your {name} account is out of credit. Add credit at {_billing(provider)} and try again "
            "(new credit can take a few minutes to apply).",
            detail=redact(body),
            status=402,
        )
    if status == 404:
        return OmuError(
            f"{name} could not find that model or job. Pick another model or refresh the model list.",
            detail=redact(body),
            status=404,
        )
    if status in (400, 422):
        return OmuError(
            f"{name} rejected the request: {message[:240].rstrip('. ') or 'invalid input'}.",
            detail=redact(body),
        )
    if status == 429:
        return OmuError(
            f"{name} is rate limiting this key. Wait a minute and try again.", detail=redact(body)
        )
    if status >= 500:
        return OmuError(
            f"{name} is having problems right now ({status}). Try again in a few minutes.",
            detail=redact(body),
        )
    return OmuError(f"{name} returned error {status}: {message[:200]}", detail=redact(body))


def _billing(provider: str) -> str:
    return {
        "replicate": "replicate.com/account/billing",
        "fal": "fal.ai/dashboard/billing",
        "openrouter": "openrouter.ai/credits",
        "elevenlabs": "elevenlabs.io/app/subscription",
        "fish": "fish.audio",
    }.get(provider, "the provider's billing page")


def _message(body: str) -> str:
    import json

    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:300]
    if isinstance(data, dict):
        for key in ("detail", "error", "message", "title"):
            value = data.get(key)
            if isinstance(value, dict):
                value = value.get("message") or value.get("detail")
            if isinstance(value, list):
                value = "; ".join(str(v.get("msg", v)) if isinstance(v, dict) else str(v) for v in value)
            if value:
                return str(value).strip()
    return str(data)[:300]


class Http:
    """httpx with the retry policy above."""

    def __init__(
        self, provider: str, base_url: str, headers: Callable[[], dict[str, str]], timeout: float = 120
    ) -> None:
        self.provider, self.base_url, self._headers, self.timeout = provider, base_url, headers, timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, transport=transport, follow_redirects=True)

    def request(self, method: str, url: str, *, retries: int = 3, **kwargs: Any) -> httpx.Response:
        if not url.startswith("http"):
            url = self.base_url + url
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        waits = errors = 0
        while True:
            try:
                with self._client() as client:
                    response = client.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                errors += 1
                if errors > retries:
                    raise OmuError(
                        f"Could not reach {DISPLAY.get(self.provider, self.provider)}. Check your connection and try again.",
                        detail=redact(str(exc)),
                    ) from exc
                sleep(2 ** (errors - 1))
                continue
            status = response.status_code
            if status == 429:
                waits += 1
                if waits > MAX_RATE_WAITS:
                    raise plain_error(self.provider, 429, response.text)
                delay = _retry_after(response)
                if on_wait:
                    on_wait(self.provider, delay)
                sleep(delay)
                continue
            if status >= 500:
                errors += 1
                if errors > retries:
                    raise plain_error(self.provider, status, response.text)
                sleep(2 ** (errors - 1))
                continue
            if status >= 400:
                raise plain_error(self.provider, status, response.text)
            return response

    def json(self, method: str, url: str, **kwargs: Any) -> Any:
        return self.request(method, url, **kwargs).json()


def _retry_after(response: httpx.Response) -> float:
    try:
        value = float(response.json().get("retry_after"))
    except (ValueError, TypeError, AttributeError):
        value = None  # type: ignore[assignment]
    if value is None:
        try:
            value = float(response.headers.get("Retry-After", ""))
        except ValueError:
            value = 10.0
    return max(1.0, value) + 1.0


class Provider:
    """What an adapter offers. Synchronous providers return a finished result from ``submit``."""

    name = ""
    display = ""

    def key(self) -> str:
        key = config.get_key(self.name)
        if not key:
            raise OmuError(f"Add your {self.display} API key in Settings to use {self.display}.", status=400)
        return key

    def configured(self) -> bool:
        return bool(config.get_key(self.name))

    def check_key(self) -> str:
        raise NotImplementedError

    def upload(self, path: Path) -> str:
        raise NotImplementedError

    def submit(self, model: str, inputs: dict[str, Any], *, version: str | None = None) -> Submission:
        raise NotImplementedError

    def poll(self, job_id: str) -> PollResult:
        raise NotImplementedError

    def cancel(self, job_id: str) -> None:  # best effort
        return None

    def download(self, output: Output) -> tuple[bytes, str]:
        """(bytes, extension) for one output."""
        if output.data is not None:
            return output.data, output.ext or "bin"
        url = output.url
        if url.startswith("data:"):
            head, _, payload = url.partition(",")
            mime = head[5:].split(";")[0]
            return base64.b64decode(payload), (mimetypes.guess_extension(mime) or ".bin").lstrip(".")
        with httpx.Client(timeout=300, transport=transport, follow_redirects=True) as client:
            try:
                response = client.get(url, headers=output.headers)
            except httpx.HTTPError as exc:
                raise OmuError(
                    f"Could not download the result from {self.display}.", detail=redact(str(exc))
                ) from exc
        if response.status_code >= 400:
            raise plain_error(self.name, response.status_code, response.text[:300])
        ext = (
            output.ext
            or Path(url.split("?")[0]).suffix.lstrip(".")
            or _ext_from_type(response.headers.get("content-type", ""))
        )
        return response.content, ext or "bin"


def _ext_from_type(content_type: str) -> str:
    return (mimetypes.guess_extension(content_type.split(";")[0].strip()) or "").lstrip(".")


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
