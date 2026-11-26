"""Storyboard: draft shots from the script, preview each as a still, edit, approve (design D8, D9)."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from typing import Any

from oh_my_ugc import brands, costs, db, jobs, llm, projects, runner, scripts, store
from oh_my_ugc.catalog import load, mapping
from oh_my_ugc.errors import NotFound, OmuError

PURPOSES = ("hook", "problem", "demo", "proof", "offer", "cta", "other")
TYPES = ("talking", "product_in_hand", "cutaway", "real_product")
MOTIONS = ("push_in", "pan", "parallax", "rotate_in")
BACKGROUNDS = ("blur", "brand", "image")
VISUAL_FIELDS = ("type", "framing", "setting", "action")
EDITABLE = (
    "purpose",
    "type",
    "framing",
    "setting",
    "action",
    "line",
    "onscreen",
    "duration",
    "motion",
    "background",
    "voice_mode",
)
PAD = 0.4  # seconds of breathing room per spoken shot

SHOT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["shots"],
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "purpose",
                    "type",
                    "framing",
                    "setting",
                    "action",
                    "line",
                    "onscreen",
                    "duration",
                ],
                "properties": {
                    "purpose": {"type": "string", "enum": list(PURPOSES)},
                    "type": {"type": "string", "enum": list(TYPES)},
                    "framing": {"type": "string"},
                    "setting": {"type": "string"},
                    "action": {"type": "string"},
                    "line": {"type": "string"},
                    "onscreen": {"type": "string"},
                    "duration": {"type": "number"},
                },
            },
        }
    },
}


# ── script alignment (the coverage invariant) ────────────────────────────────


def _norm(token: str) -> str:
    return re.sub(r"[^\w']", "", token.lower())


def align_script(script: str, lines: list[str]) -> list[str]:
    """Re-cut the script into len(lines) pieces following the model's boundaries.

    The model may paraphrase; the script is the source of truth. The model's words are aligned
    to the script's with difflib and each shot boundary is carried across, so the pieces
    always concatenate to exactly the script's words.
    """
    source = script.split()
    if not lines:
        return []
    model_tokens: list[str] = []
    bounds = []
    for line in lines:
        model_tokens += line.split()
        bounds.append(len(model_tokens))
    matcher = difflib.SequenceMatcher(
        a=[_norm(t) for t in model_tokens], b=[_norm(t) for t in source], autojunk=False
    )
    ops = matcher.get_opcodes()

    def to_source(i: int) -> int:
        if i <= 0:
            return 0
        for tag, i1, i2, j1, j2 in ops:
            if i1 < i <= i2 or (i == i2 and tag != "insert" and i1 < i2):
                if tag == "equal":
                    return j1 + (i - i1)
                span = max(1, i2 - i1)
                return j1 + round((j2 - j1) * (i - i1) / span)
        return len(source)

    cuts = [to_source(b) for b in bounds[:-1]]
    cuts = [min(len(source), max(0, c)) for c in cuts]
    for k in range(1, len(cuts)):
        cuts[k] = max(cuts[k], cuts[k - 1])
    edges = [0, *cuts, len(source)]
    return [" ".join(source[edges[k] : edges[k + 1]]) for k in range(len(lines))]


def shot_seconds(line: str, fallback: float) -> float:
    words = scripts.word_count(line)
    return round(words / scripts.WORDS_PER_SECOND + PAD, 2) if words else fallback


def fit_durations(
    durations: list[float], silent: list[bool], target: float, tolerance: float = 0.1
) -> list[float]:
    """Scale shot durations so the total is within ``tolerance`` of the target length."""
    total = sum(durations)
    if total <= 0 or abs(total - target) <= target * tolerance:
        return durations
    wanted = target * (1.05 if total > target else 0.95)
    out = list(durations)
    adjustable = [i for i, s in enumerate(silent) if s]
    if adjustable:  # absorb the difference in shots with no spoken line first
        fixed = sum(d for i, d in enumerate(out) if i not in adjustable)
        free = sum(out[i] for i in adjustable)
        room = wanted - fixed
        if room > 0 and free > 0:
            factor = max(0.4, min(2.0, room / free))
            for i in adjustable:
                out[i] = max(1.5, round(out[i] * factor, 2))
    total = sum(out)
    if abs(total - target) > target * tolerance:
        factor = wanted / total
        out = [max(1.5, round(d * factor, 2)) for d in out]
    return out


# ── persistence ──────────────────────────────────────────────────────────────


def get_shot(shot_id: str) -> dict[str, Any]:
    shot = db.one("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not shot:
        raise NotFound("That shot")
    return shot


def shots_of(project_id: str, variant_id: str | None = None) -> list[dict[str, Any]]:
    if variant_id:
        return db.many(
            "SELECT * FROM shots WHERE project_id = ? AND variant_id = ? ORDER BY position",
            (project_id, variant_id),
        )
    return db.many(
        "SELECT * FROM shots WHERE project_id = ? AND variant_id IS NULL ORDER BY position", (project_id,)
    )


def _context(project: dict[str, Any]):
    actor = (
        db.one("SELECT * FROM actors WHERE id = ?", (project["actor_id"],))
        if project.get("actor_id")
        else None
    )
    product = (
        db.one("SELECT * FROM products WHERE id = ?", (project["product_id"],))
        if project.get("product_id")
        else None
    )
    return actor, product


def basis(project: dict[str, Any], shot: dict[str, Any]) -> str:
    """Hash of everything that changes what a shot's frame looks like (design D9)."""
    actor, product = _context(project)
    uses_actor = shot["type"] in ("talking", "product_in_hand")
    payload = {
        "type": shot["type"],
        "framing": shot["framing"],
        "setting": shot["setting"],
        "action": shot["action"],
        "actor": actor["refs"] if actor and uses_actor else None,
        "product": product["primary_photo"] if product else None,
        "aspect": project["aspect"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def shot_public(project: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    out = dict(shot)
    out["frame_url"] = store.url(shot.get("frame"))
    out["end_frame_url"] = store.url(shot.get("end_frame"))
    out["stale"] = (
        bool(shot.get("frame"))
        and shot.get("frame_basis") != basis(project, shot)
        and shot["type"] != "real_product"
    )
    out["history"] = [
        {**f, "url": store.url(f["media"]), "current": f["media"] == shot.get("frame")}
        for f in db.many(
            "SELECT * FROM frames WHERE shot_id = ? ORDER BY created_at DESC, rowid DESC", (shot["id"],)
        )
    ]
    out["takes"] = [
        {**t, "url": store.url(t["media"])}
        for t in db.many("SELECT * FROM takes WHERE shot_id = ? ORDER BY created_at, rowid", (shot["id"],))
    ]
    out["audio_url"] = store.url(shot.get("audio"))
    jobs_for = jobs.listing(shot_id=shot["id"], limit=1)
    out["job"] = jobs_for[0] if jobs_for else None
    return out


def listing(project_id: str, variant_id: str | None = None) -> list[dict[str, Any]]:
    project = projects.get(project_id)
    return [shot_public(project, s) for s in shots_of(project_id, variant_id)]


def _insert_shot(
    project_id: str, position: int, values: dict[str, Any], variant_id: str | None = None
) -> str:
    row = {
        "project_id": project_id,
        "variant_id": variant_id,
        "position": position,
        "created_at": db.now(),
        **{
            k: values[k]
            for k in (
                "purpose",
                "type",
                "framing",
                "setting",
                "action",
                "line",
                "onscreen",
                "duration",
                "motion",
                "background",
            )
            if k in values
        },
    }
    return db.insert("shots", row)


def _renumber(project_id: str, variant_id: str | None = None) -> None:
    for i, s in enumerate(shots_of(project_id, variant_id)):
        if s["position"] != i:
            db.update("shots", s["id"], {"position": i})


# ── drafting ─────────────────────────────────────────────────────────────────


def estimate_draft(project_id: str) -> dict[str, Any]:
    project = projects.get(project_id)
    if not llm.available("llm", project.get("models")):
        return {"available": False, "message": "No language model chosen. " + load.requirement("llm")}
    entry = llm.pick("llm", project.get("models"))
    return {"available": True, "model": entry.name, "total": costs.total([costs.estimate(entry)])}


def draft(project_id: str, replace: bool = False) -> list[dict[str, Any]]:
    """Draft the storyboard with the project's language model, covering the whole script."""
    project = projects.get(project_id)
    script = project["script"].strip()
    if not script:
        raise OmuError("Write or paste the script first, then draft the storyboard.")
    existing = shots_of(project_id)
    if existing and not replace:
        raise OmuError(
            "This project already has a storyboard. Redraft to replace it (frames and approvals will be lost).",
            status=409,
        )
    entry = llm.pick("llm", project.get("models"))
    actor, product = _context(project)
    system = llm.prompt(
        "storyboard",
        seconds=str(round(project["target_seconds"])),
        format=scripts.FORMAT_NOTES.get(project["format"], project["format"]),
        platform=project["platform"],
        actor=(actor["description"] if actor and actor["description"] else "a relatable everyday person"),
        product=(f"{product['name']}. {product['facts']}" if product else "(none given)"),
    )
    user = f"{scripts._context(project)}\n\nScript (use these exact words, in order):\n{script}"
    result = llm.chat_json(entry, system, user, SHOT_SCHEMA, step="storyboard", project_id=project_id)
    drafts = [s for s in result.get("shots", []) if isinstance(s, dict)]
    if not drafts:
        raise OmuError("The language model returned no shots. Try again or pick another model.")
    lines = align_script(script, [str(s.get("line", "")) for s in drafts])
    durations = [
        shot_seconds(lines[i], max(1.5, min(8.0, float(drafts[i].get("duration") or 3))))
        for i in range(len(drafts))
    ]
    durations = fit_durations(durations, [not line for line in lines], project["target_seconds"])
    for old in existing:
        db.delete("shots", old["id"])
    for i, s in enumerate(drafts):
        stype = s.get("type") if s.get("type") in TYPES else "talking"
        _insert_shot(
            project_id,
            i,
            {
                "purpose": s.get("purpose") if s.get("purpose") in PURPOSES else "other",
                "type": stype,
                "framing": str(s.get("framing", "")),
                "setting": str(s.get("setting", "")),
                "action": str(s.get("action", "")),
                "line": lines[i],
                "onscreen": str(s.get("onscreen", ""))[:60],
                "duration": durations[i],
            },
        )
    projects.update(project_id, {"stage": "storyboard"})
    _preview_real_products(project_id)
    return listing(project_id)


def _preview_real_products(project_id: str) -> None:
    """Real-product shots preview for free, from the product photo, as soon as they exist."""
    for s in shots_of(project_id):
        if s["type"] == "real_product" and not s["frame"]:
            try:
                make_frame(s["id"])
            except OmuError:
                pass  # no product chosen yet: the preview appears once there is one


# ── editing ──────────────────────────────────────────────────────────────────


def update_shot(shot_id: str, values: dict[str, Any]) -> dict[str, Any]:
    shot = get_shot(shot_id)
    project = projects.get(shot["project_id"])
    row: dict[str, Any] = {}
    for key in EDITABLE:
        if key in values and values[key] is not None:
            row[key] = values[key]
    if "type" in row and row["type"] not in TYPES:
        raise OmuError(f"'{row['type']}' is not a shot type. Choose one of: {', '.join(TYPES)}.")
    if "purpose" in row and row["purpose"] not in PURPOSES:
        raise OmuError(f"'{row['purpose']}' is not a purpose. Choose one of: {', '.join(PURPOSES)}.")
    if "duration" in row:
        row["duration"] = max(1.0, min(30.0, float(row["duration"])))
    if "onscreen" in row:
        row["onscreen"] = str(row["onscreen"])[:80]
    if "motion" in row and row["motion"] not in MOTIONS:
        raise OmuError("Choose push in, pan, parallax or rotate in.")
    if "background" in row and row["background"] not in BACKGROUNDS:
        raise OmuError("Choose a blurred, brand colour or uploaded background.")
    visual_changed = any(k in row and row[k] != shot[k] for k in VISUAL_FIELDS)
    if visual_changed:
        row["approved"] = 0  # approving again is deliberate after a visual change
    if "line" in row and row["line"] != shot["line"]:
        row["audio"], row["words"] = None, []  # stale voiceover
    db.update("shots", shot_id, row)
    projects.touch(project["id"])
    if row.get("type") == "real_product" and shot["type"] != "real_product" and project.get("product_id"):
        _preview_real_products(project["id"])
    return shot_public(project, get_shot(shot_id))


def add_shot(
    project_id: str,
    values: dict[str, Any] | None = None,
    after: str | None = None,
    variant_id: str | None = None,
) -> dict[str, Any]:
    project = projects.get(project_id)
    siblings = shots_of(project_id, variant_id)
    position = len(siblings)
    if after:
        position = next((s["position"] + 1 for s in siblings if s["id"] == after), position)
    for s in siblings:
        if s["position"] >= position:
            db.update("shots", s["id"], {"position": s["position"] + 1})
    values = values or {}
    shot_id = _insert_shot(
        project_id,
        position,
        {
            "purpose": "other",
            "type": "cutaway",
            "framing": "",
            "setting": "",
            "action": "",
            "line": "",
            "onscreen": "",
            "duration": 3.0,
            **values,
        },
        variant_id,
    )
    projects.touch(project_id)
    return shot_public(project, get_shot(shot_id))


def duplicate_shot(shot_id: str) -> dict[str, Any]:
    shot = get_shot(shot_id)
    new = add_shot(
        shot["project_id"],
        {k: shot[k] for k in EDITABLE if k in shot and k != "voice_mode"},
        after=shot_id,
        variant_id=shot["variant_id"],
    )
    db.update("shots", new["id"], {"frame": shot["frame"], "frame_basis": shot["frame_basis"]})
    return shot_public(projects.get(shot["project_id"]), get_shot(new["id"]))


def delete_shot(shot_id: str) -> None:
    shot = get_shot(shot_id)
    db.delete("shots", shot_id)
    _renumber(shot["project_id"], shot["variant_id"])
    projects.touch(shot["project_id"])


def reorder(project_id: str, ordered_ids: list[str]) -> list[dict[str, Any]]:
    current = [s["id"] for s in shots_of(project_id)]
    if sorted(current) != sorted(ordered_ids):
        raise OmuError("The shot order must list every shot exactly once.")
    for i, sid in enumerate(ordered_ids):
        db.update("shots", sid, {"position": i})
    projects.touch(project_id)
    return listing(project_id)


def approve(shot_id: str, approved: bool = True) -> dict[str, Any]:
    shot = get_shot(shot_id)
    project = projects.get(shot["project_id"])
    if approved and shot["type"] != "real_product" and not shot["text_card"] and not shot["frame"]:
        raise OmuError("Generate a frame for this shot before approving it.")
    db.update("shots", shot_id, {"approved": 1 if approved else 0})
    return shot_public(project, get_shot(shot_id))


def approve_all(project_id: str) -> list[dict[str, Any]]:
    project = projects.get(project_id)
    missing = [
        s["position"] + 1
        for s in shots_of(project_id)
        if s["type"] != "real_product" and not s["text_card"] and not s["frame"]
    ]
    if missing:
        raise OmuError(
            f"Shot {', '.join(map(str, missing))} still need a frame before everything can be approved."
        )
    for s in shots_of(project_id):
        db.update("shots", s["id"], {"approved": 1})
    projects.update(project_id, {"stage": "clips"}) if project["stage"] == "storyboard" else None
    return listing(project_id)


def add_text_card(
    project_id: str, text: str, after: str | None = None, duration: float = 2.0
) -> dict[str, Any]:
    """A full-screen text card between shots (drawn by the app, never by a model)."""
    text = " ".join((text or "").split())
    if not text:
        raise OmuError("Write the text for the card.")
    shot = add_shot(
        project_id,
        {"purpose": "other", "type": "cutaway", "onscreen": text[:80], "duration": max(1.0, float(duration))},
        after=after,
    )
    db.update("shots", shot["id"], {"text_card": 1, "approved": 1})
    return shot_public(projects.get(project_id), get_shot(shot["id"]))


def ensure_variant_shot(variant_id: str) -> dict[str, Any]:
    """The shot that replaces the first shot for a hook variant: same frame, different line."""
    from oh_my_ugc import scripts

    variant = scripts.get_variant(variant_id)
    existing = shots_of(variant["project_id"], variant_id)
    base = shots_of(variant["project_id"])
    if not base:
        raise OmuError("Draft the storyboard first; hooks replace its first shot.")
    first = base[0]
    if first["block"] is not None:
        raise OmuError("The first shot is part of a block. Ungroup it so a hook can replace it.")
    if existing:
        db.update(
            "shots",
            existing[0]["id"],
            {"line": variant["hook"], "audio": None, "words": []}
            if existing[0]["line"] != variant["hook"]
            else {},
        )
        return get_shot(existing[0]["id"])
    new_id = db.insert(
        "shots",
        {
            **{
                k: first[k]
                for k in (
                    "project_id",
                    "purpose",
                    "type",
                    "framing",
                    "setting",
                    "action",
                    "onscreen",
                    "duration",
                    "motion",
                    "background",
                    "frame",
                    "frame_basis",
                    "end_frame",
                    "voice_mode",
                )
            },
            "variant_id": variant_id,
            "position": 0,
            "line": variant["hook"],
            "approved": 1,
            "created_at": db.now(),
        },
    )
    return get_shot(new_id)


def change_actor(project_id: str, actor_id: str | None) -> dict[str, Any]:
    """Swap the actor for the whole storyboard: every shot with a person needs a new frame."""
    projects.update(project_id, {"actor_id": actor_id})
    for s in shots_of(project_id):
        if s["type"] in ("talking", "product_in_hand"):
            db.update("shots", s["id"], {"approved": 0})
    return projects.public(projects.get(project_id), detail=True)


# ── frames ───────────────────────────────────────────────────────────────────


def shows_product(shot: dict[str, Any], product: dict[str, Any] | None) -> bool:
    if not product:
        return False
    if shot["type"] in ("product_in_hand", "cutaway"):
        return True
    text = f"{shot['framing']} {shot['action']}".lower()
    return "product" in text or product["name"].lower() in text


def frame_prompt(project: dict[str, Any], shot: dict[str, Any], note: str = "") -> str:
    actor, product = _context(project)
    uses_actor = shot["type"] in ("talking", "product_in_hand") and actor
    orientation = {
        "9:16": "vertical 9:16",
        "1:1": "square 1:1",
        "4:5": "portrait 4:5",
        "16:9": "horizontal 16:9",
    }[project["aspect"]]
    parts = [
        f"A {orientation} UGC-style photograph, shot on a smartphone. {shot['framing']}.".replace("..", ".")
    ]
    if shot["setting"]:
        parts.append(f"Setting: {shot['setting']}.")
    if shot["action"]:
        parts.append(f"{shot['action']}")
    if uses_actor:
        parts.append(
            f"The person is the same person as in the first reference image(s): {actor['description'] or 'keep their face, hair and clothing identical'}. Keep their face, hair, skin tone and clothing identical."
        )
    if product:
        label = (
            f' Its label reads exactly "{product["label_text"]}". Spell every letter correctly.'
            if product["label_text"]
            else ""
        )
        which = "the last reference image" if uses_actor else "the reference image"
        parts.append(
            f'The product "{product["name"]}" must look exactly like the product in {which}: same shape, colours and packaging.{label}'
        )
    parts.append(
        "Natural phone-camera look, realistic skin and lighting, no text overlays, no captions, no logos added, no watermark."
    )
    if note.strip():
        parts.append(f"Extra direction: {note.strip()}")
    return " ".join(parts)


def closest_aspect(aspect: str, supported: list[str] | None) -> str | None:
    if not supported or aspect in supported:
        return aspect

    def ratio(a: str) -> float:
        w, h = (float(x) for x in a.split(":"))
        return w / h

    return min(supported, key=lambda a: abs(ratio(a) - ratio(aspect)))


def frame_resolution(entry) -> str | None:
    values = entry.limits.resolutions or []
    return "2K" if "2K" in values else (max(values, key=mapping._res_px) if values else None)


def _frame_entry(project: dict[str, Any]):
    entry = load.chosen_for("image_edit", project.get("models"))
    if entry is None:
        raise OmuError(f"No image model chosen, so frames cannot be made. {load.requirement('image_edit')}")
    return entry


def frame_needs(project_id: str, only_missing: bool = True) -> list[dict[str, Any]]:
    project = projects.get(project_id)
    out = []
    for s in shots_of(project_id):
        if s["type"] == "real_product" or s["text_card"]:
            continue
        if only_missing and s["frame"] and s["frame_basis"] == basis(project, s):
            continue
        out.append(s)
    return out


def estimate_frames(project_id: str, only_missing: bool = True) -> dict[str, Any]:
    project = projects.get(project_id)
    try:
        entry = _frame_entry(project)
    except OmuError as exc:
        return {"available": False, "message": exc.message}
    needs = frame_needs(project_id, only_missing)
    est = costs.estimate(entry, images=1, resolution=frame_resolution(entry))
    return {
        "available": True,
        "model": entry.name,
        "shots": len(needs),
        "each": est.amount,
        "total": costs.total([est] * len(needs)),
    }


def _references(project: dict[str, Any], shot: dict[str, Any]) -> list:
    actor, product = _context(project)
    refs = []
    if actor and shot["type"] in ("talking", "product_in_hand"):
        refs += [store.path(m) for m in actor["refs"][:2]]
    if product:
        refs.append(store.path(product["primary_photo"]))
    return refs


@jobs.register("frame")
def _frame_job(job: dict[str, Any]) -> dict[str, Any]:
    p = job["payload"]
    return make_frame(p["shot_id"], p.get("note", ""), p.get("target", "frame"), int(p.get("take", 0)))


def make_frame(shot_id: str, note: str = "", target: str = "frame", take: int = 0) -> dict[str, Any]:
    from oh_my_ugc import fidelity, render_local

    shot = get_shot(shot_id)
    project = projects.get(shot["project_id"])
    actor, product = _context(project)
    if shot["type"] == "real_product":
        if not product:
            raise OmuError("Choose a product for this project to preview the real-product shot.")
        media = render_local.real_product_still(project, shot, product)
        cost = 0.0
    else:
        entry = _frame_entry(project)
        if shot["type"] in ("talking", "product_in_hand") and not actor:
            raise OmuError(
                "Choose an actor for this project, or change this shot to a cutaway or real-product shot."
            )
        slots = {
            "prompt": frame_prompt(project, shot, note),
            "reference_images": _references(project, shot),
            "aspect_ratio": closest_aspect(project["aspect"], entry.limits.aspect_ratios),
            "resolution": frame_resolution(entry),
        }
        res = runner.call(
            entry,
            slots,
            project_id=project["id"],
            step="frames",
            take=take,
            quantities={"images": 1, "resolution": frame_resolution(entry)},
        )
        media, cost = res.media[0], res.cost
    current_basis = basis(project, shot)
    drift = None
    if shot["type"] != "real_product" and product and shows_product(shot, product) and target == "frame":
        runner.stage("Checking the product against your photo")
        drift = fidelity.check_frame(project, product, store.path(media))
    if target == "end":
        db.update("shots", shot_id, {"end_frame": media})
        return {"media": media, "cost": cost}
    db.insert(
        "frames",
        {
            "shot_id": shot_id,
            "media": media,
            "basis": current_basis,
            "note": note,
            "drift": drift,
            "created_at": db.now(),
        },
    )
    db.update(
        "shots",
        shot_id,
        {
            "frame": media,
            "frame_basis": current_basis,
            "frame_drift": drift,
            "approved": 0 if take else shot["approved"],
        },
    )
    return {"media": media, "cost": cost, "drift": drift}


def generate_frame(shot_id: str, note: str = "", target: str = "frame") -> str:
    shot = get_shot(shot_id)
    take = (
        len(db.many("SELECT id FROM frames WHERE shot_id = ?", (shot_id,)))
        if note.strip() or shot["frame"]
        else 0
    )
    return jobs.enqueue(
        "frame",
        project_id=shot["project_id"],
        shot_id=shot_id,
        payload={"shot_id": shot_id, "note": note, "target": target, "take": take},
    )


def generate_frames(project_id: str, only_missing: bool = True) -> list[str]:
    projects.get(project_id)
    return [generate_frame(s["id"]) for s in frame_needs(project_id, only_missing)]


def use_frame(shot_id: str, frame_id: str) -> dict[str, Any]:
    shot = get_shot(shot_id)
    frame = db.one("SELECT * FROM frames WHERE id = ? AND shot_id = ?", (frame_id, shot_id))
    if not frame:
        raise NotFound("That frame")
    db.update(
        "shots",
        shot_id,
        {"frame": frame["media"], "frame_basis": frame["basis"], "frame_drift": frame["drift"]},
    )
    return shot_public(projects.get(shot["project_id"]), get_shot(shot_id))


def upload_frame(shot_id: str, filename: str, data: bytes, target: str = "frame") -> dict[str, Any]:
    from oh_my_ugc import products

    shot = get_shot(shot_id)
    project = projects.get(shot["project_id"])
    media = products.validate_image(filename, data)
    if target == "end":
        db.update("shots", shot_id, {"end_frame": media})
    else:
        current = basis(project, shot)
        db.insert(
            "frames",
            {
                "shot_id": shot_id,
                "media": media,
                "basis": current,
                "note": "uploaded",
                "drift": None,
                "created_at": db.now(),
            },
        )
        db.update("shots", shot_id, {"frame": media, "frame_basis": current, "frame_drift": None})
    return shot_public(project, get_shot(shot_id))


def set_end_frame(shot_id: str, source: str) -> dict[str, Any]:
    """End frame from the next shot's frame, or cleared ('none')."""
    shot = get_shot(shot_id)
    project = projects.get(shot["project_id"])
    if source == "none":
        db.update("shots", shot_id, {"end_frame": None})
    elif source == "next":
        siblings = shots_of(shot["project_id"], shot["variant_id"])
        nxt = next((s for s in siblings if s["position"] == shot["position"] + 1), None)
        if not nxt or not nxt["frame"]:
            raise OmuError("The next shot has no frame yet.")
        db.update("shots", shot_id, {"end_frame": nxt["frame"]})
    else:
        raise OmuError("Use 'next' or 'none', or upload an image / generate one.")
    return shot_public(project, get_shot(shot_id))


# ── blocks ───────────────────────────────────────────────────────────────────


def group_block(project_id: str, shot_ids: list[str]) -> list[dict[str, Any]]:
    """Group consecutive shots into one clip for models that support multi-shot prompts."""
    project = projects.get(project_id)
    ordered = [s for s in shots_of(project_id) if s["id"] in shot_ids]
    if len(ordered) < 2 or len(ordered) != len(shot_ids):
        raise OmuError("Pick two or more shots to group.")
    positions = [s["position"] for s in ordered]
    if positions != list(range(positions[0], positions[0] + len(positions))):
        raise OmuError("Only shots that follow each other can be grouped.")
    if any(s["type"] == "real_product" for s in ordered):
        raise OmuError("Real-product shots are made locally and cannot be part of a block.")
    entry = load.chosen_for("image_to_video", project.get("models"))
    if entry is None:
        raise OmuError(f"No video model chosen. {load.requirement('image_to_video')}")
    if not entry.multi_shot:
        raise OmuError(
            f"{entry.name} does not do multi-shot blocks. Choose a model that does (such as Seedance), or keep the shots separate."
        )
    longest = mapping.max_clip_seconds(entry)
    total = sum(s["duration"] for s in ordered)
    if total > longest + 1e-6:
        raise OmuError(
            f"These shots add up to {total:.0f} seconds, but {entry.name} makes at most {longest:.0f} seconds per clip."
        )
    taken = [s["block"] for s in shots_of(project_id) if s["block"] is not None]
    block_id = (max(taken) + 1) if taken else 1
    for s in ordered:
        db.update("shots", s["id"], {"block": block_id})
    return listing(project_id)


def ungroup_block(project_id: str, block_id: int) -> list[dict[str, Any]]:
    projects.get(project_id)
    db.run("UPDATE shots SET block = NULL WHERE project_id = ? AND block = ?", (project_id, block_id))
    return listing(project_id)


def units(project_id: str, variant_id: str | None = None) -> list[list[dict[str, Any]]]:
    """Shots grouped into the units that become one clip each (a single shot, or a block)."""
    out: list[list[dict[str, Any]]] = []
    for s in shots_of(project_id, variant_id):
        if s["block"] is not None and out and out[-1][0]["block"] == s["block"] and not s["text_card"]:
            out[-1].append(s)
        else:
            out.append([s])
    return out


def warnings(project_id: str) -> list[str]:
    """Things the user should know before rendering (shown on the clips stage)."""
    project = projects.get(project_id)
    entry = load.chosen_for("image_to_video", project.get("models"))
    msgs: list[str] = []
    if entry is None:
        return [f"No video model chosen. {load.requirement('image_to_video')}"]
    for s in shots_of(project_id):
        if s["end_frame"] and "last_frame" not in entry.inputs:
            msgs.append(
                f"Shot {s['position'] + 1} has an end frame, but {entry.name} has no last-frame input, so it will be ignored."
            )
    if project["voice_mode"] == "native" and any(s["line"] for s in shots_of(project_id)):
        actor, _ = _context(project)
        if not entry.native_audio:
            msgs.append(f"{entry.name} cannot speak lines itself. Use voiceover or talking avatar mode.")
        elif not (entry.reference_audio and actor and actor["voice_sample"]):
            msgs.append(
                "The voice may differ between shots: this model has no voice reference, or the actor has no voice sample."
            )
    return msgs


_ = brands  # re-exported for callers that build prompts from brand context


@jobs.register("draft_storyboard")
def _draft_job(job: dict[str, Any]) -> dict[str, Any]:
    p = job["payload"]
    shots = draft(p["project_id"], replace=bool(p.get("replace")))
    return {"shots": len(shots)}


def start_draft(project_id: str, replace: bool = False) -> str:
    project = projects.get(project_id)
    if shots_of(project_id) and not replace:
        raise OmuError(
            "This project already has a storyboard. Redraft to replace it (frames and approvals will be lost).",
            status=409,
        )
    if not project["script"].strip():
        raise OmuError("Write or paste the script first, then draft the storyboard.")
    llm.pick("llm", project.get("models"))
    return jobs.enqueue(
        "draft_storyboard", project_id=project_id, payload={"project_id": project_id, "replace": replace}
    )
