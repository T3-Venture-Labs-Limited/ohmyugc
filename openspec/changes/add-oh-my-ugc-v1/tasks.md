# Tasks

## 1. Scaffold

- [x] 1.1 Create the Python package `src/oh_my_ugc/` (config, db, api, cli, jobs modules per design D1) with `pyproject.toml` (Python 3.11–3.12, hatchling, entry points `oh-my-ugc` and `omu`), ruff and pytest config; verify `uv sync` succeeds and `omu --help` and `oh-my-ugc --help` both print usage
- [x] 1.2 Implement `OMU_HOME` data layout (`omu.db`, `media/`, `projects/`, `catalog/`) and SQLite schema with migrations (settings, brands, products, actors, projects, shots, frames, takes, jobs, media, ledger, variants); verify a pytest creates a fresh home, runs migrations twice idempotently, and the database file is created with mode 600
- [x] 1.3 Scaffold `frontend/` (React 19, Vite, Tailwind 4, TypeScript, TanStack Query, vitest) building into `src/oh_my_ugc/web/`, served by FastAPI with `index.html` sent as no-cache; verify `npm run build` then `omu serve` serves the placeholder page on localhost
- [x] 1.4 Vendor the popcaps caption engine modules (`ass`, `layout`, `presets`, `fonts` with OFL licences, `words`, export helpers) into `src/oh_my_ugc/captions/` with a provenance note and no faster-whisper or MediaPipe imports at module load; verify an import test and a compile test that burns one caption onto a synthetic clip with ffmpeg
- [x] 1.5 Add `find_ffmpeg()` with libass detection and the macOS `ffmpeg-full` search order used by the sibling tools; verify unit tests for the search order and a doctor-style check on the local ffmpeg

## 2. Providers

- [x] 2.1 Build the shared HTTP layer (httpx client, retry policy for 429/5xx/network, no retry for 400/401/402/403/404/422, per-provider plain-English error table, key redaction in logs) per design D2; verify MockTransport tests for each status class including that 402 and 422 are attempted exactly once
- [x] 2.2 Implement provider key storage and resolution (settings table, env-var precedence, last-four display, `check_key()` free requests) per the providers spec; verify tests that no API response or log line contains a full key and that env overrides stored keys
- [x] 2.3 Implement the Replicate adapter (Files upload, official vs community routing with automatic version lookup, submit, poll, cancel, output download, `retry_after` handling, metrics capture); verify fixture tests for 201/200/402/404/429 and the community-model path
- [x] 2.4 Implement the fal adapter (storage upload, queue submit, status, result, cancel, billing capture); verify fixture tests for queued → completed, failed and invalid-key cases
- [x] 2.5 Implement the OpenRouter adapter (chat with JSON schema output and image inputs, image generation, video generation, model metadata) after confirming the live request formats for image and video generation and HeyGen Avatar IV with one cheap call each; record scrubbed fixtures and verify fixture tests for each endpoint. Result: chat, image and video formats confirmed live (Seedream 4.5 needs 2K or larger; Seedance 1.5 Pro 4 s at 480p billed $0.0487 against a $0.0461 estimate). **HeyGen Avatar IV is not confirmed**: the account's OpenRouter credit is below the request's worst-case cost (HTTP 402 before any input validation), so its image/audio inputs stay unmapped and it is listed as unavailable until someone verifies and adds a catalog entry
- [x] 2.6 Implement the ElevenLabs (`with-timestamps`) and Fish Audio (streaming alignment) speech adapters returning audio plus word timings; verify fixture tests that word timings are returned in seconds and cover every word
- [x] 2.7 Implement durable jobs (design D3): job rows with provider job id committed after submit, worker threads with per-provider concurrency, resume of running jobs on start, timeouts with cancel; verify tests that a simulated restart resumes polling without a second submit and that a timeout produces the plain-English message

## 3. Model catalog

