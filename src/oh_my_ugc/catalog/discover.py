"""Live model discovery: OpenRouter, fal and Replicate listings become catalog entries.

Discovered entries are marked ``discovered`` and cached for 24 hours. A model whose inputs cannot
be mapped is kept but marked unavailable with the reason.
"""

from __future__ import annotations

import time
from typing import Any

from oh_my_ugc import config, providers
from oh_my_ugc.catalog import load
from oh_my_ugc.catalog.schema import Entry, Limits, Price, PriceRow
from oh_my_ugc.errors import OmuError

FIRST_FRAME = (
    "first_frame_image",
    "start_image",
    "start_image_url",
    "first_frame",
    "image_url",
    "init_image",
    "input_image",
    "image",
)
LAST_FRAME = (
    "last_frame_image",
    "last_frame",
    "end_image",
    "end_image_url",
    "tail_image_url",
    "final_frame_image",
)
REFERENCE_IMAGES = ("reference_images", "image_input", "image_urls", "input_images", "images", "image")
AUDIO_IN = ("audio_url", "audio", "driving_audio", "audio_file")
VIDEO_IN = ("video_url", "video")


def _first(names: tuple[str, ...], props: dict) -> str | None:
    return next((n for n in names if n in props), None)


def _kind(prop: dict) -> str:
    kind = prop.get("type")
    if kind is None and "anyOf" in prop:
        kinds = [p.get("type") for p in prop["anyOf"] if p.get("type") and p.get("type") != "null"]
        kind = kinds[0] if kinds else None
    if kind is None and "allOf" in prop:
        kind = "enum"
    return kind or "string"


def _convert_for(prop: dict) -> str | None:
    kind = _kind(prop)
    enum = prop.get("enum") or []
    if kind == "array":
        return "list"
    if kind == "integer":
        return "int"
    if kind == "number":
        return "float"
    if kind == "boolean":
        return "bool"
    if enum and all(isinstance(v, str) and v.endswith("s") and v[:-1].isdigit() for v in enum):
        return "seconds_str"
    if enum and all(isinstance(v, str) and v.isdigit() for v in enum):
        return "str"
    return None


def slots_from_params(task: str, props: dict[str, dict]) -> dict[str, Any]:
    """Heuristic mapping from a model's parameter names to workflow slots."""
    inputs: dict[str, Any] = {}

    def put(slot: str, name: str | None, convert: bool = True) -> None:
        if name:
            as_ = _convert_for(props[name]) if convert else None
            inputs[slot] = {"param": name, **({"as": as_} if as_ else {})} if as_ else name

    if task in ("image_generation", "image_edit"):
        put("prompt", _first(("prompt", "text"), props))
        if task == "image_edit":
            name = _first(("image_input", "image_urls", "input_images", "images", "image"), props)
            if name:
                inputs["reference_images"] = (
                    {"param": name, "as": "list"}
                    if _kind(props[name]) == "array"
                    else {"param": name, "as": "list"}
                )
        put("aspect_ratio", "aspect_ratio" if "aspect_ratio" in props else None, convert=False)
        put("resolution", "resolution" if "resolution" in props else None, convert=False)
    elif task == "image_to_video":
        put("prompt", _first(("prompt", "text"), props))
        put("first_frame", _first(FIRST_FRAME, props), convert=False)
        put("last_frame", _first(LAST_FRAME, props), convert=False)
        put("duration", _first(("duration", "duration_seconds", "length"), props))
        put("resolution", "resolution" if "resolution" in props else None, convert=False)
        put("aspect_ratio", "aspect_ratio" if "aspect_ratio" in props else None, convert=False)
        put("audio", _first(("generate_audio", "enable_audio", "with_audio"), props))
        refs = _first(("reference_images",), props)
        if refs:
            inputs["reference_images"] = {"param": refs, "as": "list"}
        ref_audio = _first(("reference_audios",), props)
        if ref_audio:
            inputs["reference_audio"] = {"param": ref_audio, "as": "list"}
    elif task == "talking_avatar":
        put("first_frame", _first(("image_url", "image", "input_image"), props), convert=False)
        put("audio", _first(AUDIO_IN, props), convert=False)
        put("prompt", "prompt" if "prompt" in props else None, convert=False)
    elif task == "lipsync":
        put("video", _first(VIDEO_IN, props), convert=False)
        put("audio", _first(AUDIO_IN, props), convert=False)
    elif task == "background_removal":
        put("image", _first(("image_url", "image", "input_image"), props), convert=False)
    return inputs


def _enum_values(prop: dict) -> list[Any] | None:
    if "enum" in prop:
        return prop["enum"]
    for key in ("anyOf", "allOf"):
        for sub in prop.get(key, []):
            if "enum" in sub:
                return sub["enum"]
    return None


