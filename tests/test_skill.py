import json
import re
from pathlib import Path

import pytest

from oh_my_ugc import cli, jobs

from .conftest import needs_ffmpeg
from .helpers import SCRIPT, make_png, storyboard_reply

SKILL = Path(__file__).resolve().parents[1] / "skills" / "oh-my-ugc" / "SKILL.md"


def skill_commands() -> list[str]:
    text = SKILL.read_text()
    blocks = re.findall(r"```bash\n(.*?)```", text, re.S)
    return [
        line.strip() for block in blocks for line in block.splitlines() if line.strip().startswith("omu ")
    ]


def test_skill_has_frontmatter_and_json_everywhere():
    text = SKILL.read_text()
    assert text.startswith("---\nname: oh-my-ugc\ndescription:")
    for command in skill_commands():
        assert "--json" in command, command


@needs_ffmpeg
def test_every_command_in_the_skill_runs(capsys, fakes, tmp_path, monkeypatch, small):
    monkeypatch.setattr(jobs, "ensure_worker", lambda: None)
    photo, face, script = tmp_path / "p.png", tmp_path / "f.png", tmp_path / "s.txt"
    photo.write_bytes(make_png(text="LUMA"))
    face.write_bytes(make_png((220, 180, 150)))
    script.write_text(SCRIPT)
    fakes["openrouter"].llm_reply = lambda m, s: storyboard_reply(
        [
            "Okay, I have to tell you about this serum.",
            "Two drops every morning, and my skin looks brighter by lunch.",
            "It is light, it smells fresh, and it did not break me out.",
            "Link is right here.",
        ]
    )
    ids: dict[str, str] = {"PHOTO": str(photo), "FACE": str(face), "SCRIPT": str(script), "VOICE": "voice123"}
    ran = 0
    for command in skill_commands():
        line = command
        for key, value in ids.items():
            line = line.replace("$" + key, value)
        argv = __import__("shlex").split(line)[1:]
        if "keys" in argv and "test" in argv:
            argv = ["doctor", "--json"]  # key checks go to the network; doctor covers the same path offline
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        out = capsys.readouterr().out
        assert e.value.code == 0, (line, out)
        data = json.loads(out)
        ran += 1
        if argv[:2] == ["brands", "create"]:
            ids["BRAND"] = data["id"]
        elif argv[:2] == ["products", "add"]:
            ids["PRODUCT"] = data["product"]["id"]
        elif argv[:2] == ["actors", "add"]:
            ids["ACTOR"] = data["id"]
        elif argv[:2] == ["projects", "create"]:
            ids["PROJECT"] = data["id"]
        elif argv[:2] == ["storyboard", "show"]:
            ids["SHOT"] = data["shots"][1]["id"]
    assert ran == len(skill_commands()) and ran >= 20