- [x] 3.1 Define the catalog entry schema (task, inputs mapping with transforms, extra parameters, limits, multi_shot, price formula) per design D5, with loading from bundled and user folders and invalid-file reporting; verify tests for a valid entry, an invalid user file reported with its reason, and user entries overriding bundled ones
- [x] 3.2 Write curated entries for every task type across Replicate, fal and OpenRouter, including Seedance 1.5 Pro (with the undocumented `resolution`), Seedance 2.5 (`reference_audios`), Kling 2.6, Seedream 4.5, Nano Banana 2, Qwen Image Edit 2511, OmniHuman, a background remover, a speech model and default LLM and vision models, plus per-provider defaults; verify a test that every bundled entry validates and maps every declared slot, and that each task type has a default with only an OpenRouter key set or a stated provider requirement
- [x] 3.3 Implement live discovery for OpenRouter (image and video model lists), fal (category search plus OpenAPI) and Replicate (collections plus version schema) with heuristic slot mapping, unavailable-with-reason marking and a 24-hour cache; verify fixture tests for a mappable model, an unmappable model ("no first-frame input") and a failing listing that leaves curated models available
- [x] 3.4 Expose catalog API and CLI (`omu models [--task] [--refresh] --json`); verify an API test filtering by task and a CLI JSON output test

## 4. Cost tracking

- [x] 4.1 Implement price resolution (curated → provider metadata → Replicate page parser → unknown) with criteria such as resolution, audio and duration, cached for 24 hours, per design D6; verify tests including the Replicate pricing-page fixture and a resolution/audio change producing the right price
- [x] 4.2 Implement estimates for every paid action and for full draft/final renders, with partial totals when a price is unknown; verify tests for a five-shot storyboard estimate and the "price unknown" partial label
- [x] 4.3 Implement the ledger (estimated vs actual or computed cost, zero for unbilled failures) and spend reports per project, step and provider; verify tests and a `omu spend --json` output test
- [x] 4.4 Implement budget caps with transactional reservations (design D7); verify tests for the over-budget refusal message and that two parallel reservations cannot jointly exceed the cap
- [x] 4.5 Implement the content-addressed cache and "New take" (design D4) shared by all paid jobs; verify tests that an identical request is a free cache hit, a changed input file hash misses, and a new take misses

## 5. Brand kit and actors

- [x] 5.1 Implement brands (all context fields, logo, CRUD) via API and CLI; verify API tests for minimal and full brands and CLI JSON tests
- [x] 5.2 Implement products (1–8 photos, primary photo, facts, label text, format and 20 MB limits, manual upload only) via API and CLI; verify tests that HEIC and oversized files are rejected with the stated limits
- [x] 5.3 Implement automatic cutouts with the background-removal task and user-supplied cutout replacement, never modifying originals; verify a fake-provider test and the no-model fallback message
- [x] 5.4 Implement actors from description (N candidates with estimate) and from uploaded photo (responsibility reminder, no consent gate), extra references, default voice (provider voice id or uploaded or generated voice sample), library CRUD and safe deletion; verify API tests including that deleting a used actor keeps the project's frames and clips

## 6. Scripts and hooks

- [x] 6.1 Implement pasted scripts kept verbatim; verify a test that the stored script is byte-identical after save and storyboard drafting
- [x] 6.2 Implement AI script writing with prompt files, brand block, formats (talking head with product, problem and solution, unboxing, demo voiceover, testimonial), target length at about 2.5 words a second and must-mention coverage, plus deterministic claims-to-avoid detection; verify fake-LLM tests for word-count range, must-mention presence, the claims warning, and the disabled state with no LLM
- [x] 6.3 Implement hook variants (generate or write, edit, keep, discard) stored as project variants; verify tests that kept hooks appear as export variants

## 7. Storyboard

