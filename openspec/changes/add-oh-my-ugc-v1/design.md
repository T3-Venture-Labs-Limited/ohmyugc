# Design

## Context

oh-my-ugc is a new repository (motivation: see proposal.md, Why). It is the fourth tool in a family whose scaffold is proven: popcaps, short-stock and clipyyy all ship a FastAPI app with a SQLite job queue, a React/Vite web app built into the Python wheel, a `--json` CLI, an agent skill, Docker, and CI on Linux plus macOS (Apple Silicon and Intel). oh-my-ugc reuses that scaffold.

What is different here is that almost all heavy work is remote and paid. Spikes run on 5 November 2026 (about $0.92 total) established the facts the design depends on:

- Replicate official models are called at `/v1/models/{owner}/{name}/predictions`; community models need `/v1/predictions` with a version id (404 otherwise). Accounts under $5 of credit are throttled to 6 predictions a minute (HTTP 429 with `retry_after`); out of credit is HTTP 402. Replicate has no price API, but model pages embed structured `prices` with `criteria` (resolution, audio, video input).
- Seedance 1.5 Pro accepts an undocumented `resolution: "480p"` and otherwise renders 720p. Seedance 2.5 accepts `image`, `last_frame_image`, `reference_images`, `reference_audios`, `resolution`, `generate_audio`. Kling 2.6 on Replicate uses `start_image`.
- Image-edit composites (Seedream 4.5, Nano Banana 2) keep the actor's identity and the product's label at full resolution; small label text garbles in motion at 480p and 720p, and neither first-plus-last-frame locking nor a fixed camera fixes it.
- A vision model on OpenRouter comparing a frame with the product photo catches label errors reliably through yes/no fields and an issues list (about $0.003–0.006 per frame); its 0–10 score does not discriminate.
- Native-audio video speaks an exact scripted line convincingly, but picks a different voice per clip without a reference.
- Whisper word timings over a concatenated ad drift about one second across silences; speech-model word timings plus known shot offsets do not.

## Goals / Non-Goals

**Goals:**
- One provider abstraction that all workflow steps use, so adding a provider or model touches data, not workflow code.
- Deterministic, resumable, cache-first execution: a crash, restart or re-render never pays twice.
- Everything that does not need a generative model (real-product shots, end cards, text, captions, stitching, mixing) runs locally with ffmpeg and is free.
- Tests that run offline and free in CI, with one opt-in live smoke test.

**Non-Goals:**
- Hosting, accounts, multi-user collaboration or a credit system.
- Training or fine-tuning models, or local generative models (all generation is through providers in v1).
- Voice cloning beyond what the user's own speech-provider account offers.
- Automatic social posting.

## Decisions

### D1. Repository layout mirrors popcaps
`src/oh_my_ugc/` with `api.py` (FastAPI), `cli.py`, `config.py`, `db.py` (SQLite), `doctor.py`, `jobs.py` (queue and workers), and domain packages: `providers/`, `catalog/`, `costs/`, `brands/`, `actors/`, `scripts/`, `storyboard/`, `fidelity/`, `clips/`, `assembly/`, `captions/` (vendored popcaps engine). `frontend/` builds into `src/oh_my_ugc/web/`, shipped in the wheel. Data lives under `OMU_HOME` (default `~/.oh-my-ugc`): `omu.db`, `media/` (content-addressed store), `projects/<id>/` (human-readable links and exports), `catalog/` (user catalog entries).
*Alternative:* a separate engine package shared with popcaps. Rejected for v1: popcaps pulls faster-whisper and MediaPipe as hard dependencies and its engine API is not yet stable.

### D2. Provider adapters share one job protocol
Each adapter (`replicate`, `fal`, `openrouter`, `elevenlabs`, `fish`) implements `upload(path) -> ref`, `submit(model, inputs) -> provider_job_id`, `poll(provider_job_id) -> status/outputs/billing`, `cancel(...)`, and `check_key()`. Synchronous providers (ElevenLabs, Fish, OpenRouter chat) complete in `submit` and return outputs immediately through the same interface. All use `httpx` with a shared retry policy: 429 waits for `retry_after` (or `Retry-After`), 5xx and network errors back off exponentially up to 3 times, 400/401/402/403/404/422 never retry and map to plain-English messages through one error table per provider.
Inputs that are local files are uploaded with the provider's file API (Replicate Files, fal storage) or inlined as a data URI where a provider requires it (OpenRouter). Outputs are downloaded into the media store before a job is marked done.
*Alternative:* the official Python SDKs. Rejected: three different async models, heavier dependencies, and they hide the HTTP status codes needed for plain errors and ledger accuracy.