def limits_from_params(props: dict[str, dict]) -> Limits:
    limits = Limits()
    if "duration" in props:
        values = _enum_values(props["duration"])
        if values:
            nums = [
                float("".join(c for c in str(v) if c.isdigit() or c == "."))
                for v in values
                if any(ch.isdigit() for ch in str(v))
            ]
            limits.durations = sorted(nums) or None
    if "resolution" in props:
        limits.resolutions = [str(v) for v in (_enum_values(props["resolution"]) or [])] or None
    if "aspect_ratio" in props:
        limits.aspect_ratios = [
            str(v) for v in (_enum_values(props["aspect_ratio"]) or []) if ":" in str(v)
        ] or None
    return limits


# ── OpenRouter ───────────────────────────────────────────────────────────────


def price_from_openrouter_skus(skus: dict[str, str]) -> Price | None:
    """Turn OpenRouter ``pricing_skus`` (price per second or per token) into a price table."""
    rows: list[PriceRow] = []
    unit = None
    for key, value in (skus or {}).items():
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if key.startswith("video_tokens"):
            unit, base = "token", key[len("video_tokens") :]
        elif key.startswith("duration_seconds"):
            unit, base = "second", key[len("duration_seconds") :]
        else:
            continue
        if base.startswith("_with_video_input") or base.startswith("_with_audio_4k") or "4k" in base:
            continue
        when: dict[str, Any] = {}
        if "without_audio" in base:
            when["audio"] = False
        elif "with_audio" in base:
            when["audio"] = True
        for res in ("360p", "480p", "720p", "1080p"):
            if res in base:
                when["resolution"] = res
        if base.startswith("_image_to_video") or base.startswith("image_to_video") or "text_to_video" in key:
            continue
        rows.append(PriceRow(when=when, price=amount))
    if not rows or not unit:
        return None
    default = next((r.price for r in rows if not r.when), rows[0].price)
    return Price(unit=unit, table=rows, default=default, source="metadata")  # type: ignore[arg-type]


def entry_from_openrouter_video(m: dict) -> Entry:
    frames = m.get("supported_frame_images") or []
    inputs: dict[str, Any] = {"prompt": "prompt"}
    if "first_frame" in frames:
        inputs["first_frame"] = {"param": "frame_images", "role": "first_frame"}
    if "last_frame" in frames:
        inputs["last_frame"] = {"param": "frame_images", "role": "last_frame"}
    if m.get("supported_durations"):
        inputs["duration"] = {"param": "duration", "as": "int"}
    if m.get("supported_resolutions"):
        inputs["resolution"] = "resolution"
    if m.get("supported_aspect_ratios"):
        inputs["aspect_ratio"] = "aspect_ratio"
    if m.get("generate_audio"):
        inputs["audio"] = {"param": "generate_audio", "as": "bool"}
    if m.get("seed"):
        inputs["seed"] = {"param": "seed", "as": "int"}
    entry = Entry(
        id="openrouter/" + m["id"].split("/", 1)[-1],
        provider="openrouter",
        model=m["id"],
        name=m.get("name", m["id"]).split(": ", 1)[-1],
        task="image_to_video",
        inputs=inputs,
        discovered=True,
        native_audio=bool(m.get("generate_audio")),
        limits=Limits(
            durations=[float(d) for d in m["supported_durations"]] if m.get("supported_durations") else None,
            resolutions=m.get("supported_resolutions"),
            aspect_ratios=m.get("supported_aspect_ratios"),
        ),
        price=price_from_openrouter_skus(m.get("pricing_skus") or {}),
    )
    return load.mark_availability(entry)


def entry_from_openrouter_image(m: dict) -> Entry:
    params = m.get("supported_parameters") or {}
    can_edit = (
        "image" in (m.get("architecture", {}).get("input_modalities") or [])
        and (params.get("input_references", {}).get("max") or 0) > 0
    )
    inputs: dict[str, Any] = {"prompt": "prompt"}
    if can_edit:
        inputs["reference_images"] = {"param": "input_references", "as": "image_url_list"}
    for slot in ("aspect_ratio", "resolution"):
        if slot in params:
            inputs[slot] = slot
    return load.mark_availability(
        Entry(
            id="openrouter/" + m["id"].split("/", 1)[-1] + ("" if can_edit else "-generate"),
            provider="openrouter",
            model=m["id"],
            name=m.get("name", m["id"]).split(": ", 1)[-1],
            task="image_edit" if can_edit else "image_generation",
            inputs=inputs,
            extra={"__kind": "image"},
            discovered=True,
            limits=Limits(
                resolutions=params.get("resolution", {}).get("values"),
                aspect_ratios=[v for v in params.get("aspect_ratio", {}).get("values", []) if v != "auto"]
                or None,
                max_references=int(params.get("input_references", {}).get("max") or 0),
            ),
        )
    )


def discover_openrouter() -> list[Entry]:
    client = providers.get("openrouter")
    entries = [entry_from_openrouter_video(m) for m in client.list_models("video")]  # type: ignore[attr-defined]
    entries += [entry_from_openrouter_image(m) for m in client.list_models("image")]  # type: ignore[attr-defined]
    return entries


