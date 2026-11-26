"""Scripts: pasted or written by the user's language model, plus hook variants."""

from __future__ import annotations

from typing import Any

from oh_my_ugc import brands, costs, db, llm, projects
from oh_my_ugc.errors import NotFound, OmuError

WORDS_PER_SECOND = 2.5
FORMAT_NOTES = {
    "talking_head": "talking head: one person talks to camera about the product, holding it up at key moments",
    "problem_solution": "problem and solution: show the frustration, then the product as the fix",
    "unboxing": "unboxing: first impressions while opening and trying the product",
    "demo_voiceover": "demo with voiceover: the product in use while a voice explains",
    "testimonial": "testimonial: a customer story about before and after, honest and specific",
}


def word_count(text: str) -> int:
    return len(text.split())


def target_words(project: dict[str, Any]) -> int:
    return max(8, round(project["target_seconds"] * WORDS_PER_SECOND))


def set_script(project_id: str, text: str) -> dict[str, Any]:
    """Store a pasted script exactly as typed."""
    projects.get(project_id)
    db.update("projects", project_id, {"script": text, "updated_at": db.now()})
    return analysis(projects.get(project_id))


def analysis(project: dict[str, Any]) -> dict[str, Any]:
    brand = (
        db.one("SELECT * FROM brands WHERE id = ?", (project["brand_id"],))
        if project.get("brand_id")
        else None
    )
    text = project["script"]
    return {
        "script": text,
        "words": word_count(text),
        "target_words": target_words(project),
        "seconds": round(word_count(text) / WORDS_PER_SECOND, 1),
        "claim_hits": brands.claim_hits(text, brand),
        "missing_mentions": brands.missing_mentions(text, brand),
    }


def estimate(project_id: str) -> dict[str, Any]:
    project = projects.get(project_id)
    if not llm.available("llm", project.get("models")):
        return {
            "available": False,
            "message": "No language model chosen, so AI writing is off. You can still paste a script. "
            + __import__("oh_my_ugc.catalog.load", fromlist=["x"]).requirement("llm"),
        }
    entry = llm.pick("llm", project.get("models"))
    return {"available": True, "model": entry.name, "total": costs.total([costs.estimate(entry)])}


def _context(project: dict[str, Any]) -> str:
    from oh_my_ugc import products

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
    parts = [brands.block(brand)]
    if product:
        parts.append(f"Product: {product['name']}")
        if product["facts"]:
            parts.append(f"Product facts and benefits: {product['facts']}")
        if product["label_text"]:
            parts.append(f"Exact text on the product label: {product['label_text']}")
    parts.append(f"Platform: {project['platform']}")
    if project["brief"]:
        parts.append(f"Brief from the user: {project['brief']}")
    _ = products
    return "\n".join(parts)


SCRIPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "script"],
    "properties": {"title": {"type": "string"}, "script": {"type": "string"}},
}
HOOKS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hooks"],
    "properties": {"hooks": {"type": "array", "items": {"type": "string"}}},
}


def write(project_id: str, prompt: str = "") -> dict[str, Any]:
    """Have the project's language model write the script. The result replaces the project script."""
    project = projects.get(project_id)
    entry = llm.pick("llm", project.get("models"))
    words = target_words(project)
    system = llm.prompt(
        "script_write",
        words=str(words),
        seconds=str(round(project["target_seconds"])),
        min_words=str(round(words * 0.85)),
        max_words=str(round(words * 1.15)),
        format=FORMAT_NOTES.get(project["format"], project["format"]),
    )
    user = _context(project) + (f"\nExtra direction: {prompt}" if prompt.strip() else "")
    result = llm.chat_json(entry, system, user, SCRIPT_SCHEMA, step="script", project_id=project_id)
    script = " ".join(str(result.get("script", "")).split())
    if not script:
        raise OmuError("The language model returned an empty script. Try again.")
    if not words * 0.7 <= word_count(script) <= words * 1.3:  # one corrective retry
        note = (
            f"That was {word_count(script)} words. Rewrite it to about {words} words, keeping the same ideas."
        )
        retry = llm.chat_json(
            entry,
            system,
            user + f"\n\nPrevious attempt:\n{script}\n\n{note}",
            SCRIPT_SCHEMA,
            step="script",
            project_id=project_id,
        )
        script = " ".join(str(retry.get("script", script)).split())
    db.update("projects", project_id, {"script": script, "updated_at": db.now()})
    return {**analysis(projects.get(project_id)), "title": result.get("title", "")}


