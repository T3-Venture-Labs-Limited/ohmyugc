"""Setup checks shown in Settings and by ``omu doctor``."""

from __future__ import annotations

import sys

from oh_my_ugc import config, providers
from oh_my_ugc.catalog import availability, load
from oh_my_ugc.media import find_ffmpeg, install_hint
from oh_my_ugc.providers.base import DISPLAY


def _check(name: str, label: str, ok: bool, detail: str, required: bool = True) -> dict:
    return {"name": name, "label": label, "ok": ok, "detail": detail, "required": required}


def checks(*, verify_keys: bool = False) -> list[dict]:
    out = [_ffmpeg(), _captions(), _folders(), _catalog(), _providers(verify_keys), _models()]
    out += [_provider(p, verify_keys) for p in config.PROVIDERS]
    return out


def _ffmpeg() -> dict:
    found = find_ffmpeg()
    if found.ffmpeg and found.ffprobe:
        return _check("ffmpeg", "FFmpeg", True, found.ffmpeg)
    return _check("ffmpeg", "FFmpeg", False, f"ffmpeg and ffprobe not found. {install_hint()}")


def _captions() -> dict:
    found = find_ffmpeg()
    if found.libass:
        return _check("captions", "Text and captions", True, "ffmpeg has libass")
    if not found.ffmpeg:
        return _check("captions", "Text and captions", False, "needs ffmpeg")
    return _check(
        "captions",
        "Text and captions",
        False,
        f"This ffmpeg can't draw text (it has no libass). {install_hint()}",
    )


def _folders() -> dict:
    try:
        for folder in (config.home(), config.media_dir(), config.projects_dir(), config.user_catalog_dir()):
            probe = folder / ".write-test"
            probe.write_text("ok")
            probe.unlink()
    except OSError as exc:
        return _check("folders", "Data folder", False, f"{config.home()} is not writable: {exc.strerror}")
    return _check("folders", "Data folder", True, str(config.home()))


def _catalog() -> dict:
    entries = load.curated()
    problems = list(load.problems)
    discovered = load.load_discovered()
    retired = [e.id for e in entries if e.id in availability.gone()]
    detail = f"{len(entries)} models" + (f", {len(discovered)} discovered" if discovered else "")
    if problems:
        detail += f". {len(problems)} of your own model files could not be read: " + "; ".join(
            f"{p['file'].split('/')[-1]}: {p['reason']}" for p in problems
        )
    if retired:
        detail += ". Their provider no longer offers: " + ", ".join(retired) + " (hidden from the pickers)"
    return _check("catalog", "Model catalog", not problems and not retired, detail, required=False)


def _providers(verify: bool) -> dict:
    connected = providers.connected()
    if connected:
        return _check(
            "providers", "Providers", True, "connected: " + ", ".join(DISPLAY[p] for p in connected)
        )
    return _check(
        "providers",
        "Providers",
        False,
        "No provider key yet. Add one in Settings (or run `omu keys set replicate ...`).",
    )


STEPS = (
    ("llm", "writing"),
    ("vision_check", "product check"),
    ("image_edit", "storyboard pictures"),
    ("image_to_video", "video clips"),
    ("speech", "voices"),
)


def _models() -> dict:
    """Nothing is picked for the user: once a key is connected, each step needs a chosen model."""
    from oh_my_ugc.catalog import load

    if not providers.connected():
        return _check(
            "models", "Models chosen", False, "Add a key first, then choose models.", required=False
        )
    missing = [
        label
        for task, label in STEPS
        if load.chosen_for(task) is None
        and any(
            e.task == task and e.provider in providers.connected() and load.usable(e) for e in load.curated()
        )
    ]
    if missing:
        return _check(
            "models",
            "Models chosen",
            False,
            "Not chosen yet: " + ", ".join(missing) + ". Choose them in Settings (`omu models default`).",
            required=False,
        )
    return _check("models", "Models chosen", True, "every step you can run has a model", required=False)


def _provider(name: str, verify: bool) -> dict:
    label = DISPLAY[name]
    if not (config.get_key(name) or name in providers.overrides):
        return _check(f"key_{name}", f"{label} key", False, "not set", required=False)
    if not verify:
        return _check(
            f"key_{name}",
            f"{label} key",
            True,
            f"set ({config.setting_source(config.key_name(name)) or 'settings'})",
            required=False,
        )
    try:
        providers.get(name).check_key()
    except Exception as exc:
        return _check(f"key_{name}", f"{label} key", False, getattr(exc, "message", str(exc)), required=False)
    return _check(f"key_{name}", f"{label} key", True, "works", required=False)


def ok() -> bool:
    return all(c["ok"] for c in checks() if c["required"] and c["name"] != "providers")


def platform_note() -> str:
    return sys.platform
