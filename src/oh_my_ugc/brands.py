"""Brands: the context the AI needs to write for a company."""

from __future__ import annotations

import re
from typing import Any

from oh_my_ugc import db, store
from oh_my_ugc.errors import NotFound, OmuError, check_lengths

FIELDS = (
    "name",
    "description",
    "voice_tone",
    "audience",
    "must_mention",
    "avoid_claims",
    "offer",
    "cta",
    "website",
)
LIST_FIELDS = ("must_mention", "avoid_claims")  # one point per line


def public(brand: dict[str, Any]) -> dict[str, Any]:
    out = dict(brand)
    out["logo_url"] = store.url(brand.get("logo"))
    out["must_mention_list"] = lines(brand.get("must_mention", ""))
    out["avoid_claims_list"] = lines(brand.get("avoid_claims", ""))
    return out


def lines(text: str) -> list[str]:
    return [p.strip(" -•\t") for p in re.split(r"[\n;]", text or "") if p.strip(" -•\t")]


def get(brand_id: str) -> dict[str, Any]:
    brand = db.one("SELECT * FROM brands WHERE id = ?", (brand_id,))
    if not brand:
        raise NotFound("That brand")
    return brand


def listing() -> list[dict[str, Any]]:
    out = []
    for b in db.many("SELECT * FROM brands ORDER BY created_at DESC"):
        out.append(
            {
                **public(b),
                "products": db.one("SELECT COUNT(*) AS n FROM products WHERE brand_id = ?", (b["id"],))["n"],
            }
        )  # type: ignore[index]
    return out


def create(values: dict[str, Any]) -> dict[str, Any]:
    check_lengths(values)
    name = (values.get("name") or "").strip()
    if not name:
        raise OmuError("Give the brand a name.")
    row = {f: str(values.get(f) or "").strip() for f in FIELDS}
    row["name"] = name
    brand_id = db.insert("brands", {**row, "created_at": db.now()})
    return public(get(brand_id))


def update(brand_id: str, values: dict[str, Any]) -> dict[str, Any]:
    get(brand_id)
    check_lengths(values)
    row = {f: str(values[f]).strip() for f in FIELDS if f in values and values[f] is not None}
    if "name" in row and not row["name"]:
        raise OmuError("Give the brand a name.")
    db.update("brands", brand_id, row)
    return public(get(brand_id))


def set_logo(brand_id: str, filename: str, data: bytes) -> dict[str, Any]:
    from oh_my_ugc import products

    get(brand_id)
    media = products.validate_image(filename, data)
    db.update("brands", brand_id, {"logo": media})
    return public(get(brand_id))


def delete(brand_id: str) -> None:
    get(brand_id)
    db.run("UPDATE projects SET brand_id = NULL WHERE brand_id = ?", (brand_id,))
    db.delete("brands", brand_id)


def block(brand: dict[str, Any] | None) -> str:
    """The brand as a labelled block for prompts."""
    if not brand:
        return "(no brand information given)"
    parts = [f"Brand: {brand['name']}"]
    labels = [
        ("description", "About"),
        ("voice_tone", "Voice and tone"),
        ("audience", "Target audience"),
        ("offer", "Current offer"),
        ("cta", "Call to action"),
        ("website", "Website"),
    ]
    parts += [f"{label}: {brand[k]}" for k, label in labels if brand.get(k)]
    if lines(brand.get("must_mention", "")):
        parts.append("Must mention: " + "; ".join(lines(brand["must_mention"])))
    if lines(brand.get("avoid_claims", "")):
        parts.append("Never claim or imply: " + "; ".join(lines(brand["avoid_claims"])))
    return "\n".join(parts)


def claim_hits(text: str, brand: dict[str, Any] | None) -> list[str]:
    """Phrases from 'claims to avoid' that appear in ``text`` (case-insensitive)."""
    if not brand:
        return []
    lowered = (text or "").lower()
    return [c for c in lines(brand.get("avoid_claims", "")) if c.lower() in lowered]


def missing_mentions(text: str, brand: dict[str, Any] | None) -> list[str]:
    if not brand:
        return []
    lowered = (text or "").lower()
    return [m for m in lines(brand.get("must_mention", "")) if not _mentioned(m, lowered)]


def _mentioned(point: str, lowered_text: str) -> bool:
    words = [w for w in re.findall(r"[a-z0-9']+", point.lower()) if len(w) > 3]
    if not words:
        return point.lower() in lowered_text
    return sum(1 for w in words if w in lowered_text) >= max(1, round(len(words) * 0.6))
