"""Shared builders for workflow tests."""

from __future__ import annotations

import io

from oh_my_ugc import actors, brands, db, products, projects, scripts, storyboard

SCRIPT = (
    "Okay, I have to tell you about this serum. Two drops every morning, and my skin looks brighter by lunch. "
    "It is light, it smells fresh, and it did not break me out. Link is right here."
)


def make_png(color=(200, 60, 60), size=(240, 320), text=None) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    d.rectangle((size[0] // 4, size[1] // 5, size[0] * 3 // 4, size[1] * 4 // 5), fill=(250, 250, 250))
    if text:
        d.text((size[0] // 3, size[1] // 2), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_cutout_png() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (240, 320), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((60, 40, 180, 300), radius=30, fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_world(*, voice_mode="voiceover", with_actor=True, budget=None, **extra):
    brand = brands.create(
        {
            "name": "Acme",
            "cta": "Shop now",
            "offer": "20% off this week",
            "must_mention": "vitamin C\nlight texture",
            "avoid_claims": "cures acne",
        }
    )
    product = products.create(
        brand["id"],
        "LUMA Vitamin C Serum",
        [("front.png", make_png(text="LUMA")), ("side.png", make_png((60, 120, 200)))],
        facts="30 ml. Light texture.",
        label_text="LUMA Vitamin C Serum",
    )
    actor = None
    if with_actor:
        actor = actors.from_photo(
            "Maya", "maya.png", make_png((220, 180, 150), (240, 320)), "woman in her late 20s"
        )
        actors.update(actor["id"], {"voice_provider": "elevenlabs", "voice_id": "voice123"})
    project = projects.create(
        {
            "name": "Serum ad",
            "brand_id": brand["id"],
            "product_id": product["id"],
            "actor_id": actor["id"] if actor else None,
            "target_seconds": 20,
            "voice_mode": voice_mode,
            "budget": budget,
            "script": SCRIPT,
            **extra,
        }
    )
    return brand, product, actor, project


def storyboard_reply(lines):
    """A fake LLM storyboard for the given lines (the last shot is a real-product shot)."""
    shots = []
    kinds = ["talking", "product_in_hand", "cutaway", "real_product"]
    for i, line in enumerate(lines):
        shots.append(
            {
                "purpose": ["hook", "demo", "proof", "cta"][min(i, 3)],
                "type": kinds[min(i, 3)],
                "framing": f"handheld selfie, chest up, angle {i}",
                "setting": "bright kitchen",
                "action": f"She holds up the serum bottle, take {i}.",
                "line": line,
                "onscreen": "",
                "duration": 4,
            }
        )
    return {"shots": shots}


def draft_storyboard(fakes, project_id, lines=None, paraphrase=False):
    lines = lines or [
        "Okay, I have to tell you about this serum.",
        "Two drops every morning, and my skin looks brighter by lunch.",
        "It is light, it smells fresh, and it did not break me out.",
        "Link is right here.",
    ]
    sent = [(" ".join(reversed(l.split())) if paraphrase else l) for l in lines]
    fakes["openrouter"].llm_reply = lambda messages, schema: storyboard_reply(sent)
    return storyboard.draft(project_id, replace=True)


def approved_storyboard(fakes, project_id):
    shots = draft_storyboard(fakes, project_id)
    for s in storyboard.shots_of(project_id):
        if s["type"] != "real_product":
            db.update(
                "shots",
                s["id"],
                {
                    "frame": __import__("oh_my_ugc.store", fromlist=["x"]).put_bytes(make_png(), "png"),
                    "frame_basis": storyboard.basis(projects.get(project_id), s),
                },
            )
    storyboard.approve_all(project_id)
    _ = scripts
    return shots
