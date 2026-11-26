"""Prices, estimates, the ledger, budgets and the output cache (design D4, D6, D7)."""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from oh_my_ugc import db, store
from oh_my_ugc.catalog.mapping import file_paths
from oh_my_ugc.catalog.schema import Entry, Price, PriceRow
from oh_my_ugc.errors import BudgetExceeded

PRICE_TTL = 24 * 3600


# ── price lookup ─────────────────────────────────────────────────────────────


def parse_replicate_page(page: str) -> Price | None:
    """Read ``billingConfig.current_tiers`` from a Replicate model page (the page embeds it as JSON)."""
    text = html.unescape(page)
    start = text.find('"billingConfig":')
    if start < 0:
        return None
    try:
        config, _ = json.JSONDecoder().raw_decode(text[start + len('"billingConfig":') :].lstrip())
    except ValueError:
        return None
    if not isinstance(config, dict):  # a page can carry "billingConfig": null
        return None
    rows: list[PriceRow] = []
    unit = "run"
    for tier in config.get("current_tiers", []):
        price = next((p for p in tier.get("prices", []) if p.get("type") == "per-unit"), None)
        if not price:
            continue
        try:
            amount = float(str(price["price"]).lstrip("$"))
        except (KeyError, ValueError):
            continue
        metric = price.get("metric", "")
        unit = (
            "second"
            if "duration_seconds" in metric
            else "image"
            if "image" in metric
            else "token"
            if "token" in metric
            else "run"
        )
        when: dict[str, Any] = {}
        for crit in tier.get("criteria", []):
            if isinstance(crit.get("value"), bool) and "audio" in str(crit.get("title", "")).lower():
                when["audio"] = crit["value"]  # newer pages: title "with audio", value true or false
                continue
            value = str(crit.get("value", ""))
            if value in ("with_audio", "without_audio"):
                when["audio"] = value == "with_audio"
            elif re.fullmatch(r"\d{3,4}p|\d[Kk]", value):
                when["resolution"] = value
            elif value in ("video_in", "non_video_in"):
                when["video_input"] = value == "video_in"
        if when.get("video_input"):
            continue  # video-to-video pricing; ads use image inputs
        when.pop("video_input", None)
        rows.append(PriceRow(when=when, price=amount))
    if not rows:
        return None
    default = next((r.price for r in rows if not r.when), max(r.price for r in rows))
    return Price(unit=unit, table=rows, default=default, source="page")  # type: ignore[arg-type]


def parse_fal_llms(text: str) -> Price | None:
    """Best-effort read of the ``## Pricing`` section of a fal endpoint's llms.txt."""
    section = text.split("## Pricing", 1)[-1].split("##", 1)[0]
    match = re.search(
        r"\$\s?([0-9]*\.?[0-9]+)\**\s*(?:per|/)\s*(?:compute\s+)?(second|image|minute|1,?000 characters|request)",
        section,
        re.I,
    )
    if not match:
        return None
    unit = {"second": "second", "image": "image", "minute": "minute", "request": "run"}.get(
        match.group(2).lower(), "1k_chars"
    )
    return Price(unit=unit, default=float(match.group(1)), source="metadata")  # type: ignore[arg-type]


def _cached_price(key: str) -> Price | None | bool:
    row = db.one("SELECT value, fetched_at FROM price_cache WHERE key = ?", (key,))
    if row and time.time() - row["fetched_at"] < PRICE_TTL:
        data = json.loads(row["value"])
        return Price.model_validate(data) if data else None
    return False


def _store_price(key: str, price: Price | None) -> None:
    db.run(
        "INSERT INTO price_cache (key, value, fetched_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, fetched_at = excluded.fetched_at",
        (key, json.dumps(price.model_dump() if price else None), time.time()),
    )


def lookup_price(entry: Entry) -> Price | None:
    """Curated price, else the provider's published price (cached 24 hours), else unknown."""
    if entry.price is not None:
        return entry.price
    key = f"{entry.provider}:{entry.model}"
    cached = _cached_price(key)
    if cached is not False:
        return cached  # type: ignore[return-value]
    price = None
    try:
        if entry.provider == "replicate":
            from oh_my_ugc.providers import base

            with httpx.Client(timeout=30, transport=base.transport, follow_redirects=True) as client:
                response = client.get(f"https://replicate.com/{entry.model}")
            price = parse_replicate_page(response.text) if response.status_code == 200 else None
        elif entry.provider == "fal":
            from oh_my_ugc.providers import base

            with httpx.Client(timeout=30, transport=base.transport, follow_redirects=True) as client:
                response = client.get(f"https://fal.ai/models/{entry.model}/llms.txt")
            price = parse_fal_llms(response.text) if response.status_code == 200 else None
    except httpx.HTTPError:
        price = None
    _store_price(key, price)
    return price


