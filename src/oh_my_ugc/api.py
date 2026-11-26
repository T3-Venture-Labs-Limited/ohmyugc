"""HTTP API and web app."""

from __future__ import annotations

import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from oh_my_ugc import (
    __version__,
    actors,
    assembly,
    brands,
    clips,
    config,
    costs,
    db,
    doctor,
    handlers,
    jobs,
    products,
    projects,
    providers,
    scripts,
    store,
    storyboard,
)
from oh_my_ugc.catalog import availability, discover, load
from oh_my_ugc.config import PACKAGE_DIR, SETTINGS
from oh_my_ugc.errors import NotFound, OmuError

WEB_DIR = PACKAGE_DIR / "web"
_ = handlers


def _check_availability() -> None:
    try:  # a quiet background check against the providers' public pages; failures change nothing
        availability.refresh()
    except Exception:
        pass


def allowed_hosts() -> set[str]:
    """Host names the app answers to. Others are refused so a web page cannot reach it by DNS rebinding."""
    extra = {h.strip().lower() for h in os.environ.get("OMU_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return {"127.0.0.1", "localhost", "::1", "testserver"} | extra


def _hostname(value: str) -> str:
    try:
        return (urlsplit(value if "//" in value else "//" + value).hostname or "").lower()
    except ValueError:
        return ""


class Values(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class Note(BaseModel):
    note: str = ""


class IdList(BaseModel):
    ids: list[str]


class ScriptBody(BaseModel):
    script: str = ""
    prompt: str = ""
    count: int = 3


class RenderBody(BaseModel):
    quality: str = "draft"
    shot_ids: list[str] | None = None
    variant_id: str | None = None


class TakeBody(BaseModel):
    quality: str = "draft"
    note: str = ""


class TrimBody(BaseModel):
    take_id: str
    start: float = 0.0
    end: float | None = None


class ActorGenerateBody(BaseModel):
    name: str = ""
    description: str
    count: int = 4


async def _read(upload: UploadFile) -> tuple[str, bytes]:
    return upload.filename or "upload", await upload.read()


def create_app(start_worker: bool = True) -> FastAPI:
    worker = jobs.Worker()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.connect()
        if start_worker:
            jobs.claim_pidfile()
            worker.start()
            threading.Thread(target=_check_availability, daemon=True).start()
        yield
        worker.stop()

    app = FastAPI(title="oh-my-ugc", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        allowed = allowed_hosts()
        if _hostname(request.headers.get("host", "")) not in allowed:
            return JSONResponse(
                {"error": "oh-my-ugc only answers on this computer. Open it at http://127.0.0.1:8000."},
                status_code=403,
            )
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and _hostname(origin) not in allowed:
            return JSONResponse(
                {"error": "That request came from another website, so it was refused."}, status_code=403
            )
        return await call_next(request)

    @app.exception_handler(OmuError)
    async def omu_error(_: Request, exc: OmuError):
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    def start(job_id: str) -> dict[str, Any]:
        worker.wake()
        return {"job_id": job_id, "job": jobs.get(job_id)}

    def start_many(job_ids: list[str]) -> dict[str, Any]:
        worker.wake()
        return {"job_ids": job_ids, "count": len(job_ids)}

    # ── system ───────────────────────────────────────────────────────────────

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/doctor")
    def doctor_checks(verify: bool = False):
        return {"checks": doctor.checks(verify_keys=verify)}

    @app.get("/api/settings")
    def get_settings():
        out: dict[str, Any] = {}
        for key, spec in SETTINGS.items():
            if spec.secret:
                value = config.get_setting(key)
                out[key] = {
                    "set": bool(value),
                    "masked": config.mask(value),
                    "source": config.setting_source(key),
                    "description": spec.description,
                }
            else:
                out[key] = {"value": config.get_setting(key), "description": spec.description}
        return {"settings": out, "connected": providers.connected(), "defaults": load.global_overrides()}

    @app.put("/api/settings")
    def put_settings(body: Values):
        for key, value in body.values.items():
            if key not in SETTINGS:
                raise OmuError(f"'{key}' is not a setting.")
            db.set_setting(key, str(value or "").strip())
        return get_settings()

    @app.post("/api/settings/test/{provider}")
    def test_key(provider: str):
        if provider not in config.PROVIDERS:
            raise NotFound("That provider")
        try:
            providers.get(provider).check_key()
        except OmuError as exc:
            return {"ok": False, "message": exc.message}
        return {"ok": True, "message": "Connected."}

    @app.get("/api/voices/{provider}")
    def voices(provider: str, search: str = ""):
        client = providers.get(provider)
        if not hasattr(client, "voices"):
            raise OmuError(f"{provider} has no voice list. Type a voice name or id instead.")
        return {"voices": client.voices(search) if provider == "fish" else client.voices()}  # type: ignore[attr-defined]

    @app.get("/api/caption-styles")
    def caption_styles():
        from oh_my_ugc.captions import presets as caption_presets

        return {
            "styles": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "font": p.font,
                    "text_color": p.text_color,
                    "active_color": p.active_color,
                    "box": p.box,
                    "box_color": p.box_color,
                }
                for p in caption_presets.builtin()
            ]
        }

    # ── models ───────────────────────────────────────────────────────────────

    @app.get("/api/models")
    def models(task: str | None = None, connected: bool = False):
        return {
            "models": load.listing(task, connected_only=connected),
            "discovery": load.discovery_status(),
            "problems": load.curated() and load.problems,
            "defaults": load.global_overrides(),
            "requirements": {
                t: load.requirement(t)
                for t in (
                    "llm",
                    "vision_check",
                    "image_edit",
                    "image_generation",
                    "image_to_video",
                    "speech",
                    "talking_avatar",
                    "background_removal",
                )
            },
        }

    @app.post("/api/models/refresh")
    def models_refresh(provider: str | None = None):
        result = discover.refresh(provider, force=True)
        availability.refresh(force=True)
        return {"result": result}

    @app.put("/api/models/defaults")
    def models_defaults(body: Values):
        for task, entry_id in body.values.items():
            load.set_global_default(task, entry_id or None)
        return {"defaults": load.global_overrides()}

    # ── brands and products ──────────────────────────────────────────────────

    @app.get("/api/brands")
    def brands_list():
        return {"brands": brands.listing()}

    @app.post("/api/brands")
    def brands_create(body: Values):
        return brands.create(body.values)

    @app.get("/api/brands/{brand_id}")
    def brands_get(brand_id: str):
        return {**brands.public(brands.get(brand_id)), "products": products.listing(brand_id)}

    @app.patch("/api/brands/{brand_id}")
    def brands_update(brand_id: str, body: Values):
        return brands.update(brand_id, body.values)

    @app.delete("/api/brands/{brand_id}")
    def brands_delete(brand_id: str):
        brands.delete(brand_id)
        return {"ok": True}

    @app.post("/api/brands/{brand_id}/logo")
    async def brands_logo(brand_id: str, file: UploadFile = File(...)):
        name, data = await _read(file)
        return brands.set_logo(brand_id, name, data)

    @app.get("/api/products")
    def products_list(brand_id: str | None = None):
        return {"products": products.listing(brand_id)}

    @app.post("/api/brands/{brand_id}/products")
    async def products_create(
        brand_id: str,
        name: str = Form(...),
        facts: str = Form(""),
        label_text: str = Form(""),
        photos: list[UploadFile] = File(...),
    ):
        files = [await _read(p) for p in photos]
        product = products.create(brand_id, name, files, facts, label_text)
        job = products.start_cutout(product["id"])
        worker.wake()
        return {**product, "cutout_job": job}

    @app.patch("/api/products/{product_id}")
    def products_update(product_id: str, body: Values):
        return products.update(product_id, body.values)

    @app.post("/api/products/{product_id}/photos")
    async def products_photos(product_id: str, photos: list[UploadFile] = File(...)):
        return products.add_photos(product_id, [await _read(p) for p in photos])

    @app.delete("/api/products/{product_id}/photos/{media}")
    def products_remove_photo(product_id: str, media: str):
        return products.remove_photo(product_id, media)

    @app.post("/api/products/{product_id}/cutout")
    def products_cutout(product_id: str):
        return start(products.start_cutout(product_id))

    @app.post("/api/products/{product_id}/cutout/upload")
    async def products_cutout_upload(product_id: str, file: UploadFile = File(...)):
        name, data = await _read(file)
        return products.set_custom_cutout(product_id, name, data)

    @app.delete("/api/products/{product_id}")
    def products_delete(product_id: str):
        products.delete(product_id)
        return {"ok": True}

    # ── actors ───────────────────────────────────────────────────────────────

    @app.get("/api/actors")
    def actors_list():
        return {"actors": actors.listing(), "likeness_reminder": actors.LIKENESS_REMINDER}

    @app.post("/api/actors/photo")
    async def actors_photo(name: str = Form(""), description: str = Form(""), file: UploadFile = File(...)):
        fname, data = await _read(file)
        return actors.from_photo(name, fname, data, description)

    @app.post("/api/actors/generate")
    def actors_generate(body: ActorGenerateBody):
        actor = actors.create_for_generation(body.name, body.description)
        return {**start(actors.generate_candidates(actor["id"], body.count)), "actor": actor}

    @app.get("/api/actors/estimate")
    def actors_estimate(count: int = 4):
        return actors.estimate_candidates(count)

    @app.get("/api/actors/{actor_id}")
    def actors_get(actor_id: str):
        return actors.public(actors.get(actor_id))

    @app.post("/api/actors/{actor_id}/candidates")
    def actors_more(actor_id: str, count: int = 4):
        return start(actors.generate_candidates(actor_id, count))

    @app.post("/api/actors/{actor_id}/reference")
    def actors_reference(actor_id: str, body: Values):
        return start(
            actors.generate_reference(actor_id, body.values.get("view") or "Side profile, head and shoulders")
        )

    @app.post("/api/actors/{actor_id}/accept")
    def actors_accept(actor_id: str, body: Values):
        return actors.accept(actor_id, body.values["media"], bool(body.values.get("main")))

    @app.post("/api/actors/{actor_id}/discard")
    def actors_discard(actor_id: str, body: Values):
        return actors.discard_candidate(actor_id, body.values["media"])

    @app.patch("/api/actors/{actor_id}")
    def actors_update(actor_id: str, body: Values):
        return actors.update(actor_id, body.values)

    @app.post("/api/actors/{actor_id}/voice-sample")
    async def actors_voice_upload(actor_id: str, file: UploadFile = File(...)):
        name, data = await _read(file)
        return actors.set_voice_sample(actor_id, name, data)

    @app.post("/api/actors/{actor_id}/voice-sample/generate")
    def actors_voice_generate(actor_id: str):
        return start(actors.start_voice_sample(actor_id))

    @app.delete("/api/actors/{actor_id}")
    def actors_delete(actor_id: str):
        actors.delete(actor_id)
        return {"ok": True}

    # ── projects ─────────────────────────────────────────────────────────────

    @app.get("/api/projects")
    def projects_list():
        return {"projects": projects.listing()}

    @app.post("/api/projects")
    def projects_create(body: Values):
        return projects.create(body.values)

    @app.get("/api/projects/{project_id}")
    def projects_get(project_id: str):
        return projects.public(projects.get(project_id), detail=True)

    @app.patch("/api/projects/{project_id}")
    def projects_update(project_id: str, body: Values):
        return projects.update(project_id, body.values)

    @app.delete("/api/projects/{project_id}")
    def projects_delete(project_id: str):
        projects.delete(project_id)
        return {"ok": True}

    @app.post("/api/projects/{project_id}/duplicate")
    def projects_duplicate(project_id: str):
        return projects.duplicate(project_id)

    @app.post("/api/projects/{project_id}/music")
    async def projects_music(project_id: str, file: UploadFile = File(...)):
        name, data = await _read(file)
        return projects.set_music(project_id, name, data)

    @app.post("/api/projects/{project_id}/background")
    async def projects_background(project_id: str, file: UploadFile = File(...)):
        name, data = await _read(file)
        media = products.validate_image(name, data)
        project = projects.get(project_id)
        return projects.update(
            project_id,
            {"end_card": {**(project["end_card"] or {}), "background_image": media, "background": "image"}},
        )

    @app.get("/api/projects/{project_id}/workspace")
    def workspace(project_id: str):
        project = projects.get(project_id)
        return {
            "project": projects.public(project, detail=True),
            "shots": storyboard.listing(project_id),
            "variants": scripts.variants(project_id),
            "script": scripts.analysis(project),
            "jobs": jobs.listing(project_id, limit=30),
            "progress": clips.progress(project_id),
            "warnings": storyboard.warnings(project_id) if storyboard.shots_of(project_id) else [],
            "unit_blocks": [[s["id"] for s in u] for u in storyboard.units(project_id) if len(u) > 1],
            "variant_progress": {
                v["id"]: clips.progress(project_id, v["id"])
                for v in scripts.variants(project_id)
                if storyboard.shots_of(project_id, v["id"])
            },
            "exports": [
                j
                for j in jobs.listing(project_id, limit=30)
                if j["kind"] in ("assemble", "export_all") and j["status"] == "done"
            ][:3],
        }

    # ── script ───────────────────────────────────────────────────────────────

    @app.put("/api/projects/{project_id}/script")
    def script_put(project_id: str, body: ScriptBody):
        return scripts.set_script(project_id, body.script)

    @app.get("/api/projects/{project_id}/script/estimate")
    def script_estimate(project_id: str):
        return scripts.estimate(project_id)

    @app.post("/api/projects/{project_id}/script/write")
    def script_write(project_id: str, body: ScriptBody):
        return start(scripts.start_write(project_id, body.prompt))

    @app.post("/api/projects/{project_id}/hooks/generate")
    def hooks_generate(project_id: str, body: ScriptBody):
        return start(scripts.start_hooks(project_id, body.count))

    @app.post("/api/projects/{project_id}/hooks")
    def hooks_add(project_id: str, body: Values):
        return scripts.add_hook(project_id, body.values.get("hook", ""), body.values.get("name", ""))

    @app.patch("/api/hooks/{variant_id}")
    def hooks_update(variant_id: str, body: Values):
        return scripts.update_hook(variant_id, body.values)

    @app.delete("/api/hooks/{variant_id}")
    def hooks_delete(variant_id: str):
        scripts.delete_hook(variant_id)
        return {"ok": True}

    # ── storyboard ───────────────────────────────────────────────────────────

    @app.get("/api/projects/{project_id}/storyboard/estimate")
    def sb_estimate(project_id: str):
        return {
            "draft": storyboard.estimate_draft(project_id),
            "frames": storyboard.estimate_frames(project_id),
        }

    @app.post("/api/projects/{project_id}/storyboard/draft")
    def sb_draft(project_id: str, replace: bool = False):
        return start(storyboard.start_draft(project_id, replace))

    @app.post("/api/projects/{project_id}/storyboard/frames")
    def sb_frames(project_id: str, all: bool = False):
        return start_many(storyboard.generate_frames(project_id, only_missing=not all))

    @app.post("/api/projects/{project_id}/storyboard/approve-all")
    def sb_approve_all(project_id: str):
        return {"shots": storyboard.approve_all(project_id)}

    @app.post("/api/projects/{project_id}/storyboard/reorder")
    def sb_reorder(project_id: str, body: IdList):
        return {"shots": storyboard.reorder(project_id, body.ids)}

    @app.post("/api/projects/{project_id}/storyboard/actor")
    def sb_actor(project_id: str, body: Values):
        return storyboard.change_actor(project_id, body.values.get("actor_id"))

    @app.post("/api/projects/{project_id}/shots")
    def shot_add(project_id: str, body: Values, after: str | None = None):
        return storyboard.add_shot(project_id, body.values, after=after)

    @app.post("/api/projects/{project_id}/text-cards")
    def card_add(project_id: str, body: Values, after: str | None = None):
        return storyboard.add_text_card(
            project_id, body.values.get("text", ""), after, float(body.values.get("duration", 2.0))
        )

    @app.post("/api/projects/{project_id}/blocks")
    def block_group(project_id: str, body: IdList):
        return {"shots": storyboard.group_block(project_id, body.ids)}

    @app.delete("/api/projects/{project_id}/blocks/{block_id}")
    def block_ungroup(project_id: str, block_id: int):
        return {"shots": storyboard.ungroup_block(project_id, block_id)}

    @app.patch("/api/shots/{shot_id}")
    def shot_update(shot_id: str, body: Values):
        return storyboard.update_shot(shot_id, body.values)

    @app.delete("/api/shots/{shot_id}")
    def shot_delete(shot_id: str):
        storyboard.delete_shot(shot_id)
        return {"ok": True}

    @app.post("/api/shots/{shot_id}/duplicate")
    def shot_duplicate(shot_id: str):
        return storyboard.duplicate_shot(shot_id)

    @app.post("/api/shots/{shot_id}/approve")
    def shot_approve(shot_id: str, approved: bool = True):
        return storyboard.approve(shot_id, approved)

    @app.post("/api/shots/{shot_id}/frame")
    def shot_frame(shot_id: str, body: Note, target: str = "frame"):
        return start(storyboard.generate_frame(shot_id, body.note, target))

    @app.post("/api/shots/{shot_id}/frame/upload")
    async def shot_frame_upload(shot_id: str, target: str = "frame", file: UploadFile = File(...)):
        name, data = await _read(file)
        return storyboard.upload_frame(shot_id, name, data, target)

    @app.post("/api/shots/{shot_id}/frame/use/{frame_id}")
    def shot_use_frame(shot_id: str, frame_id: str):
        return storyboard.use_frame(shot_id, frame_id)

    @app.post("/api/shots/{shot_id}/end-frame")
    def shot_end_frame(shot_id: str, source: str):
        return storyboard.set_end_frame(shot_id, source)

    # ── clips ────────────────────────────────────────────────────────────────

    @app.get("/api/projects/{project_id}/clips/estimate")
    def clips_estimate(project_id: str, quality: str = "draft", variant_id: str | None = None):
        return clips.estimate_render(project_id, quality, variant_id=variant_id)

    @app.post("/api/projects/{project_id}/clips/render")
    def clips_render(project_id: str, body: RenderBody):
        return start_many(clips.render(project_id, body.quality, body.shot_ids, body.variant_id))

    @app.get("/api/projects/{project_id}/clips/progress")
    def clips_progress(project_id: str, variant_id: str | None = None):
        return {"progress": clips.progress(project_id, variant_id)}

    @app.post("/api/shots/{shot_id}/take")
    def clips_new_take(shot_id: str, body: TakeBody):
        return start(clips.new_take(shot_id, body.quality, body.note))

    @app.post("/api/shots/{shot_id}/take/{take_id}/choose")
    def clips_choose(shot_id: str, take_id: str):
        return clips.choose_take(shot_id, take_id)

    @app.post("/api/shots/{shot_id}/trim")
    def clips_trim(shot_id: str, body: TrimBody):
        return clips.trim(shot_id, body.take_id, body.start, body.end)

    @app.post("/api/shots/{shot_id}/real-product")
    def clips_swap(shot_id: str):
        return clips.swap_to_real_product(shot_id)

    @app.post("/api/shots/{shot_id}/clear-takes")
    def clips_clear(shot_id: str):
        return clips.clear_takes(shot_id)

    # ── export ───────────────────────────────────────────────────────────────

    @app.get("/api/projects/{project_id}/plan")
    def export_plan(project_id: str, variant_id: str | None = None):
        p = assembly.plan(project_id, variant_id)
        return {
            "duration": p["duration"],
            "end_card": p["end_card"],
            "segments": [
                {
                    "kind": s["kind"],
                    "start": s["start"],
                    "length": s["length"],
                    "shots": [x["id"] for x in s["shots"]],
                }
                for s in p["segments"]
            ],
        }

    @app.post("/api/projects/{project_id}/assemble")
    def export_assemble(project_id: str, variant_id: str | None = None, captions: bool | None = None):
        return start(assembly.assemble(project_id, variant_id, captions))

    @app.post("/api/projects/{project_id}/export")
    def export_all(project_id: str):
        return start(assembly.export_all(project_id))

    # ── jobs, spend, media ───────────────────────────────────────────────────

    @app.get("/api/jobs")
    def jobs_list(project_id: str | None = None, limit: int = 50):
        return {"jobs": jobs.listing(project_id, limit=limit)}

    @app.get("/api/jobs/{job_id}")
    def jobs_get(job_id: str):
        return jobs.get(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def jobs_cancel(job_id: str):
        return jobs.cancel(job_id)

    @app.get("/api/spend")
    def spend(project_id: str | None = None):
        out: dict[str, Any] = {
            "spend": costs.spend(project_id),
            "ledger": costs.recent_ledger(200, project_id),
        }
        if project_id:
            out["budget"] = costs.budget_status(project_id)
        else:
            out["by_project"] = [
                {"id": p["id"], "name": p["name"], "spend": costs.spend(p["id"])["total"]}
                for p in db.many("SELECT id, name FROM projects ORDER BY updated_at DESC")
            ]
        return out

    @app.get("/api/media/{media_id}")
    def media_file(media_id: str):
        path = store.maybe_path(media_id)
        if not path:
            raise NotFound("That file")
        return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/api/projects/{project_id}/download/{media_id}")
    def download(project_id: str, media_id: str, name: str = "ad"):
        path = store.maybe_path(media_id)
        if not path:
            raise NotFound("That file")
        return FileResponse(path, filename=f"{name}{path.suffix}")

    # ── web app ──────────────────────────────────────────────────────────────

    if WEB_DIR.exists():
        if (WEB_DIR / "assets").exists():
            app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                raise NotFound("That page")
            target = (WEB_DIR / path).resolve()
            if path and target.is_file() and WEB_DIR.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
_ = (json, Path)
