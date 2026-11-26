import base64
import json

import httpx
import pytest

from oh_my_ugc import config, db
from oh_my_ugc.errors import OmuError, OutOfCredit
from oh_my_ugc.providers import base, fal, openrouter, replicate, speech


@pytest.fixture
def mock(monkeypatch):
    """Install a MockTransport; returns the list of requests it saw."""
    seen: list[httpx.Request] = []
    state = {"handler": lambda r: httpx.Response(200, json={})}

    def handler(request):
        seen.append(request)
        return state["handler"](request)

    monkeypatch.setattr(base, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(base, "sleep", lambda s: seen.append(("sleep", s)))
    db.set_setting("replicate_api_key", "r8_testkey123456789")
    db.set_setting("fal_api_key", "fal-testkey-123456789")
    db.set_setting("openrouter_api_key", "sk-or-testkey-123456789")
    db.set_setting("elevenlabs_api_key", "eleven-test-1234567")
    db.set_setting("fish_api_key", "fish-test-123456789")

    class Ctl:
        requests = seen

        def respond(self, fn):
            state["handler"] = fn

    return Ctl()


def calls(seen):
    return [r for r in seen if isinstance(r, httpx.Request)]


# ── keys ────────────────────────────────────────────────────────────────────


def test_env_overrides_stored_key(monkeypatch):
    db.set_setting("replicate_api_key", "stored-key-12345678")
    assert config.get_key("replicate") == "stored-key-12345678"
    assert config.setting_source("replicate_api_key") == "settings"
    monkeypatch.setenv("REPLICATE_API_TOKEN", "env-key-12345678")
    assert config.get_key("replicate") == "env-key-12345678"
    assert config.setting_source("replicate_api_key") == "environment"


def test_mask_shows_only_last_four():
    assert config.mask("abcdefghijklmnop") == "••••mnop"
    assert config.mask("short") == "••••"


def test_redact_removes_stored_keys_and_bearer_tokens():
    db.set_setting("fal_api_key", "fal-secret-abcdefgh")
    text = "boom Authorization: Bearer abcdef1234567890 and fal-secret-abcdefgh and r8_abcdefghijklmnop"
    out = base.redact(text)
    assert (
        "fal-secret-abcdefgh" not in out
        and "abcdef1234567890" not in out
        and "r8_abcdefghijklmnop" not in out
    )


# ── retry policy ────────────────────────────────────────────────────────────


def test_429_waits_retry_after_then_succeeds(mock):
    n = {"i": 0}

    def handler(request):
        n["i"] += 1
        if n["i"] == 1:
            return httpx.Response(429, json={"retry_after": 7})
        return httpx.Response(200, json={"urls": {"get": "x"}})

    mock.respond(handler)
    waited = []
    base.on_wait = lambda provider, secs: waited.append((provider, secs))
    try:
        replicate.Replicate().http.json("GET", "/account")
    finally:
        base.on_wait = None
    assert waited == [("replicate", 8.0)]
    assert ("sleep", 8.0) in mock.requests


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
def test_client_errors_are_attempted_exactly_once(mock, status):
    mock.respond(lambda r: httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(OmuError):
        replicate.Replicate().http.json("GET", "/account")
    assert len(calls(mock.requests)) == 1


def test_402_is_plain_out_of_credit(mock):
    mock.respond(lambda r: httpx.Response(402, json={"detail": "Insufficient credit"}))
    with pytest.raises(OutOfCredit) as e:
        replicate.Replicate().http.json("POST", "/predictions", json={})
    assert "out of credit" in e.value.message and "Replicate" in e.value.message
    assert "r8_" not in e.value.message


def test_5xx_retries_three_times_then_fails(mock):
    mock.respond(lambda r: httpx.Response(503, text="down"))
    with pytest.raises(OmuError):
        replicate.Replicate().http.json("GET", "/account")
    assert len(calls(mock.requests)) == 4  # first try plus three retries


def test_422_message_names_provider_and_reason(mock):
    mock.respond(lambda r: httpx.Response(422, json={"detail": "prompt is required"}))
    with pytest.raises(OmuError) as e:
        replicate.Replicate().http.json("POST", "/predictions", json={})
    assert e.value.message.startswith("Replicate rejected the request: prompt is required")


# ── replicate ───────────────────────────────────────────────────────────────


def test_replicate_official_model_route(mock):
    def handler(request):
        if request.url.path.endswith("/models/bytedance/seedance-1.5-pro"):
            return httpx.Response(200, json={"is_official": True})
        return httpx.Response(201, json={"id": "p1", "status": "starting"})

    mock.respond(handler)
    sub = replicate.Replicate().submit("bytedance/seedance-1.5-pro", {"prompt": "x"})
    assert sub.job_id == "p1"
    assert calls(mock.requests)[-1].url.path == "/v1/models/bytedance/seedance-1.5-pro/predictions"


def test_replicate_community_model_uses_latest_version(mock):
    def handler(request):
        if request.url.path.endswith("/models/851-labs/background-remover"):
            return httpx.Response(200, json={"is_official": False, "latest_version": {"id": "abc123"}})
        return httpx.Response(201, json={"id": "p2", "status": "starting"})

    mock.respond(handler)
    replicate.Replicate().submit("851-labs/background-remover", {"image": "u"})
    last = calls(mock.requests)[-1]
    assert last.url.path == "/v1/predictions"
    assert json.loads(last.content)["version"] == "abc123"


def test_replicate_poll_states(mock):
    r = replicate.Replicate()
    mock.respond(lambda q: httpx.Response(200, json={"status": "starting"}))
    assert r.poll("p").status == "queued"
    mock.respond(lambda q: httpx.Response(200, json={"status": "processing"}))
    assert r.poll("p").status == "running"
    mock.respond(
        lambda q: httpx.Response(
            200, json={"status": "succeeded", "output": ["https://x/a.mp4"], "metrics": {"predict_time": 3.2}}
        )
    )
    done = r.poll("p")
    assert (
        done.status == "succeeded"
        and done.outputs[0].url == "https://x/a.mp4"
        and done.meta["predict_time"] == 3.2
    )
    mock.respond(lambda q: httpx.Response(200, json={"status": "failed", "error": "NSFW"}))
    assert r.poll("p").error == "NSFW"


def test_replicate_upload_returns_file_url(mock, tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"png")
    mock.respond(
        lambda q: httpx.Response(201, json={"urls": {"get": "https://api.replicate.com/v1/files/1"}})
    )
    assert replicate.Replicate().upload(f).endswith("/files/1")


# ── fal ─────────────────────────────────────────────────────────────────────


def test_fal_queue_lifecycle(mock):
    def handler(request):
        url = str(request.url)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "request_id": "r1",
                    "status_url": "https://queue.fal.run/x/requests/r1/status",
                    "response_url": "https://queue.fal.run/x/requests/r1",
                    "cancel_url": "https://queue.fal.run/x/requests/r1/cancel",
                },
            )
        if url.endswith("/status"):
            return httpx.Response(200, json={"status": state["s"]})
        return httpx.Response(200, json={"video": {"url": "https://v3.fal.media/o.mp4"}})

    state = {"s": "IN_QUEUE"}
    mock.respond(handler)
    f = fal.Fal()
    sub = f.submit("fal-ai/kling-video/v2.6/pro/image-to-video", {"prompt": "x"})
    assert f.poll(sub.job_id).status == "queued"
    state["s"] = "IN_PROGRESS"
    assert f.poll(sub.job_id).status == "running"
    state["s"] = "COMPLETED"
    done = f.poll(sub.job_id)
    assert done.status == "succeeded" and done.outputs[0].url.endswith("o.mp4")
    assert calls(mock.requests)[0].headers["Authorization"].startswith("Key ")


