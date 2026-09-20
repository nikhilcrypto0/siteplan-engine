"""Search the building rules as published, so an answer can quote the order, not a memory.

A language model asked "what setback does a 35 m tower need?" will answer from whatever it
half-remembers. This reads the government order itself and hands back the passage with its
page number, so the answer can be checked against the source in one step.

The extracted text is cached beside the PDF: the order runs to a couple of hundred pages and
pulling the text out takes the best part of a minute.
"""

from __future__ import annotations

import contextlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

STOPWORDS = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in",
    "is", "it", "its", "of", "on", "or", "shall", "that", "the", "to", "with", "which",
    "what", "how", "much", "many", "does", "do", "can", "i", "we", "you", "my",
))
PHRASE_WEIGHT = 1.5
K1 = 1.2  # BM25: how quickly a repeated word stops adding to the score
B = 0.75  # BM25: how much a passage's length counts against it
MIN_CHUNK_CHARS = 120
MAX_CHUNK_CHARS = 900
CACHE_VERSION = 1


@dataclass(frozen=True)
class Passage:
    page: int
    text: str
    score: float

    def as_dict(self) -> dict:
        return {"page": self.page, "text": self.text, "score": round(self.score, 2)}


class RuleBook:
    """The rules document, chunked into passages that can be searched and quoted."""

    def __init__(self, source: str, passages: list[tuple[int, str]]) -> None:
        self.source = source
        self.passages = passages
        self._words = [_words(text) for _, text in passages]
        # The order writes "drive way", people ask about a "driveway"; joining neighbouring
        # words lets one find the other without a synonym list.
        self._joined = [
            {a + b for a, b in zip(words, words[1:], strict=False)} for words in self._words
        ]
        self._average_length = (
            sum(len(w) for w in self._words) / len(self._words) if self._words else 0.0
        )
        self._document_frequency: dict[str, int] = {}
        for words, joined in zip(self._words, self._joined, strict=True):
            for word in set(words) | joined:
                self._document_frequency[word] = self._document_frequency.get(word, 0) + 1

    @classmethod
    def load(cls, pdf: str | Path) -> RuleBook:
        """Read the PDF, using the cached text when it is still current."""
        path = Path(pdf)
        if not path.is_file():
            raise FileNotFoundError(f"no rules document at {path}")
        cache = path.with_suffix(".passages.json")
        stamp = {"version": CACHE_VERSION, "size": path.stat().st_size,
                 "mtime": int(path.stat().st_mtime)}
        if cache.is_file():
            try:
                stored = json.loads(cache.read_text())
                if stored.get("stamp") == stamp:
                    return cls(path.name, [(p["page"], p["text"]) for p in stored["passages"]])
            except (json.JSONDecodeError, KeyError):
                pass  # a broken cache is not worth a crash; rebuild it
        passages = _read_pdf(path)
        with contextlib.suppress(OSError):  # a read-only folder just means slower next time
            cache.write_text(json.dumps(
                {"stamp": stamp,
                 "passages": [{"page": page, "text": text} for page, text in passages]}
            ))
        return cls(path.name, passages)

    def search(self, query: str, limit: int = 3) -> list[Passage]:
        """The passages that best match the question, best first."""
        terms = _words(query)
        if not terms:
            return []
        total = len(self.passages) or 1
        found: list[Passage] = []
        for (page, text), words, joined in zip(
            self.passages, self._words, self._joined, strict=True
        ):
            score = 0.0
            counts = {w: float(words.count(w)) for w in set(terms) if w in words}
            # Matching a word the document spells as two ("drive way" for "driveway") is
            # stronger evidence than matching one ordinary word, so it weighs more.
            counts |= {w: PHRASE_WEIGHT for w in set(terms) if w not in counts and w in joined}
            # BM25: repeating a word stops helping after a while, and a long passage needs
            # more matches to count. Without this a wide table of road widths outranks the
            # one clause that answers "how wide must the driveway be".
            length = len(words) / (self._average_length or 1)
            for word, count in counts.items():
                rarity = math.log(1 + total / (1 + self._document_frequency.get(word, 0)))
                saturated = count * (K1 + 1) / (count + K1 * (1 - B + B * length))
                score += saturated * rarity
            if len(counts) > 1:
                score *= 1 + 0.35 * (len(counts) - 1)  # passages covering more of the question
            if query.strip().lower() in text.lower():
                score *= 2
            if score > 0:
                found.append(Passage(page=page, text=text, score=score))
        found.sort(key=lambda p: (-p.score, p.page))
        return found[:limit]


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9.]+", text.lower()) if w not in STOPWORDS]


def _read_pdf(path: Path) -> list[tuple[int, str]]:
    import pdfplumber  # imported here: only a rules search pays for it

    passages: list[tuple[int, str]] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            for chunk in _chunks(page.extract_text() or ""):
                passages.append((number, chunk))
    return passages


def _chunks(text: str) -> list[str]:
    """Clause-sized pieces: split where a new numbered clause starts, then cap the length."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    pieces: list[list[str]] = [[]]
    for line in lines:
        starts_clause = re.match(r"^(\(?[ivx]+\)|\(?[a-z]\)|\d+\.|TABLE|\d+\))", line, re.I)
        if starts_clause and sum(len(x) for x in pieces[-1]) >= MIN_CHUNK_CHARS:
            pieces.append([])
        pieces[-1].append(line)
    out: list[str] = []
    for piece in pieces:
        joined = " ".join(piece).strip()
        while len(joined) > MAX_CHUNK_CHARS:
            cut = joined.rfind(" ", 0, MAX_CHUNK_CHARS)
            out.append(joined[:cut])
            joined = joined[cut:].strip()
        if len(joined) >= 40:
            out.append(joined)
    return out
