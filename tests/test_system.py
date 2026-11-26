import json
import os
import subprocess
import sys

import pytest

from oh_my_ugc import cli, doctor, media, store, texts
from oh_my_ugc.captions import ass, presets
from oh_my_ugc.captions import words as cwords

from .conftest import needs_ffmpeg


def fake_ffmpeg(tmp_path, name="ffmpeg", libass=True):
    folder = tmp_path / name
    folder.mkdir()
    binary = folder / "ffmpeg"
    binary.write_text(
        "#!/bin/sh\n" + ('echo " T.. ass  V->V  Render ASS subtitles"\n' if libass else "echo ''\n")
    )
    binary.chmod(0o755)
    (folder / "ffprobe").write_text("#!/bin/sh\n")
    (folder / "ffprobe").chmod(0o755)
    return folder


def test_ffmpeg_search_prefers_a_build_with_libass(tmp_path, monkeypatch):
    plain, full = fake_ffmpeg(tmp_path, "plain", libass=False), fake_ffmpeg(tmp_path, "full", libass=True)
    # A real Mac (or CI runner) may have ffmpeg-full installed; only the fake builds count here.
    monkeypatch.setattr(media, "HOMEBREW_DIRS", ())
    monkeypatch.setenv("PATH", str(plain))
    monkeypatch.setenv("HOMEBREW_PREFIX", str(tmp_path / "brew"))
    (tmp_path / "brew" / "opt" / "ffmpeg-full").mkdir(parents=True)
    os.symlink(full, tmp_path / "brew" / "opt" / "ffmpeg-full" / "bin")
    media.find_ffmpeg.cache_clear()
    found = media.find_ffmpeg()
    assert found.libass and found.ffmpeg and "brew/opt/ffmpeg-full/bin" in found.ffmpeg
    media.find_ffmpeg.cache_clear()
    monkeypatch.setenv("OMU_FFMPEG", str(full))
    assert media.find_ffmpeg().ffmpeg == str(full / "ffmpeg")
    monkeypatch.delenv("OMU_FFMPEG")
    monkeypatch.delenv("HOMEBREW_PREFIX")
    monkeypatch.setenv("PATH", str(plain))
    media.find_ffmpeg.cache_clear()
    assert media.find_ffmpeg().libass is False  # only the plain build exists: usable, but without text
    media.find_ffmpeg.cache_clear()


def test_doctor_gives_a_macos_hint_when_libass_is_missing(tmp_path, monkeypatch):
    plain = fake_ffmpeg(tmp_path, "plain", libass=False)
    monkeypatch.setenv("PATH", str(plain))
    monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)
    monkeypatch.setattr(media, "HOMEBREW_DIRS", ())
    monkeypatch.setattr(sys, "platform", "darwin")
    media.find_ffmpeg.cache_clear()
    try:
        check = next(c for c in doctor.checks() if c["name"] == "captions")
        assert not check["ok"] and "brew install ffmpeg-full" in check["detail"]
        monkeypatch.setattr(sys, "platform", "linux")
        assert "OMU_FFMPEG" in media.install_hint()
    finally:
        media.find_ffmpeg.cache_clear()


def test_doctor_reports_unreadable_user_models_and_working_folders(omu_home):
    from oh_my_ugc import config

    (config.user_catalog_dir() / "bad.json").write_text("{nope")
    checks = {c["name"]: c for c in doctor.checks()}
    assert (
        checks["folders"]["ok"] and not checks["catalog"]["ok"] and "bad.json" in checks["catalog"]["detail"]
    )
    assert checks["providers"]["ok"] is False and "Settings" in checks["providers"]["detail"]