def test_fal_failed_result_and_bad_key(mock):
    f = fal.Fal()
    sub = json.dumps(
        {
            "request_id": "r",
            "status_url": "https://q/s",
            "response_url": "https://q/r",
            "cancel_url": "https://q/c",
        }
    )
    mock.respond(
        lambda q: (
            httpx.Response(200, json={"status": "COMPLETED"})
            if str(q.url).endswith("/s")
            else httpx.Response(422, json={"detail": "bad image"})
        )
    )
    assert f.poll(sub).status == "failed"
    mock.respond(lambda q: httpx.Response(401, json={"detail": "no"}))
    with pytest.raises(OmuError) as e:
        f.check_key()
    assert "rejected the API key" in e.value.message


# ── openrouter ──────────────────────────────────────────────────────────────


def test_openrouter_chat_returns_text_and_cost(mock):
    mock.respond(
        lambda q: httpx.Response(
            200, json={"choices": [{"message": {"content": '{"a":1}'}}], "usage": {"cost": 0.0042}}
        )
    )
    text, cost = openrouter.OpenRouter().chat(
        "google/gemini-3.8-flash", [{"role": "user", "content": "hi"}], schema={"type": "object"}
    )
    assert json.loads(text) == {"a": 1} and cost == 0.0042
    body = json.loads(calls(mock.requests)[0].content)
    assert body["response_format"]["json_schema"]["strict"] is True and body["usage"] == {"include": True}


