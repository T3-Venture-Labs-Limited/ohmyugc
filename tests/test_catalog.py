import json

import pytest

from oh_my_ugc import config, providers
from oh_my_ugc.catalog import discover, load, mapping
from oh_my_ugc.catalog.schema import REQUIRED, TASKS, Entry
from oh_my_ugc.errors import OmuError

FILE_DUMMY = {
    "first_frame": "F",
    "last_frame": "L",
    "reference_images": ["R1", "R2"],
    "reference_audio": "RA",
    "image": "I",
    "audio": "A",
    "video": "V",
    "prompt": "p",
    "duration": 5,
    "resolution": "720p",
    "aspect_ratio": "9:16",
    "audio_flag": True,
    "text": "hello",
    "voice": "v1",
    "speed": 1.0,
    "seed": 3,
}


def test_every_bundled_entry_validates_and_maps_every_slot():
    entries = load.curated()
    assert len(entries) >= 30 and not load.problems
    for e in entries:
        assert e.task in TASKS
        slots = {
            s: FILE_DUMMY["audio_flag" if s == "audio" and e.task == "image_to_video" else s]
            for s in e.inputs
        }
        mapped = mapping.build_inputs(e, slots)
        for slot in e.inputs:
            spec = e.spec(slot)
            assert spec.param in mapped, f"{e.id}: slot {slot} did not map to {spec.param}"
        for required in REQUIRED[e.task]:
            assert required in e.inputs, f"{e.id} cannot serve {e.task} without {required}"


def test_no_entry_claims_to_be_a_default():
    """Nothing is picked for the user: no catalog entry may carry a default marker."""
    for e in load.curated():
        assert "default_for" not in type(e).model_fields, "default_for must not exist on entries"
    for f in load.BUNDLED.glob("*.json"):
        assert "default_for" not in json.loads(f.read_text()), f"{f.name} still marks a default"


@pytest.mark.parametrize(
    "task", ["image_generation", "image_edit", "image_to_video", "llm", "vision_check", "speech"]
)
def test_connecting_a_key_never_picks_a_model(task, monkeypatch):
    for var in ("OPENROUTER_API_KEY", "REPLICATE_API_TOKEN", "FAL_KEY", "ELEVENLABS_API_KEY", "FISH_API_KEY"):
        monkeypatch.setenv(var, "x" * 12)
    assert load.chosen_for(task) is None