# ── estimates ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Estimate:
    amount: float | None  # None when the price is unknown
    note: str = ""

    @property
    def known(self) -> bool:
        return self.amount is not None


def pixels(resolution: str | None, aspect: str | None) -> int:
    digits = "".join(c for c in (resolution or "720p") if c.isdigit())
    short = int(digits or 720)
    try:
        w, h = (float(x) for x in (aspect or "9:16").split(":"))
        long = short * max(w, h) / min(w, h)
    except ValueError:
        long = short * 16 / 9
    return int(short * long)


def _row_for(price: Price, criteria: dict[str, Any]) -> float | None:
    best: tuple[int, float] | None = None
    for row in price.table:
        if all(criteria.get(k) == v for k, v in row.when.items()) and (
            best is None or len(row.when) > best[0]
        ):
            best = (len(row.when), row.price)
    return best[1] if best else price.default


def estimate(
    entry: Entry,
    *,
    seconds: float = 0,
    images: int = 1,
    chars: int = 0,
    resolution: str | None = None,
    audio: bool | None = None,
    aspect: str | None = None,
    **criteria: Any,
) -> Estimate:
    price = lookup_price(entry)
    if price is None:
        return Estimate(None, "price unknown")
    if price.unit == "free":
        return Estimate(0.0)
    crit = {"resolution": resolution, "audio": audio, **criteria}
    unit_price = _row_for(price, {k: v for k, v in crit.items() if v is not None})
    if unit_price is None:
        return Estimate(None, "price unknown")
    if price.unit == "second":
        amount = unit_price * seconds
    elif price.unit == "minute":
        amount = unit_price * seconds / 60
    elif price.unit == "image":
        amount = unit_price * images
    elif price.unit == "1k_chars":
        amount = unit_price * chars / 1000
    elif price.unit == "token":
        amount = unit_price * pixels(resolution, aspect) * price.token_fps * seconds / 1024
    elif price.unit == "predict_second":
        amount = unit_price * price.typical_seconds
    else:
        amount = unit_price
    return Estimate(round(amount, 6), price.note)


def total(estimates: list[Estimate]) -> dict[str, Any]:
    """Sum estimates; the total is labelled partial when any price is unknown."""
    amount = round(sum(e.amount for e in estimates if e.amount is not None), 4)
    unknown = sum(1 for e in estimates if e.amount is None)
    return {
        "amount": amount,
        "partial": unknown > 0,
        "unknown": unknown,
        "label": f"${amount:.2f}" + (" + unknown" if unknown else ""),
    }


def actual_cost(entry: Entry, meta: dict[str, Any], quantities: dict[str, Any]) -> tuple[float | None, bool]:
    """(cost, computed). Billed amounts come from the provider; Replicate timings are priced here."""
    price = lookup_price(entry)
    if price and price.unit == "predict_second" and meta.get("predict_time") is not None:
        unit = _row_for(price, {}) or 0
        return round(unit * float(meta["predict_time"]), 6), True
    return None, False


# ── cache ────────────────────────────────────────────────────────────────────