@needs_ffmpeg
def test_vendored_captions_burn_onto_a_synthetic_clip(tmp_path):
    words = cwords.clean(
        [{"text": "LUMA", "start": 0.1, "end": 0.5}, {"text": "glow", "start": 0.5, "end": 0.9}]
    )
    preset = presets.get_builtin("punch")
    assert preset is not None
    compiled = ass.compile_captions(words, preset, 270, 480, font_dirs=(texts.fonts_dir(),))
    assert "LUMA" in compiled.ass
    src, out, sub = tmp_path / "in.mp4", tmp_path / "out.mp4", tmp_path / "c.ass"
    subprocess.run(
        [
            media.ffmpeg_bin(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=270x480:d=1:r=24",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        check=True,
    )
    sub.write_text(compiled.ass)
    media.run_ffmpeg(
        [
            "-i",
            str(src),
            "-vf",
            f"ass={media.filter_path(sub)}:fontsdir={media.filter_path(texts.fonts_dir())}",
            str(out),
        ]
    )
    proc = subprocess.run(
        [
            media.ffmpeg_bin(),
            "-v",
            "error",
            "-ss",
            "0.3",
            "-i",
            str(out),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
    )
    assert max(proc.stdout) > 200  # white caption pixels were drawn on the black clip


def test_caption_engine_imports_without_transcription_or_face_libraries():
    code = (
        "import sys, oh_my_ugc.captions, oh_my_ugc.captions.ass, oh_my_ugc.captions.layout, oh_my_ugc.captions.presets, "
        "oh_my_ugc.captions.fonts, oh_my_ugc.captions.words; "
        "bad = [m for m in ('faster_whisper', 'mediapipe', 'ctranslate2') if m in sys.modules]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_store_keeps_each_file_once_and_never_changes_originals(omu_home, tmp_path):
    original = tmp_path / "photo.png"
    original.write_bytes(b"\x89PNG one")
    a, b = store.put_file(original), store.put_bytes(b"\x89PNG one", "png")
    assert a == b and original.read_bytes() == b"\x89PNG one"
    assert (
        store.kind_of("mp4") == "video"
        and store.kind_of("mp3") == "audio"
        and store.kind_of("PNG") == "image"
    )


# ── every CLI command has JSON errors ───────────────────────────────────────

COMMANDS = [
    ["config", "set", "bogus_key", "x"],
    ["keys", "test", "bogus"],
    ["models", "default", "--task", "image_to_video", "nope/none"],
    ["brands", "show", "x"],
    ["brands", "delete", "x"],
    ["brands", "create", "--name", ""],
    ["products", "add", "--brand", "x", "--name", "n", "--photo", "/no/file.png"],
    ["products", "cutout", "x"],
    ["products", "delete", "x"],
    ["actors", "add", "--name", "n", "--photo", "/no/file.png"],
    ["actors", "accept", "x", "--media", "m"],
    ["actors", "voice", "x"],
    ["actors", "delete", "x"],
    ["actors", "generate", "--description", ""],
    ["projects", "show", "x"],
    ["projects", "update", "x"],
    ["projects", "budget", "x"],
    ["projects", "delete", "x"],
    ["script", "show", "x"],
    ["script", "set", "x", "--file", "/no/file.txt"],
    ["script", "write", "x"],
    ["script", "hooks", "x"],
    ["script", "hook", "x", "--text", "hi"],
    ["storyboard", "show", "x"],
    ["storyboard", "draft", "x"],
    ["storyboard", "frames", "x"],
    ["storyboard", "approve", "x"],
    ["storyboard", "edit", "--shot", "x", "--line", "hi"],
    ["storyboard", "warnings", "x"],
    ["render", "x"],
    ["render", "x", "--estimate"],
    ["assemble", "x"],
    ["jobs", "show", "x"],
    ["jobs", "wait", "x"],
    ["jobs", "cancel", "x"],
]


@pytest.mark.parametrize("argv", COMMANDS, ids=[" ".join(c[:3]) for c in COMMANDS])
def test_every_failing_command_prints_one_error_document(capsys, argv):
    with pytest.raises(SystemExit) as e:
        cli.main([*argv, "--json"])
    out = capsys.readouterr().out
    assert e.value.code in (1, 2) and out.count("\n") == 1
    data = json.loads(out)
    assert list(data) == ["error"] and data["error"] and "Traceback" not in data["error"]


def test_doctor_lists_steps_with_no_chosen_model(monkeypatch):
    from oh_my_ugc.catalog import load

    assert not next(c for c in doctor.checks() if c["name"] == "models")["ok"]  # no key yet
    monkeypatch.setenv("OPENROUTER_API_KEY", "x" * 12)
    check = next(c for c in doctor.checks() if c["name"] == "models")
    assert not check["ok"] and "video clips" in check["detail"] and not check["required"]
    for task in ("llm", "vision_check", "image_edit", "image_to_video"):
        entry = next(e for e in load.curated() if e.task == task and e.provider == "openrouter")
        load.set_global_default(task, entry.id)
    assert next(c for c in doctor.checks() if c["name"] == "models")["ok"]
