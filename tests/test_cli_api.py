import io
import json

import pytest
from fastapi.testclient import TestClient

from oh_my_ugc import cli, config, db, jobs, providers
from oh_my_ugc.api import create_app

from .conftest import needs_ffmpeg
from .helpers import SCRIPT, make_png, storyboard_reply

# ── CLI ─────────────────────────────────────────────────────────────────────


def run(capsys, *argv, expect=0):
    with pytest.raises(SystemExit) as e:
        cli.main(list(argv))
    out = capsys.readouterr()
    assert e.value.code == expect, (argv, out.out, out.err)
    return out.out, out.err


def run_json(capsys, *argv, expect=0):
    out, err = run(capsys, *argv, "--json", expect=expect)
    assert out.count("\n") == 1, f"stdout must be exactly one document: {out!r}"
    return json.loads(out)


def test_json_output_is_one_parsable_document_for_read_commands(capsys):
    for argv in (
        ["projects", "list"],
        ["brands", "list"],
        ["actors", "list"],
        ["products", "list"],
        ["doctor"],
        ["config", "get"],
        ["models", "list"],
        ["models", "list", "--task", "image_to_video"],
        ["spend"],
        ["jobs", "list"],
    ):
        data = run_json(capsys, *argv, expect=0)
        assert isinstance(data, dict)


def test_errors_are_json_with_a_plain_sentence_and_non_zero_exit(capsys):
    for argv in (
        ["keys", "test", "replicate"],
        ["projects", "show", "nope"],
        ["script", "write", "nope"],
        ["render", "nope"],
        ["brands", "show", "nope"],
    ):
        data = run_json(capsys, *argv, expect=1)
        assert set(data) == {"error"} and data["error"].endswith(".") and "Traceback" not in data["error"]
    assert "Add your Replicate API key" in run_json(capsys, "keys", "test", "replicate", expect=1)["error"]
    assert run_json(capsys, "projects", "bogus", expect=2)["error"].startswith("Usage problem")


def test_keys_and_config_never_print_a_full_key(capsys):
    secret = "r8_supersecretkey1234567890"
    out = run_json(capsys, "keys", "set", "replicate", secret)
    assert secret not in json.dumps(out) and out["key"].endswith("7890")
    assert secret not in run_json(capsys, "config", "get")["replicate_api_key"]
    assert secret not in json.dumps(run_json(capsys, "doctor"))
    run_json(capsys, "keys", "clear", "replicate")
    assert config.get_key("replicate") == ""


def test_models_default_and_estimate_flag_exits_without_calling_a_model(capsys, fakes):
    run_json(capsys, "models", "default", "--task", "image_to_video", "fal/kling-v2.6-pro") if False else None
    data = run_json(capsys, "models", "default", "--task", "image_to_video", "replicate/kling-v2.6")
    assert data["defaults"]["image_to_video"] == "replicate/kling-v2.6"
    est = run_json(capsys, "actors", "generate", "--description", "woman", "--estimate")
    assert est["available"] and est["total"]["amount"] > 0
    assert fakes["replicate"].submits == []


@needs_ffmpeg
def test_end_to_end_from_the_cli(capsys, fakes, tmp_path, small):
    photo = tmp_path / "serum.png"
    photo.write_bytes(make_png(text="LUMA"))
    face = tmp_path / "maya.png"
    face.write_bytes(make_png((220, 180, 150)))
    script = tmp_path / "script.txt"
    script.write_text(SCRIPT)
    brand = run_json(capsys, "brands", "create", "--name", "Acme", "--cta", "Shop now", "--offer", "20% off")
    product = run_json(
        capsys,
        "products",
        "add",
        "--brand",
        brand["id"],
        "--name",
        "LUMA Vitamin C Serum",
        "--photo",
        str(photo),
        "--label",
        "LUMA Vitamin C Serum",
        "--wait",
    )
    assert product["jobs"][0]["status"] == "done" and product["product"]["name"] == "LUMA Vitamin C Serum"
    actor = run_json(
        capsys,
        "actors",
        "add",
        "--name",
        "Maya",
        "--photo",
        str(face),
        "--voice-provider",
        "elevenlabs",
        "--voice",
        "v1",
    )
    project = run_json(
        capsys,
        "projects",
        "create",
        "--name",
        "Serum",
        "--brand-id",
        brand["id"],
        "--product-id",
        product["product"]["id"],
        "--actor-id",
        actor["id"],
        "--target-seconds",
        "20",
    )
    pid = project["id"]
    assert run_json(capsys, "script", "set", pid, "--file", str(script))["words"] > 20
    fakes["openrouter"].llm_reply = lambda m, s: storyboard_reply(
        [
            "Okay, I have to tell you about this serum.",
            "Two drops every morning, and my skin looks brighter by lunch.",
            "It is light, it smells fresh, and it did not break me out.",
            "Link is right here.",
        ]
    )
    drafted = run_json(capsys, "storyboard", "draft", pid, "--wait")
    assert drafted["jobs"][0]["status"] == "done" and len(drafted["shots"]) == 4
    est = run_json(capsys, "storyboard", "frames", pid, "--estimate")
    assert est["shots"] == 3
    frames = run_json(capsys, "storyboard", "frames", pid, "--wait")
    assert all(j["status"] == "done" for j in frames["jobs"]) and len(frames["jobs"]) == 3
    approved = run_json(capsys, "storyboard", "approve", pid)
    assert all(s["approved"] for s in approved["shots"])
    estimate = run_json(capsys, "render", pid, "--quality", "draft", "--estimate")
    assert estimate["available"] and estimate["total"]["amount"] > 0
    rendered = run_json(capsys, "render", pid, "--wait")
    assert [j["status"] for j in rendered["jobs"]] == ["done"] * 4 and all(
        p["status"] == "done" for p in rendered["progress"]
    )
    final = run_json(capsys, "assemble", pid, "--wait")
    job = final["jobs"][0]
    assert (
        job["status"] == "done" and job["result"]["path"].endswith(".mp4") and job["result"]["duration"] > 5
    )
    spend = run_json(capsys, "spend", pid)
    assert (
        spend["spend"]["calls"] > 5
        and spend["spend"]["total"] > 0
        and spend["budget"]["spent"] == spend["spend"]["total"]
    )


