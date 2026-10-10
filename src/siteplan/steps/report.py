"""A step's report, written so the architect can read it at a glance: what was done, what is
happening, what it looks at, the rules and where each comes from, what the engine chose by itself,
and the result. The five questions are the architect's own (2026-10-10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RuleUsed:
    name: str  # a few words: "The 12 m band"
    says: str  # what it asks, in plain words
    source: str  # the document, the clause and the page


@dataclass(frozen=True)
class Choice:
    """Something the engine decided by itself: not a rule and not an answer. Each is listed, so
    nothing it assumes is hidden."""

    what: str
    why: str


@dataclass(frozen=True)
class Table:
    title: str
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass
class StepReport:
    number: int
    title: str
    site: str
    did: list[str] = field(default_factory=list)  # 1. What I did
    happening: list[str] = field(default_factory=list)  # 2. What is happening
    elements: list[str] = field(default_factory=list)  # 3. What it looks at
    rules: list[RuleUsed] = field(default_factory=list)  # 4. Rules, and where they come from
    choices: list[Choice] = field(default_factory=list)  # 4. Not rules: the engine's own
    output: list[str] = field(default_factory=list)  # 5. The result
    tables: list[Table] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)  # what only the architect can answer
    stopped: str | None = None  # why the step stopped, when it did
    picture: str | None = None  # the drawing's file name, beside the report
    files: list[tuple[str, str]] = field(default_factory=list)  # (file name, what it holds)

    def markdown(self) -> str:
        out = [f"# Step {self.number}: {self.title}", "", f"**Site:** {self.site}", ""]
        if self.stopped:
            out += [f"**STOPPED.** {self.stopped}", ""]
        out += _section("1. What I did", self.did)
        out += _section("2. What is happening", self.happening)
        out += _section("3. What it looks at", self.elements)
        out += ["## 4. Rules used, and where each one comes from", ""]
        if self.rules:
            out += _table(("Rule", "What it says", "Where it comes from"),
                          [(r.name, r.says, r.source) for r in self.rules])
        else:
            out += ["No building rule is used in this step.", ""]
        out += ["**Not rules: what the engine decided by itself** (check these)", ""]
        out += _table(("What", "Why"), [(c.what, c.why) for c in self.choices]) if self.choices \
            else ["Nothing.", ""]
        out += ["## 5. Final output", ""]
        if self.picture:
            out += [f"![Step {self.number}]({self.picture})", ""]
        out += [f"- {line}" for line in self.output] + [""]
        for table in self.tables:
            out += [f"**{table.title}**", ""] + _table(table.header, table.rows)
        if self.questions:
            out += ["## Questions for you", ""]
            out += [f"{i}. {q}" for i, q in enumerate(self.questions, 1)] + [""]
        if self.files:
            out += ["## Files", ""] + [f"- `{name}`: {what}" for name, what in self.files] + [""]
        return "\n".join(out)

    def write(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "REPORT.md"
        path.write_text(self.markdown())
        return path


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"## {title}", ""] + [f"- {line}" for line in lines] + [""]


def _table(header: tuple[str, ...], rows) -> list[str]:
    def cell(value: str) -> str:
        return str(value).replace("|", "/").replace("\n", " ")

    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return out + [""]
