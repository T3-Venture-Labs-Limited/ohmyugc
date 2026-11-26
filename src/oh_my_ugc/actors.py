"""Actors: a consistent on-screen person, from a description or an uploaded photo."""

from __future__ import annotations

from typing import Any

from oh_my_ugc import costs, db, jobs, runner, store
from oh_my_ugc.catalog import load
from oh_my_ugc.errors import NotFound, OmuError, check_lengths

LIKENESS_REMINDER = "You are responsible for having the right to use this person's likeness, and for labelling AI-generated ads where platforms require it."

PORTRAIT_STYLE = (
    "Candid vertical smartphone selfie photo, natural light, realistic skin texture, casual everyday setting, "
    "looking at the camera, relaxed friendly expression, shot on a phone, not a studio portrait. "
)


def public(actor: dict[str, Any]) -> dict[str, Any]:
    out = dict(actor)
    out["ref_urls"] = [store.url(m) for m in actor.get("refs", [])]
    out["candidate_urls"] = [{**c, "url": store.url(c["media"])} for c in actor.get("candidates", [])]
    out["voice_sample_url"] = store.url(actor.get("voice_sample"))
    out["portrait_url"] = (
        store.url(actor["refs"][0])
        if actor.get("refs")
        else (store.url(actor["candidates"][0]["media"]) if actor.get("candidates") else None)
    )
    out["likeness_reminder"] = LIKENESS_REMINDER
    return out


def get(actor_id: str) -> dict[str, Any]:
    actor = db.one("SELECT * FROM actors WHERE id = ?", (actor_id,))
    if not actor:
        raise NotFound("That actor")
    return actor


def listing() -> list[dict[str, Any]]:
    return [public(a) for a in db.many("SELECT * FROM actors ORDER BY created_at DESC")]


def from_photo(name: str, filename: str, data: bytes, description: str = "") -> dict[str, Any]:
    """An actor from an uploaded photo. There is no consent gate, only a reminder."""
    from oh_my_ugc import products

    check_lengths({"name": name or "", "description": description})
    name = (name or "").strip() or "New actor"
    media = products.validate_image(filename, data)
    actor_id = db.insert(
        "actors", {"name": name, "description": description.strip(), "refs": [media], "created_at": db.now()}
    )
    return public(get(actor_id))


def create_for_generation(name: str, description: str) -> dict[str, Any]:
    check_lengths({"name": name or "", "description": description or ""})
    if not (description or "").strip():
        raise OmuError(
            "Describe the actor first, for example: woman in her late 20s, natural makeup, casual knit sweater."
        )
    actor_id = db.insert(
        "actors",
        {
            "name": (name or "").strip() or "New actor",
            "description": description.strip(),
            "created_at": db.now(),
        },
    )
    return public(get(actor_id))


def estimate_candidates(count: int, models: dict | None = None) -> dict[str, Any]:
    entry = load.chosen_for("image_generation", models)
    if entry is None:
        return {
            "available": False,
            "message": f"No image model chosen. {load.requirement('image_generation')}",
        }
    est = costs.estimate(entry, images=1)
    return {"available": True, "model": entry.name, "total": costs.total([est] * count)}


def _prompt(actor: dict[str, Any]) -> str:
    return f"{PORTRAIT_STYLE}{actor['description']}"


@jobs.register("actor_candidates")
def _candidates_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = job["payload"]
    actor = get(payload["actor_id"])
    entry = load.chosen_for("image_generation", payload.get("models"))
    if entry is None:
        raise OmuError(f"No image model chosen. {load.requirement('image_generation')}")
    made = []
    for i in range(int(payload.get("count", 4))):
        runner.stage(f"Generating portrait {i + 1} of {payload.get('count', 4)}")
        res = runner.call(
            entry,
            {"prompt": _prompt(actor), "aspect_ratio": "3:4"},
            step="actor",
            take=int(payload.get("take", 0)) + i,
            quantities={"images": 1},
        )
        made.append({"media": res.media[0], "kind": "portrait"})
        current = get(actor["id"])
        db.update("actors", actor["id"], {"candidates": [*current["candidates"], made[-1]]})
    return {"made": len(made)}


