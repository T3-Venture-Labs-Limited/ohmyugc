import pytest

from oh_my_ugc import actors, brands, db, jobs, products, projects, scripts, storyboard
from oh_my_ugc.errors import OmuError

from .conftest import needs_ffmpeg
from .helpers import SCRIPT, draft_storyboard, make_cutout_png, make_png, make_world

# ── brands and products ─────────────────────────────────────────────────────


def test_minimal_brand_is_enough():
    b = brands.create({"name": "Acme"})
    assert b["name"] == "Acme" and brands.listing()[0]["products"] == 0
    with pytest.raises(OmuError):
        brands.create({"name": "  "})


def test_brand_block_and_claim_detection():
    b = brands.create(
        {
            "name": "Acme",
            "voice_tone": "warm",
            "must_mention": "vitamin C; light texture",
            "avoid_claims": "cures acne\nclinically proven",
        }
    )
    block = brands.block(b)
    assert (
        "Must mention: vitamin C; light texture" in block
        and "Never claim or imply: cures acne; clinically proven" in block
    )
    assert brands.claim_hits("This CURES ACNE fast", b) == ["cures acne"]
    assert brands.missing_mentions("It has vitamin C", b) == ["light texture"]


def test_product_upload_rules():
    b = brands.create({"name": "Acme"})
    p = products.create(b["id"], "Serum", [("a.png", make_png()), ("b.jpg", make_png())], label_text="LUMA")
    assert p["primary_photo"] == p["photos"][0] and len(p["photos"]) == 2
    changed = products.update(p["id"], {"primary_photo": p["photos"][1]})
    assert changed["primary_photo"] == p["photos"][1]
    with pytest.raises(OmuError) as e:
        products.create(b["id"], "X", [("photo.heic", b"x")])
    assert "JPEG, PNG or WebP photo up to 20 MB" in e.value.message
    with pytest.raises(OmuError) as e:
        products.create(b["id"], "X", [("big.png", b"0" * (30 * 1024 * 1024))])
    assert "30 MB" in e.value.message and "20 MB" in e.value.message
    with pytest.raises(OmuError):
        products.create(b["id"], "X", [("fake.png", b"not an image")])
    with pytest.raises(OmuError):
        products.create(b["id"], "X", [])


@needs_ffmpeg
def test_cutout_runs_with_a_model_and_keeps_the_original(fakes):
    _, product, _, _ = make_world()
    before = product["primary_photo"]
    result = products.make_cutout(product["id"])
    assert result["status"] == "done" and products.get(product["id"])["primary_photo"] == before
    assert products.get(product["id"])["cutout"]


def test_cutout_without_a_model_explains_and_custom_cutout_works(monkeypatch):
    from oh_my_ugc import providers

    _, product, _, _ = make_world()
    assert providers.connected() == []
    r = products.make_cutout(product["id"])
    assert r["status"] == "skipped" and "uncut photo" in r["message"]
    custom = products.set_custom_cutout(product["id"], "cut.png", make_cutout_png())
    assert custom["cutout"] and products.make_cutout(product["id"])["status"] == "custom"
    with pytest.raises(OmuError):
        products.set_custom_cutout(product["id"], "flat.png", make_png())


# ── actors ──────────────────────────────────────────────────────────────────


@needs_ffmpeg
def test_actor_candidates_then_accept(fakes):
    a = actors.create_for_generation("Maya", "woman in her late 20s")
    est = actors.estimate_candidates(4)
    assert est["available"] and est["total"]["amount"] == pytest.approx(0.16)
    jid = actors.generate_candidates(a["id"], 4)
    jobs.run_pending()
    assert jobs.get(jid)["status"] == "done"
    actor = actors.get(a["id"])
    assert len(actor["candidates"]) == 4
    picked = actors.accept(a["id"], actor["candidates"][1]["media"], main=True)
    assert picked["refs"] == [actor["candidates"][1]["media"]] and len(picked["candidates"]) == 3
    ref_job = actors.generate_reference(a["id"], "Side profile")
    jobs.run_pending()
    assert jobs.get(ref_job)["status"] == "done"
    extra = actors.get(a["id"])["candidates"][-1]
    assert extra["kind"] == "Side profile"
    assert len(actors.accept(a["id"], extra["media"])["refs"]) == 2


def test_upload_face_has_no_consent_gate_only_a_reminder():
    a = actors.from_photo("Real person", "p.png", make_png(), "")
    assert a["refs"] and "right to use" in a["likeness_reminder"]


