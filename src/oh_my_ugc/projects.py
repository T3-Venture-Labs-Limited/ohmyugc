"""Projects: one ad, from brief to export."""

from __future__ import annotations

import json
import shutil
from typing import Any

from oh_my_ugc import config, costs, db, jobs, store
from oh_my_ugc.catalog import load
from oh_my_ugc.errors import NotFound, OmuError, check_lengths

FORMATS = {
    "talking_head": "Talking head with product",
    "problem_solution": "Problem and solution",
    "unboxing": "Unboxing",
    "demo_voiceover": "Demo with voiceover",
    "testimonial": "Testimonial",
}
ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}
PLATFORMS = ("tiktok", "reels", "shorts", "meta", "other")
VOICE_MODES = ("voiceover", "native", "avatar")
STAGES = ("brief", "script", "storyboard", "clips", "export")
MODEL_TASKS = (
    "llm",
    "vision_check",
    "image_edit",
    "image_generation",
    "image_to_video",
    "speech",
    "talking_avatar",
    "lipsync",
    "background_removal",
)


def output_size(project: dict[str, Any]) -> tuple[int, int]:
    return ASPECTS.get(project["aspect"], (1080, 1920))


def get(project_id: str) -> dict[str, Any]:
    project = db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise NotFound("That project")
    return project


