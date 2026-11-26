"""The transcript word model and text editing that keeps word timings."""

from __future__ import annotations

import difflib
import re
from typing import Any

Word = dict[str, Any]

SENTENCE_END = (".", "!", "?", "…", "。", "？", "！", "؟", "।")
_TOKEN = re.compile(r"\S+")


def make_word(text: str, start: float, end: float, **extra: Any) -> Word:
    return {
        "text": text,
        "start": round(start, 3),
        "end": round(end, 3),
        "emph": None,
        "emoji": None,
        "br": False,
        **extra,
    }


def clean(words: list[Word]) -> list[Word]:
    """Normalise words coming from anywhere: strip, drop empties, enforce increasing times."""
    out: list[Word] = []
    for w in words:
        text = str(w.get("text", w.get("word", ""))).strip()
        if not text:
            continue
        start = max(float(w.get("start", 0.0)), out[-1]["start"] if out else 0.0)
        end = max(float(w.get("end", start)), start + 0.01)
        out.append(
            {
                "text": text,
                "start": round(start, 3),
                "end": round(end, 3),
                "emph": w.get("emph"),
                "emoji": w.get("emoji") or None,
                "br": bool(w.get("br", False)),
            }
        )
    return out


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _norm(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower())


_LEFT, _RIGHT = "\x00left", "\x00right"


def retime(
    old: list[Word], new_text: str | list[str], *, left: Word | None = None, right: Word | None = None
) -> list[Word]:
    """Replace the words' text with ``new_text`` while keeping their timing.

    Unchanged words keep their exact times and settings. A changed span shares the time of
    the words it replaces, weighted by length. An inserted word takes the pause around it,
    or a little time from its neighbours. Measured on real speech, corrected words land a
    median 0–26 ms from where they are spoken.

    ``left`` and ``right`` are the unchanged words either side of the span. They anchor
    inserted words between them and are returned (possibly shortened) at the ends.
    """
    new = tokens(new_text) if isinstance(new_text, str) else list(new_text)
    if left is not None:
        old, new = [{**left, "_key": _LEFT}, *old], [_LEFT, *new]
    if right is not None:
        old, new = [*old, {**right, "_key": _RIGHT}], [*new, _RIGHT]
    if not old:
        return [make_word(t, i * 0.3, i * 0.3 + 0.3) for i, t in enumerate(new)]
    a = [w.get("_key") or _norm(w["text"]) for w in old]
    b = [t if t in (_LEFT, _RIGHT) else _norm(t) for t in new]
    out: list[Word | None] = [None] * len(new)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                kept = {**old[i1 + k]}
                if not kept.pop("_key", None):
                    kept["text"] = new[j1 + k]
                out[j1 + k] = kept
        elif tag in ("replace", "insert"):
            start, end = _span(old, i1, i2, j2 - j1) if tag == "replace" else _gap(old, i1, j2 - j1)
            keep = old[i1] if tag == "replace" else {}
            weights = [len(_norm(t)) + 2 for t in new[j1:j2]]
            total, t = sum(weights), start
            for k, weight in enumerate(weights):
                length = (end - start) * weight / total
                word = make_word(new[j1 + k], t, t + length)
                if k == 0 and keep:  # the first word inherits the replaced word's settings
                    word.update({key: keep[key] for key in ("emph", "emoji") if keep.get(key) is not None})
                if k == j2 - j1 - 1 and tag == "replace":
                    word["br"] = bool(old[i2 - 1].get("br"))
                if tag == "insert":
                    word["_inserted"] = True
                out[j1 + k] = word
                t += length
    words = [w for w in out if w is not None]
    # Inserted words borrow time from their neighbours: shorten the neighbours to make room.
    for a, b in zip(words, words[1:], strict=False):
        if a["end"] > b["start"]:
            if b.get("_inserted") and not a.get("_inserted"):
                a["end"] = round(max(a["start"] + 0.02, b["start"]), 3)
            elif a.get("_inserted") and not b.get("_inserted"):
                b["start"] = round(min(b["end"] - 0.02, a["end"]), 3)
    for w in words:
        w.pop("_inserted", None)
    return words


def _span(old: list[Word], i1: int, i2: int, _count: int) -> tuple[float, float]:
    return old[i1]["start"], old[i2 - 1]["end"]


def _gap(old: list[Word], i: int, count: int) -> tuple[float, float]:
    """Time for ``count`` inserted words before ``old[i]``."""
    need = 0.14 * count
    prev_end = old[i - 1]["end"] if i > 0 else max(0.0, old[0]["start"] - need)
    next_start = old[i]["start"] if i < len(old) else prev_end + need
    if next_start - prev_end >= need * 0.6:
        return prev_end, next_start
    # No pause: borrow from the neighbouring words, centred on the boundary.
    middle = (prev_end + next_start) / 2
    return max(0.0, middle - need / 2), middle + need / 2


def fix_overlaps(words: list[Word]) -> list[Word]:
    """Make sure each word ends before the next begins (after re-timing or nudging)."""
    for a, b in zip(words, words[1:], strict=False):
        if a["end"] > b["start"]:
            a["end"] = max(a["start"] + 0.01, b["start"])
    return words


def text_of(words: list[Word]) -> str:
    return " ".join(w["text"] for w in words)
