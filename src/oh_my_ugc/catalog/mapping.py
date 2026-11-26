"""Turn workflow slots into a provider's request parameters, and snap values to a model's limits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oh_my_ugc.catalog.schema import Entry


def build_inputs(entry: Entry, slots: dict[str, Any]) -> dict[str, Any]:
    """Map slots (first_frame, prompt, duration…) to the model's own parameter names.

    File values stay as ``Path`` objects; the runner uploads them just before submission.
    """
    out: dict[str, Any] = dict(entry.extra)
    for slot, value in slots.items():
        if value is None or value == "" or value == []:
            continue
        spec = entry.spec(slot)
        if spec is None:
            continue
        converted = _convert(spec.as_, value)
        if spec.role:  # e.g. OpenRouter frame_images: a list of {frame_type, image_url}
            out.setdefault(spec.param, []).append(
                {"type": "image_url", "image_url": {"url": converted}, "frame_type": spec.role}
            )
        elif spec.as_ == "image_url_list":
            out.setdefault(spec.param, []).extend(
                {"type": "image_url", "image_url": {"url": p}}
                for p in (value if isinstance(value, list) else [value])
            )
        else:
            out[spec.param] = converted
    return out


def _convert(kind: str | None, value: Any) -> Any:
    if kind == "int":
        return int(round(float(value)))
    if kind == "float":
        return float(value)
    if kind == "str":
        return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    if kind == "bool":
        return bool(value)
    if kind == "list":
        return value if isinstance(value, list) else [value]
    if kind == "seconds_str":
        return f"{int(round(float(value)))}s"
    return value


def supports(entry: Entry, slot: str) -> bool:
    return slot in entry.inputs


def snap_duration(entry: Entry, seconds: float) -> float:
    """The nearest allowed duration that is at least ``seconds`` (or the longest allowed)."""
    allowed = sorted(entry.limits.durations or [])
    if not allowed:
        low = max(1.0, seconds)
        return min(low, entry.limits.max_duration) if entry.limits.max_duration else low
    for value in allowed:
        if value >= seconds - 1e-6:
            return value
    return allowed[-1]


def max_clip_seconds(entry: Entry) -> float:
    if entry.limits.durations:
        return max(entry.limits.durations)
    return entry.limits.max_duration or 15.0


def cheapest_resolution(entry: Entry) -> str | None:
    values = entry.limits.resolutions or []
    return min(values, key=_res_px) if values else None


def _res_px(value: str) -> int:
    digits = "".join(ch for ch in value if ch.isdigit())
    if value.upper().endswith("K"):
        return int(digits or 0) * 1000
    return int(digits or 0)


def pick_resolution(entry: Entry, wanted: str | None) -> str | None:
    """The closest supported resolution at or below ``wanted`` (else the lowest above it)."""
    values = sorted(entry.limits.resolutions or [], key=_res_px)
    if not values or not wanted:
        return values[0] if values else None
    below = [v for v in values if _res_px(v) <= _res_px(wanted)]
    return below[-1] if below else values[0]


def resolve_files(obj: Any, upload) -> Any:
    """Replace every ``Path`` in a nested structure with the provider's reference to the upload."""
    if isinstance(obj, Path):
        return upload(obj)
    if isinstance(obj, dict):
        return {k: resolve_files(v, upload) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_files(v, upload) for v in obj]
    return obj


def file_paths(obj: Any) -> list[Path]:
    if isinstance(obj, Path):
        return [obj]
    if isinstance(obj, dict):
        return [p for v in obj.values() for p in file_paths(v)]
    if isinstance(obj, list):
        return [p for v in obj for p in file_paths(v)]
    return []
