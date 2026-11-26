# Release click-through (6 November 2026)

Every control in the web app was clicked and its effect checked, in a fresh browser session, at 1440 px and at 390 px wide, against the real app running on a fake provider (tiny real media, instant). A separate run used real Replicate, OpenRouter and ElevenLabs keys to make the demo ad. 129 checks passed on desktop and 119 on a phone-width screen (the keyboard checks run on desktop only), including that no page scrolls sideways.

| Area | What was clicked and asserted |
|---|---|
| First run | With no key, `/` opens Settings once, explains what each provider is for; the brief warns that nothing can be generated |
| Settings | Save key (never shown again), Test, Remove, defaults per step, concurrency, budget, find new models, setup check |
| Brands | New brand (empty name is refused), edit, logo upload, delete asks twice |
| Products | Add (photos, label text; empty product refused), edit, make main photo, remove photo, add photos, make cutout, upload own cutout, delete |
| Actors | Upload a photo (likeness reminder, no consent gate), describe and generate (cost first), choose a portrait, more candidates, discard, side view as a reference, voice picker, voice sample, details, delete asks twice |
| Ads | New ad, duplicate, delete asks twice |
| Brief | Brand, product, actor, format, length, platform, shape, voice mode, final quality, caption style, budget, notes, every model picker |
| Script | Write with AI (replace asks first), edit, save, claims-to-avoid warning, hooks (write, add, keep, delete), keep or redraft after an edit |
| Storyboard | Draft, make pictures, approve, edit a line (stays approved), edit the camera (unapproves), regenerate with a note, earlier pictures, own picture, end picture, group and split a block, move, duplicate, delete, add a shot, add a text card, approve all, redraft asks first |
| Clips | Render draft, cost breakdown, players, product check result, new take, preview and choose a take, trim, clear other takes, real-product swap, final render |
| Export | Captions on and off, style, music upload and level, crossfade, end card (call to action, offer, seconds, background, image), hook clips, export, export with hooks, downloads |
| Spend | Totals, by ad, recent calls |
| Keyboard | Every shot action is reachable with Tab, Enter triggers it, a visible focus ring, focused controls scroll clear of the floating bar, every control has a label, every image has alt text |

Contrast: every text and background pair in the theme is at least 4.5:1.
