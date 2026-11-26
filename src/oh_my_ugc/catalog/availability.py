"""Which bundled models a provider has stopped offering.

Providers retire models (Seedance 1.5 Pro disappeared from Replicate and OpenRouter), so the bundled
catalog is checked against each provider's public pages. No key is needed and nothing is spent. Only a
clear "gone" answer counts (a 404, or a model missing from OpenRouter's own list); a network error
never marks a model as gone. The answer is cached for 24 hours in ``OMU_HOME/cache``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from oh_my_ugc import config
from oh_my_ugc.providers import base

TTL = 24 * 3600
OPENROUTER_LISTS = (
    "https://openrouter.ai/api/v1/videos/models",
    "https://openrouter.ai/api/v1/images/models",
    "https://openrouter.ai/api/v1/models",
)
PAGES = {  # one public page per model; a 404 means the provider no longer has it
    "replicate": "https://replicate.com/{model}",
    "fal": "https://fal.ai/models/{model}/llms.txt",
}
_memo: dict[str, Any] = {"mtime": None, "data": {}}


def _file():
    return config.cache_dir() / "availability.json"


def _read() -> dict[str, Any]:
    path = _file()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _memo["mtime"] != (str(path), mtime):
        try:
            _memo["data"] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            _memo["data"] = {}
        _memo["mtime"] = (str(path), mtime)
    return _memo["data"]


def gone() -> dict[str, str]:
    """Entry id to reason, from the last check (reads a file; never touches the network)."""
    return dict(_read().get("gone", {}))


def checked_at() -> float | None:
    return _read().get("checked_at")


def _openrouter_ids(client: httpx.Client) -> set[str] | None:
    ids: set[str] = set()
    for url in OPENROUTER_LISTS:
        response = client.get(url)
        if response.status_code != 200:
            return None
        ids |= {m.get("id") for m in response.json().get("data", []) if m.get("id")}
    return ids or None


def refresh(*, force: bool = False) -> dict[str, str]:
    """Check every bundled model against its provider's public pages. Returns the gone ones."""
    from oh_my_ugc.catalog import load

    last = checked_at()
    if not force and last and time.time() - last < TTL:
        return gone()
    names = {"replicate": "Replicate", "fal": "fal", "openrouter": "OpenRouter"}
    found: dict[str, str] = {}
    with httpx.Client(timeout=15, transport=base.transport, follow_redirects=True) as client:
        try:
            listed = _openrouter_ids(client)
        except (httpx.HTTPError, ValueError):
            listed = None
        for entry in load.curated():
            reason = f"{names.get(entry.provider, entry.provider)} no longer offers this model."
            try:
                if entry.provider == "openrouter":
                    if listed is not None and entry.model not in listed:
                        found[entry.id] = reason
                    continue
                url = PAGES.get(entry.provider)
                if url and client.get(url.format(model=entry.model)).status_code == 404:
                    found[entry.id] = reason
            except httpx.HTTPError:
                continue
    _file().write_text(json.dumps({"checked_at": time.time(), "gone": found}), encoding="utf-8")
    return found
