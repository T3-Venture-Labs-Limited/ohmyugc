"""Caption presets: a small JSON format describing how captions look and move.

Built-in presets live in ``engine/presets/*.json``. Users save their own (a brand kit is
just a preset with their font and colours). Unknown keys are ignored and values are clamped,
so a preset written for a newer version still loads.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

BUILTIN_DIR = Path(__file__).resolve().parent / "presets"

# How built-in presets are listed; any others follow alphabetically.
ORDER = [
    "punch",
    "karaoke",
    "boxed",
    "clean",
    "spotlight",
    "bounce",
    "neon",
    "reveal",
    "comic",
    "headline",
    "subtitle",
    "sticker",
    "lowkey",
    "marker",
    "glass",
]

MODES = ("group", "karaoke", "reveal")
ENTERS = ("none", "pop", "fade", "slide", "drop", "bounce")
ACTIVE_ANIMS = ("none", "pop", "grow")
CASES = ("upper", "lower", "none")
BOXES = ("none", "word", "line")


@dataclass(slots=True)
class Preset:
    id: str = "custom"
    name: str = "Custom"
    description: str = ""
    # Type
    font: str = "Montserrat Black"
    size: float = 0.055  # fraction of the video height
    case: str = "upper"
    spacing: float = 0.0  # letter spacing, fraction of the font size
    punctuation: bool = False  # keep commas and full stops (question and exclamation marks always stay)
    # Colour (hex RGB)
    text_color: str = "#FFFFFF"
    active_color: str = "#FFD400"
    emphasis_color: str = "#00E5FF"
    outline_color: str = "#000000"
    outline: float = 0.08  # fraction of the font size
    shadow_color: str = "#000000"
    shadow_alpha: float = 0.6  # 0 transparent … 1 opaque
    shadow: float = 0.04  # fraction of the font size
    blur: float = 0.0  # softens the outline into a glow, fraction of the font size
    # Box behind the words
    box: str = "none"
    box_color: str = "#FF3B8D"
    box_alpha: float = 1.0
    # Behaviour
    mode: str = "group"  # group: line shown, active word highlighted; karaoke: fill; reveal: appear as spoken
    max_words: int = 3
    max_chars: int = 16
    lines: int = 1
    inactive_alpha: float = 1.0  # opacity of words not being spoken (group mode)
    position: float = 0.68  # vertical centre of the caption, fraction from the top
    enter: str = "pop"
    active_anim: str = "pop"
    active_scale: float = 1.12
    emphasis_scale: float = 1.15
    tilt: float = 0.0  # degrees; alternates left and right per caption
    emoji_size: float = 0.09  # fraction of the video height

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Preset:
        known = {f.name for f in fields(cls)}
        preset = cls(**{k: v for k, v in data.items() if k in known})
        return preset.clamped()

    def merged(self, overrides: dict[str, Any] | None) -> Preset:
        return Preset.from_dict({**asdict(self), **(overrides or {})}) if overrides else self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def clamped(self) -> Preset:
        self.size = _clamp(float(self.size), 0.015, 0.2)
        self.case = self.case if self.case in CASES else "none"
        self.mode = self.mode if self.mode in MODES else "group"
        self.enter = self.enter if self.enter in ENTERS else "none"
        self.active_anim = self.active_anim if self.active_anim in ACTIVE_ANIMS else "none"
        self.box = self.box if self.box in BOXES else "none"
        self.max_words = int(_clamp(int(self.max_words), 1, 12))
        self.max_chars = int(_clamp(int(self.max_chars), 4, 80))
        self.lines = int(_clamp(int(self.lines), 1, 2))
        for name in ("outline", "shadow", "blur", "spacing"):
            setattr(self, name, _clamp(float(getattr(self, name)), 0.0, 0.5))
        for name in ("inactive_alpha", "shadow_alpha", "box_alpha"):
            setattr(self, name, _clamp(float(getattr(self, name)), 0.0, 1.0))
        self.position = _clamp(float(self.position), 0.05, 0.95)
        self.active_scale = _clamp(float(self.active_scale), 1.0, 1.6)
        self.emphasis_scale = _clamp(float(self.emphasis_scale), 1.0, 1.6)
        self.tilt = _clamp(float(self.tilt), 0.0, 15.0)
        self.emoji_size = _clamp(float(self.emoji_size), 0.03, 0.25)
        for name in (
            "text_color",
            "active_color",
            "emphasis_color",
            "outline_color",
            "shadow_color",
            "box_color",
        ):
            setattr(self, name, _hex(getattr(self, name)))
        return self


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _hex(value: str) -> str:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        int(text, 16)
    except ValueError:
        return "#FFFFFF"
    return f"#{text[:6].upper():0<6}"


def builtin() -> list[Preset]:
    presets = []
    for path in sorted(BUILTIN_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        presets.append(Preset.from_dict({"id": path.stem, **data}))
    order = {preset_id: i for i, preset_id in enumerate(ORDER)}
    return sorted(presets, key=lambda p: (order.get(p.id, len(ORDER)), p.name))


def get_builtin(preset_id: str) -> Preset | None:
    path = BUILTIN_DIR / f"{preset_id}.json"
    if not path.exists():
        return None
    return Preset.from_dict({"id": preset_id, **json.loads(path.read_text(encoding="utf-8"))})
