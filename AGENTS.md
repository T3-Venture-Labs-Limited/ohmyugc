# oh-my-ugc codebase map

oh-my-ugc makes UGC-style video ads: product photos, brand context and a script in, AI-actor video out, using the user's own provider keys. Python 3.11+ (FastAPI, SQLite) with a React + Vite web app. The behaviour is specified in `openspec/` (specs per capability, design decisions D1–D16).

## Layout

- `src/oh_my_ugc/providers/`: one adapter per provider (`replicate`, `fal`, `openrouter`, `speech` for ElevenLabs and Fish). `base.py` has the HTTP layer: 429 waits for `retry_after`, 5xx retries, 4xx never retries, one plain sentence per error, key redaction.
- `catalog/`: `models/*.json` are curated model entries (slot to parameter mapping, limits, price). `discover.py` turns live provider listings into entries. `load.py` merges them, picks defaults and explains what is missing.
- `runner.py`: `call()` runs one paid call: cache, budget reservation, upload, submit, poll, download, ledger. Re-running after a crash resumes the provider job from the `calls` table instead of paying twice. `jobs.py` runs user-visible work in background threads.
- `costs.py`: prices, estimates, ledger, budget reservations, the content-addressed cache. `store.py` keeps every file once by hash.
- The workflow: `brands.py`, `products.py` (cutouts), `actors.py`, `scripts.py` (writing, hooks), `storyboard.py` (draft, frames, approval, blocks), `fidelity.py` (vision drift check), `render_local.py` (real-product shots, no model), `voice.py`, `clips.py`, `assembly.py` (stitch, mix, captions, export), `texts.py` (all on-screen text through libass).
- `captions/`: the caption engine vendored from popcaps. `api.py`, `cli.py` (every command takes `--json`), `doctor.py`, `db.py`, `config.py`, `prompts/*.md`.
- `frontend/src/`: the web app. Stages live in `pages/stages/`. `components/ui.tsx` has the primitives, including the floating `Console`.

## Rules that keep it working

- Every paid call goes through `runner.call`; every LLM call through `llm.chat_json`. Both record the ledger and check the budget.
- Never print or log a key. `config.mask` for display, `providers.base.redact` for anything that might carry one.
- The script is the single source of truth for words: storyboard lines are re-aligned onto it with difflib, captions use script spelling.
- Real-product shots and the end card use pixels from the original upload; text is drawn by libass, never by a model.
- Never call `ffmpeg` by name: use `media.ffmpeg_bin()`. On macOS the build that can draw text is Homebrew's `ffmpeg-full`.
- Errors shown to people are one plain sentence (`OmuError.message`); detail stays in `OmuError.detail`.

## Checks

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q
npm --prefix frontend test && npm --prefix frontend run build
```
