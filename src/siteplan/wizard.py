"""Start a project by answering plain questions, instead of writing a settings file by hand.

Everything an architect has to tell us is asked in their own words: how wide the road is,
which authority approves it, how many floors, what mix of flats. The answers are turned
into the project file the rest of the tool reads.

Nothing here guesses: a question with no sensible default is asked until it is answered,
and an answer that does not parse is asked again with an example.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

FEET_PER_M = 3.28084
AUTHORITIES = ("GHMC", "CMC", "HMDA", "DTCP", "OTHER")


@dataclass(frozen=True)
class Question:
    key: str
    prompt: str
    default: str = ""
    example: str = ""
    optional: bool = False
    parse: Callable[[str], Any] | None = None  # checked as it is typed, not at the end
    when: Callable[[dict[str, str]], bool] | None = None  # asked only if the answers so far say so



def parse_mix(text: str) -> dict[str, float]:
    """'70% 2BHK, 30% 3BHK' or '2BHK 70, 3BHK 30' -> shares that add up to 1."""
    pattern = (r"(\d+(?:\.\d+)?)\s*%?\s*([1-9]\s?BHK)"       # "70% 2BHK"
               r"|([1-9]\s?BHK)\s*[: ]\s*(\d+(?:\.\d+)?)")    # "2BHK 70"
    pairs = re.findall(pattern, text, re.I)
    found: dict[str, float] = {}
    for a_value, a_name, b_name, b_value in pairs:
        name = (a_name or b_name).upper().replace(" ", "")
        found[name] = found.get(name, 0.0) + float(a_value or b_value)
    if not found:
        raise ValueError("write it like '70% 2BHK, 30% 3BHK'")
    total = sum(found.values())
    if abs(total - 100) > 1:
        raise ValueError(f"the shares add up to {total:g}%, not 100%")
    return {name: value / total for name, value in found.items()}


def parse_length(text: str) -> tuple[str, float]:
    """'40 ft' or '12 m' -> ('ft', 40.0) or ('m', 12.0). A bare number is read as feet,
    which is how these roads are spoken about locally."""
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(ft|feet|'|m|metre|meter|metres|meters)?\s*$",
                     text, re.I)
    if not match:
        raise ValueError("write it like '40 ft' or '12 m'")
    unit = (match.group(2) or "ft").lower()
    return ("m" if unit.startswith("m") else "ft", float(match.group(1)))


def parse_number(text: str, what: str) -> float:
    try:
        return float(text.strip())
    except ValueError:
        raise ValueError(f"{what} should be a number") from None


QUESTIONS = (
    Question("name", "Project name", example="Dhulapally group housing"),
    Question("client", "Client name", optional=True),
    Question("architect", "Architect or firm", optional=True),
    Question("road", "How wide is the road the site faces", example="40 ft, or 12 m",
             parse=lambda v: parse_length(v)),
    Question("master_road", "How wide will that road be after widening, if it is being "
             "widened", optional=True, example="60 ft", parse=lambda v: parse_length(v)),
    Question("authority", f"Which authority approves it ({', '.join(AUTHORITIES)})",
             default="HMDA"),
    Question("floors", "How many floors above the stilt", example="8",
             parse=lambda v: parse_number(v, "floors")),
    Question("mix", "What mix of flats", default="70% 2BHK, 30% 3BHK", parse=parse_mix),
    Question("floor_height", "Floor to floor height in metres", default="3",
             parse=lambda v: parse_number(v, "floor height")),
    Question("stilt_height", "Stilt height in metres", default="3",
             parse=lambda v: parse_number(v, "stilt height")),
    Question("common_area", "Common area loading, as a percentage", default="22",
             parse=lambda v: parse_number(v, "common area")),
)


def build_project(answers: dict[str, str]) -> dict[str, Any]:
    """Turn the answers into the project file, in the shape `Project` expects."""
    unit, road = parse_length(answers["road"])
    site: dict[str, Any] = {f"abutting_road_{unit}": road}
    if answers.get("master_road"):
        master_unit, master = parse_length(answers["master_road"])
        site[f"master_plan_road_{master_unit}"] = master
    authority = (answers.get("authority") or "HMDA").strip().upper()
    if authority and authority != "OTHER":
        site["authority"] = authority

    floors = int(parse_number(answers["floors"], "floors"))
    layout = {
        "floors": floors,
        "unit_mix": parse_mix(answers["mix"]),
        "floor_height_m": parse_number(answers.get("floor_height") or "3", "floor height"),
        "stilt_height_m": parse_number(answers.get("stilt_height") or "3", "stilt height"),
        "common_area_pct": parse_number(answers.get("common_area") or "22", "common area"),
        "options": 3,
    }
    project: dict[str, Any] = {"name": answers["name"].strip(), "site": site, "layout": layout}
    sheet = {k: answers.get(k, "").strip() for k in ("client", "architect")}
    if any(sheet.values()):
        project["sheet"] = {k: v for k, v in sheet.items() if v}
    return project


def collect(ask: Callable[[str], str], say: Callable[[str], None] = print,
            questions: tuple[Question, ...] = QUESTIONS) -> dict[str, str]:
    """Ask every question that applies, re-asking anything that does not make sense."""
    answers: dict[str, str] = {}
    for question in questions:
        if question.when is None or question.when(answers):
            answers[question.key] = _one(question, ask, say)
    return answers


def _one(question: Question, ask: Callable[[str], str], say: Callable[[str], None]) -> str:
    hint = f" [{question.default}]" if question.default else (
        " (press enter to skip)" if question.optional else ""
    )
    while True:
        answer = ask(f"{question.prompt}{hint}: ").strip() or question.default
        if not answer:
            if question.optional:
                return ""
            say(f"  This one is needed. For example: {question.example}")
            continue
        if question.parse is None:
            return answer
        try:
            question.parse(answer)
        except ValueError as exc:
            say(f"  {exc}")  # said next to the question that caused it, not at the end
            continue
        return answer