def test_openrouter_image_is_synchronous(mock):
    png = base64.b64encode(b"\x89PNG....").decode()
    mock.respond(lambda q: httpx.Response(200, json={"data": [{"b64_json": png}], "usage": {"cost": 0.04}}))
    sub = openrouter.OpenRouter().submit("bytedance-seed/seedream-4.5", {"__kind": "image", "prompt": "x"})
    assert sub.result.status == "succeeded" and sub.result.cost == 0.04
    assert sub.result.outputs[0].data.startswith(b"\x89PNG")
    assert calls(mock.requests)[0].url.path == "/api/v1/images"


def test_openrouter_video_submit_poll_and_download_auth(mock):
    def handler(request):
        if request.method == "POST":
            return httpx.Response(202, json={"id": "v1", "status": "pending"})
        return httpx.Response(200, json={"status": "completed", "usage": {"cost": 0.06}})

    mock.respond(handler)
    o = openrouter.OpenRouter()
    sub = o.submit("bytedance/seedance-1-5-pro", {"prompt": "x", "duration": 5})
    assert sub.job_id == "v1"
    done = o.poll("v1")
    assert done.status == "succeeded" and done.cost == 0.06
    assert done.outputs[0].url.endswith("/videos/v1/content?index=0")
    assert done.outputs[0].headers["Authorization"].startswith("Bearer ")


def test_openrouter_parse_json_handles_code_fence():
    assert openrouter.parse_json('```json\n{"a": 2}\n```') == {"a": 2}
    with pytest.raises(OmuError):
        openrouter.parse_json("nope")


# ── speech ──────────────────────────────────────────────────────────────────


def test_elevenlabs_word_timings_cover_every_word(mock):
    text = "Two drops every morning"
    chars = list(text)
    starts = [i * 0.05 for i in range(len(chars))]
    ends = [s + 0.05 for s in starts]
    mock.respond(
        lambda q: httpx.Response(
            200,
            json={
                "audio_base64": base64.b64encode(b"mp3data").decode(),
                "alignment": {
                    "characters": chars,
                    "character_start_times_seconds": starts,
                    "character_end_times_seconds": ends,
                },
            },
        )
    )
    sub = speech.ElevenLabs().submit(
        "eleven_multilingual_v2", {"text": text, "voice": "EXAVITQu4vr4xnSDxMaL"}
    )
    words = sub.result.meta["words"]
    assert [w["text"] for w in words] == text.split()
    assert all(w["end"] > w["start"] for w in words) and words[0]["start"] == 0
    assert sub.result.outputs[0].data == b"mp3data"


