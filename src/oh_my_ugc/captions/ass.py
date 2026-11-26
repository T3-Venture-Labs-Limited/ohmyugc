"""Compile cards into an ASS subtitle file, with animation, and plan the emoji overlays.

The same ASS is rendered by libass twice: in the browser preview (JASSUB, libass compiled to
WebAssembly) and in the export (ffmpeg's ``ass`` filter). One compiler and one renderer is
what keeps the preview and the exported video identical.

Override tags carry over to the following text in an ASS line, so every word sets all of
its own tags (colour, alpha and scale) instead of relying on the previous word's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from oh_my_ugc.captions.layout import Card, build_cards, display
from oh_my_ugc.captions.presets import Preset
from oh_my_ugc.captions.words import Word

_ALPHA_1 = re.compile(r"\\1a&H[0-9A-F]{2}&")


@dataclass(slots=True)
class Compiled:
    ass: str
    cards: list[Card]
    emoji: list[dict]  # {"emoji", "start", "end", "x", "y", "size"} in video pixels


def compile_captions(
    words: list[Word],
    preset: Preset,
    width: int,
    height: int,
    *,
    position: float | None = None,
    emphasis: str = "auto",
    font_dirs: tuple = (),
) -> Compiled:
    if position is not None:
        preset = preset.merged({"position": position})
    cards = build_cards(words, preset, width, height, emphasis, font_dirs)
    size = round(preset.size * height)
    lines = _header(preset, width, height, size)
    for card in cards:
        lines += _card_events(card, words, preset, width, height, size)
    return Compiled(
        ass="\n".join(lines) + "\n", cards=cards, emoji=plan_emoji(cards, words, preset, width, height)
    )


# ── header ───────────────────────────────────────────────────────────────────


def _header(p: Preset, width: int, height: int, size: int) -> list[str]:
    primary, secondary = (
        (p.active_color, p.text_color) if p.mode == "karaoke" else (p.text_color, p.text_color)
    )
    style = (
        f"{p.font},{size},{_colour(primary)},{_colour(secondary)},{{outline}},"
        f"{_colour(p.shadow_color, p.shadow_alpha)},0,0,0,0,100,100,{round(p.spacing * size, 1)},0,"
        "{border_style},{border},{shadow},5,0,0,0,1"
    )
    styles = [
        "Style: Default,"
        + style.format(
            outline=_colour(p.outline_color),
            border_style=1,
            border=round(size * p.outline, 1),
            shadow=round(size * p.shadow, 1),
        )
    ]
    if p.box != "none":  # an opaque box (BorderStyle 3) drawn on a layer under the text
        styles.append(
            "Style: Box,"
            + style.format(
                outline=_colour(p.box_color, p.box_alpha),
                border_style=3,
                border=round(size * 0.16, 1),
                shadow=0,
            )
        )
    return [
        "[Script Info]",
        "; Made with oh-my-ugc",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


# ── events ───────────────────────────────────────────────────────────────────


def _card_events(card: Card, words: list[Word], p: Preset, width: int, height: int, size: int) -> list[str]:
    group = [words[i] for i in card.indices]
    boxes: list[str] = []
    if p.mode == "karaoke":
        spans = [(card.start, card.end, _karaoke_text(card, group, p, width, height, size))]
    else:
        spans = []
        for i in range(len(group)):
            start = card.start if i == 0 else group[i]["start"]
            end = group[i + 1]["start"] if i + 1 < len(group) else card.end
            if end - start >= 0.01:
                spans.append((start, end, _group_text(card, group, p, i, width, height, size)))
                if p.box != "none":
                    box = _group_text(card, group, p, i, width, height, size, box_layer=True)
                    boxes.append(_event(start, end, box, layer=0, style="Box"))
    if not p.blur:
        return boxes + [_event(start, end, text, layer=1) for start, end, text in spans]
    # Glow: a blurred, text-less outline underneath, crisp text on top.
    glow, crisp = round(p.blur * size, 1), list(boxes)
    for start, end, text in spans:
        under = _ALPHA_1.sub(r"\\1a&HFF&", text).replace("{\\an5", f"{{\\blur{glow}\\an5", 1)
        crisp.append(_event(start, end, under, layer=0))
        crisp.append(_event(start, end, text.replace("{\\an5", "{\\bord0\\shad0\\an5", 1), layer=1))
    return crisp


def _event(start: float, end: float, text: str, layer: int = 0, style: str = "Default") -> str:
    return f"Dialogue: {layer},{_ts(start)},{_ts(end)},{style},,0,0,0,,{text}"


def _position(card: Card, p: Preset, width: int, height: int, first: bool) -> str:
    x, y = round(width / 2), round(p.position * height)
    tags = "\\an5"
    if first and p.enter == "slide":
        tags += f"\\move({x},{y + round(height * 0.025)},{x},{y},0,170)\\fad(110,0)"
    elif first and p.enter == "drop":
        tags += f"\\move({x},{y - round(height * 0.03)},{x},{y},0,150)\\fad(80,0)"
    else:
        tags += f"\\pos({x},{y})"
    if first and p.enter == "fade":
        tags += "\\fad(140,0)"
    if first and p.enter == "bounce":
        t = card.tilt
        tags += f"\\frz{t - 7:g}\\t(0,110,\\frz{t + 4:g})\\t(110,220,\\frz{t:g})"
    elif card.tilt:
        tags += f"\\frz{card.tilt:g}"
    return tags


def _group_text(
    card: Card,
    group: list[Word],
    p: Preset,
    active: int,
    width: int,
    height: int,
    size: int,
    box_layer: bool = False,
) -> str:
    first = active == 0
    parts: list[str] = []
    for line in card.lines:
        out = []
        for j in line:
            word = group[j]
            emph = j in card.emphasis
            colour = word.get("color") or (
                p.emphasis_color
                if emph
                else p.active_color
                if j == active and p.mode == "group"
                else p.text_color
            )
            visible = 1.0
            if p.mode == "reveal" and j > active:
                visible = 0.0
            elif p.mode == "group" and j != active:
                visible = p.inactive_alpha
            tags = f"\\1c{_bgr(colour)}" + (
                _box_tags(visible, p, j == active) if box_layer else _alpha_tags(visible, p)
            )
            base = card.scale * 100 * (p.emphasis_scale if emph else 1.0)
            tags += _scale_tags(base, p, first and p.enter in ("pop", "bounce"), j == active)
            out.append("{" + tags + "}" + _escape(display(word["text"], p)))
        parts.append(" ".join(out))
    return "{" + _position(card, p, width, height, first) + "}" + "\\N".join(parts)


def _karaoke_text(card: Card, group: list[Word], p: Preset, width: int, height: int, size: int) -> str:
    parts: list[str] = []
    for line in card.lines:
        out = []
        for j in line:
            word = group[j]
            end = group[j + 1]["start"] if j + 1 < len(group) else word["end"]
            cs = max(1, round((end - word["start"]) * 100))
            emph = j in card.emphasis
            base = card.scale * 100 * (p.emphasis_scale if emph else 1.0)
            tags = f"\\kf{cs}" + (f"\\1c{_bgr(p.emphasis_color)}" if emph else f"\\1c{_bgr(p.active_color)}")
            tags += _scale_tags(base, p, p.enter in ("pop", "bounce"), False)
            out.append("{" + tags + "}" + _escape(display(word["text"], p)))
        parts.append(" ".join(out))
    return "{" + _position(card, p, width, height, True) + "}" + "\\N".join(parts)


def _alpha_tags(visible: float, p: Preset) -> str:
    text = _alpha(visible)
    return f"\\1a{text}\\3a{text}\\4a{_alpha(p.shadow_alpha * visible)}"


def _box_tags(visible: float, p: Preset, active: bool) -> str:
    """On the box layer only the box shows; the text itself is drawn by the layer above."""
    shown = visible > 0 and (p.box == "line" or active)
    return f"\\1a&HFF&\\3a{_alpha(p.box_alpha) if shown else '&HFF&'}\\4a&HFF&"


def _scale_tags(base: float, p: Preset, enter_pop: bool, active: bool) -> str:
    b = round(base, 1)
    peak = round(base * (p.active_scale if active and p.active_anim != "none" else 1.06), 1)
    if enter_pop:
        start = round(base * 0.78, 1)
        return (
            f"\\fscx{start}\\fscy{start}\\t(0,90,\\fscx{peak}\\fscy{peak})"
            f"\\t(90,180,\\fscx{b}\\fscy{b})" + _settle(base, p, active, 180)
        )
    if active and p.active_anim == "pop":
        return f"\\fscx{b}\\fscy{b}\\t(0,70,\\fscx{peak}\\fscy{peak})\\t(70,160,\\fscx{b}\\fscy{b})"
    if active and p.active_anim == "grow":
        return f"\\fscx{b}\\fscy{b}\\t(0,120,\\fscx{peak}\\fscy{peak})"
    return f"\\fscx{b}\\fscy{b}"


def _settle(base: float, p: Preset, active: bool, at: int) -> str:
    """After an entrance pop, a "grow" preset keeps the active word slightly larger."""
    if active and p.active_anim == "grow":
        peak = round(base * p.active_scale, 1)
        return f"\\t({at},{at + 80},\\fscx{peak}\\fscy{peak})"
    return ""


# ── emoji ────────────────────────────────────────────────────────────────────


def plan_emoji(cards: list[Card], words: list[Word], p: Preset, width: int, height: int) -> list[dict]:
    """Where and when each emoji appears: above its caption, from its word to the caption's end.

    libass cannot draw colour emoji, so they are drawn as images over the video, in the
    preview and in the export, from this plan.
    """
    plans = []
    size = round(p.emoji_size * height)
    for card in cards:
        marked = [i for i in card.indices if words[i].get("emoji")]
        if not marked:
            continue
        index = marked[-1]
        text_height = len(card.lines) * p.size * height * card.scale
        y = p.position * height - text_height / 2 - size * 0.62
        if y - size / 2 < height * 0.04:  # no room above: go below the caption
            y = p.position * height + text_height / 2 + size * 0.62
        plans.append(
            {
                "emoji": words[index]["emoji"],
                "start": round(max(words[index]["start"], card.start), 3),
                "end": round(card.end, 3),
                "x": round(width / 2),
                "y": round(y),
                "size": size,
            }
        )
    return plans


# ── helpers ──────────────────────────────────────────────────────────────────


def _bgr(hex_rgb: str) -> str:
    rgb = hex_rgb.lstrip("#")
    return f"&H{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&".upper()


def _colour(hex_rgb: str, opacity: float = 1.0) -> str:
    rgb = hex_rgb.lstrip("#")
    return f"&H{_alpha_byte(opacity):02X}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def _alpha_byte(opacity: float) -> int:
    return max(0, min(255, round((1 - opacity) * 255)))


def _alpha(opacity: float) -> str:
    return f"&H{_alpha_byte(opacity):02X}&"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _ts(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"
