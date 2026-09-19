"""Deterministic guards around the model: clean what goes in, check what comes out.

- sanitize_brief: strip role markers and chat-template tokens, normalise markdown,
  cap the length. What was removed is returned for the internal log only; it is never
  echoed back to whoever wrote the brief.
- ungrounded_values: numbers the model extracted that the brief never stated.
- ungrounded_numbers: numbers in an explanation that the solver never produced.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ROLE_MARKERS = re.compile(
    r"(?i)\b(system|assistant|user|developer|tool)\s*:\s*"
    r"|<\|?/?im_(start|end)\|?>|<\|(system|user|assistant|endoftext)\|>"
    r"|\[/?INST\]|<</?SYS>>"
)
_INJECTION_HINTS = re.compile(
    r"(?i)(ignore|disregard|forget) (all |any |the )?(previous|prior|above|earlier) "
    r"(instructions|rules|prompt)|you are now|new instructions:"
)
_MARKDOWN = re.compile(r"(?m)^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+)|```[a-zA-Z]*|[*_`]{1,3}")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class CleanBrief:
    text: str
    removed: tuple[str, ...]  # internal log only


def sanitize_brief(raw: str, max_chars: int) -> CleanBrief:
    removed = []
    text = "".join(ch for ch in raw if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    if text != raw:
        removed.append("control characters")
    if _ROLE_MARKERS.search(text):
        removed.append("role markers")
        text = _ROLE_MARKERS.sub(" ", text)
    if _INJECTION_HINTS.search(text):
        removed.append("instruction-override phrasing (kept, flagged)")
    text = _MARKDOWN.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()
    if len(text) > max_chars:
        removed.append(f"truncated from {len(text)} characters")
        text = text[:max_chars]
    return CleanBrief(text, tuple(removed))


_CATEGORY_AFTER = re.compile(r"\s*(bhk|b\.h\.k|bed)", re.IGNORECASE)


def numbers_in(text: str) -> list[float]:
    """Numbers written in the text, excluding digits that name a flat type ("3BHK",
    "2 bed"), which would otherwise make an invented "3 floors" look stated."""
    return [
        float(m.group().replace(",", ""))
        for m in _NUMBER.finditer(text)
        if not _CATEGORY_AFTER.match(text, m.end())
    ]


def ungrounded_values(
    values: dict[str, float], brief: str, percent_fields: set[str] | None = None
) -> list[str]:
    """Fields whose value the brief never states. A percentage is also accepted when it is
    100 minus the other stated percentages ("the rest")."""
    stated = set(numbers_in(brief))
    percent_fields = percent_fields or set()
    stated_percents = {k: v for k, v in values.items() if k in percent_fields and v in stated}
    flagged = []
    for field, value in values.items():
        if value in stated:
            continue
        if field in percent_fields and stated_percents:
            remainder = 100 - sum(v for k, v in stated_percents.items() if k != field)
            if abs(remainder - value) < 1e-6:
                continue
        flagged.append(field)
    return flagged


def _flatten_numbers(data) -> list[float]:
    if isinstance(data, bool):
        return []
    if isinstance(data, (int, float)):
        return [float(data)]
    if isinstance(data, str):
        return numbers_in(data)
    if isinstance(data, dict):
        return [n for v in data.values() for n in _flatten_numbers(v)]
    if isinstance(data, (list, tuple)):
        return [n for v in data for n in _flatten_numbers(v)]
    return []


def ungrounded_numbers(text: str, source) -> list[float]:
    """Numbers in `text` that do not come from `source` (allowing rounding, shares shown as
    percentages, and small counting words like 'option 2')."""
    allowed = _flatten_numbers(source)
    allowed += [a * 100 for a in allowed if 0 < a < 1]
    bad = []
    for n in numbers_in(text):
        if n <= 10 and n == int(n):
            continue
        if not any(abs(n - a) <= max(0.005 * abs(a), 0.51) for a in allowed):
            bad.append(n)
    return bad
