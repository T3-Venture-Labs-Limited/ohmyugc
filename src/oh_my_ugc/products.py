"""Products: real photos, facts and the exact label text, plus automatic cutouts."""

from __future__ import annotations

import io
from typing import Any

from oh_my_ugc import db, runner, store
from oh_my_ugc.catalog import load
from oh_my_ugc.errors import NotFound, OmuError, check_lengths

ACCEPTED = {"jpg", "jpeg", "png", "webp"}
MAX_BYTES = 20 * 1024 * 1024
MAX_PHOTOS = 8
LIMIT_TEXT = "Use a JPEG, PNG or WebP photo up to 20 MB."


def validate_image(filename: str, data: bytes) -> str:
    """Check an upload and put it in the media store (the original bytes are kept as they are)."""
    from PIL import Image

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ACCEPTED:
        raise OmuError(f"'{filename}' is not an accepted format. {LIMIT_TEXT}")
    if len(data) > MAX_BYTES:
        raise OmuError(f"'{filename}' is {len(data) / 1048576:.0f} MB. {LIMIT_TEXT}")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:
        raise OmuError(f"'{filename}' could not be read as an image. {LIMIT_TEXT}") from exc
    return store.put_bytes(data, "jpg" if ext == "jpeg" else ext)


def public(product: dict[str, Any]) -> dict[str, Any]:
    out = dict(product)
    out["photo_urls"] = [store.url(p) for p in product.get("photos", [])]
    out["primary_url"] = store.url(product.get("primary_photo"))
    out["cutout_url"] = store.url(product.get("cutout"))
    return out


def get(product_id: str) -> dict[str, Any]:
    product = db.one("SELECT * FROM products WHERE id = ?", (product_id,))
    if not product:
        raise NotFound("That product")
    return product


def listing(brand_id: str | None = None) -> list[dict[str, Any]]:
    if brand_id:
        rows = db.many("SELECT * FROM products WHERE brand_id = ? ORDER BY created_at DESC", (brand_id,))
    else:
        rows = db.many("SELECT * FROM products ORDER BY created_at DESC")
    return [public(p) for p in rows]


def create(
    brand_id: str, name: str, photos: list[tuple[str, bytes]], facts: str = "", label_text: str = ""
) -> dict[str, Any]:
    from oh_my_ugc import brands

    brands.get(brand_id)
    check_lengths({"name": name or "", "facts": facts, "label_text": label_text})
    name = (name or "").strip()
    if not name:
        raise OmuError("Give the product a name.")
    if not 1 <= len(photos) <= MAX_PHOTOS:
        raise OmuError(f"Upload between 1 and {MAX_PHOTOS} photos of the product.")
    media = [validate_image(fn, data) for fn, data in photos]
    product_id = db.insert(
        "products",
        {
            "brand_id": brand_id,
            "name": name,
            "facts": facts.strip(),
            "label_text": label_text.strip(),
            "photos": media,
            "primary_photo": media[0],
            "created_at": db.now(),
        },
    )
    return public(get(product_id))


def update(product_id: str, values: dict[str, Any]) -> dict[str, Any]:
    product = get(product_id)
    check_lengths({k: v for k, v in values.items() if k in ("name", "facts", "label_text")})
    row = {
        k: str(values[k]).strip()
        for k in ("name", "facts", "label_text")
        if k in values and values[k] is not None
    }
    if "name" in row and not row["name"]:
        raise OmuError("Give the product a name.")
    if values.get("primary_photo"):
        if values["primary_photo"] not in product["photos"]:
            raise OmuError("That photo does not belong to this product.")
        row["primary_photo"] = values["primary_photo"]
    db.update("products", product_id, row)
    return public(get(product_id))


def add_photos(product_id: str, photos: list[tuple[str, bytes]]) -> dict[str, Any]:
    product = get(product_id)
    if len(product["photos"]) + len(photos) > MAX_PHOTOS:
        raise OmuError(f"A product can have at most {MAX_PHOTOS} photos.")
    media = [validate_image(fn, data) for fn, data in photos]
    db.update(
        "products",
        product_id,
        {"photos": [*product["photos"], *[m for m in media if m not in product["photos"]]]},
    )
    return public(get(product_id))


def remove_photo(product_id: str, media: str) -> dict[str, Any]:
    product = get(product_id)
    photos = [p for p in product["photos"] if p != media]
    if not photos:
        raise OmuError("A product needs at least one photo.")
    db.update(
        "products",
        product_id,
        {
            "photos": photos,
            "primary_photo": product["primary_photo"] if product["primary_photo"] in photos else photos[0],
        },
    )
    return public(get(product_id))


def delete(product_id: str) -> None:
    get(product_id)
    db.run("UPDATE projects SET product_id = NULL WHERE product_id = ?", (product_id,))
    db.delete("products", product_id)


def set_custom_cutout(product_id: str, filename: str, data: bytes) -> dict[str, Any]:
    """Replace the cutout with the user's own transparent PNG."""
    from PIL import Image

    get(product_id)
    if not filename.lower().endswith(".png"):
        raise OmuError("A custom cutout must be a PNG with a transparent background.")
    media = validate_image(filename, data)
    with Image.open(io.BytesIO(data)) as image:
        if "A" not in image.getbands():
            raise OmuError(
                "That PNG has no transparency. Remove the background first, or let oh-my-ugc do it."
            )
    db.update("products", product_id, {"cutout": media, "cutout_custom": 1})
    return public(get(product_id))


def make_cutout(product_id: str, project_models: dict | None = None) -> dict[str, Any]:
    """Remove the background of the primary photo with the chosen model (the original is untouched)."""
    product = get(product_id)
    if product["cutout_custom"]:
        return {"status": "custom", "message": "Using your own cutout."}
    entry = load.chosen_for("background_removal", project_models)
    if entry is None:
        return {
            "status": "skipped",
            "message": "No background-removal model chosen, so real-product shots will use the uncut photo until you add a cutout. "
            + load.requirement("background_removal"),
        }
    result = runner.call(
        entry, {"image": store.path(product["primary_photo"])}, step="cutout", quantities={"images": 1}
    )
    db.update("products", product_id, {"cutout": result.media[0]})
    return {"status": "done", "cutout": result.media[0], "cost": result.cost, "cached": result.cached}


def shot_source(product: dict[str, Any]) -> str:
    """The pixels real-product shots use: the cutout if there is one, else the primary photo."""
    return product.get("cutout") or product["primary_photo"]


from oh_my_ugc import jobs  # noqa: E402


@jobs.register("cutout")
def _cutout_job(job: dict[str, Any]) -> dict[str, Any]:
    return make_cutout(job["payload"]["product_id"], job["payload"].get("models"))


def start_cutout(product_id: str, models: dict | None = None) -> str:
    get(product_id)
    return jobs.enqueue("cutout", payload={"product_id": product_id, "models": models})