def generate_candidates(actor_id: str, count: int = 4, models: dict | None = None) -> str:
    get(actor_id)
    if not 1 <= count <= 8:
        raise OmuError("Choose between 1 and 8 candidates.")
    existing = len(get(actor_id)["candidates"])
    return jobs.enqueue(
        "actor_candidates", payload={"actor_id": actor_id, "count": count, "models": models, "take": existing}
    )


@jobs.register("actor_reference")
def _reference_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = job["payload"]
    actor = get(payload["actor_id"])
    if not actor["refs"]:
        raise OmuError("Choose the actor's main portrait first.")
    entry = load.chosen_for("image_edit", payload.get("models"))
    if entry is None:
        raise OmuError(f"No image model chosen. {load.requirement('image_edit')}")
    prompt = (
        f"The same person as in the reference photo, same face, hair and clothing. {payload['view']}. "
        "Candid smartphone photo, natural light, realistic."
    )
    res = runner.call(
        entry,
        {"prompt": prompt, "reference_images": [store.path(actor["refs"][0])], "aspect_ratio": "3:4"},
        step="actor",
        take=int(payload.get("take", 0)),
        quantities={"images": 1},
    )
    current = get(actor["id"])
    db.update(
        "actors",
        actor["id"],
        {"candidates": [*current["candidates"], {"media": res.media[0], "kind": payload["view"]}]},
    )
    return {"media": res.media[0]}


def generate_reference(
    actor_id: str, view: str = "Side profile, head and shoulders", models: dict | None = None
) -> str:
    actor = get(actor_id)
    return jobs.enqueue(
        "actor_reference",
        payload={"actor_id": actor_id, "view": view, "models": models, "take": len(actor["candidates"])},
    )


def accept(actor_id: str, media: str, main: bool = False) -> dict[str, Any]:
    """Use a candidate as the actor's main portrait (first reference) or as an extra reference."""
    actor = get(actor_id)
    if media not in [c["media"] for c in actor["candidates"]] and media not in actor["refs"]:
        raise OmuError("That image is not one of this actor's candidates.")
    refs = [r for r in actor["refs"] if r != media]
    refs = [media, *refs] if main or not refs else [*refs, media]
    candidates = list(actor["candidates"])
    for i, c in enumerate(candidates):  # move exactly one candidate (two can share an image)
        if c["media"] == media:
            del candidates[i]
            break
    db.update("actors", actor_id, {"refs": refs, "candidates": candidates})
    return public(get(actor_id))


def discard_candidate(actor_id: str, media: str) -> dict[str, Any]:
    actor = get(actor_id)
    db.update("actors", actor_id, {"candidates": [c for c in actor["candidates"] if c["media"] != media]})
    return public(get(actor_id))


def update(actor_id: str, values: dict[str, Any]) -> dict[str, Any]:
    get(actor_id)
    check_lengths({k: v for k, v in values.items() if k in ("name", "description")})
    row = {
        k: str(values[k]).strip()
        for k in ("name", "description", "voice_provider", "voice_id")
        if k in values and values[k] is not None
    }
    if "name" in row and not row["name"]:
        raise OmuError("Give the actor a name.")
    db.update("actors", actor_id, row)
    return public(get(actor_id))


def set_voice_sample(actor_id: str, filename: str, data: bytes) -> dict[str, Any]:
    get(actor_id)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in {"mp3", "wav", "m4a", "ogg", "flac"}:
        raise OmuError("Use an MP3, WAV, M4A, OGG or FLAC voice sample.")
    if len(data) > 15 * 1024 * 1024:
        raise OmuError("The voice sample is too large. Use a clip under 15 MB.")
    db.update("actors", actor_id, {"voice_sample": store.put_bytes(data, ext)})
    return public(get(actor_id))


def delete(actor_id: str) -> None:
    """Delete an actor. Projects that used it keep their frames and clips (the shot shows the actor was removed)."""
    get(actor_id)
    db.delete("actors", actor_id)


@jobs.register("voice_sample")
def _voice_sample_job(job: dict[str, Any]) -> dict[str, Any]:
    from oh_my_ugc import voice

    return {"media": voice.make_sample(get(job["payload"]["actor_id"]))}


def start_voice_sample(actor_id: str) -> str:
    actor = get(actor_id)
    if not actor["voice_id"]:
        raise OmuError("Pick a voice for this actor first.")
    return jobs.enqueue("voice_sample", payload={"actor_id": actor_id})