# ── fal ──────────────────────────────────────────────────────────────────────

FAL_CATEGORIES = {
    "image-to-video": "image_to_video",
    "image-to-image": "image_edit",
    "text-to-image": "image_generation",
}


def entry_from_fal(endpoint: str, display: str, task: str, input_props: dict[str, dict]) -> Entry:
    inputs = slots_from_params(task, input_props)
    return load.mark_availability(
        Entry(
            id="fal/" + endpoint.replace("fal-ai/", "").replace("/", "-"),
            provider="fal",
            model=endpoint,
            name=display or endpoint,
            task=task,
            inputs=inputs,
            limits=limits_from_params(input_props),
            discovered=True,
            native_audio="generate_audio" in input_props,
        )
    )


def discover_fal(max_per_category: int = 30) -> list[Entry]:
    client = providers.get("fal")
    http = client.http  # type: ignore[attr-defined]
    entries: list[Entry] = []
    for category, task in FAL_CATEGORIES.items():
        listing = http.json(
            "GET",
            "https://api.fal.ai/v1/models",
            params={"category": category, "limit": max_per_category, "status": "active"},
        )
        for item in listing.get("models", [])[:max_per_category]:
            endpoint = item.get("endpoint_id")
            if not endpoint:
                continue
            try:
                schema = http.json(
                    "GET", "https://fal.ai/api/openapi/queue/openapi.json", params={"endpoint_id": endpoint}
                )
                props = _fal_input_props(schema)
            except OmuError:
                continue
            entries.append(
                entry_from_fal(
                    endpoint, (item.get("metadata") or {}).get("display_name", endpoint), task, props
                )
            )
    return entries


def _fal_input_props(schema: dict) -> dict[str, dict]:
    comps = schema.get("components", {}).get("schemas", {})
    for name, body in comps.items():
        if name.lower().endswith("input") and "properties" in body:
            return body["properties"]
    return {}


# ── Replicate ────────────────────────────────────────────────────────────────

REPLICATE_COLLECTIONS = {
    "image-editing": "image_edit",
    "image-to-video": "image_to_video",
    "lipsync": "lipsync",
    "text-to-image": "image_generation",
}


def entry_from_replicate(model: dict, task: str) -> Entry:
    owner, name = model.get("owner", ""), model.get("name", "")
    schema = (
        ((model.get("latest_version") or {}).get("openapi_schema") or {})
        .get("components", {})
        .get("schemas", {})
        .get("Input", {})
    )
    props = schema.get("properties", {})
    inputs = slots_from_params(task, props)
    return load.mark_availability(
        Entry(
            id=f"replicate/{name}",
            provider="replicate",
            model=f"{owner}/{name}",
            name=name.replace("-", " ").title(),
            task=task,
            inputs=inputs,
            limits=limits_from_params(props),
            discovered=True,
            native_audio="generate_audio" in props,
            version=None if model.get("is_official") else (model.get("latest_version") or {}).get("id"),
        )
    )


def discover_replicate() -> list[Entry]:
    http = providers.get("replicate").http  # type: ignore[attr-defined]
    entries: list[Entry] = []
    for slug, task in REPLICATE_COLLECTIONS.items():
        try:
            data = http.json("GET", f"/collections/{slug}")
        except OmuError:
            continue
        for model in data.get("models", []):
            if not (model.get("latest_version") or {}).get("openapi_schema"):
                try:
                    model = http.json("GET", f"/models/{model['owner']}/{model['name']}")
                except OmuError:
                    continue
            entries.append(entry_from_replicate(model, task))
    return entries


# ── refresh ──────────────────────────────────────────────────────────────────

DISCOVERERS = {"openrouter": discover_openrouter, "fal": discover_fal, "replicate": discover_replicate}


def refresh(only: str | None = None, *, force: bool = False) -> dict[str, dict]:
    """Refresh discovery for connected providers (cache lives 24 hours). Failures keep the old cache."""
    status = load.discovery_status()
    result: dict[str, dict] = {}
    for provider, fn in DISCOVERERS.items():
        if only and provider != only:
            continue
        if not (config.get_key(provider) or provider in providers.overrides):
            continue
        fetched = status[provider]["fetched_at"]
        if not force and fetched and time.time() - fetched < load.DISCOVERY_TTL:
            result[provider] = {"refreshed": False, **status[provider]}
            continue
        try:
            entries = fn()
        except OmuError as exc:
            old = load.load_discovered()
            kept = [e for e in old if e.provider == provider]
            load.save_discovered(
                provider, kept, error=f"Discovery for {provider} is temporarily unavailable: {exc.message}"
            )
            result[provider] = {"refreshed": False, "error": exc.message, "count": len(kept)}
            continue
        load.save_discovered(provider, entries)
        result[provider] = {"refreshed": True, "count": len(entries), "error": ""}
    return result
