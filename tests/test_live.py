"""Opt-in live checks against Replicate with your own key: `OMU_LIVE=1 uv run pytest tests/test_live.py`.

- One Seedream 4.5 picture (about $0.04).
- No spend: every curated Replicate price table is compared with what the model's page publishes today,
  and every bundled model is checked against its provider's public pages (retired models are reported).
- A 4-second Seedance 2.5 clip at 480p is a separate opt-in because it costs about $0.40:
  `OMU_LIVE=1 OMU_LIVE_VIDEO=1 uv run pytest tests/test_live.py`.
"""

import os

import httpx
import pytest

from oh_my_ugc import costs, db, media, runner, store
from oh_my_ugc.catalog import availability, load

pytestmark = pytest.mark.skipif(
    os.environ.get("OMU_LIVE") != "1", reason="set OMU_LIVE=1 to spend about $0.04 on Replicate"
)


# Read at import: the autouse fixtures clear provider keys from the environment for every other test.
TOKEN = os.environ.get("REPLICATE_API_TOKEN") or os.environ.get("REPLICATE_API_KEY")


@pytest.fixture
def key(monkeypatch):
    if not TOKEN:
        pytest.skip("no Replicate key in the environment")
    monkeypatch.setenv("REPLICATE_API_TOKEN", TOKEN)
    return TOKEN


def test_one_picture_on_replicate(key):
    model = load.get("replicate/seedream-4.5-generate")
    frame = runner.call(
        model,
        {
            "prompt": "A vertical smartphone photo of a small white serum bottle on a kitchen counter, natural light",
            "aspect_ratio": "9:16",
        },
        step="live-smoke",
        quantities={"images": 1},
    )
    assert store.path(frame.media[0]).stat().st_size > 10_000
    assert [r["step"] for r in db.many("SELECT * FROM ledger")] == ["live-smoke"]


@pytest.mark.skipif(
    os.environ.get("OMU_LIVE_VIDEO") != "1", reason="set OMU_LIVE_VIDEO=1 to spend about $0.40"
)
def test_one_clip_on_replicate(key):
    frame = runner.call(
        load.get("replicate/seedream-4.5-generate"),
        {"prompt": "A vertical photo of a white serum bottle on a kitchen counter", "aspect_ratio": "9:16"},
        step="live-smoke",
        quantities={"images": 1},
    )
    clip = runner.call(
        load.get("replicate/seedance-2.5"),
        {
            "first_frame": frame.path,
            "prompt": "Slow handheld push in. No speech.",
            "duration": 4,
            "resolution": "480p",
            "audio": False,
            "aspect_ratio": "9:16",
        },
        step="live-smoke",
        quantities={"seconds": 4, "resolution": "480p", "audio": False},
    )
    info = media.probe(clip.path)
    assert info.has_video and 3.5 <= info.duration <= 4.6 and min(info.width, info.height) <= 540


def test_curated_replicate_prices_match_the_published_ones():
    checked = 0
    for entry in load.curated():
        if entry.provider != "replicate" or not entry.price or not entry.price.table:
            continue
        page = httpx.get(f"https://replicate.com/{entry.model}", follow_redirects=True, timeout=30)
        published = costs.parse_replicate_page(page.text) if page.status_code == 200 else None
        if published is None:
            continue  # the page has no machine-readable price: nothing to compare
        table = {frozenset(r.when.items()): r.price for r in published.table}
        for row in entry.price.table:
            assert table.get(frozenset(row.when.items())) == pytest.approx(row.price), (
                f"{entry.id}: curated price for {row.when} differs from the published one"
            )
        checked += 1
    assert checked, "no curated Replicate price could be compared"


def test_no_bundled_model_has_been_retired():
    from .conftest import FIXTURE_MODELS

    fixtures = {f.stem.replace("__", "/") for f in FIXTURE_MODELS.glob("*.json")}  # retired on purpose
    gone = {i: why for i, why in availability.refresh(force=True).items() if i not in fixtures}
    assert not gone, "providers no longer offer: " + ", ".join(f"{i} ({why})" for i, why in gone.items())