def test_fish_keeps_latest_alignment_per_chunk(mock):
    events = [
        {
            "audio_base64": base64.b64encode(b"aa").decode(),
            "chunk_seq": 0,
            "chunk_audio_offset_sec": 0,
            "alignment": {"segments": [{"text": "old", "start": 0, "end": 1}]},
        },
        {
            "chunk_seq": 0,
            "chunk_audio_offset_sec": 0,
            "alignment": {
                "segments": [
                    {"text": "Hello", "start": 0, "end": 0.5},
                    {"text": "there", "start": 0.5, "end": 1.0},
                ]
            },
        },
        {
            "audio_base64": base64.b64encode(b"bb").decode(),
            "chunk_seq": 1,
            "chunk_audio_offset_sec": 2.0,
            "alignment": {"segments": [{"text": "friend", "start": 0.0, "end": 0.4}]},
        },
    ]
    mock.respond(lambda q: httpx.Response(200, text="".join(f"data: {json.dumps(e)}\n\n" for e in events)))
    sub = speech.Fish().submit("s2-pro", {"text": "Hello there friend", "voice": "abc"})
    assert [w["text"] for w in sub.result.meta["words"]] == ["Hello", "there", "friend"]
    assert sub.result.meta["words"][2]["start"] == 2.0 and sub.result.outputs[0].data == b"aabb"


def test_speech_requires_a_voice(mock):
    with pytest.raises(OmuError):
        speech.ElevenLabs().submit("m", {"text": "hi"})


def test_missing_key_has_plain_message():
    with pytest.raises(OmuError) as e:
        replicate.Replicate().key()
    assert "Add your Replicate API key in Settings" in e.value.message


# Recorded from the live API on 6 November 2026 (scrubbed).
OR_IMAGE_SIZE_ERROR = {
    "error": {
        "message": 'bytedance-seed/seedream-4.5 requires at least 3,686,400 output pixels; size "576x1024" is 589,824. Use a larger resolution such as "2K", or omit resolution to use the default.',
        "code": 400,
    }
}
OR_VIDEO_CREDIT_ERROR = {
    "error": {
        "message": "This request's maximum cost exceeds your available credits. Add credits, or request a shorter or lower-resolution video.",
        "code": 402,
        "metadata": {"reason": "weight_exceeds_budget"},
    }
}


def test_openrouter_live_error_shapes_read_as_one_clean_sentence(mock):
    mock.respond(lambda q: httpx.Response(400, json=OR_IMAGE_SIZE_ERROR))
    with pytest.raises(OmuError) as e:
        openrouter.OpenRouter().submit(
            "bytedance-seed/seedream-4.5", {"__kind": "image", "prompt": "x", "resolution": "1K"}
        )
    assert e.value.message.startswith(
        "OpenRouter rejected the request: bytedance-seed/seedream-4.5 requires at least 3,686,400"
    ) and not e.value.message.endswith("..")
    mock.respond(lambda q: httpx.Response(402, json=OR_VIDEO_CREDIT_ERROR))
    with pytest.raises(OutOfCredit) as c:
        openrouter.OpenRouter().submit("heygen/avatar-iv", {"prompt": "hi"})
    assert "out of credit" in c.value.message and "openrouter.ai/credits" in c.value.message


def test_openrouter_video_request_body_matches_the_live_api(mock):
    from oh_my_ugc.catalog import load, mapping

    entry = load.get("openrouter/seedance-1.5-pro")
    inputs = mapping.build_inputs(
        entry,
        {
            "prompt": "go",
            "first_frame": "data:image/jpeg;base64,AAA",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "9:16",
            "audio": False,
        },
    )
    mock.respond(lambda q: httpx.Response(202, json={"id": "v9", "status": "pending"}))
    openrouter.OpenRouter().submit(entry.model, inputs)
    body = json.loads(calls(mock.requests)[0].content)
    assert body == {
        "model": "bytedance/seedance-1-5-pro",
        "prompt": "go",
        "duration": 4,
        "resolution": "480p",
        "aspect_ratio": "9:16",
        "generate_audio": False,
        "frame_images": [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64,AAA"},
                "frame_type": "first_frame",
            }
        ],
    }
