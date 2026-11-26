# Contributing to oh-my-ugc

Thanks for helping. oh-my-ugc takes contributions through pull requests from forks. Nobody outside the maintainers pushes to this repository directly, and `main` only changes through reviewed pull requests.

## How to contribute

1. **Open an issue first for anything bigger than a small fix**, so we can agree on the approach before you spend time on it.
2. **Fork** the repository and create a branch from `main`.
3. Make your change, with tests where it makes sense.
4. Run the checks below until they pass.
5. **Open a pull request** against `main`. Describe what changed, why, and how you tested it. Add a screenshot or short clip for anything visual.

A maintainer reviews every pull request. CI must pass before it can be merged. Workflows on pull requests from first-time contributors start after a maintainer approves them.

## Add a model

New video and image models appear every month. Every model is one JSON file in [`src/oh_my_ugc/catalog/models/`](src/oh_my_ugc/catalog/models/). You can also drop the same file into `~/.oh-my-ugc/catalog/` to use a model without waiting for a release.

```json
{
  "id": "replicate/seedance-2.5",
  "provider": "replicate",
  "model": "bytedance/seedance-2.5",
  "name": "Seedance 2.5",
  "task": "image_to_video",
  "inputs": {
    "prompt": "prompt",
    "first_frame": "image",
    "last_frame": "last_frame_image",
    "reference_audio": {"param": "reference_audios", "as": "list"},
    "duration": {"param": "duration", "as": "int"},
    "resolution": "resolution",
    "audio": {"param": "generate_audio", "as": "bool"}
  },
  "limits": {"durations": [4, 5, 6, 7, 8, 9, 10], "resolutions": ["480p", "720p"]},
  "multi_shot": true,
  "native_audio": true,
  "price": {"unit": "second", "table": [{"when": {"resolution": "480p"}, "price": 0.10}, {"when": {"resolution": "720p"}, "price": 0.23}]}
}
```

`inputs` maps oh-my-ugc's slots (`first_frame`, `last_frame`, `reference_images`, `reference_audio`, `prompt`, `duration`, `resolution`, `aspect_ratio`, `audio`, `seed`, and `text`, `voice`, `speed`, `image`, `video` for the other tasks) to the model's own parameter names. `extra` holds fixed parameters, including ones missing from the provider's published schema. Prices come from the provider's page or API, with the source in the pull request. Before opening it:

- run a real generation with the entry and say what it cost, or mark the entry as untested;
- run `uv run pytest tests/test_catalog.py`, which checks that every slot maps.

A model its provider retires is hidden from the pickers automatically (oh-my-ugc checks each provider's public pages once a day), so a retired entry can simply be deleted in a pull request.

Use the "Model request" issue form if you just want one added.

## Development setup

Requires Python 3.11 or 3.12, Node 22+, [uv](https://docs.astral.sh/uv/) and ffmpeg with libass.

```bash
uv sync
npm --prefix frontend ci
npm --prefix frontend run dev     # web app on :5173, proxies /api to :8000
uv run omu serve --no-open        # API and worker on :8000
```

[`AGENTS.md`](AGENTS.md) maps the codebase. Tests never call a paid provider: they use recorded fixtures and a fake provider that returns tiny real media. An opt-in live check (`OMU_LIVE=1 uv run pytest tests/test_live.py`) runs one cheap Replicate generation (about $0.10) with your own key.

## Checks

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

For changes to the web app, click through the controls you touched at desktop width and at phone width (390 px) before opening the pull request. For changes to rendering, look at a frame of the exported video.

## Guidelines

- Keep pull requests focused: one change per pull request.
- Match the existing style. The web app has its own visual identity; discuss larger design changes in an issue first.
- Never commit API keys, personal photos, generated media of real people or other private data.
- By contributing you agree that your work is released under the [MIT licence](LICENSE).

## Your own version

oh-my-ugc is MIT licensed. You are welcome to fork it and take it in your own direction without contributing back.
