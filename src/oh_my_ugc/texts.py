"""All on-screen text (captions, on-screen text, text cards, end card) is drawn by libass (design D12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from oh_my_ugc.captions import fonts as caption_fonts

SAFE_WIDTH = 0.84


@dataclass(slots=True)
class Item:
    text: str
    start: float
    end: float
    y: float = 0.22  # vertical centre, fraction of the height
    size: float = 0.05  # fraction of the height
    font: str = "Montserrat Black"
    color: str = "#FFFFFF"
    outline: float = 0.07
    box: str | None = None  # colour of a pill behind the text (BorderStyle 3)
    animate: bool = True
    lines: list[str] = field(default_factory=list)


def _bgr(hex_rgb: str) -> str:
    rgb = hex_rgb.lstrip("#")
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def _ts(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def fit(text: str, font_name: str, size_px: float, max_width: float) -> tuple[list[str], float]:
    """Wrap ``text`` to at most two lines and shrink the size until the widest line fits."""
    info = caption_fonts.find(font_name)
    words = text.split()
    best = [" ".join(words)]
    if caption_fonts.text_width(best[0], info, size_px) > max_width and len(words) > 1:
        scored = []
        for i in range(1, len(words)):
            pair = [" ".join(words[:i]), " ".join(words[i:])]
            scored.append((max(caption_fonts.text_width(p, info, size_px) for p in pair), pair))
        best = min(scored)[1]
    width = max(caption_fonts.text_width(line, info, size_px) for line in best)
    if width > max_width:
        size_px = size_px * max_width / width
    return best, size_px


def style_line(
    name: str, font: str, size: int, color: str, outline_color: str, outline: float, box: str | None
) -> str:
    border_style = 3 if box else 1
    back = _bgr(box) if box else "&H66000000"
    out = _bgr(box) if box else _bgr(outline_color)
    return (
        f"Style: {name},{font},{size},{_bgr(color)},{_bgr(color)},{out},{back},0,0,0,0,100,100,0,0,"
        f"{border_style},{round(outline, 1) if not box else round(size * 0.22, 1)},{0 if box else round(size * 0.03, 1)},5,0,0,0,1"
    )


def build(items: list[Item], width: int, height: int) -> tuple[list[str], list[str]]:
    """(style lines, event lines) for ``items``; one style per distinct look."""
    styles: dict[tuple, str] = {}
    events: list[str] = []
    for item in items:
        size_px = item.size * height
        lines, size_px = fit(item.text, item.font, size_px, width * SAFE_WIDTH)
        size = max(8, round(size_px))
        key = (item.font, size, item.color, item.box, round(item.outline, 3))
        if key not in styles:
            styles[key] = f"T{len(styles)}"
            styles_line = style_line(
                styles[key], item.font, size, item.color, "#000000", size * item.outline, item.box
            )
            styles[key] = styles[key] + "|" + styles_line
        name = styles[key].split("|", 1)[0]
        x, y = round(width / 2), round(item.y * height)
        anim = "\\fad(120,120)\\fscx82\\fscy82\\t(0,140,\\fscx100\\fscy100)" if item.animate else ""
        body = "\\N".join(_escape(line) for line in lines)
        events.append(
            f"Dialogue: 2,{_ts(item.start)},{_ts(item.end)},{name},,0,0,0,,{{\\an5\\pos({x},{y}){anim}}}{body}"
        )
    return [v.split("|", 1)[1] for v in styles.values()], events


def merge(caption_ass: str | None, styles: list[str], events: list[str], width: int, height: int) -> str:
    """Add text styles and events to a caption ASS (or start a fresh script when there are no captions)."""
    if not caption_ass:
        caption_ass = "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                f"PlayResX: {width}",
                f"PlayResY: {height}",
                "WrapStyle: 2",
                "ScaledBorderAndShadow: yes",
                "YCbCr Matrix: None",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "",
            ]
        )
    head, _, rest = caption_ass.partition("\n[Events]")
    return (
        head.rstrip("\n")
        + "\n"
        + "\n".join(styles)
        + "\n\n[Events]"
        + rest.rstrip("\n")
        + "\n"
        + "\n".join(events)
        + "\n"
    )


def fonts_dir() -> Path:
    return caption_fonts.BUNDLED_DIR
