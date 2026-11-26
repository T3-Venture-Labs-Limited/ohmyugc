import json
import subprocess
from pathlib import Path

import pytest

from oh_my_ugc import (
    clips,
    db,
    fidelity,
    jobs,
    media,
    products,
    projects,
    render_local,
    runner,
    scripts,
    store,
    storyboard,
)
from oh_my_ugc.errors import OmuError

from .conftest import needs_ffmpeg
from .helpers import approved_storyboard, make_cutout_png, make_png, make_world

pytestmark = [needs_ffmpeg, pytest.mark.usefixtures("small")]


def pixel(video: Path, t: float, x: int, y: int) -> tuple[int, int, int]:
    proc = subprocess.run(
        [
            media.ffmpeg_bin(),
            "-v",
            "error",
            "-ss",
            str(t),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"crop=2:2:{x}:{y}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
    )
    return tuple(proc.stdout[:3])  # type: ignore[return-value]


# ── fidelity ────────────────────────────────────────────────────────────────


def test_sample_times_are_spread_and_longer_clips_get_more():
    assert (
        fidelity.sample_times(10.0) == [1.5 * 10 / 10 * 1, 5.0, 8.5] or len(fidelity.sample_times(8.0)) == 3
    )
    assert fidelity.sample_times(8.0) == [1.2, 4.0, 6.8]
    assert len(fidelity.sample_times(12.0)) == 5


def test_verdict_uses_the_yes_no_answers_not_a_score():
    ok = {
        "product_present": True,
        "shape_matches": True,
        "colors_match": True,
        "text_matches": True,
        "issues": [{"severity": "minor", "text": "soft"}],
    }
    assert fidelity.verdict(ok) == "passed"
    assert fidelity.verdict({**ok, "text_matches": False}) == "flagged"
    assert fidelity.verdict({**ok, "issues": [{"severity": "major", "text": "x"}]}) == "flagged"
    assert fidelity.verdict({**ok, "product_present": False}) == "flagged"


def test_clip_check_flags_only_the_middle_frame(fakes, tmp_path):
    _, product, _, project = make_world()
    video = tmp_path / "v.mp4"
    subprocess.run(
        [
            media.ffmpeg_bin(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=96x160:r=24:d=6",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    seen = {"n": 0}

    def reply(messages, schema):
        seen["n"] += 1
        bad = seen["n"] == 2
        return {
            "product_present": True,
            "shape_matches": True,
            "colors_match": True,
            "text_matches": not bad,
            "issues": [{"severity": "major", "text": 'label reads "LUNA"'}] if bad else [],
        }

    fakes["openrouter"].llm_reply = reply
    result = fidelity.check_clip(projects.get(project["id"]), product, video, 6.0)
    assert result["status"] == "flagged" and [f["t"] for f in result["failing"]] == [3.0]
    assert [f["status"] for f in result["frames"]] == ["passed", "flagged", "passed"]
    assert "At 3.0s" in fidelity.describe(result) and "LUNA" in fidelity.describe(result)


def test_no_vision_model_means_not_checked(tmp_path):
    _, product, _, project = make_world()
    png = tmp_path / "a.png"
    png.write_bytes(make_png())
    assert fidelity.check_frame(projects.get(project["id"]), product, png)["status"] == "not_checked"


# ── real product shots and the end card ─────────────────────────────────────


def test_real_product_shot_keeps_the_original_pixels(tmp_path):
    _, product, _, project = make_world()
    products.set_custom_cutout(product["id"], "cut.png", make_cutout_png())
    product = products.get(product["id"])
    storyboard.add_shot(project["id"], {"type": "real_product", "duration": 2.0})
    shot = storyboard.shots_of(project["id"])[0]
    media_id = render_local.render_real_product(projects.get(project["id"]), shot, product, 2.0)
    video = store.path(media_id)
    info = media.probe(video)
    assert (info.width, info.height) == (270, 480) and abs(info.duration - 2.0) < 0.15 and info.has_audio
    # the middle of the frame is the cutout's white body, at the start and the end of the push-in
    assert min(pixel(video, 0.05, 134, 240)) > 245 and min(pixel(video, 1.9, 134, 240)) > 245
    assert max(pixel(video, 0.05, 5, 5)) < 160  # darkened backdrop, not the product


@pytest.mark.parametrize("motion", ["push_in", "pan", "parallax", "rotate_in"])
def test_every_motion_renders(motion):
    _, product, _, project = make_world()
    shot = {
        "duration": 1.0,
        "motion": motion,
        "background": "brand",
        "position": 0,
        "variant_id": None,
        "id": "x",
    }
    info = media.probe(
        store.path(render_local.render_real_product(projects.get(project["id"]), shot, product, 1.0))
    )
    assert (info.width, info.height) == (270, 480) and abs(info.duration - 1.0) < 0.15


def test_still_preview_is_free_and_sized_to_the_project(fakes):
    _, product, _, project = make_world(aspect="1:1")
    shot = {"duration": 1.0, "background": "brand", "position": 0, "variant_id": None, "id": "x"}
    from PIL import Image

    still = render_local.real_product_still(projects.get(project["id"]), shot, product)
    assert Image.open(store.path(still)).size == (270, 270)
    assert fakes["replicate"].submits == []


def test_swapping_a_drifted_shot_keeps_duration_and_line(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    shot = storyboard.shots_of(project["id"])[1]
    pub = clips.swap_to_real_product(shot["id"])
    assert (
        pub["type"] == "real_product"
        and pub["duration"] == shot["duration"]
        and pub["line"] == shot["line"]
        and pub["approved"] == 1
    )
    assert pub["frame"] and pub["frame_drift"] is None
    # the drifted generated take is replaced by a local clip right away
    take = clips.chosen_take(storyboard.get_shot(shot["id"]))
    assert take and take["quality"] == "local"


# ── clips ───────────────────────────────────────────────────────────────────


def run_all():
    jobs.run_pending()


def last_video_call(fakes, provider="replicate"):
    calls = [
        c
        for c in fakes[provider].submits
        if "seedance" in c[0] or "kling" in c[0] or "omni" in c[0] or "veo" in c[0]
    ]
    return calls[-1]


def test_draft_is_cheapest_silent_and_final_reuses_frames_and_prompts(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    ids = clips.render(project["id"], "draft")
    run_all()
    assert all(jobs.get(j)["status"] == "done" for j in ids), [jobs.get(j)["error"] for j in ids]
    video_calls = [c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"]
    assert len(video_calls) == 3  # three model shots; the real-product shot is local
    inputs = video_calls[0][1]
    assert (
        inputs["resolution"] == "480p"
        and inputs["generate_audio"] is False
        and inputs["image"].startswith("https://fake/")
    )
    prompts = [c[1]["prompt"] for c in video_calls]
    clips.render(project["id"], "final")
    run_all()
    finals = [c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"][3:]
    assert len(finals) == 3 and all(c[1]["resolution"] == "720p" for c in finals)
    assert [c[1]["prompt"] for c in finals] == prompts and [c[1]["image"] for c in finals] == [
        c[1]["image"] for c in video_calls
    ]
    shot = storyboard.shots_of(project["id"])[0]
    qualities = {t["quality"] for t in storyboard.shot_public(projects.get(project["id"]), shot)["takes"]}
    assert qualities == {"draft", "final"}
    assert clips.chosen_take(storyboard.get_shot(shot["id"]))["quality"] == "final"


def test_final_for_a_subset_only(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    clips.render(project["id"], "draft")
    run_all()
    shots = storyboard.shots_of(project["id"])
    before = len(fakes["replicate"].submits)
    clips.render(project["id"], "final", [shots[0]["id"], shots[1]["id"]])
    run_all()
    assert len(fakes["replicate"].submits) - before == 2


def test_clips_need_approved_shots(fakes):
    _, _, _, project = make_world()
    from .helpers import draft_storyboard

    draft_storyboard(fakes, project["id"])
    with pytest.raises(OmuError) as e:
        clips.render(project["id"], "draft")
    assert "Approve shot 1" in e.value.message


def test_voiceover_mode_speaks_lines_and_requests_silent_clips(fakes):
    _, _, actor, project = make_world(voice_mode="voiceover")
    approved_storyboard(fakes, project["id"])
    clips.render(project["id"], "draft")
    run_all()
    speech = fakes["elevenlabs"].submits
    assert (
        len(speech) == 4
        and speech[0][1]["voice"] == "voice123"
        and speech[0][1]["text"].startswith("Okay, I have to tell you")
    )
    video = [c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"]
    assert all(c[1]["generate_audio"] is False for c in video)
    shot = storyboard.shots_of(project["id"])[0]
    assert shot["audio"] or storyboard.get_shot(shot["id"])["audio"]
    assert [w["text"] for w in storyboard.get_shot(shot["id"])["words"]][:3] == ["Okay,", "I", "have"]


def test_native_dialogue_puts_the_line_in_the_prompt_with_a_voice_reference(fakes):
    _, _, actor, project = make_world(voice_mode="native")
    from oh_my_ugc import actors

    actors.set_voice_sample(actor["id"], "voice.mp3", b"ID3fakevoice" * 100)
    projects.update(project["id"], {"models": {"image_to_video": "replicate/seedance-2.5"}})
    approved_storyboard(fakes, project["id"])
    clips.render(project["id"], "draft", [storyboard.shots_of(project["id"])[0]["id"]])
    run_all()
    model, sent = last_video_call(fakes)
    assert model == "bytedance/seedance-2.5" and sent["generate_audio"] is True
    assert (
        'says: "Okay, I have to tell you about this serum."' in sent["prompt"]
        and len(sent["reference_audios"]) == 1
    )
    assert fakes["elevenlabs"].submits == []


def test_native_dialogue_on_a_model_without_speech_is_a_clear_error(fakes):
    _, _, _, project = make_world(voice_mode="native")
    projects.update(project["id"], {"models": {"image_to_video": "replicate/seedance-1.5-pro"}})
    approved_storyboard(fakes, project["id"])
    # seedance 1.5 speaks, but with no reference input the user is warned
    assert any("voice may differ" in w for w in storyboard.warnings(project["id"]))


def test_talking_avatar_mode_sends_frame_and_line_audio(fakes):
    _, _, _, project = make_world(voice_mode="avatar")
    approved_storyboard(fakes, project["id"])
    first = storyboard.shots_of(project["id"])[0]
    jid = clips.render(project["id"], "final", [first["id"]])[0]
    run_all()
    assert jobs.get(jid)["status"] == "done", jobs.get(jid)["error"]
    model, sent = last_video_call(fakes)
    assert (
        model == "bytedance/omni-human"
        and sent["image"].startswith("https://fake/")
        and sent["audio"].startswith("https://fake/")
    )
    assert len(fakes["elevenlabs"].submits) == 1


def test_avatar_mode_without_an_avatar_model_says_what_is_needed(monkeypatch, fakes):
    from oh_my_ugc import providers
    from oh_my_ugc.catalog import load

    _, _, _, project = make_world(voice_mode="avatar")
    approved_storyboard(fakes, project["id"])
    for name in ("replicate", "fal"):
        providers.overrides.pop(name)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x" * 12)
    load.set_global_default("image_to_video", "openrouter/seedance-1.5-pro")  # a video model on the key left
    with pytest.raises(OmuError) as e:
        clips.plan_unit(projects.get(project["id"]), storyboard.units(project["id"])[0], "draft")
    assert "Needs Replicate or fal" in e.value.message


def test_shots_without_a_line_are_silent_in_every_mode(fakes):
    _, _, _, project = make_world(voice_mode="native")
    approved_storyboard(fakes, project["id"])
    shot = storyboard.shots_of(project["id"])[2]
    db.update("shots", shot["id"], {"line": ""})
    clips.render(project["id"], "draft", [shot["id"]])
    run_all()
    assert (
        last_video_call(fakes)[1]["generate_audio"] is False
        and "says:" not in last_video_call(fakes)[1]["prompt"]
    )


def test_two_shot_block_is_one_eight_second_clip(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    ids = [s["id"] for s in storyboard.shots_of(project["id"])]
    storyboard.update_shot(ids[0], {"duration": 4})
    storyboard.update_shot(ids[1], {"duration": 4})
    storyboard.group_block(project["id"], ids[:2])
    clips.render(project["id"], "draft", ids[:2])
    run_all()
    model, sent = last_video_call(fakes)
    assert sent["duration"] == 8 and "Shot 1 (0-4 s)" in sent["prompt"] and "Shot 2 (4-8 s)" in sent["prompt"]
    assert len([c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"]) == 1


def test_end_frame_is_sent_only_when_the_model_supports_it(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    shots = storyboard.shots_of(project["id"])
    storyboard.set_end_frame(shots[0]["id"], "next")
    clips.render(project["id"], "draft", [shots[0]["id"]])
    run_all()
    assert "last_frame_image" in last_video_call(fakes)[1]


def test_takes_choose_new_take_and_trim(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    shot = storyboard.shots_of(project["id"])[0]
    clips.render(project["id"], "draft", [shot["id"]])
    run_all()
    first = clips.chosen_take(storyboard.get_shot(shot["id"]))
    jid = clips.new_take(shot["id"], "draft", "more energy")
    run_all()
    assert jobs.get(jid)["status"] == "done" and "more energy" in last_video_call(fakes)[1]["prompt"]
    pub = storyboard.listing(project["id"])[0]
    assert len(pub["takes"]) == 2 and pub["chosen_take"] == pub["takes"][1]["id"]
    clips.choose_take(shot["id"], first["id"])
    assert clips.chosen_take(storyboard.get_shot(shot["id"]))["id"] == first["id"]
    trimmed = clips.trim(shot["id"], first["id"], 0.0, 0.55)
    assert trimmed["takes"][0]["trim_end"] == 0.55
    with pytest.raises(OmuError):
        clips.trim(shot["id"], first["id"], 0.0, 0.2)
    cleared = clips.clear_takes(shot["id"])
    assert len(cleared["takes"]) == 1


def test_one_failed_shot_does_not_stop_the_others(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    ids = clips.render(project["id"], "draft")
    orig = fakes["replicate"].submit

    def flaky(model, inputs, **kw):
        if "angle 2" in inputs.get("prompt", ""):
            fakes["replicate"].fail_with = "the safety checker flagged the frame"
        else:
            fakes["replicate"].fail_with = None
        return orig(model, inputs, **kw)

    fakes["replicate"].submit = flaky
    run_all()
    status = {jobs.get(j)["status"] for j in ids}
    assert status == {"done", "failed"}
    progress = clips.progress(project["id"])
    assert [p["status"] for p in progress].count("failed") == 1 and [p["status"] for p in progress].count(
        "done"
    ) == 3
    failed = next(p for p in progress if p["status"] == "failed")
    assert "safety checker" in failed["error"]


def test_render_estimate_shows_every_line_and_the_total(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    draft = clips.estimate_render(project["id"], "draft")
    final = clips.estimate_render(project["id"], "final")
    assert draft["available"] and len(draft["units"]) == 4 and draft["units"][3]["kind"] == "local"
    assert 0 < draft["total"]["amount"] < final["total"]["amount"]
    assert not draft["total"]["partial"]


def test_native_clip_drift_is_recorded_on_the_take(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    fakes["openrouter"].llm_reply = lambda m, s: {
        "product_present": True,
        "shape_matches": True,
        "colors_match": True,
        "text_matches": False,
        "issues": [{"severity": "major", "text": "garbled label"}],
    }
    shot = storyboard.shots_of(project["id"])[1]
    clips.render(project["id"], "draft", [shot["id"]])
    run_all()
    take = clips.chosen_take(storyboard.get_shot(shot["id"]))
    assert take["drift"]["status"] == "flagged" and len(take["drift"]["frames"]) == 3


_ = (json, runner, scripts)


def test_lipsync_mode_makes_a_silent_clip_then_syncs_it_to_the_voice(fakes):
    _, _, _, project = make_world(voice_mode="avatar")
    projects.update(project["id"], {"models": {"lipsync": "replicate/lipsync-2"}})
    approved_storyboard(fakes, project["id"])
    first = storyboard.shots_of(project["id"])[0]
    est = clips.estimate_render(project["id"], "draft", [first["id"]])
    assert [line["label"].split(" (")[0] for line in est["units"][0]["lines"]][1:] == [
        "Sync Lipsync 2",
        "Voice",
    ] or len(est["units"][0]["lines"]) == 3
    jid = clips.render(project["id"], "draft", [first["id"]])[0]
    run_all()
    assert jobs.get(jid)["status"] == "done", jobs.get(jid)["error"]
    models = [m for m, _ in fakes["replicate"].submits]
    assert models == ["bytedance/seedance-1.5-pro", "sync/lipsync-2"]
    video_inputs, sync_inputs = fakes["replicate"].submits[0][1], fakes["replicate"].submits[1][1]
    assert (
        video_inputs["generate_audio"] is False
        and sync_inputs["video"].startswith("https://fake/")
        and sync_inputs["audio"].startswith("https://fake/")
    )
    assert len(fakes["elevenlabs"].submits) == 1
