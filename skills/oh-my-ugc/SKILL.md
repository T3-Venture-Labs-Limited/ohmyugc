---
name: oh-my-ugc
description: Make UGC-style video ads (AI actor, real product, captions) from product photos and a script with the oh-my-ugc CLI. Use when the user wants a UGC ad, a product video with an AI actor, hook variants for testing, or a cost estimate for one. Every command prints JSON with --json.
---

# oh-my-ugc

`omu` (alias `oh-my-ugc`) turns product photos, brand context and a script into UGC video ads. The user brings their own provider keys (Replicate, fal, OpenRouter, ElevenLabs, Fish Audio) and pays the providers directly, so **show costs before spending and wait for the user's go-ahead on anything paid**.

Rules for agents:

- Always pass `--json`. Standard output is exactly one JSON document; progress goes to standard error. Failures exit non-zero with `{"error": "<plain sentence>"}`; show that sentence to the user.
- Steps that spend money accept `--estimate`: it prints the cost and calls no model. Run it first and tell the user the total.
- Long steps return job ids; add `--wait` to block until they finish.
- Never print or ask the user to paste API keys into chat. Tell them to run `omu keys set <provider> <key>` themselves or add keys in the web app (`omu serve`).
- Products are added only from photo files the user provides. Quote the exact text printed on the label with `--label`; the app checks generated frames against it.
- The first approval gate is the storyboard: show the user the shots (`storyboard show`) and get approval before rendering clips.

## Workflow

Check the setup, then build the brand, product, actor and project:

```bash
omu doctor --json
omu keys test replicate --json
omu brands create --name "Acme" --cta "Shop now" --offer "20% off this week" --must-mention "vitamin C" --avoid-claims "cures acne" --json
omu products add --brand $BRAND --name "LUMA Vitamin C Serum" --photo $PHOTO --label "LUMA Vitamin C Serum" --facts "30 ml. Light texture." --wait --json
omu actors add --name "Maya" --photo $FACE --voice-provider elevenlabs --voice $VOICE --description "woman in her late 20s" --json
omu projects create --name "Serum ad" --brand-id $BRAND --product-id $PRODUCT --actor-id $ACTOR --target-seconds 20 --voice-mode voiceover --json
```

Give the project a script (paste your own, or have the user's language model write one):

```bash
omu script set $PROJECT --file $SCRIPT --json
omu script show $PROJECT --json
omu script hook $PROJECT --text "Stop scrolling right now." --json
```

(`omu script write $PROJECT --estimate --json` then `omu script write $PROJECT --wait --json` writes one from the brand context; `omu script hooks $PROJECT --wait --json` writes hook variants.)

Draft and approve the storyboard. Frames cost a few cents each; their images become the first frames of the video clips:

```bash
omu storyboard draft $PROJECT --estimate --json
omu storyboard draft $PROJECT --wait --json
omu storyboard frames $PROJECT --estimate --json
omu storyboard frames $PROJECT --wait --json
omu storyboard show $PROJECT --json
omu storyboard warnings $PROJECT --json
omu storyboard approve $PROJECT --json
```

A shot whose `frame_drift.status` is `flagged` has a product mismatch (for example a misspelled label): regenerate it, or change its type to `real_product`: `omu storyboard edit --shot $SHOT --type real_product --json`.

Render clips as a cheap draft first, then final quality, then assemble:

```bash
omu render $PROJECT --quality draft --estimate --json
omu render $PROJECT --quality draft --wait --json
omu render $PROJECT --quality final --estimate --json
omu render $PROJECT --quality final --wait --json
omu assemble $PROJECT --wait --json
omu spend $PROJECT --json
```

`omu assemble $PROJECT --all --wait --json` also exports every kept hook variant. The result's `path` is the MP4 (and `srt_path` the captions file).

## Other commands

- `omu models list --task image_to_video --connected --json`: models the user can run now; `omu models refresh` rediscovers models. There is no automatic default: a step fails with "No ... model chosen" until the user picks one. Show the user the list with prices and let them choose; never pick a model for them. Then `omu models default --task image_to_video <id>` sets it for every ad (leave `<id>` out to clear the choice). `omu doctor --json` lists the steps still unchosen.
- `omu projects budget $PROJECT --json` and `omu projects update $PROJECT --budget 5 --json`: a budget stops any step that would go over it.
- `omu jobs list --json`, `omu jobs show <id> --json`, `omu jobs cancel <id> --json`.
- `omu serve` opens the web app.
