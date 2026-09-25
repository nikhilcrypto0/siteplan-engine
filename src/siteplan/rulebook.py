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
CACHE_VERSION = 2  # passages now carry their section and clause


# The 2012 order is the only one we can search: the amending orders are scanned images with
# no text to index. So its superseded passages have to announce themselves, or the search
# hands back a repealed rule with a real page number, which is the most convincing way to be
# wrong. Each pattern is the wording as it appears in the 2012 text.
SUPERSEDED = (
    (re.compile(r"TABLE\s*[–—-]\s*IV", re.I),
     "G.O.Ms.No.50 of 2019 substituted this table. Call rules_for_height for what is in force."),
    (re.compile(r"high[-\s]rise building.{0,60}?18\s*m|below\s*18\s*m\s+in height", re.I | re.S),
     "G.O.Ms.No.95 of 2026 raised the high-rise threshold to 21 m."),
    (re.compile(r"green planting strip", re.I),
     "G.O.Ms.No.7 of 2016 limited this to sides where the setback is 9 m or more."),
)


def _superseded_by(text: str) -> str:
    """What later order replaced this passage, if any."""
    notes = [note for pattern, note in SUPERSEDED if pattern.search(text)]
    return " ".join(notes)


@dataclass(frozen=True)
class Passage:
    page: int
    text: str
    score: float
    section: str = ""  # the numbered heading this sits under, e.g. "13. PARKING"
    clause: str = ""  # the marker the passage opens with, e.g. "(vii)"
    superseded_by: str = ""  # set when a later order replaced this wording

    @property
    def citation(self) -> str:
        """How to refer to this passage, built from the document, never composed by a model."""
        number = re.match(r"\s*(\d+)\.", self.section)
        rule = f"rule {number.group(1)}" if number else self.section or "the order"
        if self.clause:
            return f"{rule}{self.clause} (page {self.page})"
        return f"{rule}, page {self.page}"

    def as_dict(self) -> dict:
        return {"page": self.page, "section": self.section, "clause": self.clause,
                "citation": self.citation, "text": self.text, "score": round(self.score, 2),
                "superseded_by": self.superseded_by,
                "still_in_force": not self.superseded_by}


@dataclass(frozen=True)
class Chunk:
    """A passage as stored: the text with where it came from."""

    page: int
    text: str
    section: str = ""
    clause: str = ""


class RuleBook:
    """The rules document, chunked into passages that can be searched and quoted."""

    def __init__(self, source: str, passages: list[Chunk]) -> None:
        self.source = source
        self.passages = passages
        self._words = [_words(chunk.text) for chunk in passages]
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
                    return cls(path.name, [Chunk(**p) for p in stored["passages"]])
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # a broken or older cache is not worth a crash; rebuild it
        passages = _read_pdf(path)
        with contextlib.suppress(OSError):  # a read-only folder just means slower next time
            cache.write_text(json.dumps(
                {"stamp": stamp, "passages": [vars(chunk) for chunk in passages]}
            ))
        return cls(path.name, passages)

    def search(self, query: str, limit: int = 3) -> list[Passage]:
        """The passages that best match the question, best first."""
        terms = _words(query)
        if not terms:
            return []
        total = len(self.passages) or 1
        found: list[Passage] = []
        for chunk, words, joined in zip(self.passages, self._words, self._joined, strict=True):
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
            if query.strip().lower() in chunk.text.lower():
                score *= 2
            if score > 0:
                found.append(Passage(page=chunk.page, text=chunk.text, score=score,
                                     section=chunk.section, clause=chunk.clause,
                                     superseded_by=_superseded_by(chunk.text)))
        found.sort(key=lambda p: (-p.score, p.page))
        return found[:limit]


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9.]+", text.lower()) if w not in STOPWORDS]


SECTION_RE = re.compile(r"^(\d+)\.\s+([A-Z][A-Z /&,'-]{4,})")  # no brackets: "(viii)" follows
CLAUSE_RE = re.compile(r"^(\([ivxlc]+\)|\([a-z]\)|\([0-9]+\))", re.I)


def _read_pdf(path: Path) -> list[Chunk]:
    import pdfplumber  # imported here: only a rules search pays for it

    chunks: list[Chunk] = []
    section = ""  # headings carry on across pages until the next one
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            page_chunks, section = _chunks(page.extract_text() or "", section)
            chunks += [Chunk(number, text, section_here, clause)
                       for text, section_here, clause in page_chunks]
    return chunks


def _chunks(text: str, section: str) -> tuple[list[tuple[str, str, str]], str]:
    """Clause-sized pieces, each tagged with the section heading it sits under and the clause
    marker it opens with, so an answer can cite the document rather than guess a rule number."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    pieces: list[tuple[list[str], str]] = [([], section)]
    for line in lines:
        heading = SECTION_RE.match(line)
        if heading:
            section = f"{heading.group(1)}. {heading.group(2).strip()}"
        starts_clause = CLAUSE_RE.match(line) or heading or re.match(r"^(TABLE|\d+\))", line, re.I)
        if starts_clause and sum(len(x) for x in pieces[-1][0]) >= MIN_CHUNK_CHARS:
            pieces.append(([], section))
        pieces[-1][0].append(line)
        if heading:  # the heading belongs to the section it opens
            pieces[-1] = (pieces[-1][0], section)
    out: list[tuple[str, str, str]] = []
    for lines_here, section_here in pieces:
        joined = " ".join(lines_here).strip()
        # A chunk may open with its section heading ("13. PARKING (viii) ..."); the clause is
        # whatever marker follows it.
        body = SECTION_RE.sub("", joined, count=1).lstrip()
        opener = CLAUSE_RE.match(body)
        clause = opener.group(1) if opener else ""
        while len(joined) > MAX_CHUNK_CHARS:
            cut = joined.rfind(" ", 0, MAX_CHUNK_CHARS)
            out.append((joined[:cut], section_here, clause))
            joined, clause = joined[cut:].strip(), ""
        if len(joined) >= 40:
            out.append((joined, section_here, clause))
    return out, section
