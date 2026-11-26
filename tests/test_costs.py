import json
import threading
from pathlib import Path

import pytest

from oh_my_ugc import costs, db, store
from oh_my_ugc.catalog import load
from oh_my_ugc.errors import BudgetExceeded

FIX = Path(__file__).parent / "fixtures"


def test_replicate_page_parser_reads_tiers():
    price = costs.parse_replicate_page((FIX / "replicate_seedance_page.html").read_text())
    assert price and price.unit == "second" and price.source == "page"
    table = {(r.when.get("resolution"), r.when.get("audio")): r.price for r in price.table}
    assert (
        table[("480p", False)] == 0.013 and table[("720p", True)] == 0.052 and table[("1080p", True)] == 0.12
    )


def test_resolution_and_audio_change_the_price():
    e = load.get("replicate/seedance-1.5-pro")
    low = costs.estimate(e, seconds=5, resolution="480p", audio=False)
    high = costs.estimate(e, seconds=5, resolution="720p", audio=True)
    assert low.amount == pytest.approx(0.065) and high.amount == pytest.approx(0.26)


def test_unit_formulas():
    assert costs.estimate(load.get("replicate/seedream-4.5"), images=3).amount == pytest.approx(0.12)
    assert costs.estimate(load.get("fal/elevenlabs-v3"), chars=450).amount == pytest.approx(0.045)
    assert costs.estimate(load.get("fal/sync-lipsync-v2"), seconds=30).amount == pytest.approx(1.5)
    assert costs.estimate(load.get("fal/rembg")).amount == 0
    assert costs.estimate(load.get("replicate/background-remover")).amount == pytest.approx(0.000675)
    tok = costs.estimate(
        load.get("openrouter/seedance-1.5-pro"), seconds=5, resolution="480p", aspect="9:16", audio=False
    )
    assert tok.amount is not None and 0.05 < tok.amount < 0.07  # about $0.012 a second silent at 480p


def test_unknown_price_makes_the_total_partial(monkeypatch):
    monkeypatch.setattr(costs, "lookup_price", lambda entry: None)
    e = load.get("replicate/omni-human")
    est = costs.estimate(e, seconds=5)
    assert est.amount is None and est.note == "price unknown"
    t = costs.total([costs.Estimate(1.0), est])
    assert t["partial"] and t["amount"] == 1.0 and t["label"] == "$1.00 + unknown"


def test_five_shot_storyboard_estimate():
    e = load.get("replicate/seedance-1.5-pro")
    parts = [costs.estimate(e, seconds=5, resolution="480p", audio=False) for _ in range(5)]
    assert costs.total(parts)["amount"] == pytest.approx(0.325)
    assert not costs.total(parts)["partial"]


def test_fal_llms_parser():
    price = costs.parse_fal_llms("## Pricing\nYour request will cost **$0.08** per image. For $1...\n## API")
    assert price is not None and price.unit == "image" and price.default == 0.08


def make_project(budget=None):
    return db.insert(
        "projects", {"name": "p", "budget": budget, "created_at": db.now(), "updated_at": db.now()}
    )


def ledger(pid, amount, status="ok"):
    e = load.get("fal/rembg")
    costs.record(
        project_id=pid,
        job_id=None,
        step="t",
        entry=e,
        units="{}",
        estimated=amount,
        actual=amount,
        status=status,
    )


def test_ledger_spend_breakdown_and_failed_calls_cost_nothing():
    pid = make_project()
    e = load.get("replicate/seedream-4.5")
    costs.record(project_id=pid, job_id=None, step="frames", entry=e, units="{}", estimated=0.04, actual=0.04)
    costs.record(
        project_id=pid,
        job_id=None,
        step="frames",
        entry=e,
        units="{}",
        estimated=0.04,
        actual=0.0,
        status="failed",
    )
    costs.record(
        project_id=pid,
        job_id=None,
        step="clips",
        entry=load.get("fal/kling-v2.6-pro"),
        units="{}",
        estimated=0.35,
        actual=None,
    )
    s = costs.spend(pid)
    assert s["total"] == pytest.approx(0.39) and s["by_step"] == {"frames": 0.04, "clips": 0.35}
    assert s["by_provider"]["fal"] == pytest.approx(0.35) and s["includes_estimates"] is True


def test_over_budget_message_has_the_numbers():
    pid = make_project(budget=5.0)
    ledger(pid, 4.20)
    with pytest.raises(BudgetExceeded) as exc:
        costs.reserve(pid, 3.10)
    assert "$3.10" in exc.value.message and "$0.80" in exc.value.message and "$5.00" in exc.value.message


def test_parallel_reservations_cannot_jointly_exceed_the_cap():
    pid = make_project(budget=1.0)
    outcomes = []

    def go():
        try:
            outcomes.append(costs.reserve(pid, 0.4))
        except BudgetExceeded:
            outcomes.append(None)

    threads = [threading.Thread(target=go) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(1 for o in outcomes if o) == 2  # 2 x 0.4 fits in 1.0, a third would not


def test_released_reservations_free_the_budget():
    pid = make_project(budget=1.0)
    r = costs.reserve(pid, 0.9)
    with pytest.raises(BudgetExceeded):
        costs.reserve(pid, 0.5)
    costs.release(r)
    assert costs.reserve(pid, 0.5)
    assert costs.budget_status(pid)["remaining"] == pytest.approx(0.5)


def test_no_budget_means_no_limit():
    pid = make_project()
    assert costs.reserve(pid, 999) is None


def test_cache_key_follows_file_content_and_take(tmp_path):
    e = load.get("replicate/background-remover")
    f = tmp_path / "a.png"
    f.write_bytes(b"one")
    k1 = costs.cache_key(e, {"image": f})
    assert costs.cache_key(e, {"image": f}) == k1
    f.write_bytes(b"two")
    assert costs.cache_key(e, {"image": f}) != k1
    assert costs.cache_key(e, {"image": f}, take=1) != costs.cache_key(e, {"image": f})


def test_cache_roundtrip_requires_the_file_to_exist():
    m = store.put_bytes(b"hello", "png")
    costs.cache_put("k", [m], {"a": 1}, 0.04)
    cached = costs.cache_get("k")
    assert cached is not None and cached["outputs"] == [m]
    store.path(m).unlink()
    assert costs.cache_get("k") is None


def test_a_page_with_null_billing_config_has_no_price():
    assert costs.parse_replicate_page('<script>{"billingConfig": null}</script>') is None
    assert costs.parse_replicate_page('{"billingConfig": []}') is None


def test_boolean_audio_criteria_on_newer_replicate_pages():
    def tier(value, price):
        return {
            "criteria": [{"title": "with audio", "type": "equals", "subtype": "boolean", "value": value}],
            "prices": [{"type": "per-unit", "metric": "video_output_duration_seconds", "price": price}],
        }

    page = (
        "<script>"
        + json.dumps({"billingConfig": {"current_tiers": [tier(False, "$0.07"), tier(True, "$0.14")]}})
        + "</script>"
    )
    published = costs.parse_replicate_page(page)
    assert published is not None
    assert [(r.when, r.price) for r in published.table] == [({"audio": False}, 0.07), ({"audio": True}, 0.14)]