- [x] 7.1 Implement storyboard drafting with structured LLM output and the deterministic script re-alignment and duration scaling of design D8; verify tests that the shots' lines concatenate to the exact script even when the fake LLM paraphrases, and that durations sum within 15% of the target
- [x] 7.2 Implement preview frame generation (references order, prompt assembly, aspect ratio, minimum 1080 px short side), local previews for real-product shots, and automatic drift check for product shots; verify fake-provider tests that only non-real-product shots call the model and the estimate counts them
- [x] 7.3 Implement storyboard editing (fields, reorder, add, duplicate, delete, regenerate with note, upload replacement, change actor), frame history, basis hashing and approval rules (design D9); verify tests that visual edits unapprove and mark frames out of date while line-only edits do not
- [x] 7.4 Implement end frames (generated, uploaded, or the next shot's frame) and multi-shot blocks (grouping limited by model duration and `multi_shot` support, combined prompt); verify tests for the unsupported-end-frame warning and an 8-second two-shot block request

## 8. Product fidelity

- [x] 8.1 Implement the frame drift check with the strict JSON schema and pass/fail from booleans and issues (design D10), with "not checked" when no vision model exists; verify fixture tests for a misspelled label, a clean frame and no-model behaviour
- [x] 8.2 Implement clip drift checks on sampled frames (15/50/85%, more for long clips) with the failing timestamp recorded; verify a test with a fake vision model that fails only the middle frame
- [x] 8.3 Implement real-product shot rendering (push-in, pan, parallax, rotate-in over blurred neighbour frame, brand colour or uploaded background) with ffmpeg per design D13; verify integration tests on synthetic inputs for duration, resolution and that the product region's pixels match the cutout
- [x] 8.4 Implement the end card (cutout, product name, CTA, offer, optional logo, 1.5–5 s) with text drawn through libass; verify an integration test that renders the end card and checks duration and non-empty text region

## 9. Clip generation

- [x] 9.1 Implement clip jobs that map the approved frame to `first_frame`, the end frame to `last_frame`, duration snapping, draft (cheapest resolution, silent unless native audio) and final quality, and final for a subset of shots; verify fake-provider tests asserting the mapped request parameters for draft and final
- [x] 9.2 Implement the three voice modes (native dialogue with reference audio and the no-reference warning; voiceover with per-line speech and timings over silent clips; talking avatar from frame plus line audio) with silent generation for line-less shots; verify tests per mode asserting provider requests
- [x] 9.3 Implement takes (list, play, choose, new take with changed prompt, trim, switch to real-product shot, clear old takes) and automatic clip drift checks; verify API tests for choosing a take and swapping to a real-product shot
- [x] 9.4 Expose render progress per shot (queued, rate-limited, running, checking, done, failed with reason) through the API and `omu render --wait --json`; verify a test where one of six fake shots fails and the rest finish

## 10. Assembly and export

- [x] 10.1 Implement stitching (normalise scale/crop, 30 fps, audio track for silent clips, trim or hold to line length, optional crossfade) for 9:16, 1:1, 4:5 and 16:9; verify integration tests on mixed-resolution synthetic clips for output size, duration and audio presence
- [x] 10.2 Implement the audio mix (voice, uploaded music with sidechain ducking, loudnorm to -14 LUFS); verify an integration test that music level during speech is at least 6 dB below its level in a gap and integrated loudness is within 1 LU of -14
- [x] 10.3 Implement captions from speech timings plus shot offsets, per-clip transcription with re-timing for native-dialogue shots, the silence-detect fallback, and script spelling (design D13); verify tests that "LUMA" stays spelled from the script and that offset words land within 0.1 s
- [x] 10.4 Implement on-screen text per shot and full-screen text cards through libass; verify an integration test that the text appears only during its shot
- [x] 10.5 Implement export (MP4 H.264/AAC, optional SRT) and hook variants sharing a cached body; verify a test that three variants produce three files and only the hook shots trigger provider calls

## 11. Web app

- [x] 11.1 Run the visual identity design pass (palette, type, layout, floating bottom console, shot cards) following the family design rules, distinct from clipyyy, short-stock and popcaps; present the direction to the owner and record the approval. Result: the direction was chosen without a separate pre-build mock (the owner asked for end-to-end execution): a warm "shelf label" look, Bricolage Grotesque with Instrument Sans, hard ink edges with flat offset shadows, one clay red for the action to press, and the floating bottom console. The finished UI is the thing for the owner to review; changing the look is a CSS-and-tokens job
- [x] 11.2 Build the app shell, API client, first-run settings (provider keys with test buttons, defaults, concurrency, budgets) and library pages (projects, brands and products, actors, spend); verify vitest tests for the API client and a manual check of first-run redirect to settings
- [x] 11.3 Build the Brief and Script stages (brand, product, actor, format, length, platform, voice mode, models with estimates; paste or write script, claims warnings, hooks); verify by clicking every control at 1440 px and 390 px
- [x] 11.4 Build the Storyboard stage (shot cards with frames, drift badges, edit, reorder, regenerate, upload, end frames, blocks, approvals, running estimate) with keyboard support; verify by clicking every control at 1440 px and 390 px, and keyboard-only navigation of shot actions
- [x] 11.5 Build the Clips stage (live per-shot progress, players, takes, drift results, new take, trim, swap to real-product shot) and the Export stage (preview, captions style, music, end card, variants, download); verify by clicking every control at 1440 px and 390 px
- [x] 11.6 Add cost display on every paid control, the project header spend and budget, stage gating with "what's missing" messages and confirm-before-discard; verify vitest tests for gating logic and a click-through of going back from Storyboard to Script

## 12. CLI, doctor and agent skill

- [x] 12.1 Complete CLI coverage (serve, config, keys, models, brands, products, actors, projects, script, hooks, storyboard, frames, approve, render, assemble, export, spend, jobs) with `--json`, `--wait` and `--estimate`, one JSON document on stdout and `{"error": ...}` with non-zero exit; verify CLI tests for parsable output and error format on every command
- [x] 12.2 Implement `omu doctor` (ffmpeg and libass, folders, provider keys, catalog health with missing-model detection) with OS-specific hints; verify tests including the macOS `ffmpeg-full` hint
- [x] 12.3 Write `skills/oh-my-ugc/SKILL.md` and `llms.txt` covering the CLI workflow with estimates and approvals; verify every command in the skill runs against a fake-provider home in a test

## 13. Packaging, CI and docs

- [x] 13.1 Add the Dockerfile (Node build stage, Python slim with ffmpeg and libass) and docker-compose; verify `docker build` succeeds and `omu doctor` passes inside the container
- [ ] 13.2 Add CI (`backend`: ruff and pytest; `frontend`: typecheck, vitest, build; `macos` on `macos-latest` and `macos-15-intel` with `ffmpeg-full`); verify all jobs pass on a branch push once the repository exists
- [x] 13.3 Write README (pitch, demo GIF, quick start, provider setup, cost table, model list, product truth layer, macOS notes, AI-disclosure guidance), CONTRIBUTING, SECURITY, CODEOWNERS, PR template, issue forms (including a "model request" form), MIT licence for T3 Venture Labs Limited; verify links and commands in the README by running them

## 14. End-to-end verification and release

- [x] 14.1 Run the opt-in live smoke test (`OMU_LIVE=1`: one Seedream frame and one Seedance 1.5 Pro 480p silent clip on Replicate, about $0.10) and check that ledger costs match the Replicate billing for those predictions
- [x] 14.2 Make one full demo ad end to end through the web app with the fictional LUMA product (frames, draft, final for at least two shots, real-product shot, end card, captions, two hook variants) within an agreed small budget, and save the README demo assets
- [x] 14.3 Do the full click-through QA of every control at desktop and 390 px in a fresh browser session, fix every finding, and record the checklist
- [ ] 14.4 Run the secret-value scan and check for private references, create a single fresh commit, push to `T3-Venture-Labs-Limited/ohmyugc` once the owner creates it, apply the family repository hardening, and verify CI is green on main