def canonical(obj: Any) -> Any:
    """A JSON-safe copy where each file is replaced by its content hash."""
    if isinstance(obj, Path):
        return {"file": store.hash_file(obj)}
    if isinstance(obj, dict):
        return {k: canonical(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [canonical(v) for v in obj]
    return obj


def cache_key(entry: Entry, inputs: dict[str, Any], take: int = 0) -> str:
    payload = {
        "provider": entry.provider,
        "model": entry.model,
        "version": entry.version,
        "inputs": canonical(inputs),
        "take": take,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def cache_get(key: str) -> dict | None:
    row = db.one("SELECT * FROM cache WHERE key = ?", (key,))
    if not row:
        return None
    outputs = row["outputs"] if isinstance(row["outputs"], list) else json.loads(row["outputs"])
    if not all(store.maybe_path(o) for o in outputs):
        return None
    return {
        "outputs": outputs,
        "meta": json.loads(row["meta"]) if isinstance(row["meta"], str) else row["meta"],
        "cost": row["cost"],
    }


def cache_put(key: str, outputs: list[str], meta: dict, cost: float) -> None:
    db.run(
        "INSERT INTO cache (key, outputs, meta, cost, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET outputs = excluded.outputs, meta = excluded.meta, cost = excluded.cost",
        (key, json.dumps(outputs), json.dumps(meta), cost, db.now()),
    )


def input_files(inputs: dict[str, Any]) -> list[Path]:
    return file_paths(inputs)


# ── ledger ───────────────────────────────────────────────────────────────────


def record(
    *,
    project_id: str | None,
    job_id: str | None,
    step: str,
    entry: Entry,
    units: str,
    estimated: float,
    actual: float | None,
    computed: bool = False,
    status: str = "ok",
) -> None:
    db.insert(
        "ledger",
        {
            "ts": db.now(),
            "project_id": project_id,
            "job_id": job_id,
            "step": step,
            "provider": entry.provider,
            "model": entry.model,
            "units": units,
            "estimated": estimated,
            "actual": actual,
            "computed": computed,
            "status": status,
        },
    )


def spend(project_id: str | None = None) -> dict[str, Any]:
    where, params = ("WHERE project_id = ?", (project_id,)) if project_id else ("", ())
    rows = db.many(f"SELECT * FROM ledger {where} ORDER BY id", params)
    by_step: dict[str, float] = {}
    by_provider: dict[str, float] = {}
    amount = 0.0
    estimated_only = False
    for r in rows:
        cost = r["actual"] if r["actual"] is not None else r["estimated"]
        if r["status"] != "ok":
            cost = r["actual"] or 0.0
        if r["actual"] is None and r["status"] == "ok":
            estimated_only = True
        amount += cost
        by_step[r["step"]] = round(by_step.get(r["step"], 0) + cost, 4)
        by_provider[r["provider"]] = round(by_provider.get(r["provider"], 0) + cost, 4)
    return {
        "total": round(amount, 4),
        "by_step": by_step,
        "by_provider": by_provider,
        "calls": len(rows),
        "includes_estimates": estimated_only,
    }


def recent_ledger(limit: int = 100, project_id: str | None = None) -> list[dict]:
    where, params = ("WHERE project_id = ?", (project_id,)) if project_id else ("", ())
    return db.many(f"SELECT * FROM ledger {where} ORDER BY id DESC LIMIT {int(limit)}", params)


# ── budget (design D7) ───────────────────────────────────────────────────────


def reserve(project_id: str | None, amount: float) -> str | None:
    """Hold ``amount`` against the project's budget in one transaction, or raise BudgetExceeded."""
    if not project_id:
        return None
    with db.tx() as conn:
        project = conn.execute("SELECT budget FROM projects WHERE id = ?", (project_id,)).fetchone()
        budget = project["budget"] if project else None
        if budget is None:
            return None
        spent = _spent(conn, project_id)
        held = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM reservations WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        remaining = round(budget - spent - held, 4)
        if amount > remaining + 1e-9:
            raise BudgetExceeded(
                f"This needs ${amount:.2f} but only ${max(remaining, 0):.2f} remains of the ${budget:.2f} budget. Raise the budget in the project settings to continue.",
                status=402,
            )
        rid = uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO reservations (id, project_id, amount, created_at) VALUES (?, ?, ?, ?)",
            (rid, project_id, amount, db.now()),
        )
        return rid


def _spent(conn, project_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN status = 'ok' THEN COALESCE(actual, estimated) ELSE COALESCE(actual, 0) END), 0) FROM ledger WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    return float(row[0])


def release(reservation_id: str | None) -> None:
    if reservation_id:
        db.run("DELETE FROM reservations WHERE id = ?", (reservation_id,))


def budget_status(project_id: str) -> dict[str, Any]:
    project = db.one("SELECT budget FROM projects WHERE id = ?", (project_id,))
    spent = spend(project_id)["total"]
    held = db.one(
        "SELECT COALESCE(SUM(amount), 0) AS v FROM reservations WHERE project_id = ?", (project_id,)
    )["v"]  # type: ignore[index]
    budget = project["budget"] if project else None
    return {
        "budget": budget,
        "spent": spent,
        "held": round(held, 4),
        "remaining": None if budget is None else round(budget - spent - held, 4),
    }