# ── hook variants ────────────────────────────────────────────────────────────


def variants(project_id: str) -> list[dict[str, Any]]:
    return db.many("SELECT * FROM variants WHERE project_id = ? ORDER BY created_at, rowid", (project_id,))


def get_variant(variant_id: str) -> dict[str, Any]:
    v = db.one("SELECT * FROM variants WHERE id = ?", (variant_id,))
    if not v:
        raise NotFound("That hook")
    return v


def add_hook(project_id: str, hook: str, name: str = "") -> dict[str, Any]:
    projects.get(project_id)
    hook = " ".join((hook or "").split())
    if not hook:
        raise OmuError("Write the hook's words first.")
    n = len(variants(project_id)) + 1
    vid = db.insert(
        "variants",
        {
            "project_id": project_id,
            "name": name or f"Hook {n}",
            "hook": hook,
            "kept": 1,
            "created_at": db.now(),
        },
    )
    return get_variant(vid)


def update_hook(variant_id: str, values: dict[str, Any]) -> dict[str, Any]:
    get_variant(variant_id)
    row: dict[str, Any] = {}
    if "hook" in values and values["hook"] is not None:
        row["hook"] = " ".join(str(values["hook"]).split())
    if "name" in values and values["name"]:
        row["name"] = str(values["name"])
    if "kept" in values and values["kept"] is not None:
        row["kept"] = 1 if values["kept"] else 0
    db.update("variants", variant_id, row)
    return get_variant(variant_id)


def delete_hook(variant_id: str) -> None:
    get_variant(variant_id)
    db.run("DELETE FROM shots WHERE variant_id = ?", (variant_id,))
    db.delete("variants", variant_id)


def generate_hooks(project_id: str, count: int = 3) -> list[dict[str, Any]]:
    """Ask the language model for alternative opening lines; each is stored as a kept variant."""
    project = projects.get(project_id)
    if not project["script"].strip():
        raise OmuError("Write or paste the script first; hooks are alternative openings for it.")
    if not 1 <= count <= 8:
        raise OmuError("Choose between 1 and 8 hooks.")
    entry = llm.pick("llm", project.get("models"))
    system = llm.prompt("hooks", count=str(count), seconds="3", words="8", body=project["script"])
    result = llm.chat_json(
        entry, system, _context(project), HOOKS_SCHEMA, step="hooks", project_id=project_id
    )
    made = []
    for text in [h for h in result.get("hooks", []) if str(h).strip()][:count]:
        made.append(add_hook(project_id, str(text)))
    if not made:
        raise OmuError("The language model returned no hooks. Try again.")
    return made


# ── jobs ─────────────────────────────────────────────────────────────────────

from oh_my_ugc import jobs  # noqa: E402


@jobs.register("write_script")
def _write_job(job: dict[str, Any]) -> dict[str, Any]:
    p = job["payload"]
    return write(p["project_id"], p.get("prompt", ""))


@jobs.register("hooks")
def _hooks_job(job: dict[str, Any]) -> dict[str, Any]:
    p = job["payload"]
    return {"hooks": generate_hooks(p["project_id"], int(p.get("count", 3)))}


def start_write(project_id: str, prompt: str = "") -> str:
    project = projects.get(project_id)
    llm.pick("llm", project.get("models"))  # fail now, with a plain message, if no language model is chosen
    return jobs.enqueue(
        "write_script", project_id=project_id, payload={"project_id": project_id, "prompt": prompt}
    )


def start_hooks(project_id: str, count: int = 3) -> str:
    project = projects.get(project_id)
    llm.pick("llm", project.get("models"))
    if not project["script"].strip():
        raise OmuError("Write or paste the script first; hooks are alternative openings for it.")
    return jobs.enqueue("hooks", project_id=project_id, payload={"project_id": project_id, "count": count})