def project_dir(project_id: str):
    path = config.projects_dir() / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_for(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The model each step will use, with whether it was chosen or defaulted."""
    chosen = project.get("models") or {}
    out: dict[str, dict[str, Any]] = {}
    for task in MODEL_TASKS:
        entry = (
            load.get(chosen[task])
            if task == "lipsync" and chosen.get("lipsync")
            else (None if task == "lipsync" else load.chosen_for(task, chosen))
        )
        out[task] = {
            "id": entry.id if entry else None,
            "name": entry.name if entry else None,
            "provider": entry.provider if entry else None,
            "chosen": bool(chosen.get(task)),
            "requirement": None if entry or task == "lipsync" else load.requirement(task),
        }
    return out


def public(project: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    from oh_my_ugc import actors, brands, products

    out = {k: v for k, v in project.items() if k != "models"}
    out["models"] = project.get("models") or {}
    out["music_url"] = store.url(project.get("music"))
    out["size"] = list(output_size(project))
    brand = (
        db.one("SELECT * FROM brands WHERE id = ?", (project["brand_id"],))
        if project.get("brand_id")
        else None
    )
    product = (
        db.one("SELECT * FROM products WHERE id = ?", (project["product_id"],))
        if project.get("product_id")
        else None
    )
    actor = (
        db.one("SELECT * FROM actors WHERE id = ?", (project["actor_id"],))
        if project.get("actor_id")
        else None
    )
    out["brand"] = brands.public(brand) if brand else None
    out["product"] = products.public(product) if product else None
    out["actor"] = actors.public(actor) if actor else None
    out["actor_removed"] = bool(project.get("actor_id")) and actor is None
    out["spend"] = costs.spend(project["id"])
    out["budget_status"] = costs.budget_status(project["id"])
    out["shot_count"] = db.one(
        "SELECT COUNT(*) AS n FROM shots WHERE project_id = ? AND variant_id IS NULL", (project["id"],)
    )["n"]  # type: ignore[index]
    out["active_jobs"] = len(jobs.active(project["id"]))
    if detail:
        out["resolved_models"] = models_for(project)
    return out


def listing() -> list[dict[str, Any]]:
    return [public(p) for p in db.many("SELECT * FROM projects ORDER BY updated_at DESC")]


def _validate(values: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    check_lengths({k: v for k, v in values.items() if k in ("name", "brief", "script", "caption_style")})
    for key in ("name", "brief", "script", "caption_style"):
        if key in values and values[key] is not None:
            row[key] = str(values[key])
    for key, allowed in (
        ("format", FORMATS),
        ("aspect", ASPECTS),
        ("platform", PLATFORMS),
        ("voice_mode", VOICE_MODES),
        ("stage", STAGES),
    ):
        if key in values and values[key] is not None:
            if values[key] not in allowed:
                raise OmuError(
                    f"'{values[key]}' is not a valid {key.replace('_', ' ')}. Choose one of: {', '.join(allowed)}."
                )
            row[key] = values[key]
    if "target_seconds" in values and values["target_seconds"] is not None:
        seconds = float(values["target_seconds"])
        if not 5 <= seconds <= 120:
            raise OmuError("Choose a length between 5 and 120 seconds.")
        row["target_seconds"] = seconds
    if "budget" in values:
        row["budget"] = None if values["budget"] in (None, "") else max(0.0, float(values["budget"]))
    for key in ("brand_id", "product_id", "actor_id"):
        if key in values:
            row[key] = values[key] or None
    for key in ("caption_on",):
        if key in values and values[key] is not None:
            row[key] = 1 if values[key] else 0
    for key in ("music_volume", "crossfade"):
        if key in values and values[key] is not None:
            row[key] = float(values[key])
    if "final_resolution" in values and values["final_resolution"]:
        if values["final_resolution"] not in ("480p", "720p", "1080p"):
            raise OmuError("Final quality must be 480p, 720p or 1080p.")
        row["final_resolution"] = values["final_resolution"]
    if "models" in values and values["models"] is not None:
        models = {k: v for k, v in dict(values["models"]).items() if v}
        for task, entry_id in models.items():
            if task not in MODEL_TASKS:
                raise OmuError(f"'{task}' is not a step you can choose a model for.")
            load.get(entry_id)
        row["models"] = models
    if "end_card" in values and values["end_card"] is not None:
        card = dict(values["end_card"])
        if "seconds" in card:
            card["seconds"] = max(1.5, min(5.0, float(card["seconds"])))
        row["end_card"] = card
    return row


def create(values: dict[str, Any]) -> dict[str, Any]:
    from oh_my_ugc import brands

    row = _validate(values)
    row.setdefault("name", "Untitled ad")
    if not row["name"].strip():
        row["name"] = "Untitled ad"
    if "budget" not in row and config.get_setting("default_budget"):
        row["budget"] = float(config.get_setting("default_budget"))
    if "caption_style" not in row:
        row["caption_style"] = config.get_setting("caption_style") or "punch"
    brand = None
    if row.get("brand_id"):
        brand = brands.get(row["brand_id"])
    if "end_card" not in row:
        row["end_card"] = {
            "on": True,
            "seconds": 3.0,
            "cta": (brand or {}).get("cta", ""),
            "offer": (brand or {}).get("offer", ""),
            "background": "blur",
        }
    now = db.now()
    project_id = db.insert("projects", {**row, "created_at": now, "updated_at": now})
    return public(get(project_id), detail=True)


def update(project_id: str, values: dict[str, Any]) -> dict[str, Any]:
    get(project_id)
    row = _validate(values)
    if row:
        db.update("projects", project_id, {**row, "updated_at": db.now()})
    return public(get(project_id), detail=True)


def touch(project_id: str) -> None:
    db.update("projects", project_id, {"updated_at": db.now()})


def set_music(project_id: str, filename: str, data: bytes) -> dict[str, Any]:
    get(project_id)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in {"mp3", "wav", "m4a", "ogg", "flac"}:
        raise OmuError("Use an MP3, WAV, M4A, OGG or FLAC music file.")
    db.update("projects", project_id, {"music": store.put_bytes(data, ext), "updated_at": db.now()})
    return public(get(project_id), detail=True)


def delete(project_id: str) -> None:
    get(project_id)
    db.run("DELETE FROM jobs WHERE project_id = ?", (project_id,))
    db.delete("projects", project_id)
    shutil.rmtree(config.projects_dir() / project_id, ignore_errors=True)


def duplicate(project_id: str) -> dict[str, Any]:
    p = get(project_id)
    values = {
        k: p[k]
        for k in (
            "brand_id",
            "product_id",
            "actor_id",
            "format",
            "target_seconds",
            "aspect",
            "platform",
            "voice_mode",
            "brief",
            "script",
            "budget",
            "caption_style",
            "final_resolution",
            "end_card",
        )
    }
    return create({**values, "name": f"{p['name']} (copy)", "models": p.get("models") or {}})


def _dump(obj: Any) -> str:
    return json.dumps(obj, default=str)
