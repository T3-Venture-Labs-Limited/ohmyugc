"""A fake provider that returns tiny real media, for offline tests."""

from __future__ import annotations

import subprocess
from functools import cache

from oh_my_ugc.catalog import load
from oh_my_ugc.media import ffmpeg_bin
from oh_my_ugc.providers.base import Output, PollResult, Provider, Submission


@cache
def _bytes(kind: str, seconds: float = 0.6, size: str = "96x160") -> tuple[bytes, str]:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        if kind == "image":
            out = Path(tmp) / "a.png"
            subprocess.run(
                [
                    ffmpeg_bin(),
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"testsrc=s={size}:d=1",
                    "-frames:v",
                    "1",
                    str(out),
                ],
                check=True,
            )
            return out.read_bytes(), "png"
        if kind == "video":
            out = Path(tmp) / "a.mp4"
            subprocess.run(
                [
                    ffmpeg_bin(),
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"testsrc=s={size}:r=24:d={seconds}",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=f=440:d={seconds}",
                    "-shortest",
                    "-pix_fmt",
                    "yuv420p",
                    str(out),
                ],
                check=True,
            )
            return out.read_bytes(), "mp4"
        if kind == "silent_video":
            out = Path(tmp) / "a.mp4"
            subprocess.run(
                [
                    ffmpeg_bin(),
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"testsrc=s={size}:r=24:d={seconds}",
                    "-pix_fmt",
                    "yuv420p",
                    str(out),
                ],
                check=True,
            )
            return out.read_bytes(), "mp4"
        out = Path(tmp) / "a.mp3"
        subprocess.run(
            [ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=330:d={seconds}", str(out)],
            check=True,
        )
        return out.read_bytes(), "mp3"


class FakeProvider(Provider):
    """Pretends to be any provider name. ``polls`` running states come before success."""

    def __init__(self, name: str, polls: int = 1) -> None:
        self.name = name
        self.display = name.title()
        self.polls = polls
        self.submits: list[tuple[str, dict]] = []
        self.polled: list[str] = []
        self.uploads: list[str] = []
        self.fail_with: str | None = None
        self.llm_reply: dict = {}
        self.chat_calls: list[tuple[str, list]] = []
        self._count = 0
        self._state: dict[str, int] = {}
        self.cost: float | None = None
        self.video_seconds = 0.6
        self.speech_words: list | None = None

    def configured(self) -> bool:
        return True

    def key(self) -> str:
        return "fake"

    def check_key(self) -> str:
        return "connected"

    def upload(self, path):
        self.uploads.append(str(path))
        return f"https://fake/{path.name}"

    def _task(self, model: str) -> str:
        for e in load.all_entries():
            if e.model == model and e.provider == self.name:
                return e.task
        return "image_to_video"

    def _outputs(self, model: str, inputs: dict) -> PollResult:
        task = self._task(model)
        if task in ("image_generation", "image_edit", "background_removal"):
            import hashlib
            import io

            from PIL import Image

            digest = hashlib.sha256(
                repr((model, inputs.get("prompt") or inputs.get("text"))).encode()
            ).digest()
            buf = io.BytesIO()
            Image.new("RGB", (96, 160), tuple(digest[:3])).save(buf, "PNG")
            data, ext = buf.getvalue(), "png"
        elif task == "speech":
            data, ext = _bytes("audio", 1.2)
        else:
            audio = inputs.get("generate_audio", False) or task in ("talking_avatar", "lipsync")
            data, ext = _bytes("video" if audio else "silent_video", self.video_seconds)
        meta = {}
        if task == "speech":
            words = self.speech_words or [
                {"text": w, "start": i * 0.2, "end": i * 0.2 + 0.18}
                for i, w in enumerate(str(inputs.get("text", "hi there")).split())
            ]
            meta = {"words": words, "characters": len(str(inputs.get("text", "")))}
        return PollResult("succeeded", [Output(data=data, ext=ext)], meta=meta, cost=self.cost)

    def submit(self, model, inputs, *, version=None):
        self.submits.append((model, inputs))
        if self.fail_with:
            return Submission("", PollResult("failed", error=self.fail_with))
        self._count += 1
        job = f"job{self._count}"
        if self._task(model) == "speech":
            return Submission("", self._outputs(model, inputs))
        self._state[job] = 0
        self._inputs = getattr(self, "_inputs", {})
        self._inputs[job] = (model, inputs)
        return Submission(job)

    def poll(self, job_id):
        self.polled.append(job_id)
        self._state[job_id] += 1
        if self._state[job_id] <= self.polls:
            return PollResult("running")
        model, inputs = self._inputs[job_id]
        return self._outputs(model, inputs)

    def chat(self, model, messages, *, schema=None, temperature=None, max_tokens=None):
        import json

        self.chat_calls.append((model, messages))
        reply = self.llm_reply(messages, schema) if callable(self.llm_reply) else self.llm_reply
        return json.dumps(reply), 0.004


def _voices(self, search=""):
    return [
        {"id": "voice-sarah", "name": "Sarah", "description": "warm, young, american", "preview_url": None},
        {
            "id": "voice-george",
            "name": "George",
            "description": "calm, british, narrator",
            "preview_url": None,
        },
    ]


FakeProvider.voices = _voices
