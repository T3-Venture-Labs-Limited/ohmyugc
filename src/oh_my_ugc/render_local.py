"""Shots made without a generative model: the real product, from the original pixels (design D13)."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any

from oh_my_ugc import media, projects, store
from oh_my_ugc.errors import OmuError

FPS = 30
BRAND_DEFAULT = "#14151A"


def _size(project: dict[str, Any]) -> tuple[int, int]:
    return projects.output_size(project)


def _cover(image, size: tuple[int, int]):
    from PIL import Image

    w, h = size
    scale = max(w / image.width, h / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left, top = (resized.width - w) // 2, (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _neighbor_frame(project: dict[str, Any], shot: dict[str, Any]) -> Path | None:
    from oh_my_ugc import storyboard

    siblings = storyboard.shots_of(project["id"], shot.get("variant_id"))
    order = sorted(siblings, key=lambda s: abs(s["position"] - shot["position"]))
    for other in order:
        if other["id"] != shot["id"] and other.get("frame"):
            return store.maybe_path(other["frame"])
    return None


def background(project: dict[str, Any], shot: dict[str, Any], product: dict[str, Any], size: tuple[int, int]):
    """The backdrop image for a real-product shot."""
    from PIL import Image, ImageEnhance, ImageFilter

    card = project.get("end_card") or {}
    kind = shot.get("background") or "blur"
    if kind == "image" and card.get("background_image"):
        path = store.maybe_path(card["background_image"])
        if path:
            return _cover(Image.open(path).convert("RGB"), size)
    if kind == "brand" or kind == "image":
        return Image.new("RGB", size, card.get("color") or BRAND_DEFAULT)
    source = _neighbor_frame(project, shot) or store.path(product["primary_photo"])
    image = _cover(Image.open(source).convert("RGB"), size).filter(ImageFilter.GaussianBlur(max(size) // 40))
    return ImageEnhance.Brightness(image).enhance(0.55)


def product_layer(product: dict[str, Any], size: tuple[int, int], fraction: float = 0.72):
    """The product (cutout, or the photo) with a soft shadow, as an RGBA image sized for the frame."""
    from PIL import Image, ImageFilter

    source = Image.open(store.path(product.get("cutout") or product["primary_photo"])).convert("RGBA")
    if not product.get("cutout"):  # no cutout: round the photo's corners so it reads as an object
        mask = Image.new("L", source.size, 0)
        from PIL import ImageDraw

        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, source.width - 1, source.height - 1), radius=source.width // 16, fill=255
        )
        source.putalpha(mask)
    bbox = source.getchannel("A").getbbox()
    if bbox:
        source = source.crop(bbox)
    max_w, max_h = size[0] * fraction, size[1] * 0.62
    scale = min(max_w / source.width, max_h / source.height)
    source = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))), Image.LANCZOS
    )
    pad = max(size) // 18
    layer = Image.new("RGBA", (source.width + pad * 2, source.height + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    alpha = source.getchannel("A").point(lambda v: int(v * 0.45))
    shadow.paste((0, 0, 0, 255), (pad, pad + pad // 3), alpha)
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(pad // 2)))
    layer.alpha_composite(source, (pad, pad))
    return layer


def real_product_still(project: dict[str, Any], shot: dict[str, Any], product: dict[str, Any]) -> str:
    """A still preview of a real-product shot (frame zero), stored as media."""
    size = _size(project)
    bg = background(project, shot, product, size).convert("RGBA")
    layer = product_layer(product, size)
    bg.alpha_composite(layer, ((size[0] - layer.width) // 2, (size[1] - layer.height) // 2))
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "JPEG", quality=92)
    return store.put_bytes(buf.getvalue(), "jpg")


def _filter(motion: str, size: tuple[int, int], seconds: float) -> str:
    w, h = size
    d = max(0.5, seconds)
    base = f"[0:v]scale={w}:{h},setsar=1[bg];"
    if motion == "pan":
        return base + (
            f"[1:v]scale=w='iw*1.06':h='ih*1.06':eval=init[fg];"
            f"[bg][fg]overlay=x='(W-w)/2-{0.04 * w:.1f}+{0.08 * w:.1f}*t/{d:.2f}':y='(H-h)/2':eval=frame,format=yuv420p[v]"
        )
    if motion == "parallax":
        return (
            f"[0:v]scale=w='{w}*(1+0.06*t/{d:.2f})':h='{h}*(1+0.06*t/{d:.2f})':eval=frame,crop={w}:{h},setsar=1[bg];"
            f"[1:v]scale=w='iw*(1+0.10*t/{d:.2f})':h='ih*(1+0.10*t/{d:.2f})':eval=frame[fg];"
            f"[bg][fg]overlay=x='(W-w)/2+{0.03 * w:.1f}*(1-t/{d:.2f})':y='(H-h)/2':eval=frame,format=yuv420p[v]"
        )
    if motion == "rotate_in":
        return base + (
            f"[1:v]rotate=a='(1-min(t/({d:.2f}*0.45),1))*0.35':ow='hypot(iw,ih)':oh='hypot(iw,ih)':c=none,"
            f"scale=w='iw*(0.92+0.10*min(t/({d:.2f}*0.45),1))':h=-1:eval=frame[fg];"
            f"[bg][fg]overlay=x='(W-w)/2':y='(H-h)/2':eval=frame,format=yuv420p[v]"
        )
    # push_in (default)
    return base + (
        f"[1:v]scale=w='iw*(1+0.14*t/{d:.2f})':h='ih*(1+0.14*t/{d:.2f})':eval=frame[fg];"
        f"[bg][fg]overlay=x='(W-w)/2':y='(H-h)/2':eval=frame,format=yuv420p[v]"
    )


def render_real_product(
    project: dict[str, Any],
    shot: dict[str, Any],
    product: dict[str, Any],
    seconds: float | None = None,
    logo: Path | None = None,
) -> str:
    """Render a real-product shot with ffmpeg: no model, no cost, pixels from the original upload."""
    size = _size(project)
    seconds = float(seconds or shot["duration"])
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        bg_path, fg_path, out = tmp_dir / "bg.png", tmp_dir / "fg.png", tmp_dir / "shot.mp4"
        backdrop = background(project, shot, product, size)
        if logo:  # the brand logo sits at the top of the frame
            from PIL import Image

            mark = Image.open(logo).convert("RGBA")
            scale = min(size[0] * 0.34 / mark.width, size[1] * 0.07 / mark.height)
            mark = mark.resize(
                (max(1, round(mark.width * scale)), max(1, round(mark.height * scale))), Image.LANCZOS
            )
            backdrop = backdrop.convert("RGBA")
            backdrop.alpha_composite(mark, ((size[0] - mark.width) // 2, round(size[1] * 0.06)))
            backdrop = backdrop.convert("RGB")
        backdrop.save(bg_path)
        product_layer(product, size).save(fg_path)
        args = [
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{seconds:.3f}",
            "-i",
            str(bg_path),
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{seconds:.3f}",
            "-i",
            str(fg_path),
            "-f",
            "lavfi",
            "-t",
            f"{seconds:.3f}",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-filter_complex",
            _filter(shot.get("motion") or "push_in", size, seconds),
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ]
        media.run_ffmpeg(args)
        return store.put_file(out)


def require_product(project: dict[str, Any]) -> dict[str, Any]:
    from oh_my_ugc import db

    product = (
        db.one("SELECT * FROM products WHERE id = ?", (project.get("product_id"),))
        if project.get("product_id")
        else None
    )
    if not product:
        raise OmuError("Choose a product for this project to make real-product shots.")
    return product
