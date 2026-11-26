"""The ``oh-my-ugc`` / ``omu`` command line.

Every command accepts ``--json`` and then prints exactly one JSON document to standard output
(progress goes to standard error). Failures exit non-zero and print ``{"error": "..."}``.
Commands that start long jobs return the job id unless ``--wait`` is given.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from oh_my_ugc import __version__
from oh_my_ugc.errors import OmuError

_WANT_JSON = False


class Parser(argparse.ArgumentParser):
    def error(self, message: str):  # JSON in, JSON out
        if _WANT_JSON:
            print(json.dumps({"error": f"Usage problem: {message}."}))
            raise SystemExit(2)
        super().error(message)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def emit(args: argparse.Namespace, data: Any, text: str | None = None) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, default=str))
    elif text is not None:
        print(text)
    else:
        print(json.dumps(data, indent=2, default=str))


def money(total: dict[str, Any]) -> str:
    return total["label"] if isinstance(total, dict) and "label" in total else str(total)


# ── job helpers ──────────────────────────────────────────────────────────────


def run_jobs(args: argparse.Namespace, job_ids: list[str]) -> dict[str, Any]:
    """Return job ids immediately, or with --wait run them here and print each result."""
    from oh_my_ugc import jobs

    if not getattr(args, "wait", False):
        jobs.ensure_worker()
        return {"job_ids": job_ids}
    worker = jobs.Worker()
    worker.start()
    results = []
    try:
        for job_id in job_ids:
            last = ""
            while True:
                job = jobs.get(job_id)
                if job["stage"] != last and not getattr(args, "json", False):
                    log(f"  {job_id}: {job['stage']}")
                    last = job["stage"]
                if job["status"] in ("done", "failed", "canceled"):
                    break
                time.sleep(0.4)
            results.append(job)
    finally:
        worker.stop()
    failed = [j for j in results if j["status"] != "done"]
    out = {
        "jobs": [
            {
                "id": j["id"],
                "kind": j["kind"],
                "status": j["status"],
                "error": j["error"],
                "result": j["result"],
            }
            for j in results
        ]
    }
    if failed:
        out["error"] = failed[0]["error"] or f"Job {failed[0]['status']}."
    return out


def add_wait(p: argparse.ArgumentParser) -> None:
    p.add_argument("--wait", action="store_true", help="block until the job finishes and print its result")


def add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="print one JSON document")


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_serve(args):
    import uvicorn

    from oh_my_ugc.api import create_app

    url = f"http://{args.host}:{args.port}"
    log(f"oh-my-ugc {__version__} at {url}")
    if not args.no_open and args.host in ("127.0.0.1", "localhost"):
        import threading
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


def cmd_worker(args):
    from oh_my_ugc import handlers, jobs  # noqa: F401

    jobs.claim_pidfile()
    worker = jobs.Worker()
    worker.start()
    idle = 0
    while idle < args.idle:
        time.sleep(1)
        busy = bool(jobs.db.one("SELECT id FROM jobs WHERE status IN ('queued','running') LIMIT 1"))
        idle = 0 if busy else idle + 1
    worker.stop()


def cmd_doctor(args):
    from oh_my_ugc import doctor

    checks = doctor.checks(verify_keys=args.verify)
    required_failed = [c for c in checks if c["required"] and not c["ok"] and c["name"] != "providers"]
    text = "\n".join(
        f"{'ok ' if c['ok'] else 'FAIL' if c['required'] else 'info'}  {c['label']}: {c['detail']}"
        for c in checks
    )
    emit(args, {"ok": not required_failed, "checks": checks}, text)
    return 1 if required_failed else 0


def cmd_config(args):
    from oh_my_ugc import config, db

    if args.action == "get":
        out = {}
        for key, spec in config.SETTINGS.items():
            value = config.get_setting(key)
            out[key] = config.mask(value) if spec.secret else value
        emit(args, out)
    else:
        if args.key not in config.SETTINGS:
            raise OmuError(f"'{args.key}' is not a setting. Choose one of: {', '.join(config.SETTINGS)}.")
        db.set_setting(args.key, args.value or "")
        emit(args, {"ok": True, "key": args.key})


def cmd_keys(args):
    from oh_my_ugc import config, db, providers

    if args.provider not in config.PROVIDERS:
        raise OmuError(f"'{args.provider}' is not a provider. Choose one of: {', '.join(config.PROVIDERS)}.")
    if args.action == "set":
        db.set_setting(config.key_name(args.provider), args.value or "")
        emit(args, {"ok": True, "provider": args.provider, "key": config.mask(config.get_key(args.provider))})
    elif args.action == "clear":
        db.set_setting(config.key_name(args.provider), "")
        emit(args, {"ok": True, "provider": args.provider})
    else:
        providers.get(args.provider).check_key()
        emit(
            args,
            {"ok": True, "provider": args.provider, "message": "Connected."},
            f"{args.provider}: connected",
        )


def cmd_models(args):
    from oh_my_ugc.catalog import availability, discover, load

    if args.action == "refresh":
        result = discover.refresh(args.provider, force=True)
        availability.refresh(force=True)
        emit(args, {"result": result})
    elif args.action == "default":
        load.set_global_default(args.task, args.model or None)
        emit(args, {"defaults": load.global_overrides()})
    else:
        rows = load.listing(args.task, connected_only=args.connected)
        text = "\n".join(
            f"{r['id']:<42} {r['task']:<18} {'ready' if r['usable'] else ('needs ' + r['provider'] if not r['connected'] else r.get('unavailable_reason', 'unavailable'))}"
            for r in rows
        )
        emit(args, {"models": rows, "defaults": load.global_overrides()}, text)


def _read_file(path: str) -> tuple[str, bytes]:
    p = Path(path).expanduser()
    if not p.is_file():
        raise OmuError(f"The file {path} does not exist.")
    return p.name, p.read_bytes()


def cmd_brands(args):
    from oh_my_ugc import brands

    if args.action == "list":
        rows = brands.listing()
        emit(
            args,
            {"brands": rows},
            "\n".join(f"{b['id']}  {b['name']}  ({b['products']} products)" for b in rows),
        )
    elif args.action == "create":
        values = {
            k: getattr(args, k)
            for k in (
                "name",
                "description",
                "voice_tone",
                "audience",
                "must_mention",
                "avoid_claims",
                "offer",
                "cta",
                "website",
            )
        }
        brand = brands.create(values)
        if args.logo:
            brand = brands.set_logo(brand["id"], *_read_file(args.logo))
        emit(args, brand, f"Created brand {brand['name']} ({brand['id']})")
    elif args.action == "delete":
        brands.delete(args.id)
        emit(args, {"ok": True})
    else:
        emit(args, brands.public(brands.get(args.id)))


def cmd_products(args):
    from oh_my_ugc import products

    if args.action == "list":
        rows = products.listing(args.brand)
        emit(
            args,
            {"products": rows},
            "\n".join(f"{p['id']}  {p['name']}  ({len(p['photos'])} photos)" for p in rows),
        )
    elif args.action == "add":
        product = products.create(
            args.brand, args.name, [_read_file(p) for p in args.photo], args.facts or "", args.label or ""
        )
        job = None
        if not args.no_cutout:
            job = products.start_cutout(product["id"])
        out: dict[str, Any] = {"product": product}
        if job:
            out.update(run_jobs(args, [job]))
        emit(args, out, f"Added {product['name']} ({product['id']})")
    elif args.action == "cutout":
        emit(args, run_jobs(args, [products.start_cutout(args.id)]))
    else:
        products.delete(args.id)
        emit(args, {"ok": True})


def cmd_actors(args):
    from oh_my_ugc import actors

    if args.action == "list":
        rows = actors.listing()
        emit(
            args,
            {"actors": rows},
            "\n".join(
                f"{a['id']}  {a['name']}  voice: {a['voice_provider'] or '-'} {a['voice_id'] or ''}"
                for a in rows
            ),
        )
    elif args.action == "add":
        actor = actors.from_photo(args.name, *_read_file(args.photo), description=args.description or "")
        if args.voice_provider or args.voice:
            actor = actors.update(
                actor["id"], {"voice_provider": args.voice_provider or "", "voice_id": args.voice or ""}
            )
        emit(args, actor, f"Added {actor['name']} ({actor['id']}). {actors.LIKENESS_REMINDER}")
    elif args.action == "generate":
        if args.estimate:
            emit(args, actors.estimate_candidates(args.count))
            return
        actor = actors.create_for_generation(args.name, args.description)
        out = run_jobs(args, [actors.generate_candidates(actor["id"], args.count)])
        out["actor"] = actors.public(actors.get(actor["id"]))
        emit(args, out)
    elif args.action == "accept":
        emit(args, actors.accept(args.id, args.media, args.main))
    elif args.action == "voice":
        actor = actors.update(args.id, {"voice_provider": args.provider or "", "voice_id": args.voice or ""})
        emit(args, actor)
    else:
        actors.delete(args.id)
        emit(args, {"ok": True})


def _project_values(args) -> dict[str, Any]:
    keys = (
        "name",
        "brand_id",
        "product_id",
        "actor_id",
        "format",
        "target_seconds",
        "aspect",
        "platform",
        "voice_mode",
        "brief",
        "budget",
        "caption_style",
        "final_resolution",
    )
    return {k: getattr(args, k) for k in keys if getattr(args, k, None) is not None}


def cmd_projects(args):
    from oh_my_ugc import costs, projects

    if args.action == "list":
        rows = projects.listing()
        emit(
            args,
            {"projects": rows},
            "\n".join(
                f"{p['id']}  {p['name']}  {p['shot_count']} shots  ${p['spend']['total']:.2f}" for p in rows
            ),
        )
    elif args.action == "create":
        project = projects.create(_project_values(args))
        emit(args, project, f"Created project {project['name']} ({project['id']})")
    elif args.action == "show":
        project = projects.public(projects.get(args.id), detail=True)
        emit(args, project)
    elif args.action == "update":
        emit(args, projects.update(args.id, _project_values(args)))
    elif args.action == "budget":
        projects.get(args.id)
        emit(args, costs.budget_status(args.id))
    else:
        projects.delete(args.id)
        emit(args, {"ok": True})


def cmd_script(args):
    from oh_my_ugc import scripts

    if args.action == "set":
        text = Path(args.file).read_text() if args.file else sys.stdin.read()
        emit(args, scripts.set_script(args.project, text))
    elif args.action == "write":
        if args.estimate:
            emit(args, scripts.estimate(args.project))
            return
        out = run_jobs(args, [scripts.start_write(args.project, args.prompt or "")])
        from oh_my_ugc import projects

        out["analysis"] = scripts.analysis(projects.get(args.project))
        emit(args, out)
    elif args.action == "hooks":
        out = run_jobs(args, [scripts.start_hooks(args.project, args.count)])
        out["variants"] = scripts.variants(args.project)
        emit(args, out)
    elif args.action == "hook":
        emit(args, scripts.add_hook(args.project, args.text))
    else:
        from oh_my_ugc import projects

        emit(args, scripts.analysis(projects.get(args.project)))


def cmd_storyboard(args):
    from oh_my_ugc import storyboard

    if args.action == "show":
        emit(args, {"shots": storyboard.listing(args.project)})
    elif args.action == "draft":
        if args.estimate:
            emit(args, storyboard.estimate_draft(args.project))
            return
        out = run_jobs(args, [storyboard.start_draft(args.project, args.replace)])
        out["shots"] = storyboard.listing(args.project) if args.wait else None
        emit(args, out)
    elif args.action == "frames":
        if args.estimate:
            emit(args, storyboard.estimate_frames(args.project, not args.all))
            return
        ids = storyboard.generate_frames(args.project, not args.all)
        emit(
            args,
            run_jobs(args, ids) if ids else {"job_ids": [], "message": "Every shot already has a frame."},
        )
    elif args.action == "approve":
        if args.shot:
            emit(args, storyboard.approve(args.shot, not args.undo))
        else:
            emit(args, {"shots": storyboard.approve_all(args.project)})
    elif args.action == "edit":
        values = {
            k: getattr(args, k)
            for k in ("line", "framing", "setting", "action", "onscreen", "duration", "type")
            if getattr(args, k, None) is not None
        }
        emit(args, storyboard.update_shot(args.shot, values))
    else:
        emit(args, {"warnings": storyboard.warnings(args.project)})


def cmd_render(args):
    from oh_my_ugc import clips

    if args.estimate:
        emit(args, clips.estimate_render(args.project, args.quality, args.shot or None))
        return
    ids = clips.render(args.project, args.quality, args.shot or None)
    out = run_jobs(args, ids)
    out["progress"] = clips.progress(args.project) if args.wait else None
    emit(args, out)
    return 1 if out.get("error") else 0


def cmd_assemble(args):
    from oh_my_ugc import assembly

    job = (
        assembly.export_all(args.project)
        if args.all
        else assembly.assemble(args.project, args.variant, None if not args.no_captions else False)
    )
    out = run_jobs(args, [job])
    emit(args, out)
    return 1 if out.get("error") else 0


def cmd_spend(args):
    from oh_my_ugc import costs

    data = {"spend": costs.spend(args.project), "ledger": costs.recent_ledger(args.limit, args.project)}
    if args.project:
        data["budget"] = costs.budget_status(args.project)
    emit(args, data, f"Total ${data['spend']['total']:.2f} over {data['spend']['calls']} calls")


def cmd_jobs(args):
    from oh_my_ugc import jobs

    if args.action == "list":
        rows = jobs.listing(args.project, limit=args.limit)
        emit(
            args,
            {"jobs": rows},
            "\n".join(f"{j['id']}  {j['kind']:<16} {j['display']:<9} {j['stage']}" for j in rows),
        )
    elif args.action == "show":
        emit(args, jobs.get(args.id))
    elif args.action == "wait":
        emit(args, jobs.wait(args.id, args.timeout))
    else:
        emit(args, jobs.cancel(args.id))


# ── parser ───────────────────────────────────────────────────────────────────


def build() -> argparse.ArgumentParser:
    parser = Parser(
        prog="omu", description="Make UGC video ads with AI actors, using your own provider keys."
    )
    parser.add_argument("--version", action="version", version=f"oh-my-ugc {__version__}")
    sub = parser.add_subparsers(dest="command")

    def add(name: str, fn, help: str, json_flag: bool = True):
        p = sub.add_parser(name, help=help)
        p.set_defaults(func=fn)
        if json_flag:
            add_json(p)
        return p

    p = add("serve", cmd_serve, "start the web app", json_flag=False)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-open", action="store_true")
    p = add("worker", cmd_worker, "run queued jobs in the background", json_flag=False)
    p.add_argument("--idle", type=int, default=60, help="exit after this many idle seconds")
    p = add("doctor", cmd_doctor, "check ffmpeg, folders, keys and the model catalog")
    p.add_argument("--verify", action="store_true", help="also test each provider key (free requests)")

    p = add("config", cmd_config, "show or change settings")
    p.add_argument("action", choices=["get", "set"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p = add("keys", cmd_keys, "set, clear or test a provider key")
    p.add_argument("action", choices=["set", "clear", "test"])
    p.add_argument("provider")
    p.add_argument("value", nargs="?")
    p = add("models", cmd_models, "list models, refresh discovery or choose the model for a step")
    p.add_argument("action", nargs="?", default="list", choices=["list", "refresh", "default"])
    p.add_argument("--task")
    p.add_argument("--provider")
    p.add_argument("--connected", action="store_true")
    p.add_argument("model", nargs="?")

    p = add("brands", cmd_brands, "manage brands")
    p.add_argument("action", choices=["list", "create", "show", "delete"])
    p.add_argument("id", nargs="?")
    for f in (
        "name",
        "description",
        "voice_tone",
        "audience",
        "must_mention",
        "avoid_claims",
        "offer",
        "cta",
        "website",
    ):
        p.add_argument("--" + f.replace("_", "-"), dest=f, default="")
    p.add_argument("--logo")
    p = add("products", cmd_products, "manage products")
    p.add_argument("action", choices=["list", "add", "cutout", "delete"])
    p.add_argument("id", nargs="?")
    p.add_argument("--brand")
    p.add_argument("--name")
    p.add_argument("--photo", action="append", default=[])
    p.add_argument("--facts")
    p.add_argument("--label", help="the exact text printed on the label")
    p.add_argument("--no-cutout", action="store_true")
    add_wait(p)
    p = add("actors", cmd_actors, "manage actors")
    p.add_argument("action", choices=["list", "add", "generate", "accept", "voice", "delete"])
    p.add_argument("id", nargs="?")
    p.add_argument("--name", default="")
    p.add_argument("--photo")
    p.add_argument("--description", default="")
    p.add_argument("--count", type=int, default=4)
    p.add_argument("--media")
    p.add_argument("--main", action="store_true")
    p.add_argument("--voice-provider", dest="voice_provider")
    p.add_argument("--provider")
    p.add_argument("--voice")
    p.add_argument("--estimate", action="store_true")
    add_wait(p)

    p = add("projects", cmd_projects, "manage projects")
    p.add_argument("action", choices=["list", "create", "show", "update", "budget", "delete"])
    p.add_argument("id", nargs="?")
    p.add_argument("--name")
    p.add_argument("--brand-id", dest="brand_id")
    p.add_argument("--product-id", dest="product_id")
    p.add_argument("--actor-id", dest="actor_id")
    p.add_argument(
        "--format", choices=["talking_head", "problem_solution", "unboxing", "demo_voiceover", "testimonial"]
    )
    p.add_argument("--target-seconds", dest="target_seconds", type=float)
    p.add_argument("--aspect", choices=["9:16", "1:1", "4:5", "16:9"])
    p.add_argument("--platform", choices=["tiktok", "reels", "shorts", "meta", "other"])
    p.add_argument("--voice-mode", dest="voice_mode", choices=["voiceover", "native", "avatar"])
    p.add_argument("--brief")
    p.add_argument("--budget", type=float)
    p.add_argument("--caption-style", dest="caption_style")
    p.add_argument("--final-resolution", dest="final_resolution", choices=["480p", "720p", "1080p"])

    p = add("script", cmd_script, "paste or write the script, and hooks")
    p.add_argument("action", choices=["show", "set", "write", "hooks", "hook"])
    p.add_argument("project")
    p.add_argument("--file")
    p.add_argument("--prompt")
    p.add_argument("--text")
    p.add_argument("--count", type=int, default=3)
    p.add_argument("--estimate", action="store_true")
    add_wait(p)
    p = add("storyboard", cmd_storyboard, "draft, edit, generate frames for and approve the storyboard")
    p.add_argument("action", choices=["show", "draft", "frames", "approve", "edit", "warnings"])
    p.add_argument("project", nargs="?")
    p.add_argument("--shot")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--undo", action="store_true")
    p.add_argument("--estimate", action="store_true")
    for f in ("line", "framing", "setting", "action", "onscreen", "type"):
        p.add_argument("--" + f, default=None)
    p.add_argument("--duration", type=float)
    add_wait(p)
    p = add("render", cmd_render, "make the clips (draft or final)")
    p.add_argument("project")
    p.add_argument("--quality", choices=["draft", "final"], default="draft")
    p.add_argument("--shot", action="append")
    p.add_argument("--estimate", action="store_true")
    add_wait(p)
    p = add("assemble", cmd_assemble, "stitch the ad (or --all for hook variants too)")
    p.add_argument("project")
    p.add_argument("--variant")
    p.add_argument("--all", action="store_true")
    p.add_argument("--no-captions", action="store_true")
    add_wait(p)
    p = add("spend", cmd_spend, "show what has been spent")
    p.add_argument("project", nargs="?")
    p.add_argument("--limit", type=int, default=50)
    p = add("jobs", cmd_jobs, "list, show, wait for or cancel jobs")
    p.add_argument("action", choices=["list", "show", "wait", "cancel"])
    p.add_argument("id", nargs="?")
    p.add_argument("--project")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--timeout", type=float, default=3600)
    return parser


def main(argv: list[str] | None = None) -> None:
    from oh_my_ugc import handlers  # noqa: F401  (registers job handlers)

    global _WANT_JSON
    _WANT_JSON = "--json" in (argv if argv is not None else sys.argv[1:])
    parser = build()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        # no command: start the app, as the docs say "run omu"
        args = parser.parse_args(["serve"])
    try:
        code = args.func(args) or 0
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        message = exc.message if isinstance(exc, OmuError) else _plain(exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": message}))
        else:
            print(f"error: {message}", file=sys.stderr)
        raise SystemExit(1) from None
    raise SystemExit(code)


def _plain(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return f"No permission to use {exc.filename}. Set OMU_HOME to a folder you can write to."
    if isinstance(exc, OSError):
        return f"A file problem stopped this: {exc.strerror or exc}."
    return f"Something went wrong ({type(exc).__name__}). Run again with the same command, and report it if it keeps happening."


if __name__ == "__main__":
    main()