@pytest.mark.parametrize("task", ["image_to_video", "llm"])
def test_unchosen_step_says_to_choose_when_a_provider_is_connected(task, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x" * 12)
    assert "Choose a model" in load.requirement(task) and "Settings" in load.requirement(task)


@pytest.mark.parametrize("task", ["talking_avatar", "lipsync", "background_removal"])
def test_openrouter_alone_states_the_requirement(task, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x" * 12)
    assert load.chosen_for(task) is None
    assert load.requirement(task).startswith("Needs ")


def test_requirement_sentences():
    assert load.requirement("llm") == "Needs OpenRouter."
    assert "Replicate or fal" in load.requirement("talking_avatar")


def test_build_inputs_roles_and_conversions():
    e = load.get("openrouter/seedance-1.5-pro")
    out = mapping.build_inputs(
        e, {"first_frame": "F", "last_frame": "L", "duration": 5.0, "audio": False, "prompt": "go"}
    )
    assert out["frame_images"] == [
        {"type": "image_url", "image_url": {"url": "F"}, "frame_type": "first_frame"},
        {"type": "image_url", "image_url": {"url": "L"}, "frame_type": "last_frame"},
    ]
    assert out["duration"] == 5 and out["generate_audio"] is False
    veo = mapping.build_inputs(load.get("fal/veo-3.1-fast"), {"duration": 8})
    assert veo["duration"] == "8s"
    img = mapping.build_inputs(
        load.get("openrouter/seedream-4.5"), {"reference_images": ["a", "b"], "prompt": "x"}
    )
    assert [r["image_url"]["url"] for r in img["input_references"]] == ["a", "b"] and img["__kind"] == "image"


def test_parameter_missing_from_provider_schema_is_still_sent():
    e = Entry(
        id="x/y",
        provider="replicate",
        model="a/b",
        name="B",
        task="image_to_video",
        inputs={"first_frame": "image", "resolution": "resolution"},
        extra={"hidden_flag": True},
    )
    assert mapping.build_inputs(e, {"first_frame": "F", "resolution": "480p"}) == {
        "hidden_flag": True,
        "image": "F",
        "resolution": "480p",
    }


def test_snap_duration_and_resolution():
    e = load.get("replicate/kling-v2.6")
    assert (
        mapping.snap_duration(e, 3) == 5
        and mapping.snap_duration(e, 6) == 10
        and mapping.snap_duration(e, 99) == 10
    )
    s = load.get("replicate/seedance-1.5-pro")
    assert mapping.pick_resolution(s, "480p") == "480p" and mapping.cheapest_resolution(s) == "480p"
    assert mapping.pick_resolution(s, "1080p") == "1080p"


def test_user_entries_override_bundled_and_bad_files_are_reported(omu_home):
    folder = config.user_catalog_dir()
    base_entry = json.loads((load.BUNDLED / "replicate__seedance-2.5.json").read_text())
    base_entry["name"] = "My Seedance"
    (folder / "mine.json").write_text(json.dumps(base_entry))
    (folder / "broken.json").write_text("{not json")
    (folder / "wrong.json").write_text(json.dumps({"id": "z", "provider": "fal"}))
    entries = {e.id: e for e in load.curated()}
    assert entries["replicate/seedance-2.5"].name == "My Seedance"
    reasons = {p["file"].split("/")[-1]: p["reason"] for p in load.problems}
    assert set(reasons) == {"broken.json", "wrong.json"} and all(reasons.values())


def test_global_and_project_choices(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "x" * 12)
    monkeypatch.setenv("FAL_KEY", "y" * 12)
    assert load.chosen_for("image_to_video") is None
    load.set_global_default("image_to_video", "fal/kling-v2.6-pro")
    assert load.chosen_for("image_to_video").id == "fal/kling-v2.6-pro"
    assert (
        load.chosen_for("image_to_video", {"image_to_video": "replicate/kling-v2.6"}).id
        == "replicate/kling-v2.6"
    )
    load.set_global_default("image_to_video", None)  # clearing the choice leaves nothing chosen
    assert load.chosen_for("image_to_video") is None
    with pytest.raises(OmuError):
        load.set_global_default("image_to_video", "nope/none")


def test_a_choice_on_a_disconnected_provider_does_not_count(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "y" * 12)
    load.set_global_default("image_to_video", "fal/kling-v2.6-pro")
    monkeypatch.delenv("FAL_KEY")
    assert load.chosen_for("image_to_video") is None


# ── discovery ───────────────────────────────────────────────────────────────

OR_VIDEO = {
    "id": "acme/clip-9",
    "name": "Acme: Clip 9",
    "supported_resolutions": ["720p"],
    "supported_aspect_ratios": ["9:16"],
    "supported_durations": [4, 6],
    "supported_frame_images": ["first_frame"],
    "generate_audio": True,
    "seed": True,
    "pricing_skus": {
        "duration_seconds_with_audio": "0.1",
        "duration_seconds_without_audio": "0.08",
        "duration_seconds_with_audio_4k": "0.2",
    },
}
OR_AVATAR = {
    "id": "heygen/avatar-iv",
    "name": "HeyGen: Avatar IV",
    "supported_resolutions": ["720p"],
    "supported_aspect_ratios": ["9:16"],
    "supported_durations": None,
    "supported_frame_images": None,
    "generate_audio": False,
    "pricing_skus": {"duration_seconds": "0.05"},
}
OR_IMAGE = {
    "id": "acme/pic-2",
    "name": "Acme: Pic 2",
    "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
    "supported_parameters": {
        "aspect_ratio": {"type": "enum", "values": ["1:1", "9:16", "auto"]},
        "input_references": {"type": "range", "min": 0, "max": 4},
    },
}


class FakeOR:
    name = "openrouter"

    def __init__(self, fail=False):
        self.fail = fail

    def configured(self):
        return True

    def list_models(self, kind):
        if self.fail:
            raise OmuError("down")
        return {"video": [OR_VIDEO, OR_AVATAR], "image": [OR_IMAGE]}.get(kind, [])


def test_discovery_maps_models_and_marks_unmappable(monkeypatch):
    providers.overrides["openrouter"] = FakeOR()
    try:
        result = discover.refresh("openrouter", force=True)
        assert result["openrouter"] == {"refreshed": True, "count": 3, "error": ""}
        found = {e.id: e for e in load.load_discovered()}
        ok = found["openrouter/clip-9"]
        assert (
            ok.available
            and ok.discovered
            and "first_frame" in ok.inputs
            and ok.limits.durations == [4.0, 6.0]
        )
        assert ok.price and {r.price for r in ok.price.table} == {0.1, 0.08}
        bad = found["openrouter/avatar-iv"]
        assert not bad.available and bad.unavailable_reason == "no first-frame input"
        assert found["openrouter/pic-2"].task == "image_edit" and found[
            "openrouter/pic-2"
        ].limits.aspect_ratios == ["1:1", "9:16"]
        listing = {e["id"]: e for e in load.listing("image_to_video")}
        assert (
            listing["openrouter/clip-9"]["discovered"] is True
            and listing["openrouter/avatar-iv"]["usable"] is False
        )
    finally:
        providers.overrides.pop("openrouter")


def test_failed_listing_keeps_curated_models(monkeypatch):
    providers.overrides["openrouter"] = FakeOR(fail=True)
    try:
        result = discover.refresh("openrouter", force=True)
        assert result["openrouter"]["refreshed"] is False
        assert "temporarily unavailable" in load.discovery_status()["openrouter"]["error"]
        assert any(e.id == "openrouter/seedance-1.5-pro" for e in load.all_entries())
    finally:
        providers.overrides.pop("openrouter")


def test_discovery_is_cached_for_a_day():
    fake = FakeOR()
    providers.overrides["openrouter"] = fake
    try:
        discover.refresh("openrouter", force=True)
        fake.fail = True
        assert (
            discover.refresh("openrouter")["openrouter"]["refreshed"] is False
        )  # served from cache, no error
        assert load.discovery_status()["openrouter"]["error"] == ""
    finally:
        providers.overrides.pop("openrouter")


def test_slot_heuristics_for_fal_and_replicate_schemas():
    props = {
        "prompt": {"type": "string"},
        "image_url": {"type": "string"},
        "end_image_url": {"type": "string"},
        "duration": {"enum": ["5s", "8s"]},
        "generate_audio": {"type": "boolean"},
        "aspect_ratio": {"enum": ["16:9", "9:16"]},
    }
    e = discover.entry_from_fal("fal-ai/acme/i2v", "Acme", "image_to_video", props)
    assert (
        e.available and e.spec("first_frame").param == "image_url" and e.spec("duration").as_ == "seconds_str"
    )
    assert e.limits.durations == [5.0, 8.0] and e.limits.aspect_ratios == ["16:9", "9:16"]
    no_image = discover.entry_from_fal(
        "fal-ai/acme/t2v", "T2V", "image_to_video", {"prompt": {"type": "string"}}
    )
    assert not no_image.available and no_image.unavailable_reason == "no first-frame input"
    model = {
        "owner": "acme",
        "name": "vid",
        "is_official": False,
        "latest_version": {
            "id": "v123",
            "openapi_schema": {
                "components": {
                    "schemas": {
                        "Input": {"properties": {"prompt": {"type": "string"}, "image": {"type": "string"}}}
                    }
                }
            },
        },
    }
    r = discover.entry_from_replicate(model, "image_to_video")
    assert r.available and r.version == "v123" and r.model == "acme/vid"


def test_seedance_on_replicate_has_a_four_second_minimum():
    # Found with a live call on 6 November 2026: Replicate rejects anything shorter than 4 s.
    e = load.get("replicate/seedance-1.5-pro")
    assert mapping.snap_duration(e, 2) == 4 and min(e.limits.durations) == 4


# ── models a provider has stopped offering ──────────────────────────────────


def _route(handler):
    import httpx

    from oh_my_ugc.providers import base

    base.transport = httpx.MockTransport(handler)


def test_availability_marks_models_a_provider_no_longer_lists(monkeypatch):
    import httpx

    from oh_my_ugc.catalog import availability
    from oh_my_ugc.providers import base

    def handler(request):
        url = str(request.url)
        if "openrouter.ai/api/v1" in url:
            return httpx.Response(200, json={"data": [{"id": "bytedance/seedance-2.5"}]})
        if "replicate.com/google/veo-3.1-fast" in url:
            return httpx.Response(404, text="gone")
        return httpx.Response(200, text="ok")

    _route(handler)
    try:
        gone = availability.refresh(force=True)
    finally:
        base.transport = None
    assert gone["replicate/veo-3.1-fast"].startswith("Replicate")
    assert "openrouter/wan-3.0" in gone and "openrouter/seedance-2.5" not in gone
    entry = load.get("replicate/veo-3.1-fast")
    assert not load.usable(entry) and load.mark_availability(entry).unavailable_reason.startswith("Replicate")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "x" * 12)
    load.set_global_default("image_to_video", "replicate/veo-3.1-fast")
    assert load.chosen_for("image_to_video") is None  # a retired choice no longer counts
    from oh_my_ugc import doctor

    check = next(c for c in doctor.checks() if c["name"] == "catalog")
    assert not check["ok"] and "replicate/veo-3.1-fast" in check["detail"]


def test_a_network_error_never_marks_a_model_as_gone():
    import httpx

    from oh_my_ugc.catalog import availability
    from oh_my_ugc.providers import base

    def handler(request):
        raise httpx.ConnectError("offline")

    _route(handler)
    try:
        assert availability.refresh(force=True) == {}
    finally:
        base.transport = None