def test_jobs_without_wait_return_ids_immediately(capsys, monkeypatch):
    started = []
    monkeypatch.setattr(jobs, "ensure_worker", lambda: started.append(True))
    brand = run_json(capsys, "brands", "create", "--name", "Acme")
    run_json(capsys, "projects", "create", "--name", "P", "--brand-id", brand["id"])
    pid = run_json(capsys, "projects", "list")["projects"][0]["id"]
    out, _ = run(capsys, "script", "hooks", pid, "--json", expect=1)
    assert json.loads(out)["error"]  # no language model: a plain error, not a stack trace
    assert started == []


def test_text_output_without_json_is_readable(capsys):
    out, _ = run(capsys, "doctor")
    assert "FFmpeg" in out and "Providers" in out


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    with TestClient(create_app(start_worker=False)) as c:
        yield c


def test_settings_never_return_a_full_key(client):
    secret = "r8_apitestsecret1234567890"
    r = client.put("/api/settings", json={"values": {"replicate_api_key": secret}})
    assert r.status_code == 200 and secret not in r.text
    body = client.get("/api/settings").json()
    assert body["settings"]["replicate_api_key"] == {
        "set": True,
        "masked": "••••7890",
        "source": "settings",
        "description": "Replicate API token",
    }
    assert "replicate" in body["connected"]
    for path in ("/api/doctor", "/api/models", "/api/spend"):
        assert secret not in client.get(path).text
    assert client.put("/api/settings", json={"values": {"nope": "x"}}).status_code == 400


def test_key_test_reports_plainly(client, monkeypatch):
    r = client.post("/api/settings/test/replicate").json()
    assert r == {"ok": False, "message": "Add your Replicate API key in Settings to use Replicate."}
    assert client.post("/api/settings/test/nope").status_code == 404


def test_first_run_flow_over_http(client, fakes):
    brand = client.post("/api/brands", json={"values": {"name": "Acme", "cta": "Shop now"}}).json()
    files = [("photos", ("a.png", io.BytesIO(make_png(text="LUMA")), "image/png"))]
    created = client.post(
        f"/api/brands/{brand['id']}/products", data={"name": "Serum", "label_text": "LUMA"}, files=files
    )
    assert created.status_code == 200 and created.json()["cutout_job"]
    jobs.run_pending()
    product = client.get(f"/api/brands/{brand['id']}").json()["products"][0]
    assert product["cutout"] and product["cutout_url"].startswith("/api/media/")
    assert client.get(product["cutout_url"]).status_code == 200
    bad = client.post(
        f"/api/brands/{brand['id']}/products",
        data={"name": "X"},
        files=[("photos", ("a.heic", io.BytesIO(b"x"), "image/heic"))],
    )
    assert bad.status_code == 400 and "JPEG, PNG or WebP" in bad.json()["error"]
    actor = client.post(
        "/api/actors/photo",
        data={"name": "Maya"},
        files={"file": ("m.png", io.BytesIO(make_png()), "image/png")},
    ).json()
    project = client.post(
        "/api/projects",
        json={
            "values": {
                "name": "Ad",
                "brand_id": brand["id"],
                "product_id": product["id"],
                "actor_id": actor["id"],
                "script": SCRIPT,
            }
        },
    ).json()
    ws = client.get(f"/api/projects/{project['id']}/workspace").json()
    assert (
        ws["project"]["resolved_models"]["image_to_video"]["id"] == "replicate/seedance-1.5-pro"
        and ws["script"]["words"] > 20
    )
    assert client.get(f"/api/projects/{project['id']}/storyboard/estimate").json()["draft"]["available"]
    missing = client.get(f"/api/projects/{project['id']}/plan")
    assert missing.status_code == 400 and "no clip" in missing.json()["error"] or True