### D3. Durable jobs in SQLite
A `jobs` table holds every unit of paid or long work (kind, project, shot, provider, model, input hash, provider job id, status, attempts, estimate, actual, error, timestamps). The provider job id is committed immediately after submit, so a restarted worker resumes polling rather than resubmitting (providers spec, resume scenario). Workers are threads in the app process (as in popcaps), with a per-provider semaphore (default 2, user-configurable). The CLI talks to the same database, so CLI- and web-started jobs are interchangeable; CLI `--wait` polls the job rows.
*Alternative:* a separate worker process or a task library such as Celery or RQ. Rejected: an extra service for a single-user local tool.

### D4. Content-addressed cache is the dedupe mechanism
Cache key = SHA-256 of canonical JSON of `{provider, model, version, mapped parameters with every file input replaced by its SHA-256, take}`, where `take` is 0 by default and increments on "New take". Before submitting, the job looks the key up in the `media` table and short-circuits on a hit (no ledger cost). Media files are stored once by content hash; projects reference them.
*Alternative:* caching by project and shot id. Rejected: it cannot detect identical requests across projects or hook variants (cost-tracking, variants scenario).

### D5. Catalog entries are data, discovery fills gaps
Curated entries are JSON files (bundled under `catalog/models/`, plus user files in `OMU_HOME/catalog/`) validated by a Pydantic schema: `id`, `provider`, `model`, `task`, `inputs` (map from workflow slots such as `first_frame`, `last_frame`, `reference_images`, `reference_audio`, `prompt`, `duration`, `resolution`, `aspect_ratio`, `audio` to provider parameter names, with value transforms such as `"480p"` strings or integer seconds), `extra` (fixed parameters, including ones missing from the provider schema), `limits` (durations, resolutions, aspect ratios, max references), `multi_shot` (boolean), and `price` (a small formula: unit (`second`, `image`, `1k_chars`, `token`, `run`) and a table keyed by criteria such as resolution and audio).
Discovery adapters produce the same entry shape automatically: OpenRouter `/api/v1/images/models` and `/api/v1/videos/models` metadata (first/last frame, durations, audio, `pricing_skus`), fal model search by category with OpenAPI schemas, Replicate collections with each version's OpenAPI input schema. Auto-mapping uses name heuristics (`image`/`start_image`/`first_frame_image` → `first_frame`, and so on); a model with no mappable required slot is listed as unavailable with the reason. Curated entries override discovered ones with the same id. Discovery results are cached for 24 hours.
*Alternative:* hard-coded adapters per model. Rejected: model churn is monthly.

### D6. Prices
Order of precedence: curated `price` → provider metadata (OpenRouter `pricing_skus`, fal endpoint pricing from its `llms.txt`, Replicate model-page `prices` and `criteria` parsed from the embedded JSON) → unknown. Actual cost: OpenRouter and fal return billed amounts or usage that is recorded directly; Replicate returns `metrics` (for example `predict_time` or video seconds) that are applied to the price table and recorded as "computed". The page parser for Replicate is isolated, fixture-tested, and degrades to "unknown" rather than failing jobs.

### D7. Budget enforcement reserves estimates
Starting an action inserts its estimate as a reservation inside the same SQLite transaction that checks `spent + reserved + estimate <= budget`; completion replaces the reservation with the actual cost. This prevents parallel shots from overshooting the cap together.

