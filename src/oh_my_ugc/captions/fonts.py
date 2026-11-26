"""Bundled fonts, user fonts and text measurement.

libass picks fonts by name from a fonts folder. Measuring with the same font files lets the
layout shrink a caption that would run off the frame, instead of letting it wrap or clip.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BUNDLED_DIR = Path(__file__).resolve().parent / "fonts"
FONT_SUFFIXES = (".ttf", ".otf")


@dataclass(frozen=True, slots=True)
class FontInfo:
    name: str  # full name, which is what ASS styles use
    family: str
    path: Path
    bundled: bool


def font_files(extra_dirs: tuple[Path, ...] = ()) -> list[Path]:
    files: list[Path] = []
    for folder in (BUNDLED_DIR, *extra_dirs):
        if folder.exists():
            files += sorted(p for p in folder.iterdir() if p.suffix.lower() in FONT_SUFFIXES)
    return files


@lru_cache(maxsize=256)
def font_info(path: Path) -> FontInfo:
    from fontTools.ttLib import TTFont

    font = TTFont(str(path), lazy=True, fontNumber=0)
    names = font["name"]
    family = str(names.getBestFamilyName() or path.stem)
    full = str(names.getBestFullName() or family)
    # "Anton Regular" is addressed as "Anton" by libass; keep the shorter name for Regular faces.
    if full.endswith(" Regular"):
        full = full[: -len(" Regular")]
    return FontInfo(name=full, family=family, path=path, bundled=path.parent == BUNDLED_DIR)


def available(extra_dirs: tuple[Path, ...] = ()) -> list[FontInfo]:
    seen: dict[str, FontInfo] = {}
    for path in font_files(extra_dirs):
        try:
            info = font_info(path)
        except Exception:  # not a font fontTools can read; libass would not use it either
            continue
        seen.setdefault(info.name.lower(), info)
    return sorted(seen.values(), key=lambda f: f.name.lower())


def find(name: str, extra_dirs: tuple[Path, ...] = ()) -> FontInfo | None:
    wanted = name.lower()
    fonts = available(extra_dirs)
    return next((f for f in fonts if f.name.lower() == wanted), None) or next(
        (f for f in fonts if f.family.lower() == wanted), None
    )


@lru_cache(maxsize=64)
def _metrics(path: Path) -> tuple[float, dict[int, int], int]:
    """(design units per pixel of ASS size, advance widths, fallback width).

    Like VSFilter, libass sizes a font so that its full height (Windows ascent + descent)
    equals the ASS font size, not its em square.
    """
    from fontTools.ttLib import TTFont

    font = TTFont(str(path), lazy=True, fontNumber=0)
    widths = font["hmtx"].metrics
    cmap = font.getBestCmap() or {}
    advance = {code: widths[glyph][0] for code, glyph in cmap.items() if glyph in widths}
    fallback = widths.get(cmap.get(ord("n"), ""), (font["head"].unitsPerEm // 2, 0))[0]
    os2 = font["OS/2"] if "OS/2" in font else None
    height = (os2.usWinAscent + os2.usWinDescent) if os2 else font["hhea"].ascent - font["hhea"].descent
    return float(height or font["head"].unitsPerEm), advance, fallback


def text_width(text: str, font: FontInfo | None, size: float, spacing: float = 0.0) -> float:
    """Width in pixels of ``text`` set at ``size`` pixels (the ASS font size)."""
    if font is None:
        return len(text) * size * 0.62 + spacing * len(text)
    units, advance, fallback = _metrics(font.path)
    total = sum(advance.get(ord(ch), fallback) for ch in text)
    return total * size / units + spacing * len(text)


def line_height(font: FontInfo | None, size: float) -> float:
    """Height of one line of text at ASS ``size``, which by definition is the size itself."""
    return size