@needs_ffmpeg
def test_deleting_a_used_actor_keeps_the_project_work(fakes):
    _, _, actor, project = make_world()
    draft_storyboard(fakes, project["id"])
    shot = storyboard.shots_of(project["id"])[0]
    db.update("shots", shot["id"], {"frame": "abc"})
    actors.delete(actor["id"])
    after = projects.public(projects.get(project["id"]))
    assert after["actor_removed"] is True and after["actor"] is None
    assert storyboard.get_shot(shot["id"])["frame"] == "abc"


# ── scripts ─────────────────────────────────────────────────────────────────


def test_pasted_script_is_byte_identical():
    _, _, _, project = make_world()
    text = "  Line one.\n\nLine two,   with odd   spacing!  "
    scripts.set_script(project["id"], text)
    assert projects.get(project["id"])["script"] == text


def test_ai_script_fits_length_mentions_and_flags_claims(fakes):
    _, _, _, project = make_world(target_seconds=30, script="")
    words = (
        "and it cures acne. Honestly this vitamin C serum with a light texture changed my mornings " * 6
    ).split()[:75]
    fakes["openrouter"].llm_reply = {"title": "T", "script": " ".join(words)}
    result = scripts.write(project["id"])
    assert 65 <= result["words"] <= 85
    assert result["claim_hits"] == ["cures acne"] and result["missing_mentions"] == []
    system = fakes["openrouter"].chat_calls[0][1][0]["content"]
    user = fakes["openrouter"].chat_calls[0][1][1]["content"]
    assert (
        "Never claim or imply: cures acne" in user
        and "Must mention: vitamin C; light texture" in user
        and "between 64 and 86 words" in system
    )


def test_off_length_script_gets_one_corrective_retry(fakes):
    _, _, _, project = make_world(target_seconds=30, script="")
    replies = iter([{"title": "x", "script": "too short"}, {"title": "x", "script": " ".join(["word"] * 75)}])
    fakes["openrouter"].llm_reply = lambda m, s: next(replies)
    assert scripts.write(project["id"])["words"] == 75 and len(fakes["openrouter"].chat_calls) == 2


def test_writing_is_disabled_without_a_language_model():
    _, _, _, project = make_world()
    est = scripts.estimate(project["id"])
    assert est["available"] is False and "OpenRouter" in est["message"] and "paste a script" in est["message"]
    with pytest.raises(OmuError):
        scripts.write(project["id"])


def test_hooks_become_kept_variants(fakes):
    _, _, _, project = make_world()
    fakes["openrouter"].llm_reply = {
        "hooks": ["Stop scrolling.", "I was wrong about serums.", "Three weeks, one bottle."]
    }
    made = scripts.generate_hooks(project["id"], 3)
    assert [v["kept"] for v in made] == [1, 1, 1]
    scripts.update_hook(made[1]["id"], {"kept": False, "hook": "I was totally wrong."})
    kept = [v for v in scripts.variants(project["id"]) if v["kept"]]
    assert [v["hook"] for v in kept] == ["Stop scrolling.", "Three weeks, one bottle."]
    scripts.delete_hook(made[0]["id"])
    assert len(scripts.variants(project["id"])) == 2


# ── storyboard ──────────────────────────────────────────────────────────────

LINES = [
    "Okay, I have to tell you about this serum.",
    "Two drops every morning, and my skin looks brighter by lunch.",
    "It is light, it smells fresh, and it did not break me out.",
    "Link is right here.",
]


def test_alignment_reproduces_the_script_even_when_the_model_paraphrases():
    for lines in (
        LINES,
        [" ".join(reversed(x.split())) for x in LINES],
        ["totally different words here", "and more", "so many other words", "x"],
    ):
        out = storyboard.align_script(SCRIPT, lines)
        assert " ".join(out).split() == SCRIPT.split() and len(out) == len(lines)


def test_alignment_keeps_shots_without_lines_empty():
    out = storyboard.align_script("one two three four", ["one two", "", "three four"])
    assert out == ["one two", "", "three four"]


def test_draft_covers_the_script_and_matches_target_length(fakes):
    _, _, _, project = make_world(target_seconds=30)
    shots = draft_storyboard(fakes, project["id"])
    assert " ".join(s["line"] for s in shots).split() == SCRIPT.split()
    total = sum(s["duration"] for s in shots)
    assert 25.5 <= total <= 34.5, total


def test_draft_refuses_to_overwrite_without_confirmation(fakes):
    _, _, _, project = make_world()
    draft_storyboard(fakes, project["id"])
    with pytest.raises(OmuError) as e:
        storyboard.draft(project["id"])
    assert e.value.status == 409
    with pytest.raises(OmuError):
        storyboard.draft(make_world()[3]["id"] if False else projects.create({"name": "empty"})["id"])