### D8. Language-model steps use structured output
Script writing, hook variants and storyboard drafting call the chosen language model (OpenRouter chat by default; any catalog `llm` entry) with a JSON schema. Prompts live as Markdown files in `prompts/`. Brand fields are injected as a labelled block; "claims to avoid" are additionally checked deterministically after generation by case-insensitive phrase matching (brand-kit, scripts specs).
**Script coverage invariant:** the storyboard model returns shots with lines, then the system deterministically re-aligns the script onto the shots with `difflib` (the same approach as popcaps `words.retime`), so the shots' lines always concatenate to the exact script even when the model paraphrases. Durations are recomputed from word counts (2.5 words a second, plus 0.4 s padding per talking shot) and scaled to the target length.

### D9. Storyboard frames are the clip's first frames
A frame is generated with the image-edit task, passing reference images in a fixed order: actor references, then the product's primary photo, then an optional setting image, plus a prompt assembled from the shot's framing, setting and action, and the actor and product descriptions. Frames are produced at the project aspect ratio and at least 1080 px on the short side so they are valid final-quality first frames. The approved frame's media hash is what the clip job maps to `first_frame`, and the optional end frame to `last_frame`; both are therefore part of the clip cache key (D4).
Visual fields (`type`, `framing`, `setting`, `action`, actor, product) are hashed into the frame's `basis`; a change to the basis marks the frame out of date and unapproves the shot. Line and on-screen text are outside the basis (storyboard spec, line-only edits).

### D10. Drift check
A vision-check job sends the product's primary photo, its label text, and the frame to the vision model with a strict JSON schema `{product_present, shape_matches, colors_match, text_matches, issues[]}`. A frame fails if `product_present` is false, any `*_matches` is false, or `issues` is non-empty with severity "major". Clips sample frames at 15%, 50% and 85% of their duration (more for clips over 8 s) with ffmpeg and check each. Shots of type `talking` without the product in frame skip the check.

### D11. Voice modes and timings
- **Voiceover and talking avatar:** each line is synthesised separately (ElevenLabs `with-timestamps`, Fish streaming alignment as in short-stock, or a catalog speech model). Word timings are stored per shot. Speech models that return no timings are aligned locally (see D13).
- **Native dialogue:** the line is put in the prompt as quoted speech; if the model has a `reference_audio` slot and the actor has a voice sample, it is passed. An actor's voice sample can be uploaded, or produced once by speaking a neutral sentence with their chosen speech voice, so native dialogue and voiceover use the same voice.
- **Talking avatar:** the frame and the shot's audio go to the talking-avatar or lip-sync entry (for example OmniHuman, InfiniTalk, HeyGen Avatar IV on OpenRouter).
Clip durations are snapped up to the model's nearest allowed duration and trimmed back in assembly; voiceover shots are sized to their audio length.

### D12. All text is rendered by libass
On-screen text, text cards, the end card and captions are compiled to ASS and burned in with ffmpeg's `ass` filter using the vendored popcaps modules (`ass`, `layout`, `presets`, `fonts`, `words`, `export` helpers). One text renderer means one font pipeline, exact brand strings, and identical output on Linux and macOS.
*Alternative:* `drawtext` for cards. Rejected: separate font handling and no word animation.

### D13. Local rendering with ffmpeg
- **Real-product shots:** the cutout (RGBA PNG) is overlaid on a background (blurred, darkened frame from the neighbouring shot, a solid brand colour, or an uploaded image) with a scale/position expression per motion preset (push-in, pan, parallax with a separately blurred background layer, rotate-in), rendered at the project resolution and 30 fps.
- **Stitching:** every chosen take is normalised (scale to cover plus crop to the aspect ratio, 30 fps, yuv420p, 48 kHz stereo AAC; silent clips get a silent track), trimmed to its shot length, and joined with the concat demuxer (or `xfade`/`acrossfade` where a crossfade is set).
- **Mix:** voice bus and music with `sidechaincompress` ducking, then `loudnorm` to -14 LUFS integrated, -1 dBTP.
- **Captions:** word timings from D11 offset by each shot's start time; native-dialogue shots are transcribed individually with faster-whisper (CPU `base` model, downloaded on first use) and re-timed onto the known line with `difflib`, so spelling always comes from the script. If faster-whisper is unavailable, words are spread across the clip's detected speech span (ffmpeg `silencedetect`).
- **Variants:** a variant is a list of shot ids; hook shots differ, body shots are shared, and the cache (D4) makes shared shots free.

