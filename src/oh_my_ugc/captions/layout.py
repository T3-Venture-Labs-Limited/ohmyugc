"""Group words into captions ("cards"), choose emphasis and fit each card inside the frame."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from oh_my_ugc.captions import fonts
from oh_my_ugc.captions.presets import Preset
from oh_my_ugc.captions.words import SENTENCE_END, Word

PAUSE_BREAK = 0.6  # a pause this long always starts a new caption
HOLD = 0.4  # how long a caption stays after its last word, unless the next one starts
MIN_SHOW = 0.25
SAFE_WIDTH = 0.86  # captions never get wider than this share of the frame

STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "and",
        "or",
        "but",
        "not",
        "no",
        "nor",
        "in",
        "on",
        "at",
        "to",
        "of",
        "for",
        "by",
        "with",
        "from",
        "as",
        "it",
        "its",
        "it's",
        "this",
        "that",
        "these",
        "those",
        "he",
        "she",
        "we",
        "they",
        "his",
        "her",
        "my",
        "your",
        "our",
        "their",
        "i",
        "you",
        "me",
        "us",
        "him",
        "them",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "will",
        "would",
        "could",
        "should",
        "can",
        "so",
        "if",
        "then",
        "just",
        "very",
        "too",
        "also",
        "more",
        "all",
        "about",
        "when",
        "who",
        "how",
        "what",
        "which",
        "there",
        "here",
        "than",
        "into",
        "out",
        "up",
        "down",
        "over",
        "i'm",
        "you're",
        "we're",
        "they're",
        "don't",
        "didn't",
        "isn't",
        "that's",
    ]
)
# Words that lead into the next one; a caption should not end on them.
JOINERS = frozenset(
    [
        "a",
        "an",
        "the",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "from",
        "by",
        "and",
        "or",
        "but",
        "very",
        "so",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "my",
        "your",
        "our",
        "their",
        "his",
        "her",
        "its",
        "this",
        "that",
        "these",
        "those",
        "i",
        "we",
        "you",
        "they",
        "it",
        "if",
        "not",
        "no",
    ]
)
POWER_WORDS = frozenset(
    [
        "never",
        "always",
        "free",
        "secret",
        "best",
        "worst",
        "every",
        "nobody",
        "everyone",
        "everything",
        "nothing",
        "instantly",
        "stop",
        "must",
        "huge",
        "massive",
        "biggest",
        "fastest",
        "only",
        "new",
        "now",
        "today",
        "money",
    ]
)


@dataclass(slots=True)
class Card:
    indices: list[int]  # positions in the transcript
    start: float
    end: float
    lines: list[list[int]]  # card-local word positions per line
    emphasis: set[int] = field(default_factory=set)  # card-local positions
    scale: float = 1.0  # shrink factor so the widest line fits
    tilt: float = 0.0


def display(text: str, preset: Preset) -> str:
    """The word as shown: case applied and soft punctuation dropped (questions keep ``?``)."""
    word = text.strip()
    if not preset.punctuation:
        word = re.sub(r"^[\"“‘(]+|[\"”’),.;:…]+$", "", word) or word
    if preset.case == "upper":
        return word.upper()
    if preset.case == "lower":
        return word.lower()
    return word


def build_cards(
    words: list[Word], preset: Preset, width: int, height: int, emphasis: str = "auto", font_dirs: tuple = ()
) -> list[Card]:
    groups = _group(words, preset)
    font = fonts.find(preset.font, font_dirs)
    size = preset.size * height
    cards: list[Card] = []
    for n, indices in enumerate(groups):
        group = [words[i] for i in indices]
        card = Card(
            indices=indices,
            start=group[0]["start"],
            end=group[-1]["end"] + HOLD,
            lines=_lines([display(w["text"], preset) for w in group], preset.lines, preset.max_chars),
        )
        card.emphasis = _emphasis(group, emphasis)
        widest = max(
            fonts.text_width(
                " ".join(display(group[i]["text"], preset) for i in line), font, size, preset.spacing * size
            )
            for line in card.lines
        )
        grow = max(
            preset.active_scale if preset.active_anim != "none" else 1.0,
            preset.emphasis_scale if card.emphasis else 1.0,
        )
        card.scale = min(1.0, SAFE_WIDTH * width / max(widest * grow, 1.0))
        card.tilt = preset.tilt * (1 if n % 2 == 0 else -1)
        cards.append(card)
    # Short captions stay up a moment longer, but never into the next caption.
    for n, card in enumerate(cards):
        card.end = max(card.end, card.start + MIN_SHOW)
        if n + 1 < len(cards):
            card.end = min(card.end, cards[n + 1].start)
    return cards


def _group(words: list[Word], preset: Preset) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] = []
    limit = preset.max_chars * preset.lines
    for i, word in enumerate(words):
        if current:
            prev = words[current[-1]]
            text = " ".join(display(words[j]["text"], preset) for j in [*current, i])
            natural = (
                prev.get("br")
                or prev["text"].endswith(SENTENCE_END)
                or (
                    prev["text"].endswith((",", ";", ":", "—"))
                    and (len(current) >= 2 or len(prev["text"]) > 5)
                )
                or word["start"] - prev["end"] >= PAUSE_BREAK
            )
            if natural:
                groups.append(current)
                current = []
            elif len(current) >= preset.max_words or len(text) > limit:
                # Forced by length: don't leave a lead-in word ("to", "the", "very") dangling.
                carry = []
                if len(current) > 1 and _bare(prev["text"]) in JOINERS and not prev.get("br"):
                    carry = [current.pop()]
                groups.append(current)
                current = carry
        current.append(i)
    if current:
        groups.append(current)
    return groups


def _bare(text: str) -> str:
    return re.sub(r"[^\w']", "", text.lower())


def _lines(texts: list[str], max_lines: int, max_chars: int) -> list[list[int]]:
    """Split a card into two balanced lines, only when it is too long for one."""
    if max_lines == 1 or len(texts) == 1 or len(" ".join(texts)) <= max_chars:
        return [list(range(len(texts)))]
    total = sum(len(t) for t in texts) + len(texts) - 1
    best, best_diff, run = 1, float("inf"), 0
    for k in range(1, len(texts)):
        run += len(texts[k - 1]) + (1 if k > 1 else 0)
        diff = abs(total - run - 1 - run)
        if diff < best_diff:
            best, best_diff = k, diff
    return [list(range(best)), list(range(best, len(texts)))]


def _emphasis(group: list[Word], mode: str) -> set[int]:
    forced = {i for i, w in enumerate(group) if w.get("emph") is True}
    if mode == "off":
        return set()
    if mode == "manual" or forced:
        return forced
    return {i for i in [auto_emphasis(group)] if i is not None and group[i].get("emph") is not False}


def auto_emphasis(group: list[Word]) -> int | None:
    """The word in a caption most worth highlighting: numbers, strong words, else the longest word."""
    best, best_score = None, 0.0
    for i, w in enumerate(group):
        bare = re.sub(r"[^\w$%€£']", "", w["text"]).lower()
        if not bare or bare in STOP_WORDS or w.get("emph") is False:
            continue
        score = 0.0
        if re.search(r"\d", bare) or bare.startswith(("$", "€", "£")) or bare.endswith("%"):
            score = 10
        elif bare in POWER_WORDS or w["text"].endswith("!"):
            score = 8
        elif len(bare) >= 6:
            score = len(bare) / 2
        if score > best_score:
            best, best_score = i, score
    return best
