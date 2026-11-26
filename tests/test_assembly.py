import re
import shutil
import subprocess
from pathlib import Path

import pytest

from oh_my_ugc import assembly, clips, config, db, jobs, media, projects, scripts, store, storyboard, voice

from .conftest import choose_models, install_test_models, needs_ffmpeg
from .helpers import approved_storyboard, make_world

pytestmark = [needs_ffmpeg, pytest.mark.usefixtures("small")]


_TEMPLATES: dict[tuple, Path] = {}


def _build_template(**kw) -> Path:
    """Render a project once per test session; every test gets a copy of its database.

    Media files stay where they were made (the database holds their absolute paths), so a test
    starts from a fully drafted ad without paying for the ffmpeg work again.
    """
    import os
    import tempfile

    from oh_my_ugc import providers, runner

    from .fakes import FakeProvider

    home = Path(tempfile.mkdtemp(prefix="omu-template-"))
    old = os.environ.get("OMU_HOME")
    os.environ["OMU_HOME"] = str(home)
    db.reset_for_tests()
    saved_sleep, runner.sleep = runner.sleep, lambda s: None
    saved_overrides = dict(providers.overrides)
    made = {name: FakeProvider(name) for name in config.PROVIDERS}
    providers.overrides.update(made)
    install_test_models()
    choose_models()
    try:
        _, _, _, project = make_world(**kw)
        approved_storyboard(made, project["id"])
        clips.render(project["id"], "draft")
        jobs.run_pending()
        db.connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        providers.overrides.clear()
        providers.overrides.update(saved_overrides)
        runner.sleep = saved_sleep
        db.reset_for_tests()
        if old is None:
            del os.environ["OMU_HOME"]
        else:
            os.environ["OMU_HOME"] = old
    return home


def rendered(fakes, **kw):
    key = tuple(sorted(kw.items()))
    if key not in _TEMPLATES:
        _TEMPLATES[key] = _build_template(**kw)
    db.reset_for_tests()  # the fakes fixture already wrote the model choices; drop that database first
    for leftover in config.home().glob("omu.db*"):
        leftover.unlink()
    shutil.copy(_TEMPLATES[key] / "omu.db", config.home() / "omu.db")
    return db.one("SELECT * FROM projects"), db.one("SELECT * FROM products")


def loudness(path, start=None, end=None):
    """Integrated loudness of a stretch of audio, via ebur128."""
    args = [media.ffmpeg_bin(), "-hide_banner", "-nostdin"]
    if start is not None:
        args += ["-ss", str(start), "-to", str(end)]
    args += ["-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"]
    err = subprocess.run(args, capture_output=True, text=True).stderr
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1])


def test_mixed_sources_become_one_video_at_the_project_size(fakes):
    project, _ = rendered(fakes)
    out = assembly.render(project["id"], captions=False)
    info = media.probe(store.path(out["media"]))
    p = assembly.plan(project["id"])
    assert (info.width, info.height) == (270, 480) and info.has_audio
    assert abs(info.duration - p["duration"]) < 0.4
    assert out["url"].startswith("/api/media/") and out["path"].endswith(".mp4")


def test_other_aspect_ratios(fakes):
    project, _ = rendered(fakes)
    for aspect, size in (("1:1", (270, 270)), ("4:5", (270, 338)), ("16:9", (480, 270))):
        projects.update(project["id"], {"aspect": aspect, "end_card": {"on": False}})
        info = media.probe(store.path(assembly.render(project["id"], captions=False)["media"]))
        assert (info.width, info.height) == size


def test_end_card_adds_its_duration_and_exact_text(fakes):
    project, _ = rendered(fakes)
    projects.update(
        project["id"],
        {
            "end_card": {
                "on": True,
                "seconds": 2.5,
                "cta": "Shop now",
                "offer": "20% off this week",
                "background": "brand",
            }
        },
    )
    p = assembly.plan(project["id"])
    body = sum(s["length"] for s in p["segments"])
    assert p["end_card"]["length"] == 2.5 and abs(p["duration"] - (body + 2.5)) < 1e-6
    ass, items = assembly.compile_ass(p, [], 270, 480, with_captions=False)
    texts_ = [i.text for i in items]
    assert "LUMA Vitamin C Serum" in texts_ and "Shop now" in texts_ and "20% off this week" in texts_
    assert "LUMA Vitamin C Serum" in ass and "Shop now" in ass
    out = assembly.render(project["id"], captions=False)
    assert abs(media.probe(store.path(out["media"])).duration - p["duration"]) < 0.4


