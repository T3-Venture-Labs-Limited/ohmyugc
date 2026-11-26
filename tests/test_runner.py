import pytest

from oh_my_ugc import costs, db, jobs, runner
from oh_my_ugc.catalog import load
from oh_my_ugc.errors import BudgetExceeded, OmuError

from .conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def png(tmp_path, name="f.png", data=b"png-bytes"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_call_runs_polls_stores_and_records_the_ledger(fakes, tmp_path):
    entry = load.get("replicate/seedance-1.5-pro")
    res = runner.call(
        entry,
        {"first_frame": png(tmp_path), "prompt": "go", "duration": 5, "resolution": "480p", "audio": False},
        step="clips",
        quantities={"seconds": 5, "resolution": "480p", "audio": False},
    )
    assert res.path.suffix == ".mp4" and res.path.exists() and not res.cached
    fake = fakes["replicate"]
    model, sent = fake.submits[0]
    assert (
        model == "bytedance/seedance-1.5-pro"
        and sent["image"].startswith("https://fake/")
        and sent["resolution"] == "480p"
    )
    assert len(fake.polled) == 2  # one running poll, then success
    row = db.many("SELECT * FROM ledger")[0]
    assert row["step"] == "clips" and row["estimated"] == pytest.approx(0.065) and row["actual"] is None


def test_identical_request_is_a_free_cache_hit_and_new_take_misses(fakes, tmp_path):
    entry = load.get("replicate/seedream-4.5")
    slots = {"prompt": "a", "reference_images": [png(tmp_path)]}
    first = runner.call(entry, slots, step="frames")
    again = runner.call(entry, slots, step="frames")
    assert (
        again.cached
        and again.media == first.media
        and len(fakes["replicate"].submits) == 1
        and len(db.many("SELECT * FROM ledger")) == 1
    )
    runner.call(entry, slots, step="frames", take=1)
    assert len(fakes["replicate"].submits) == 2
    (tmp_path / "f.png").write_bytes(b"different")
    runner.call(entry, slots, step="frames")
    assert len(fakes["replicate"].submits) == 3


def test_billed_cost_wins_over_the_estimate(fakes, tmp_path):
    fakes["openrouter"].cost = 0.0123
    res = runner.call(
        load.get("openrouter/seedream-4.5"),
        {"prompt": "x", "reference_images": [png(tmp_path)]},
        step="frames",
    )
    assert res.cost == 0.0123 and db.many("SELECT * FROM ledger")[0]["actual"] == 0.0123


def test_restart_resumes_the_provider_job_without_a_second_submit(fakes, tmp_path):
    entry = load.get("replicate/seedance-1.5-pro")
    slots = {"first_frame": png(tmp_path), "prompt": "go"}
    fake = fakes["replicate"]
    key = costs.cache_key(
        entry, __import__("oh_my_ugc.catalog.mapping", fromlist=["x"]).build_inputs(entry, slots)
    )
    db.insert(
        "calls",
        {
            "key": key,
            "provider": "replicate",
            "model": entry.model,
            "provider_job_id": "job-existing",
            "status": "running",
            "created_at": db.now(),
            "updated_at": db.now(),
        },
    )
    fake._state["job-existing"] = 0
    fake._inputs = {"job-existing": (entry.model, {"generate_audio": False})}
    res = runner.call(entry, slots, step="clips")
    assert fake.submits == [] and "job-existing" in fake.polled and res.path.exists()


def test_failure_is_one_plain_sentence_and_costs_nothing(fakes, tmp_path):
    fakes["fal"].fail_with = "image was flagged by the safety checker"
    with pytest.raises(OmuError) as e:
        runner.call(
            load.get("fal/kling-v2.6-pro"), {"first_frame": png(tmp_path), "prompt": "x"}, step="clips"
        )
    assert e.value.message == "Fal could not make this: image was flagged by the safety checker."
    row = db.many("SELECT * FROM ledger")[0]
    assert row["status"] == "failed" and row["actual"] == 0.0


def test_timeout_message(fakes, tmp_path, monkeypatch):
    fakes["replicate"].polls = 10**6
    entry = load.get("replicate/seedance-1.5-pro").model_copy(update={"timeout_minutes": 0})
    with pytest.raises(OmuError) as e:
        runner.call(entry, {"first_frame": png(tmp_path), "prompt": "x"}, step="clips")
    assert e.value.message == "Replicate did not finish in 0 minutes. Try again or pick another model."


def test_budget_blocks_before_any_provider_call(fakes, tmp_path):
    pid = db.insert("projects", {"name": "p", "budget": 0.01, "created_at": db.now(), "updated_at": db.now()})
    with pytest.raises(BudgetExceeded):
        runner.call(
            load.get("replicate/seedream-4.5"),
            {"prompt": "x", "reference_images": [png(tmp_path)]},
            step="frames",
            project_id=pid,
            quantities={"images": 1},
        )
    assert fakes["replicate"].submits == []
    assert db.many("SELECT * FROM reservations") == []


def test_computed_cost_for_predict_time_models(fakes, tmp_path):
    fake = fakes["replicate"]
    orig = fake._outputs

    def with_metrics(model, inputs):
        r = orig(model, inputs)
        r.meta = {"predict_time": 4.0}
        return r

    fake._outputs = with_metrics
    runner.call(load.get("replicate/background-remover"), {"image": png(tmp_path)}, step="cutout")
    row = db.many("SELECT * FROM ledger")[0]
    assert row["actual"] == pytest.approx(0.0009) and row["computed"] == 1


# ── jobs ────────────────────────────────────────────────────────────────────


def test_job_lifecycle_and_plain_failure():
    @jobs.register("t_ok")
    def ok(job):
        runner.stage("Working")
        return {"n": 1}

    @jobs.register("t_bad")
    def bad(job):
        raise OmuError("Replicate is out of credit.")

    @jobs.register("t_crash")
    def crash(job):
        raise KeyError("secret-internal")

    a, b, c = (jobs.enqueue(k) for k in ("t_ok", "t_bad", "t_crash"))
    assert jobs.run_pending() == 3
    assert jobs.get(a)["status"] == "done" and jobs.get(a)["result"] == {"n": 1}
    assert jobs.get(b)["error"] == "Replicate is out of credit."
    crashed = jobs.get(c)
    assert (
        crashed["status"] == "failed"
        and "secret-internal" not in crashed["error"]
        and "KeyError" in crashed["error"]
    )


def test_interrupted_jobs_are_requeued_and_cancel_works():
    seen = []

    @jobs.register("t_rerun")
    def rerun(job):
        seen.append(job["id"])

    j = jobs.enqueue("t_rerun")
    db.update("jobs", j, {"status": "running"})
    assert jobs.requeue_interrupted() == 1 and jobs.get(j)["status"] == "queued"
    jobs.run_pending()
    assert seen == [j]
    q = jobs.enqueue("t_rerun")
    assert jobs.cancel(q)["status"] == "canceled"
    assert jobs.run_pending() == 0


def test_rate_limit_shows_as_waiting(monkeypatch):
    from oh_my_ugc.providers import base

    @jobs.register("t_wait")
    def wait(job):
        base.on_wait("replicate", 9.0) if base.on_wait else runner._wait_hook("replicate", 9.0)
        assert jobs.get(job["id"])["display"] == "waiting"

    jid = jobs.enqueue("t_wait")
    jobs.run_pending()
    assert jobs.get(jid)["status"] == "done"
