# Proposal

## Why

Brands pay MakeUGC, Arcads and similar tools $50–280 a month in credits for AI UGC ads, and their users' most common complaints are distorted products (garbled labels, changed shapes), opaque credit billing that charges for failed renders, and a generic "AI UGC" look. No polished open-source alternative exists. Current models on Replicate, fal and OpenRouter (verified November 2026) can produce consistent actors, product-in-hand frames, multi-shot clips and exact spoken lines for about $1–7 per 30-second ad, so a self-hosted tool where users pay providers at cost, keep the real product in every shot, and control each step is now practical.

## What Changes

- New application **oh-my-ugc**: a local web app, a JSON CLI (`oh-my-ugc`, alias `omu`) and an agent skill that turn manually uploaded product photos, brand context and a script into UGC video ads with AI actors.
- **Bring-your-own-key providers**: Replicate, fal and OpenRouter for image, video, talking-avatar, lip-sync, background-removal and language models; ElevenLabs and Fish Audio for voices. Users pick the model for each step.
- **A model catalog** combining curated entries with live discovery from each provider, so new models appear without code changes.
- **Cost control**: an estimate before every paid step, an actual-cost ledger, a per-project budget cap, and caching so nothing is paid for twice.
- **Brand kit**: brand context fields (voice, audience, must-mention points, claims to avoid, offer, CTA) and products with photos, facts and automatic cutouts.
- **Actors**: generated or uploaded (any photo, no consent check), reused as consistent references.
- **Scripts**: pasted or written by the user's own language model from the brand and product context, plus opening-hook variants for testing.
- **Storyboard**: a drafted shot list with a cheap preview image per shot that the user edits and approves; approved images become the first (and optionally last) frames for image-to-video.
- **Product fidelity**: an automatic vision check that compares generated frames and clips with the real product photo, and a product truth layer that uses the real photo for close-ups, reveals and the end card.
- **Clip generation**: three voice modes (native dialogue with a voice reference, voiceover over silent video, voiceover driving a talking-avatar model), multi-shot blocks, and draft (480p) then final (720p/1080p) rendering, with per-shot review and regeneration.
- **Ad assembly**: stitching, voice, ducked music, captions (popcaps engine) timed from voiceover word timings, text cards and end card; export one ad or several hook variants of the same body.
- **Distribution**: Docker image, macOS and Linux support, README and agent skill, published under the T3 Venture Labs organisation with the same repository hardening as its siblings.

## Capabilities

### New Capabilities

- `providers`: connections to Replicate, fal, OpenRouter, ElevenLabs and Fish Audio: file upload, job submission, polling, downloads, rate-limit and out-of-credit handling, and plain-English errors.
- `model-catalog`: the task types (image edit, image-to-video, talking avatar, lip sync, speech, background removal, language model, vision check), curated model entries with parameter mapping, and live model discovery per provider.
- `cost-tracking`: price lookup per model, estimates before spending, the actual-cost ledger, budget caps and content-addressed caching of outputs.
- `brand-kit`: brands with context fields, and products with photos, facts and automatic cutouts.
- `actors`: creating actors from a prompt or an uploaded photo, character references and the actor library.
- `scripts`: pasted scripts, AI-written scripts from brand and product context, and hook variants.
- `storyboard`: drafting shot lists from a brief, generating preview frames, editing and approving the storyboard.
- `product-fidelity`: the vision drift check on frames and clips, and the product truth layer (real-photo shots and end card).
- `clip-generation`: generating each approved shot as a video clip with the chosen model and voice mode, multi-shot blocks, draft and final quality, and clip review and regeneration.
- `ad-assembly`: stitching clips into finished ads with voice, music, captions, text cards and end card, hook variants, and exports.
- `cli`: the `oh-my-ugc`/`omu` command line with JSON output for scripts and agents.
- `web-app`: the local web interface for the whole workflow, with its own visual identity.

### Modified Capabilities

None (new project).

## Impact

- New repository `T3-Venture-Labs-Limited/ohmyugc` (Python package `oh_my_ugc`, frontend in `frontend/`).
- External services called with the user's own keys: Replicate, fal, OpenRouter, ElevenLabs, Fish Audio. Users incur provider charges; the app must make them visible before they happen.
- Reuses the popcaps caption engine (vendored modules) and the clipyyy/shortstock application scaffold.
- System dependencies: ffmpeg with libass (Homebrew `ffmpeg-full` on macOS), Python 3.11–3.12, Node 22 for building the web app.
- Out of scope for v1: store integrations (Shopify and others), built-in voice cloning, social publishing, team accounts, hosted service.
