"""Speech for shot lines: the speech model of the actor's voice provider, with word timings (design D11)."""

from __future__ import annotations

from typing import Any

from oh_my_ugc import costs, db, media, runner, store
from oh_my_ugc.captions import words as cwords
from oh_my_ugc.catalog import load
from oh_my_ugc.errors import OmuError
from oh_my_ugc.providers.base import DISPLAY

LEAD = 0.15  # seconds of room before speech starts inside a shot
TAIL = 0.25


def align_even(text: str, audio_path) -> list[dict[str, Any]]:
    """Word times for audio that came without timings: spread over the detected speech, weighted by length."""
    start, end = media.silence_span(audio_path)
    tokens = text.split()
    weights = [len(t) + 2 for t in tokens]
    total, t = sum(weights), start
    words = []
    for token, weight in zip(tokens, weights, strict=False):
        length = (end - start) * weight / total
        words.append(cwords.make_word(token, t, t + length))
        t += length
    return words


def speech_entry(project: dict[str, Any], actor: dict[str, Any] | None):
    """The voice model the user chose. An actor's voice belongs to one provider, so the choice must be on it."""
    provider = (actor or {}).get("voice_provider") or ""
    entry = load.chosen_for("speech", project.get("models"))
    if entry is not None and provider and entry.provider != provider:
        raise OmuError(
            f"{(actor or {}).get('name') or 'The actor'}'s voice is on {DISPLAY[provider]}, but the voice model "
            f"you chose is {entry.name} ({DISPLAY[entry.provider]}). Choose a {DISPLAY[provider]} voice model "
            "in Settings or on this ad's Brief, or pick another voice for the actor."
        )
    if entry is None:
        raise OmuError(f"No voice model chosen, so lines cannot be spoken. {load.requirement('speech')}")
    return entry


def estimate_line(project: dict[str, Any], actor: dict[str, Any] | None, line: str) -> costs.Estimate:
    try:
        entry = speech_entry(project, actor)
    except OmuError:
        return costs.Estimate(None, "no voice provider")
    return costs.estimate(entry, chars=len(line))


def speak(
    project: dict[str, Any], line: str, actor: dict[str, Any] | None, *, step: str = "voice", take: int = 0
) -> dict[str, Any]:
    """Speak one line. Returns {media, words, duration}; words always use the script's spelling."""
    entry = speech_entry(project, actor)
    voice = (actor or {}).get("voice_id") or ""
    if not voice:
        raise OmuError(
            "Pick a voice for the actor first (Actors, then the voice menu), so lines can be spoken."
        )
    res = runner.call(
        entry,
        {"text": line, "voice": voice, "speed": 1.0},
        project_id=project["id"],
        step=step,
        take=take,
        quantities={"chars": len(line)},
    )
    path = res.path
    duration = media.probe(path).duration
    raw = res.meta.get("words") or []
    if raw:
        words = cwords.retime(
            cwords.clean(
                [{"text": w.get("text") or w.get("word"), "start": w["start"], "end": w["end"]} for w in raw]
            ),
            line,
        )
    else:
        words = align_even(line, path)
    return {"media": res.media[0], "words": words, "duration": duration}


def speak_shot(project: dict[str, Any], shot: dict[str, Any], actor: dict[str, Any] | None) -> dict[str, Any]:
    """Speak a shot's line and save the audio and word timings on the shot."""
    if shot.get("audio") and shot.get("words"):
        path = store.maybe_path(shot["audio"])
        if path:
            return {"media": shot["audio"], "words": shot["words"], "duration": media.probe(path).duration}
    result = speak(project, shot["line"], actor)
    db.update("shots", shot["id"], {"audio": result["media"], "words": result["words"]})
    return result


def make_sample(
    actor: dict[str, Any],
    project: dict[str, Any] | None = None,
    sentence: str = "Hi, I'm just here to tell you about something I've been loving lately.",
) -> str:
    """Speak a neutral sentence in the actor's voice, to use as a voice reference for models that take one."""
    project = project or {"id": None, "models": {}}
    result = speak(project, sentence, actor, step="voice-sample")
    db.update("actors", actor["id"], {"voice_sample": result["media"]})
    return result["media"]