def test_fit_durations_scales_silent_shots_first():
    out = storyboard.fit_durations([3.0, 3.0, 3.0], [False, True, False], 12.0)
    assert out[0] == 3.0 and out[2] == 3.0 and out[1] > 3.0 and abs(sum(out) - 12) <= 1.2


@needs_ffmpeg
def test_frames_only_call_the_model_for_non_real_product_shots(fakes):
    _, _, _, project = make_world()
    draft_storyboard(fakes, project["id"])
    est = storyboard.estimate_frames(project["id"])
    assert est["shots"] == 3 and est["total"]["amount"] == pytest.approx(0.12)
    ids = storyboard.generate_frames(project["id"])
    assert len(ids) == 3
    jobs.run_pending()
    assert len(fakes["replicate"].submits) == 3
    sent = fakes["replicate"].submits[0][1]
    assert (
        "Its label reads exactly" in sent["prompt"] and len(sent["image_input"]) == 2
    )  # actor photo, product photo
    cutaway = [s for s in storyboard.shots_of(project["id"]) if s["type"] == "cutaway"][0]
    assert cutaway["frame"]
    real = storyboard.shots_of(project["id"])[3]
    jid = storyboard.generate_frame(real["id"])
    jobs.run_pending()
    assert (
        jobs.get(jid)["status"] == "done"
        and storyboard.get_shot(real["id"])["frame"]
        and len(fakes["replicate"].submits) == 3
    )


@needs_ffmpeg
def test_drift_flags_a_frame_and_offers_a_fix(fakes):
    _, _, _, project = make_world()
    draft_storyboard(fakes, project["id"])
    fakes["openrouter"].llm_reply = lambda m, s: {
        "product_present": True,
        "shape_matches": True,
        "colors_match": True,
        "text_matches": False,
        "issues": [{"severity": "major", "text": 'label reads "LUMA Vitamin C Serun"'}],
    }
    shot = storyboard.shots_of(project["id"])[1]
    storyboard.generate_frame(shot["id"])
    jobs.run_pending()
    drift = storyboard.get_shot(shot["id"])["frame_drift"]
    assert drift["status"] == "flagged" and "Serun" in drift["issues"][0]["text"]


def test_edit_rules_visual_changes_unapprove_line_only_edits_do_not(fakes):
    _, _, _, project = make_world()
    draft_storyboard(fakes, project["id"])
    shot = storyboard.shots_of(project["id"])[0]
    db.update(
        "shots",
        shot["id"],
        {
            "frame": "m1",
            "frame_basis": storyboard.basis(projects.get(project["id"]), shot),
            "approved": 1,
            "audio": "a1",
            "words": [{"text": "x", "start": 0, "end": 1}],
        },
    )
    pub = storyboard.update_shot(shot["id"], {"line": "A brand new line."})
    assert pub["approved"] == 1 and pub["stale"] is False and pub["frame"] == "m1"
    assert storyboard.get_shot(shot["id"])["audio"] is None  # stale voiceover is dropped
    pub = storyboard.update_shot(shot["id"], {"framing": "wide shot from across the room"})
    assert pub["approved"] == 0 and pub["stale"] is True


def test_cannot_approve_without_a_frame_and_bulk_approve_lists_what_is_missing(fakes):
    _, _, _, project = make_world()
    draft_storyboard(fakes, project["id"])
    with pytest.raises(OmuError):
        storyboard.approve(storyboard.shots_of(project["id"])[0]["id"])
    with pytest.raises(OmuError) as e:
        storyboard.approve_all(project["id"])
    assert "Shot 1, 2, 3" in e.value.message
    assert (
        storyboard.approve(storyboard.shots_of(project["id"])[3]["id"])["approved"] == 1
    )  # real-product shots need no model frame


def test_shot_editing_operations(fakes):
    _, _, _, project = make_world()
    draft_storyboard(fakes, project["id"])
    ids = [s["id"] for s in storyboard.shots_of(project["id"])]
    storyboard.reorder(project["id"], list(reversed(ids)))
    assert [s["id"] for s in storyboard.shots_of(project["id"])] == list(reversed(ids))
    copy = storyboard.duplicate_shot(ids[0])
    assert (
        len(storyboard.shots_of(project["id"])) == 5
        and copy["position"] == storyboard.get_shot(ids[0])["position"] + 1
    )
    storyboard.delete_shot(copy["id"])
    assert [s["position"] for s in storyboard.shots_of(project["id"])] == [0, 1, 2, 3]
    added = storyboard.add_shot(project["id"], {"type": "cutaway", "action": "pour"}, after=ids[3])
    assert storyboard.get_shot(added["id"])["position"] == 1
    card = storyboard.add_text_card(project["id"], "30 day glow challenge")
    assert card["text_card"] == 1 and card["approved"] == 1
    with pytest.raises(OmuError):
        storyboard.reorder(project["id"], ids)