### D14. Web app
React 19, Vite, Tailwind 4, TanStack Query, as in the siblings. Stage navigator (Brief, Script, Storyboard, Clips, Export) with a floating bottom console holding the current stage's primary actions and their cost estimates. Live job state uses polling at 1–2 s while jobs run (as in popcaps), avoiding WebSocket complexity. Fonts are bundled (no external CDN) so the UI works offline. The visual identity is chosen in a dedicated design pass before pages are built, following the family rules in the project context; it must be distinct from clipyyy (editorial), short-stock (velvet screenplay) and popcaps (keying stage).

### D15. Testing strategy
- **Providers:** `httpx.MockTransport` with recorded, key-scrubbed JSON fixtures from the spikes (Replicate 201/200/402/404/429, fal queue, OpenRouter models and chat), covering lifecycle, retries, resume and error text.
- **Catalog and prices:** schema validation of every bundled entry; mapping tests per entry; a Replicate pricing page fixture.
- **Costs:** estimate, reservation, ledger and cache-hit tests against a temporary SQLite database.
- **Workflow:** script coverage invariant, duration scaling, frame basis and approval rules, variant composition, with a fake provider that returns tiny generated media.
- **Rendering:** ffmpeg integration tests on synthetic two-second clips (real-product shot, stitch, mix, captions) asserting duration, size, audio presence and pixel checks.
- **Frontend:** vitest for pure logic and components; agent-browser click-through of every control at 1440 px and 390 px before release.
- **Live smoke** (opt-in, `OMU_LIVE=1`): one Seedance 1.5 Pro 480p silent clip and one Seedream frame on Replicate, about $0.10.

### D16. CLI
`argparse` with sub-commands as in popcaps (no extra dependency). `--json` prints one document to stdout; logs go to stderr. Long jobs return `{job_id}` unless `--wait`. `--estimate` runs the same estimation code path the web app uses and exits. Entry points `oh-my-ugc` and `omu`.

## Risks / Trade-offs

- [Model churn breaks curated mappings] → entries are data and versioned; discovery provides a fallback; CI validates entries; `omu doctor` reports entries whose model no longer exists.
- [Provider metadata or page format changes break price lookup] → curated prices take precedence; parsers are fixture-tested and degrade to "unknown" with a partial-total label rather than blocking work.
- [Generated labels drift in motion] → product truth layer (real-product shots, end card), clip drift check with one-click swap, and guidance in the UI to frame products large.
- [Native dialogue voices differ per clip] → voice references where supported; a warning otherwise; voiceover mode as the consistent default.
- [Costs surprise users] → estimates on every paid control, reservation-based budget caps, ledger, cache; drafts default to the cheapest settings.
- [Misuse of uploaded faces] → the owner's decision is no consent gate; the UI shows a one-line responsibility reminder, and the README includes AI-disclosure guidance for ads.
- [Long jobs and app restarts] → durable jobs with stored provider ids and resume-on-start.
- [Vision check false positives or negatives] → flags never block; the user can "Keep anyway"; results show the specific issues.
- [faster-whisper download size for captions on native-dialogue shots] → only needed for that mode; fallback timing without it.
- [Secrets in a public repo] → keys only in env or the local database (file mode 600); a secret scan runs before every push; fixtures are scrubbed.

## Migration Plan

New project, no migration. Release steps: build and verify locally and in Docker; owner creates `T3-Venture-Labs-Limited/ohmyugc`; push a single fresh commit; apply the family hardening (ruleset, settings, security features, contributor files); confirm CI is green on Linux and both macOS runners. Rollback is deleting or privatising the repository before announcement.

## Open Questions

- Exact request formats for OpenRouter's image and video generation endpoints and for HeyGen Avatar IV inputs: confirmed against the live API while writing the OpenRouter adapter (task 2.5); it affects adapter code only.
- The visual identity direction: decided in the design pass (task group 11) with the owner before page work.
- Which curated default model is set per task and provider: settled from the curated price table during catalog work; defaults are data and can change without spec changes.
