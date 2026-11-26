"""Clip generation: each approved shot (or block) becomes a video clip (specs: clip-generation)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oh_my_ugc import (
    costs,
    db,
    fidelity,
    jobs,
    media,
    projects,
    render_local,
    runner,
    store,
    storyboard,
    voice,
)
from oh_my_ugc.catalog import load, mapping
from oh_my_ugc.errors import NotFound, OmuError

QUALITY_RANK = {"draft": 1, "final": 2, "local": 3}


def effective_mode(project: dict[str, Any], unit: list[dict[str, Any]]) -> str:
    return unit[0].get("voice_mode") or project["voice_mode"]


def unit_line_shots(unit: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in unit if s["line"].strip()]


def video_entry(project: dict[str, Any]):
    entry = load.chosen_for("image_to_video", project.get("models"))
    if entry is None:
        raise OmuError(
            f"No video model chosen, so clips cannot be made. {load.requirement('image_to_video')}"
        )
    return entry


def resolution_for(entry, project: dict[str, Any], quality: str) -> str | None:
    if quality == "draft":
        return mapping.cheapest_resolution(entry)
    return mapping.pick_resolution(entry, project["final_resolution"])


def prompt_for(project: dict[str, Any], unit: list[dict[str, Any]], native: bool) -> str:
    def one(s: dict[str, Any]) -> str:
        parts = [
            s["framing"].rstrip(".") + "." if s["framing"] else "",
            f"{s['action'].rstrip('.')}." if s["action"] else "",
        ]
        if s["setting"]:
            parts.append(f"Setting: {s['setting']}.")
        if native and s["line"].strip():
            parts.append(
                f'The person speaks to camera in a natural, conversational voice and says: "{s["line"].strip()}"'
            )
        return " ".join(p for p in parts if p)

    style = "Realistic smartphone UGC video, natural handheld motion, authentic and unpolished. The product and its label stay exactly as in the first frame. No text overlays, no captions, no subtitles, no logos, no watermark."
    if len(unit) == 1:
        text = one(unit[0])
    else:
        t, lines = 0.0, []
        for i, s in enumerate(unit, 1):
            lines.append(f"Shot {i} ({t:.0f}-{t + s['duration']:.0f} s): {one(s)}")
            t += s["duration"]
        text = "\n".join(lines)
    silent = "" if native else " No speech, no music, no sound effects."
    return f"{text} {style}{silent}".strip()


def plan_unit(
    project: dict[str, Any], unit: list[dict[str, Any]], quality: str, *, include_voice: bool = True
) -> dict[str, Any]:
    """What rendering a unit involves: model, resolution, audio, duration and cost lines."""
    lead = unit[0]
    actor, product = storyboard._context(project)
    if lead["type"] == "real_product":
        return {"kind": "local", "seconds": lead["duration"], "lines": [], "estimate": 0.0, "partial": False}
    entry = video_entry(project)
    mode = effective_mode(project, unit)
    spoken = unit_line_shots(unit)
    seconds = sum(s["duration"] for s in unit)
    voice_cost = costs.Estimate(0.0)
    if spoken and mode in ("voiceover", "avatar"):
        pieces = [voice.estimate_line(project, actor, s["line"]) for s in spoken]
        voice_cost = costs.Estimate(
            None if any(p.amount is None for p in pieces) else sum(p.amount or 0 for p in pieces)
        )
    native = bool(spoken) and mode == "native"
    items: list[dict[str, Any]] = []
    lipsync = load.get(project["models"]["lipsync"]) if (project.get("models") or {}).get("lipsync") else None
    if spoken and mode == "avatar" and lipsync:
        entry = video_entry(project)
        audio_seconds = sum(len(s["line"].split()) / 2.5 + 0.4 for s in spoken)
        clip_seconds = mapping.snap_duration(
            entry, min(max(audio_seconds + 0.3, 1.0), mapping.max_clip_seconds(entry))
        )
        resolution = resolution_for(entry, project, quality)
        video = costs.estimate(
            entry, seconds=clip_seconds, resolution=resolution, audio=False, aspect=project["aspect"]
        )
        sync = costs.estimate(lipsync, seconds=audio_seconds, resolution=resolution)
        items.append(
            {"label": f"{entry.name} {resolution or ''} silent".replace("  ", " "), "estimate": video.amount}
        )
        items.append({"label": f"{lipsync.name} (lip sync)", "estimate": sync.amount})
        items.append({"label": "Voice", "estimate": voice_cost.amount})
        return {
            "kind": "lipsync",
            "seconds": clip_seconds,
            "resolution": resolution,
            "lines": items,
            "estimate": _sum(items),
            "partial": any(i["estimate"] is None for i in items),
            "entry": entry.id,
            "lipsync": lipsync.id,
        }
    if spoken and mode == "avatar":
        avatar = load.chosen_for("talking_avatar", project.get("models"))
        if avatar is None:
            raise OmuError(f"Talking avatar mode needs an avatar model. {load.requirement('talking_avatar')}")
        audio_seconds = sum(len(s["line"].split()) / 2.5 + 0.4 for s in spoken)
        est = costs.estimate(
            avatar, seconds=audio_seconds, resolution=resolution_for(avatar, project, quality)
        )
        items.append({"label": f"{avatar.name} (talking avatar)", "estimate": est.amount})
        items.append({"label": "Voice", "estimate": voice_cost.amount})
        return {
            "kind": "avatar",
            "seconds": audio_seconds,
            "lines": items,
            "estimate": _sum(items),
            "partial": any(i["estimate"] is None for i in items),
            "entry": avatar.id,
        }
    seconds_snapped = mapping.snap_duration(entry, min(seconds, mapping.max_clip_seconds(entry)))
    resolution = resolution_for(entry, project, quality)
    est = costs.estimate(
        entry, seconds=seconds_snapped, resolution=resolution, audio=native, aspect=project["aspect"]
    )
    items.append(
        {
            "label": f"{entry.name} {resolution or ''} {'with audio' if native else 'silent'}".replace(
                "  ", " "
            ),
            "estimate": est.amount,
        }
    )
    if spoken and mode == "voiceover":
        items.append({"label": "Voice", "estimate": voice_cost.amount})
    if product and storyboard.shows_product(lead, product) and fidelity.available(project):
        check = llm_est(project)
        items.append({"label": "Product check", "estimate": check})
    return {
        "kind": "video",
        "seconds": seconds_snapped,
        "resolution": resolution,
        "audio": native,
        "lines": items,
        "estimate": _sum(items),
        "partial": any(i["estimate"] is None for i in items),
        "entry": entry.id,
    }


def llm_est(project: dict[str, Any]) -> float | None:
    from oh_my_ugc import llm

    entry = llm.pick("vision_check", project.get("models"))
    return (costs.estimate(entry).amount or 0.0) * 3


def _sum(items: list[dict[str, Any]]) -> float:
    return round(sum(i["estimate"] or 0.0 for i in items), 6)


def estimate_render(
    project_id: str, quality: str, shot_ids: list[str] | None = None, variant_id: str | None = None
) -> dict[str, Any]:
    project = projects.get(project_id)
    units = _units(project_id, shot_ids, variant_id)
    estimates, rows = [], []
    for unit in units:
        try:
            plan = plan_unit(project, unit, quality)
        except OmuError as exc:
            return {"available": False, "message": exc.message}
        rows.append(
            {
                "shot_id": unit[0]["id"],
                "position": unit[0]["position"] + 1,
                **{k: plan[k] for k in ("kind", "lines", "estimate")},
            }
        )
        estimates += [costs.Estimate(i["estimate"]) for i in plan["lines"]] or [costs.Estimate(0.0)]
    return {"available": True, "quality": quality, "units": rows, "total": costs.total(estimates)}


def _units(
    project_id: str, shot_ids: list[str] | None, variant_id: str | None = None
) -> list[list[dict[str, Any]]]:
    if variant_id:
        storyboard.ensure_variant_shot(variant_id)  # the hook shot exists once someone asks to render it
    units = [u for u in storyboard.units(project_id, variant_id) if not u[0]["text_card"]]
    if shot_ids:
        units = [u for u in units if any(s["id"] in shot_ids for s in u)]
    return units


# ── rendering ────────────────────────────────────────────────────────────────


def _takes(shot_id: str, quality: str | None = None) -> list[dict[str, Any]]:
    if quality:
        return db.many(
            "SELECT * FROM takes WHERE shot_id = ? AND quality = ? ORDER BY take, rowid", (shot_id, quality)
        )
    return db.many("SELECT * FROM takes WHERE shot_id = ? ORDER BY created_at, rowid", (shot_id,))


def render_unit(
    project: dict[str, Any],
    unit: list[dict[str, Any]],
    quality: str,
    *,
    new_take: bool = False,
    note: str = "",
) -> dict[str, Any]:
    from oh_my_ugc import db as _db

    lead = unit[0]
    if not all(s["approved"] for s in unit):
        raise OmuError(f"Approve shot {lead['position'] + 1} in the storyboard before making its clip.")
    actor, product = storyboard._context(project)
    spoken = unit_line_shots(unit)
    mode = effective_mode(project, unit)
    existing = _takes(lead["id"], "draft" if quality == "draft" else "final")
    take_no = (
        (max((t["take"] for t in existing), default=-1) + 1)
        if new_take
        else max((t["take"] for t in existing), default=0)
    )

    if lead["type"] == "real_product":
        prod = render_local.require_product(project)
        seconds = lead["duration"]
        if spoken and mode != "native":
            seconds = max(
                seconds, voice.speak_shot(project, lead, actor)["duration"] + voice.LEAD + voice.TAIL
            )
        runner.stage("Rendering the real product shot")
        media_id = render_local.render_real_product(project, lead, prod, seconds)
        return _save_take(lead, media_id, "local", 0, "real product shot", None, project)

    if not lead["frame"]:
        raise OmuError(
            f"Shot {lead['position'] + 1} has no frame yet. Generate frames in the storyboard first."
        )
    plan = plan_unit(project, unit, quality)
    prompt = prompt_for(project, unit, native=plan["kind"] == "video" and plan["audio"])
    if note.strip():
        prompt += f" Extra direction: {note.strip()}"
    frame = store.path(lead["frame"])

    if plan["kind"] == "lipsync":
        if len(unit) > 1:
            raise OmuError(
                "Lip sync mode makes one shot at a time. Ungroup this block or use another voice mode."
            )
        entry, lipsync = load.get(plan["entry"]), load.get(plan["lipsync"])
        spoken_audio = voice.speak_shot(project, lead, actor)
        runner.stage("Making the silent clip")
        base = runner.call(
            entry,
            {
                "prompt": prompt,
                "first_frame": frame,
                "duration": plan["seconds"],
                "resolution": plan["resolution"],
                "aspect_ratio": storyboard.closest_aspect(project["aspect"], entry.limits.aspect_ratios),
                "audio": False,
            },
            project_id=project["id"],
            step="clips",
            take=take_no,
            quantities={
                "seconds": plan["seconds"],
                "resolution": plan["resolution"],
                "audio": False,
                "aspect": project["aspect"],
            },
        )
        runner.stage("Syncing the lips to the voice")
        res = runner.call(
            lipsync,
            {"video": base.path, "audio": store.path(spoken_audio["media"])},
            project_id=project["id"],
            step="clips",
            take=take_no,
            quantities={"seconds": spoken_audio["duration"], "resolution": plan["resolution"]},
        )
        return _finish(project, product, lead, unit, res.media[0], quality, take_no, prompt, new_take)

    if plan["kind"] == "avatar":
        if len(unit) > 1:
            raise OmuError(
                "Talking avatar mode makes one shot at a time. Ungroup this block or use another voice mode."
            )
        avatar = load.get(plan["entry"])
        spoken_audio = voice.speak_shot(project, lead, actor)
        slots = {
            "first_frame": frame,
            "audio": store.path(spoken_audio["media"]),
            "prompt": f"{lead['action']} {lead['framing']}".strip() or None,
            "resolution": resolution_for(avatar, project, quality),
        }
        runner.stage("Making the talking avatar clip")
        res = runner.call(
            avatar,
            slots,
            project_id=project["id"],
            step="clips",
            take=take_no,
            quantities={"seconds": spoken_audio["duration"], "resolution": slots["resolution"]},
        )
        return _finish(project, product, lead, unit, res.media[0], quality, take_no, prompt, new_take)

    entry = video_entry(project)
    native = plan["audio"]
    if spoken and mode == "native" and not entry.native_audio:
        raise OmuError(f"{entry.name} cannot speak lines itself. Use voiceover or talking avatar mode.")
    audio_seconds = 0.0
    if spoken and mode == "voiceover":
        for s in spoken:
            audio_seconds += voice.speak_shot(project, s, actor)["duration"] + voice.LEAD + voice.TAIL
    wanted = max(sum(s["duration"] for s in unit), audio_seconds)
    seconds = mapping.snap_duration(entry, min(wanted, mapping.max_clip_seconds(entry)))
    ref_audio = None
    if native and entry.reference_audio and actor and actor.get("voice_sample"):
        ref_audio = store.path(actor["voice_sample"])
    slots = {
        "prompt": prompt,
        "first_frame": frame,
        "duration": seconds,
        "resolution": plan["resolution"],
        "aspect_ratio": storyboard.closest_aspect(project["aspect"], entry.limits.aspect_ratios),
        "audio": native,
        "reference_audio": ref_audio,
    }
    if lead["end_frame"] and "last_frame" in entry.inputs:
        slots["last_frame"] = store.path(lead["end_frame"])
    runner.stage(f"Making the clip ({plan['resolution'] or 'default'})")
    res = runner.call(
        entry,
        slots,
        project_id=project["id"],
        step="clips",
        take=take_no,
        quantities={
            "seconds": seconds,
            "resolution": plan["resolution"],
            "audio": native,
            "aspect": project["aspect"],
        },
    )
    _ = _db
    return _finish(project, product, lead, unit, res.media[0], quality, take_no, prompt, new_take)


def _finish(
    project, product, lead, unit, media_id, quality, take_no, prompt, choose: bool = False
) -> dict[str, Any]:
    drift = None
    if product and any(storyboard.shows_product(s, product) for s in unit):
        runner.stage("Checking the product in the clip")
        drift = fidelity.check_clip(project, product, store.path(media_id))
    return _save_take(
        lead, media_id, "draft" if quality == "draft" else "final", take_no, prompt, drift, project
    )


def _save_take(
    lead, media_id, quality, take_no, prompt, drift, project, choose: bool = False
) -> dict[str, Any]:
    existing = db.one(
        "SELECT id FROM takes WHERE shot_id = ? AND media = ? AND quality = ? AND take = ?",
        (lead["id"], media_id, quality, take_no),
    )
    if existing:  # the same clip again (a cache hit): keep one take, not two
        db.update("shots", lead["id"], {"chosen_take": existing["id"]}) if not lead.get(
            "chosen_take"
        ) else None
        return {"take": existing["id"], "drift": drift}
    path = store.path(media_id)
    info = media.probe(path)
    row = db.insert(
        "takes",
        {
            "shot_id": lead["id"],
            "media": media_id,
            "quality": quality,
            "take": take_no,
            "prompt": prompt,
            "drift": drift,
            "duration": info.duration,
            "has_audio": 1 if info.has_audio else 0,
            "created_at": db.now(),
        },
    )
    fresh = storyboard.get_shot(lead["id"])
    chosen = (
        db.one("SELECT * FROM takes WHERE id = ?", (fresh["chosen_take"],)) if fresh["chosen_take"] else None
    )
    if choose or not chosen or QUALITY_RANK[quality] >= QUALITY_RANK[chosen["quality"]]:
        db.update("shots", lead["id"], {"chosen_take": row})
    projects.touch(project["id"])
    return {"take": row, "drift": drift}


@jobs.register("render_shot")
def _render_job(job: dict[str, Any]) -> dict[str, Any]:
    p = job["payload"]
    shot = storyboard.get_shot(p["shot_id"])
    project = projects.get(shot["project_id"])
    unit = next(
        (u for u in storyboard.units(project["id"], shot["variant_id"]) if u[0]["id"] == shot["id"]), [shot]
    )
    return render_unit(project, unit, p["quality"], new_take=bool(p.get("new_take")), note=p.get("note", ""))


def render(
    project_id: str, quality: str = "draft", shot_ids: list[str] | None = None, variant_id: str | None = None
) -> list[str]:
    """Queue every unit (shot or block) for rendering. Costs are checked per call against the budget."""
    if quality not in ("draft", "final"):
        raise OmuError("Choose draft or final quality.")
    projects.get(project_id)
    ids = []
    for unit in _units(project_id, shot_ids, variant_id):
        if not all(s["approved"] for s in unit):
            raise OmuError(
                f"Approve shot {unit[0]['position'] + 1} first. Clips are only made for approved shots."
            )
        ids.append(
            jobs.enqueue(
                "render_shot",
                project_id=project_id,
                shot_id=unit[0]["id"],
                payload={"shot_id": unit[0]["id"], "quality": quality},
            )
        )
    if not ids:
        raise OmuError("There are no shots to render yet.")
    return ids


def new_take(shot_id: str, quality: str = "draft", note: str = "") -> str:
    shot = storyboard.get_shot(shot_id)
    return jobs.enqueue(
        "render_shot",
        project_id=shot["project_id"],
        shot_id=shot_id,
        payload={"shot_id": shot_id, "quality": quality, "new_take": True, "note": note},
    )


# ── review ───────────────────────────────────────────────────────────────────


def choose_take(shot_id: str, take_id: str) -> dict[str, Any]:
    shot = storyboard.get_shot(shot_id)
    take = db.one("SELECT * FROM takes WHERE id = ? AND shot_id = ?", (take_id, shot_id))
    if not take:
        raise NotFound("That take")
    db.update("shots", shot_id, {"chosen_take": take_id})
    return storyboard.shot_public(projects.get(shot["project_id"]), storyboard.get_shot(shot_id))


def trim(shot_id: str, take_id: str, start: float = 0.0, end: float | None = None) -> dict[str, Any]:
    shot = storyboard.get_shot(shot_id)
    take = db.one("SELECT * FROM takes WHERE id = ? AND shot_id = ?", (take_id, shot_id))
    if not take:
        raise NotFound("That take")
    length = take["duration"] or 0
    start = max(0.0, float(start))
    end = None if end in (None, "") else min(float(end), length)
    if end is not None and end - start < 0.5:
        raise OmuError("Keep at least half a second of the clip.")
    if start >= length - 0.5:
        raise OmuError("The start is beyond the end of the clip.")
    db.update("takes", take_id, {"trim_start": start, "trim_end": end})
    return storyboard.shot_public(projects.get(shot["project_id"]), storyboard.get_shot(shot_id))


def swap_to_real_product(shot_id: str) -> dict[str, Any]:
    """Replace a drifted shot with a real-product shot: same duration and line, made locally for free."""
    shot = storyboard.get_shot(shot_id)
    project = projects.get(shot["project_id"])
    product = render_local.require_product(project)
    db.update(
        "shots",
        shot_id,
        {"type": "real_product", "block": None, "end_frame": None, "frame_drift": None, "approved": 1},
    )
    shot = storyboard.get_shot(shot_id)
    still = render_local.real_product_still(project, shot, product)
    db.update("shots", shot_id, {"frame": still, "frame_basis": storyboard.basis(project, shot)})
    # make the clip now (local and free) so the old, drifted take is no longer the one used
    render_unit(project, [storyboard.get_shot(shot_id)], "draft")
    return storyboard.shot_public(project, storyboard.get_shot(shot_id))


def clear_takes(shot_id: str) -> dict[str, Any]:
    """Delete takes that are not the chosen one."""
    shot = storyboard.get_shot(shot_id)
    for t in _takes(shot_id):
        if t["id"] != shot["chosen_take"]:
            db.delete("takes", t["id"])
    return storyboard.shot_public(projects.get(shot["project_id"]), storyboard.get_shot(shot_id))


def chosen_take(shot: dict[str, Any]) -> dict[str, Any] | None:
    return (
        db.one("SELECT * FROM takes WHERE id = ?", (shot["chosen_take"],))
        if shot.get("chosen_take")
        else None
    )


def progress(project_id: str, variant_id: str | None = None) -> list[dict[str, Any]]:
    """Per-shot status for the clips stage: queued, waiting, running, checking, done or failed."""
    out = []
    for unit in storyboard.units(project_id, variant_id):
        lead = unit[0]
        if lead["text_card"]:
            continue
        job = (jobs.listing(shot_id=lead["id"], limit=1) or [None])[0]
        take = chosen_take(lead)
        status = "none"
        if job and job["status"] in ("queued", "running"):
            status = job["display"]
        elif job and job["status"] == "failed":
            status = "failed"
        elif take:
            status = "done"
        out.append(
            {
                "shot_id": lead["id"],
                "shot_ids": [s["id"] for s in unit],
                "position": lead["position"] + 1,
                "status": status,
                "stage": job["stage"] if job else "",
                "error": job["error"] if job and job["status"] == "failed" else None,
                "elapsed": _elapsed(job),
                "take": ({**take, "url": store.url(take["media"])} if take else None),
            }
        )
    return out


def _elapsed(job: dict[str, Any] | None) -> float | None:
    from datetime import datetime

    if not job or not job.get("started_at"):
        return None
    start = datetime.fromisoformat(job["started_at"])
    end = (
        datetime.fromisoformat(job["updated_at"])
        if job["status"] not in ("queued", "running")
        else datetime.now(start.tzinfo)
    )
    return round((end - start).total_seconds(), 1)


def path_of(take: dict[str, Any]) -> Path:
    return store.path(take["media"])