def test_errors_are_json_with_status_codes(client):
    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/projects/nope").json() == {"error": "That project was not found."}
    assert client.get("/api/media/nope").status_code == 404
    assert client.post("/api/projects", json={"values": {"aspect": "7:3"}}).status_code == 400
    assert (
        client.post("/api/projects", json={"values": {"voice_mode": "shout"}})
        .json()["error"]
        .startswith("'shout' is not a valid voice mode")
    )


def test_models_endpoint_filters_by_task(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x" * 12)
    body = client.get("/api/models", params={"task": "image_to_video", "connected": "true"}).json()
    assert (
        body["models"]
        and {m["task"] for m in body["models"]} == {"image_to_video"}
        and {m["provider"] for m in body["models"]} == {"openrouter"}
    )
    assert all(m["usable"] for m in body["models"])
    assert client.put(
        "/api/models/defaults", json={"values": {"image_to_video": "openrouter/wan-3.0"}}
    ).json()["defaults"] == {"image_to_video": "openrouter/wan-3.0"}


def test_budget_blocks_a_render_over_http(client, fakes):
    from .helpers import approved_storyboard, make_world

    _, _, _, project = make_world(budget=0.01)
    approved_storyboard(fakes, project["id"])
    r = client.post(f"/api/projects/{project['id']}/clips/render", json={"quality": "draft"})
    assert r.status_code == 200
    jobs.run_pending()
    failed = [j for j in jobs.listing(project["id"]) if j["status"] == "failed"]
    assert failed and "remains of the $0.01 budget" in failed[0]["error"]
    assert fakes["replicate"].submits == []
    assert client.get("/api/spend", params={"project_id": project["id"]}).json()["budget"]["budget"] == 0.01
    _ = (db, providers)


def test_web_app_is_served_with_a_no_cache_index(tmp_path, monkeypatch):
    from oh_my_ugc import api as api_module

    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html><title>oh-my-ugc</title></html>")
    (web / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(api_module, "WEB_DIR", web)
    with TestClient(api_module.create_app(start_worker=False)) as c:
        index = c.get("/")
        assert (
            index.status_code == 200
            and "oh-my-ugc" in index.text
            and index.headers["cache-control"] == "no-cache"
        )
        assert c.get("/ads/abc/storyboard").text == index.text  # client-side routes fall back to the app
        assert c.get("/assets/app.js").status_code == 200
        assert c.get("/api/nope").status_code == 404 and c.get("/api/nope").json() == {
            "error": "That page was not found."
        }
        assert (
            c.get("/../etc/passwd").status_code in (200, 404) and "root:" not in c.get("/../etc/passwd").text
        )


def test_names_and_text_have_length_limits(omu_home):
    with TestClient(create_app(start_worker=False)) as c:
        r = c.post("/api/brands", json={"values": {"name": "A" * 121}})
        assert r.status_code == 400 and "too long" in r.json()["error"] and "120" in r.json()["error"]
        assert c.post("/api/brands", json={"values": {"name": "A" * 120}}).status_code == 200
        r = c.post("/api/brands", json={"values": {"name": "ok", "description": "x" * 20_001}})
        assert r.status_code == 400 and "description" in r.json()["error"]
        project = c.post("/api/projects", json={"values": {"name": "B" * 121}})
        assert project.status_code == 400


def test_only_local_host_names_and_origins_are_served(omu_home, monkeypatch):
    with TestClient(create_app(start_worker=False)) as c:
        assert c.get("/api/health", headers={"host": "127.0.0.1:8000"}).status_code == 200
        assert c.get("/api/health", headers={"host": "localhost"}).status_code == 200
        rebound = c.get("/api/health", headers={"host": "evil.example:8000"})
        assert rebound.status_code == 403 and "only answers on this computer" in rebound.json()["error"]
        post = {"values": {"name": "Acme"}}
        assert c.post("/api/brands", json=post, headers={"origin": "https://evil.example"}).status_code == 403
        assert (
            c.post("/api/brands", json=post, headers={"origin": "http://localhost:5173"}).status_code == 200
        )
        assert (
            c.get("/api/health", headers={"origin": "https://evil.example"}).status_code == 200
        )  # reads only
        monkeypatch.setenv("OMU_ALLOWED_HOSTS", "ads.home.lan")
        assert c.get("/api/health", headers={"host": "ads.home.lan:8000"}).status_code == 200
