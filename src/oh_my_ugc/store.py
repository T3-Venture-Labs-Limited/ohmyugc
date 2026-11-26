"""Content-addressed media store: every file is kept once, named by its SHA-256."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from oh_my_ugc import config, db
from oh_my_ugc.errors import NotFound

KINDS = {
    "image": {"png", "jpg", "jpeg", "webp", "gif", "bmp"},
    "video": {"mp4", "mov", "webm", "mkv", "m4v"},
    "audio": {"mp3", "wav", "m4a", "aac", "ogg", "flac", "opus"},
}


def kind_of(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return next((k for k, exts in KINDS.items() if ext in exts), "file")


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dest(digest: str, ext: str) -> Path:
    ext = ext.lower().lstrip(".") or "bin"
    return config.media_dir() / digest[:2] / f"{digest}.{ext}"


def _register(digest: str, dest: Path, ext: str) -> str:
    if not db.one("SELECT hash FROM media WHERE hash = ?", (digest,)):
        db.insert(
            "media",
            {
                "hash": digest,
                "path": str(dest),
                "kind": kind_of(ext),
                "size": dest.stat().st_size,
                "created_at": db.now(),
            },
        )
    return digest


def put_bytes(data: bytes, ext: str) -> str:
    digest = hash_bytes(data)
    dest = _dest(digest, ext)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
    return _register(digest, dest, ext)


def put_file(path: Path) -> str:
    """Copy a file into the store (originals are never modified)."""
    digest = hash_file(path)
    dest = _dest(digest, path.suffix)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        shutil.copyfile(path, tmp)
        tmp.replace(dest)
    return _register(digest, dest, path.suffix)


def path(media_id: str) -> Path:
    row = db.one("SELECT path FROM media WHERE hash = ?", (media_id,))
    if not row or not Path(row["path"]).exists():
        raise NotFound("A media file")
    return Path(row["path"])


def maybe_path(media_id: str | None) -> Path | None:
    if not media_id:
        return None
    try:
        return path(media_id)
    except NotFound:
        return None


def url(media_id: str | None) -> str | None:
    return f"/api/media/{media_id}" if media_id else None
