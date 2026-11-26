"""Product fidelity: the vision drift check on frames and clips (design D10)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from oh_my_ugc import llm, media, store
from oh_my_ugc.catalog import load
from oh_my_ugc.errors import OmuError

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["product_present", "shape_matches", "colors_match", "text_matches", "issues"],
    "properties": {
        "product_present": {"type": "boolean"},
        "shape_matches": {"type": "boolean"},
        "colors_match": {"type": "boolean"},
        "text_matches": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "text"],
                "properties": {
                    "severity": {"type": "string", "enum": ["major", "minor"]},
                    "text": {"type": "string"},
                },
            },
        },
    },
}


def verdict(result: dict[str, Any]) -> str:
    """passed or flagged, from the yes/no answers and the issues list (never a score)."""
    issues = result.get("issues") or []
    if not result.get("product_present") or not (
        result.get("shape_matches") and result.get("colors_match") and result.get("text_matches")
    ):
        return "flagged"
    return "flagged" if any(i.get("severity") == "major" for i in issues) else "passed"


def available(project: dict[str, Any]) -> bool:
    return llm.available("vision_check", project.get("models"))


def check_frame(project: dict[str, Any], product: dict[str, Any], candidate: Path) -> dict[str, Any]:
    if not available(project):
        return {
            "status": "not_checked",
            "reason": "No product-check model chosen, so this was not compared with your product photo.",
        }
    entry = llm.pick("vision_check", project.get("models"))
    refs = [
        store.path(m)
        for m in (
            [product["primary_photo"]] + [p for p in product["photos"] if p != product["primary_photo"]][:1]
        )
    ]
    system = llm.prompt(
        "vision_check", label=product.get("label_text") or "(none given)", name=product["name"]
    )
    try:
        raw = llm.chat_json(
            entry,
            system,
            f"Reference photos first ({len(refs)}), then the candidate to check.",
            SCHEMA,
            images=[*refs, candidate],
            step="check",
            project_id=project["id"],
            temperature=0.0,
        )
    except OmuError as exc:
        return {"status": "not_checked", "reason": exc.message}
    result = {k: raw.get(k) for k in ("product_present", "shape_matches", "colors_match", "text_matches")}
    result["issues"] = [i for i in (raw.get("issues") or []) if isinstance(i, dict)]
    result["status"] = verdict(result)
    result["model"] = entry.name
    return result


def sample_times(duration: float) -> list[float]:
    fractions = [0.10, 0.30, 0.50, 0.70, 0.90] if duration > 8 else [0.15, 0.50, 0.85]
    return [round(duration * f, 3) for f in fractions]


def check_clip(
    project: dict[str, Any], product: dict[str, Any], video: Path, duration: float | None = None
) -> dict[str, Any]:
    """Sample frames across a clip (15/50/85%, more for long clips) and check each one."""
    duration = duration or media.probe(video).duration
    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(sample_times(duration)):
            image = media.extract_frame(video, t, Path(tmp) / f"s{i}.jpg")
            result = check_frame(project, product, image)
            frames.append({"t": t, **result})
    if all(f["status"] == "not_checked" for f in frames):
        return {
            "status": "not_checked",
            "reason": frames[0].get("reason", ""),
            "frames": frames,
            "failing": [],
        }
    failing = [{"t": f["t"], "issues": f.get("issues", [])} for f in frames if f["status"] == "flagged"]
    return {"status": "flagged" if failing else "passed", "frames": frames, "failing": failing}


def describe(drift: dict[str, Any] | None) -> str:
    """One line for the UI: what is wrong, or that it passed."""
    if not drift:
        return ""
    if drift.get("status") == "passed":
        return "Matches your product photo."
    if drift.get("status") == "not_checked":
        return drift.get("reason", "Not checked.")
    if "failing" in drift:
        first = drift["failing"][0]
        text = "; ".join(i.get("text", "") for i in first.get("issues", [])) or "the product does not match"
        return f"At {first['t']:.1f}s: {text}"
    return (
        "; ".join(i.get("text", "") for i in drift.get("issues", []))
        or "The product does not match your photo."
    )


_ = load