@needs_ffmpeg
def test_frame_history_regenerate_with_note_and_switch_back(fakes):
    _, _, _, project = make_world()
    draft_storyboard(fakes, project["id"])
    shot = storyboard.shots_of(project["id"])[1]
    storyboard.generate_frame(shot["id"])
    jobs.run_pending()
    first = storyboard.get_shot(shot["id"])["frame"]
    storyboard.generate_frame(shot["id"], note="hold the bottle closer to camera")
    jobs.run_pending()
    pub = storyboard.listing(project["id"])[1]
    assert (
        len(pub["history"]) == 2
        and "hold the bottle closer to camera" in fakes["replicate"].submits[-1][1]["prompt"]
    )
    assert len(fakes["replicate"].submits) == 2 and pub["frame"] == pub["history"][0]["media"]
    back = storyboard.use_frame(shot["id"], pub["history"][1]["id"])
    assert back["frame"] == first or back["frame"] == pub["history"][1]["media"]


def test_blocks_need_multi_shot_support_and_fit_the_clip_length(fakes, monkeypatch):
    _, _, _, project = make_world()
    draft_storyboard(fakes, project["id"])
    ids = [s["id"] for s in storyboard.shots_of(project["id"])]
    storyboard.update_shot(ids[0], {"duration": 4})
    storyboard.update_shot(ids[1], {"duration": 4})
    out = storyboard.group_block(project["id"], ids[:2])
    assert out[0]["block"] == out[1]["block"] and len(storyboard.units(project["id"])) == 3
    with pytest.raises(OmuError):
        storyboard.group_block(project["id"], [ids[0], ids[2]])  # not adjacent
    projects.update(project["id"], {"models": {"image_to_video": "replicate/kling-v2.6"}})
    storyboard.ungroup_block(project["id"], out[0]["block"])
    with pytest.raises(OmuError) as e:
        storyboard.group_block(project["id"], ids[:2])
    assert "does not do multi-shot" in e.value.message


def test_storyboard_warnings_about_end_frames_and_voices(fakes):
    _, _, _, project = make_world(voice_mode="native")
    draft_storyboard(fakes, project["id"])
    projects.update(project["id"], {"models": {"image_to_video": "replicate/kling-v2.6"}})
    shot = storyboard.shots_of(project["id"])[0]
    db.update("shots", shot["id"], {"end_frame": "abc"})
    msgs = storyboard.warnings(project["id"])
    assert any("no last-frame input" in m and "ignored" in m for m in msgs)
    projects.update(project["id"], {"models": {"image_to_video": "replicate/seedance-1.5-pro"}})
    assert any("voice may differ" in m for m in storyboard.warnings(project["id"]))


def test_nothing_runs_until_the_user_chooses_a_model(fakes):
    from oh_my_ugc.catalog import load

    _, _, _, project = make_world()
    for task in ("llm", "image_edit", "image_to_video", "speech"):
        load.set_global_default(task, None)
    est = scripts.estimate(project["id"])
    assert est["available"] is False and "Choose a model" in est["message"]
    with pytest.raises(OmuError) as e:
        scripts.write(project["id"])
    assert "No language model chosen" in e.value.message and "Settings" in e.value.message
    with pytest.raises(OmuError):
        storyboard.draft(project["id"], replace=True)
    assert fakes["replicate"].submits == [] and fakes["openrouter"].chat_calls == []


def test_an_ad_can_choose_its_own_model_without_a_global_choice(fakes):
    from oh_my_ugc.catalog import load

    _, _, _, project = make_world(models={"llm": "openrouter/gemini-3.8-flash"})
    load.set_global_default("llm", None)
    fakes["openrouter"].llm_reply = {"title": "T", "script": " ".join(["word"] * 50)}
    assert scripts.estimate(project["id"])["available"] is True


def test_actor_voice_must_match_the_chosen_voice_model(fakes):
    from oh_my_ugc import voice
    from oh_my_ugc.catalog import load

    _, _, actor, project = make_world()  # actor voice is on ElevenLabs
    actor = actors.get(actor["id"])
    load.set_global_default("speech", "fish/s2-pro")
    with pytest.raises(OmuError) as e:
        voice.speech_entry(project, actor)
    assert "ElevenLabs" in e.value.message and "Fish Audio" in e.value.message
    load.set_global_default("speech", "elevenlabs/multilingual-v2")
    assert voice.speech_entry(project, actor).id == "elevenlabs/multilingual-v2"
