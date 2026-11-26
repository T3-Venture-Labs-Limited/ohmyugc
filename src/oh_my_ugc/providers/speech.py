"""ElevenLabs and Fish Audio: speech with word timings (both return timing data with the audio)."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx

from oh_my_ugc.errors import OmuError
from oh_my_ugc.providers import base
from oh_my_ugc.providers.base import Http, Output, PollResult, Provider, Submission, plain_error

_FISH_CACHE: dict[tuple, tuple[float, dict]] = {}


def words_from_characters(alignment: dict) -> list[dict]:
    """ElevenLabs gives per-character times; rebuild words from them (seconds)."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words: list[dict] = []
    current, start, end = "", 0.0, 0.0
    for ch, s, e in zip(chars, starts, ends, strict=False):
        if ch.isspace():
            if current:
                words.append({"text": current, "start": round(start, 3), "end": round(end, 3)})
                current = ""
            continue
        if not current:
            start = s
        current += ch
        end = e
    if current:
        words.append({"text": current, "start": round(start, 3), "end": round(end, 3)})
    return words


class ElevenLabs(Provider):
    name = "elevenlabs"
    display = "ElevenLabs"

    def __init__(self) -> None:
        self.http = Http(
            "elevenlabs", "https://api.elevenlabs.io", lambda: {"xi-api-key": self.key()}, timeout=180
        )

    def check_key(self) -> str:
        self.http.request("GET", "/v1/models", retries=1)
        return "connected"

    def submit(self, model: str, inputs: dict[str, Any], *, version: str | None = None) -> Submission:
        voice = inputs.get("voice")
        if not voice:
            raise OmuError("Pick an ElevenLabs voice for this actor.")
        data = self.http.json(
            "POST",
            f"/v1/text-to-speech/{voice}/with-timestamps",
            params={"output_format": "mp3_44100_128"},
            json={
                "text": inputs["text"],
                "model_id": model,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "speed": float(inputs.get("speed", 1.0)),
                },
            },
        )
        alignment = data.get("alignment") or data.get("normalized_alignment") or {}
        words = words_from_characters(alignment)
        return Submission(
            "",
            PollResult(
                "succeeded",
                [Output(data=base64.b64decode(data["audio_base64"]), ext="mp3")],
                meta={"words": words, "characters": len(inputs["text"])},
            ),
        )

    def voices(self) -> list[dict]:
        data = self.http.json("GET", "/v1/voices")
        return [
            {
                "id": v["voice_id"],
                "name": v.get("name", v["voice_id"]),
                "description": ", ".join(str(x) for x in (v.get("labels") or {}).values() if x),
                "preview_url": v.get("preview_url"),
            }
            for v in data.get("voices", [])
        ]


class Fish(Provider):
    name = "fish"
    display = "Fish Audio"

    def __init__(self) -> None:
        self.http = Http(
            "fish", "https://api.fish.audio", lambda: {"Authorization": f"Bearer {self.key()}"}, timeout=300
        )

    def check_key(self) -> str:
        self.http.request("GET", "/wallet/self/api-credit", retries=1)
        return "connected"

    def submit(self, model: str, inputs: dict[str, Any], *, version: str | None = None) -> Submission:
        voice = inputs.get("voice")
        if not voice:
            raise OmuError("Pick a Fish Audio voice for this actor.")
        body = {
            "text": inputs["text"],
            "reference_id": voice,
            "format": "mp3",
            "mp3_bitrate": 192,
            "sample_rate": 44100,
            "latency": "normal",
            "normalize": True,
            "prosody": {"speed": float(inputs.get("speed", 1.0)), "volume": 0, "normalize_loudness": True},
        }
        audio = bytearray()
        alignments: dict[int, tuple[float, dict]] = {}  # latest alignment per chunk
        try:
            with (
                httpx.Client(timeout=300, transport=base.transport) as client,
                client.stream(
                    "POST",
                    "https://api.fish.audio/v1/tts/stream/with-timestamp",
                    json=body,
                    headers={**self.http._headers(), "model": model},
                ) as response,
            ):
                if response.status_code >= 400:
                    response.read()
                    raise plain_error("fish", response.status_code, response.text)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    if event.get("audio_base64"):
                        audio += base64.b64decode(event["audio_base64"])
                    if event.get("alignment"):
                        seq = int(event.get("chunk_seq") or 0)
                        alignments[seq] = (
                            float(event.get("chunk_audio_offset_sec") or 0),
                            event["alignment"],
                        )
        except httpx.HTTPError as exc:
            raise OmuError(
                "Could not reach Fish Audio. Check your connection and try again.",
                detail=base.redact(str(exc)),
            ) from exc
        if not audio:
            return Submission("", PollResult("failed", error="Fish Audio returned no audio."))
        words = []
        for seq in sorted(alignments):
            offset, alignment = alignments[seq]
            for seg in alignment.get("segments", []):
                text = str(seg.get("text", "")).strip()
                if text:
                    words.append(
                        {
                            "text": text,
                            "start": round(offset + float(seg["start"]), 3),
                            "end": round(offset + float(seg["end"]), 3),
                        }
                    )
        return Submission(
            "",
            PollResult(
                "succeeded",
                [Output(data=bytes(audio), ext="mp3")],
                meta={"words": words, "characters": len(inputs["text"])},
            ),
        )

    def voices(self, search: str = "") -> list[dict]:
        params = {
            "page_size": 50,
            "sort_by": "task_count",
            **({"title": search} if search else {"self": "true"}),
        }
        key = (self.http._headers().get("Authorization"), tuple(sorted(params.items())))
        hit = _FISH_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < 600:
            data = hit[1]
        else:
            data = self.http.json("GET", "/model", params=params)
            _FISH_CACHE[key] = (time.monotonic(), data)
        return [
            {
                "id": i["_id"],
                "name": i.get("title") or i["_id"],
                "description": ", ".join(i.get("languages") or []),
                "preview_url": ((i.get("samples") or [{}])[0] or {}).get("audio"),
            }
            for i in data.get("items", [])
        ]

    def upload(self, path: Path) -> str:
        raise OmuError("Fish Audio does not take file uploads here.")
