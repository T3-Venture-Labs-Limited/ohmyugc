"""Loading the catalog: bundled entries, user entries and cached discovery, plus default picking."""

from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import ValidationError

from oh_my_ugc import config, db
from oh_my_ugc.catalog import availability
from oh_my_ugc.catalog.schema import REQUIRED, SERVED_BY, TASKS, Entry
from oh_my_ugc.errors import OmuError

BUNDLED = Path(__file__).resolve().parent / "models"
DISCOVERY_TTL = 24 * 3600
PROVIDER_ORDER = ("replicate", "fal", "openrouter", "elevenlabs", "fish")

# Problems found while loading user files (shown in Settings and by `omu doctor`).
problems: list[dict] = []


def _read(path: Path) -> Entry:
    return Entry.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_dir(folder: Path, *, source: str) -> list[Entry]:
    entries: list[Entry] = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            entry = _read(path)
            if entry.task not in TASKS:
                raise ValueError(f"unknown task '{entry.task}'")
            entries.append(entry)
        except (ValueError, ValidationError) as exc:
            reason = (
                str(exc).splitlines()[0][:200]
                if isinstance(exc, ValueError) and not isinstance(exc, ValidationError)
                else _first_error(exc)
            )
            problems.append({"file": str(path), "source": source, "reason": reason})
    return entries


def _first_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        err = exc.errors()[0]
        return f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
    return str(exc)[:200]


def curated() -> list[Entry]:
    """Bundled entries, with user entries (``OMU_HOME/catalog``) overriding bundled ones by id."""
    problems.clear()
    merged = {e.id: e for e in load_dir(BUNDLED, source="bundled")}
    for entry in load_dir(config.user_catalog_dir(), source="user"):
        merged[entry.id] = entry
    return list(merged.values())


def _discovery_file(provider: str) -> Path:
    return config.cache_dir() / f"discovery-{provider}.json"


def load_discovered() -> list[Entry]:
    out: list[Entry] = []
    for provider in config.PROVIDERS:
        path = _discovery_file(provider)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out += [Entry.model_validate(e) for e in data.get("entries", [])]
        except (ValueError, ValidationError):
            continue
    return out


def save_discovered(provider: str, entries: list[Entry], error: str = "") -> None:
    _discovery_file(provider).write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "error": error,
                "entries": [e.model_dump(by_alias=True) for e in entries],
            }
        ),
        encoding="utf-8",
    )


def discovery_status() -> dict[str, dict]:
    status = {}
    for provider in config.PROVIDERS:
        path = _discovery_file(provider)
        if not path.exists():
            status[provider] = {"fetched_at": None, "count": 0, "error": ""}
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            status[provider] = {
                "fetched_at": data.get("fetched_at"),
                "count": len(data.get("entries", [])),
                "error": data.get("error", ""),
            }
        except ValueError:
            status[provider] = {"fetched_at": None, "count": 0, "error": ""}
    return status


def all_entries(*, discovered: bool = True) -> list[Entry]:
    entries = {e.id: e for e in (load_discovered() if discovered else [])}
    for entry in curated():  # curated entries override discovered ones with the same id
        entries[entry.id] = entry
    return list(entries.values())


def get(entry_id: str) -> Entry:
    for entry in all_entries():
        if entry.id == entry_id:
            return entry
    raise OmuError(
        f"The model '{entry_id}' is not in the catalog. Refresh the model list or pick another.", status=404
    )


def usable(entry: Entry) -> bool:
    return (
        entry.available
        and entry.id not in availability.gone()
        and not [s for s in REQUIRED.get(entry.task, []) if s not in entry.inputs]
    )


def for_task(task: str, providers: list[str] | None = None, *, discovered: bool = True) -> list[Entry]:
    out = [e for e in all_entries(discovered=discovered) if e.task == task]
    if providers is not None:
        out = [e for e in out if e.provider in providers]
    return sorted(
        out,
        key=lambda e: (
            e.discovered,
            PROVIDER_ORDER.index(e.provider) if e.provider in PROVIDER_ORDER else 9,
            e.name.lower(),
        ),
    )


def mark_availability(entry: Entry) -> Entry:
    retired = availability.gone().get(entry.id)
    if retired and entry.available:
        return entry.model_copy(update={"available": False, "unavailable_reason": retired})
    missing = [s for s in REQUIRED.get(entry.task, []) if s not in entry.inputs]
    if missing and entry.available:
        label = {
            "first_frame": "first-frame",
            "last_frame": "last-frame",
            "reference_images": "reference-image",
        }.get(missing[0], missing[0])
        entry = entry.model_copy(update={"available": False, "unavailable_reason": f"no {label} input"})
    return entry


def global_overrides() -> dict[str, str]:
    try:
        return dict(json.loads(config.get_setting("default_models") or "{}"))
    except ValueError:
        return {}


def set_global_default(task: str, entry_id: str | None) -> None:
    current = global_overrides()
    if entry_id:
        get(entry_id)
        current[task] = entry_id
    else:
        current.pop(task, None)
    db.set_setting("default_models", json.dumps(current) if current else "")


def requirement(task: str) -> str:
    """What the user must do before a task can run, as a sentence for the UI."""
    from oh_my_ugc import providers

    connected = providers.connected()
    if any(e.provider in connected and usable(e) for e in curated() if e.task == task):
        return "Choose a model for this step in Settings (or for this ad on its Brief)."
    providers = SERVED_BY.get(task) or sorted(
        {e.provider for e in curated() if e.task == task and usable(e)}, key=PROVIDER_ORDER.index
    )
    names = {
        "replicate": "Replicate",
        "fal": "fal",
        "openrouter": "OpenRouter",
        "elevenlabs": "ElevenLabs",
        "fish": "Fish Audio",
    }
    labelled = [names[p] for p in providers]
    if not labelled:
        return "No provider offers this yet."
    return (
        "Needs "
        + (labelled[0] if len(labelled) == 1 else ", ".join(labelled[:-1]) + " or " + labelled[-1])
        + "."
    )


def chosen_for(
    task: str, project_models: dict | None = None, connected: list[str] | None = None
) -> Entry | None:
    """The model the user chose for a task: this ad's choice, else the Settings choice, else none.

    There is deliberately no automatic default: everyone prefers different models and prices, so
    nothing is picked until the user picks it. A choice whose provider is no longer connected
    (or whose model can no longer run) does not count.
    """
    from oh_my_ugc import providers

    connected = connected if connected is not None else providers.connected()
    for choice in ((project_models or {}).get(task), global_overrides().get(task)):
        if choice:
            try:
                entry = get(choice)
            except OmuError:
                continue
            if entry.provider in connected and usable(entry):
                return entry
    return None


def listing(task: str | None = None, *, connected_only: bool = False) -> list[dict]:
    from oh_my_ugc import providers

    connected = providers.connected()
    out = []
    for entry in all_entries():
        if task and entry.task != task:
            continue
        if connected_only and entry.provider not in connected:
            continue
        entry = mark_availability(entry)
        out.append(
            {
                **entry.public(),
                "connected": entry.provider in connected,
                "usable": usable(entry) and entry.provider in connected,
            }
        )
    return sorted(out, key=lambda e: (e["task"], e["discovered"], e["provider"], e["name"].lower()))