def test_crossfade_shortens_the_ad(fakes):
    project, _ = rendered(fakes)
    projects.update(project["id"], {"crossfade": 0.2, "end_card": {"on": False}})
    p = assembly.plan(project["id"])
    n = len(p["segments"])
    assert abs(p["duration"] - (sum(s["length"] for s in p["segments"]) - 0.2 * (n - 1))) < 1e-6
    out = assembly.render(project["id"], captions=False)
    assert abs(media.probe(store.path(out["media"])).duration - p["duration"]) < 0.4


def test_captions_use_script_spelling_and_voice_timings(fakes):
    project, _ = rendered(fakes)
    fakes["elevenlabs"].speech_words = None
    p = assembly.plan(project["id"])
    words = assembly.caption_words(p)
    spoken = " ".join(w["text"] for w in words)
    assert spoken.split() == " ".join(s["line"] for s in storyboard.shots_of(project["id"])).split()
    # a voiceover line is delayed by the lead-in and offset by the shot's start
    seg = p["segments"][1]
    shot = seg["shots"][0]
    expected = seg["start"] + seg["offsets"][0] + voice.LEAD + shot["words"][0]["start"]
    got = [w for w in words if w["text"] == shot["words"][0]["text"] and abs(w["start"] - expected) < 0.5][0]
    assert abs(got["start"] - expected) <= 0.1
    assert all(b["start"] >= a["start"] for a, b in zip(words, words[1:], strict=False))


def test_brand_name_keeps_script_spelling_even_if_the_voice_provider_changes_it(fakes):
    project, _ = rendered(fakes)
    for shot in storyboard.shots_of(project["id"]):
        db.update("shots", shot["id"], {"audio": None, "words": []})
    scripts.set_script(project["id"], "Meet LUMA today.")
    for i, shot in enumerate(storyboard.shots_of(project["id"])):
        db.update("shots", shot["id"], {"line": "Meet LUMA today." if i == 0 else ""})
    fakes["elevenlabs"].speech_words = [
        {"text": "Meet", "start": 0.0, "end": 0.2},
        {"text": "Luma", "start": 0.2, "end": 0.5},
        {"text": "today", "start": 0.5, "end": 0.9},
    ]
    voice.speak_shot(
        projects.get(project["id"]), storyboard.shots_of(project["id"])[0], None
    ) if False else None
    clips.render(project["id"], "draft", [storyboard.shots_of(project["id"])[0]["id"]])
    jobs.run_pending()
    words = assembly.caption_words(assembly.plan(project["id"]))
    assert [w["text"] for w in words] == ["Meet", "LUMA", "today."]
    ass, _ = assembly.compile_ass(assembly.plan(project["id"]), words, 270, 480)
    assert "LUMA" in ass


def test_on_screen_text_covers_only_its_shot(fakes):
    project, _ = rendered(fakes)
    projects.update(project["id"], {"end_card": {"on": False}})
    shots = storyboard.shots_of(project["id"])
    db.update("shots", shots[1]["id"], {"onscreen": "30 day glow challenge"})
    p = assembly.plan(project["id"])
    _, items = assembly.compile_ass(p, [], 270, 480, with_captions=False)
    item = next(i for i in items if i.text == "30 day glow challenge")
    seg = p["segments"][1]
    assert seg["start"] <= item.start < item.end <= seg["start"] + seg["length"] + 1e-6
    assert (
        item.end <= p["segments"][2]["start"] + 1e-6
        and item.start >= p["segments"][0]["start"] + p["segments"][0]["length"] - 1e-6
    )


def test_text_card_is_a_segment_with_its_own_text(fakes):
    project, _ = rendered(fakes)
    projects.update(project["id"], {"end_card": {"on": False}})
    storyboard.add_text_card(
        project["id"], "Day 1 vs Day 21", after=storyboard.shots_of(project["id"])[0]["id"], duration=1.5
    )
    p = assembly.plan(project["id"])
    assert p["segments"][1]["kind"] == "card" and p["segments"][1]["length"] == 1.5
    _, items = assembly.compile_ass(p, [], 270, 480, with_captions=False)
    card = next(i for i in items if i.text == "Day 1 vs Day 21")
    assert card.start == pytest.approx(p["segments"][1]["start"]) and card.end == pytest.approx(
        p["segments"][1]["start"] + 1.5
    )
    out = assembly.render(project["id"], captions=False)
    assert abs(media.probe(store.path(out["media"])).duration - p["duration"]) < 0.4


def _rms_db(samples, start, end, rate=48000):
    import numpy as np

    chunk = samples[int(start * rate) : int(end * rate)]
    return 20 * np.log10(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)) + 1e-9)


def _read_wav(path):
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    return data


def test_music_is_ducked_under_speech(tmp_path):
    speech = tmp_path / "speech.wav"
    music = tmp_path / "music.wav"
    video = tmp_path / "v.mp4"
    # 6 s ad: speech (a tone) from 1.5 s to 3.5 s; music (noise) all the way through
    subprocess.run(
        [
            media.ffmpeg_bin(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=f=220:d=2:sample_rate=48000",
            "-af",
            "adelay=1500|1500,apad=whole_dur=6,volume=0.5",
            str(speech),
        ],
        check=True,
    )
    subprocess.run(
        [
            media.ffmpeg_bin(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=d=6:c=pink:r=48000:a=0.5",
            str(music),
        ],
        check=True,
    )
    subprocess.run(
        [
            media.ffmpeg_bin(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=6:r=30",
            "-i",
            str(speech),
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    mixed, voice_only = tmp_path / "mix.wav", tmp_path / "voice.wav"
    assembly.mix_audio(video, music, 0.5, mixed, 6.0)
    assembly.mix_audio(video, None, 0.5, voice_only, 6.0)
    ducked_music = (
        _read_wav(mixed)[: len(_read_wav(voice_only))] - _read_wav(voice_only)[: len(_read_wav(mixed))]
    )  # mix = voice + ducked music
    n = min(len(_read_wav(mixed)), len(_read_wav(voice_only)))
    ducked_music = (_read_wav(mixed)[:n] - _read_wav(voice_only)[:n]).reshape(-1, 2).mean(axis=1)
    during = _rms_db(ducked_music, 2.0, 3.2)
    gap = _rms_db(ducked_music, 4.6, 5.9)
    assert gap - during >= 6.0, (gap, during)  # noticeably quieter during speech, back to its level in gaps


def test_final_loudness_is_within_one_lu_of_target(fakes):
    project, _ = rendered(fakes)
    out = assembly.render(project["id"], captions=False)
    lufs = loudness(store.path(out["media"]))
    assert abs(lufs - assembly.LUFS) <= 1.0, lufs


def test_export_with_srt_and_hook_variants_share_the_body(fakes):
    project, _ = rendered(fakes)
    projects.update(project["id"], {"end_card": {"on": False}})
    before_video = len([c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"])
    before_speech = len(fakes["elevenlabs"].submits)
    hooks = [
        scripts.add_hook(project["id"], h)
        for h in ("Stop scrolling right now.", "I was wrong about serums.", "Three weeks, one bottle.")
    ]
    for h in hooks:
        storyboard.ensure_variant_shot(h["id"])
        clips.render(project["id"], "draft", variant_id=h["id"])
    jobs.run_pending()
    after_video = len([c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"])
    # voiceover mode: the silent video of the first shot is identical, so only the three new lines are paid for
    assert after_video == before_video and len(fakes["elevenlabs"].submits) - before_speech == 3
    jid = assembly.export_all(project["id"])
    jobs.run_pending()
    job = jobs.get(jid)
    assert job["status"] == "done", job["error"]
    files = job["result"]["files"]
    assert [f["name"] for f in files] == ["main", "Hook 1", "Hook 2", "Hook 3"] and len(
        {f["path"] for f in files}
    ) == 4
    assert all(media.probe(store.path(f["media"])).duration > 3 for f in files)
    assert files[0]["srt_path"] and "-->" in open(files[0]["srt_path"]).read()
    assert (
        len([c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"]) == after_video
    )  # export paid for nothing
    p = assembly.plan(project["id"], hooks[0]["id"])
    assert (
        p["segments"][0]["shots"][0]["line"] == "Stop scrolling right now."
        and p["segments"][1]["shots"][0]["id"]
        == assembly.plan(project["id"])["segments"][1]["shots"][0]["id"]
    )


def test_missing_clip_is_a_clear_error(fakes):
    _, _, _, project = make_world()
    approved_storyboard(fakes, project["id"])
    with pytest.raises(Exception) as e:
        assembly.plan(project["id"])
    assert "Shot 1 has no clip yet" in str(e.value)


def test_native_hooks_regenerate_only_the_hook_shot(fakes):
    project, _ = rendered(fakes, voice_mode="native")
    before = len([c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"])
    hook = scripts.add_hook(project["id"], "Stop scrolling right now.")
    storyboard.ensure_variant_shot(hook["id"])
    clips.render(project["id"], "draft", variant_id=hook["id"])
    jobs.run_pending()
    assert len([c for c in fakes["replicate"].submits if c[0] == "bytedance/seedance-1.5-pro"]) - before == 1
