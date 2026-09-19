"""Stage 2b: the assistant, as a LangGraph flow.

sanitize (code) -> extract (model) -> confirm (architect) -> solve (code) -> explain (model)

The model does two things only: read the brief into a schema, and draft the explanation.
Every number it reads is checked against the brief; every number it writes is checked
against the solver's output. The architect approves the interpreted request before
anything is solved, and that step cannot be skipped.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from openai import APIConnectionError
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError
from shapely.geometry import Polygon

from siteplan.guards import sanitize_brief, ungrounded_numbers, ungrounded_values
from siteplan.layout import LayoutRequest
from siteplan.library import FlatLibrary
from siteplan.llm import (
    AssistantConfig,
    BudgetExceeded,
    ChatModel,
    DailyLedger,
    Meter,
    estimate_tokens,
)
from siteplan.project import Project
from siteplan.runner import run_layout

log = logging.getLogger("siteplan.assistant")

# field -> (default, how the architect reads it, unit)
DEFAULTS = {
    "stilt_height_m": (3.0, "stilt height", " m"),
    "floor_height_m": (3.0, "floor-to-floor height", " m"),
    "common_area_pct": (22.0, "common area loading", "%"),
}
RANKING_WORDS = re.compile(
    r"(?i)\b(most|least|highest|lowest|best|worst|largest|smallest|biggest|more|fewer|less|"
    r"maximum|minimum|better|worse|top)\b"
)
MAX_UNCLEAR = 5
EXPLAIN_MAX_TOKENS = 400


class BriefExtraction(BaseModel):
    floors_above_stilt: int | None = None
    stilt_height_m: float | None = None
    floor_height_m: float | None = None
    unit_mix_percent: dict[str, float | None] = {}
    common_area_pct: float | None = None
    unclear: list[str] = []


def extraction_schema(categories: list[str]) -> dict:
    number = {"type": ["number", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "floors_above_stilt": {"type": ["integer", "null"]},
            "stilt_height_m": number,
            "floor_height_m": number,
            "unit_mix_percent": {
                "type": "object",
                "additionalProperties": False,
                "properties": {c: number for c in categories},
                "required": categories,
            },
            "common_area_pct": number,
            "unclear": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "floors_above_stilt",
            "stilt_height_m",
            "floor_height_m",
            "unit_mix_percent",
            "common_area_pct",
            "unclear",
        ],
    }


def extraction_prompt(categories: list[str]) -> str:
    return (
        "You turn an architect's brief into JSON for a layout tool. Copy numbers exactly as "
        "the brief states them. floors_above_stilt counts only the floors above the stilt: "
        "'stilt + 8 floors' means 8. unit_mix_percent gives the percentage of flats for each "
        f"category ({', '.join(categories)}); if the brief says 'the rest' for one category, "
        "give 100 minus the others. Use null for anything the brief does not state. Put "
        "anything you could not map into 'unclear'. Never guess."
    )


COMMENTARY_PROMPT = (
    "An architect is comparing layout options. The comparison below was computed by code "
    "and is correct; do not repeat or re-rank it. In at most 60 words, add one or two plain "
    "observations about trade-offs visible in the JSON (for example tower count against "
    "unit mix). Do not rank options, do not use words like most, best, more or less, and "
    "use only numbers that appear in the JSON."
)


class Decision(BaseModel):
    """The architect's answer at the approval step. Only a real boolean true approves."""

    model_config = ConfigDict(extra="forbid")
    approve: StrictBool
    edits: dict[str, Any] = {}


class State(TypedDict, total=False):
    brief: str
    clean_brief: str
    request: dict
    assumptions: list[str]
    flagged: list[str]
    missing: list[str]
    unclear: list[str]
    options: list[dict]
    explanation: str
    explanation_source: str
    status: str


@dataclass
class Assistant:
    model: ChatModel
    config: AssistantConfig
    project: Project
    library: FlatLibrary
    plot: Polygon
    out_dir: Path
    meter: Meter = field(init=False)
    thread_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        self.meter = Meter(self.config.budgets, DailyLedger(self.config.ledger_dir))
        self.categories = sorted(self.library.categories)
        self.graph = self._build()

    # --- running -------------------------------------------------------------------

    def start(self, brief: str) -> dict[str, Any]:
        return self._invoke({"brief": brief})

    def resume(self, decision: Any) -> dict[str, Any]:
        # LangGraph treats a None resume as "no answer yet"; make it a refused answer instead.
        return self._invoke(Command(resume={} if decision is None else decision))

    def _invoke(self, payload: Any) -> dict[str, Any]:
        return self.graph.invoke(payload, {"configurable": {"thread_id": self.thread_id}})

    @staticmethod
    def pending_question(result: dict[str, Any]) -> dict | None:
        interrupts = result.get("__interrupt__") or []
        return interrupts[0].value if interrupts else None

    # --- graph ---------------------------------------------------------------------

    def _build(self):
        g = StateGraph(State)
        g.add_node("sanitize", self._guarded(self._sanitize))
        g.add_node("extract", self._guarded(self._extract))
        g.add_node("confirm", self._confirm)
        g.add_node("solve", self._guarded(self._solve))
        g.add_node("explain", self._guarded(self._explain))
        g.add_edge(START, "sanitize")
        for here, nxt in (("sanitize", "extract"), ("extract", "confirm"), ("confirm", "solve")):
            g.add_conditional_edges(here, lambda s, n=nxt: END if s.get("status") else n)
        g.add_conditional_edges("solve", lambda s: END if s.get("status") else "explain")
        g.add_edge("explain", END)
        return g.compile(checkpointer=InMemorySaver())

    def _guarded(self, node):
        def run(state: State) -> dict:
            try:
                return node(state)
            except BudgetExceeded as exc:
                log.error("halted: %s", exc)
                return {"status": f"Stopped: {exc}. Raise the budget in the config to continue."}
            except (ConnectionError, APIConnectionError) as exc:  # includes timeouts
                log.error("model unreachable: %s", exc)
                return {"status": f"The local model is not reachable at {self.config.base_url}."}

        return run

    def _sanitize(self, state: State) -> dict:
        clean = sanitize_brief(state["brief"], self.config.max_brief_chars)
        if clean.removed:
            log.info("brief sanitised: %s", "; ".join(clean.removed))  # never shown to the user
        if not clean.text:
            return {"status": "The brief is empty."}
        return {"clean_brief": clean.text}

    def _extract(self, state: State) -> dict:
        messages = [
            {"role": "system", "content": extraction_prompt(self.categories)},
            {"role": "user", "content": state["clean_brief"]},
        ]
        schema = extraction_schema(self.categories)
        for attempt in range(1, self.config.retries + 2):
            allowance = self.meter.allowance("extract", estimate_tokens(messages))
            text, usage = self.model.complete(messages, schema, allowance)
            self.meter.charge("extract", usage)
            try:
                extraction = BriefExtraction.model_validate_json(text)
            except ValidationError as exc:
                log.warning("extraction rejected (attempt %d): %s", attempt, exc)
                continue
            if set(extraction.unit_mix_percent) - set(self.categories):
                log.warning("extraction rejected (attempt %d): unknown categories", attempt)
                continue
            return self._interpret(extraction, state["clean_brief"])
        return {"status": "The assistant could not read the brief. Please restate the floors "
                "and unit mix."}

    def _interpret(self, ext: BriefExtraction, brief: str) -> dict:
        """Deterministic: turn the extraction into a request, listing defaults, gaps and any
        value the brief never stated."""
        request: dict[str, Any] = {}
        assumptions, missing = [], []
        if ext.floors_above_stilt:
            request["floors"] = ext.floors_above_stilt
        else:
            missing.append("floors above the stilt")
        percents = {k: v for k, v in ext.unit_mix_percent.items() if v}
        total = sum(percents.values())
        if not percents:
            missing.append("unit mix")
        elif abs(total - 100) > 1:
            missing.append(f"unit mix (the stated shares add up to {total:g}%)")
        else:
            request["unit_mix"] = {k: v / total for k, v in percents.items()}
        for name, (default, label, unit) in DEFAULTS.items():
            value = getattr(ext, name)
            if value is None:
                assumptions.append(f"{label} not stated; using {default:g}{unit}")
            else:
                request[name] = value
        stated = {k: v for k, v in request.items() if isinstance(v, (int, float))}
        stated |= {f"unit mix {k}": v for k, v in percents.items()}
        flagged = ungrounded_values(
            stated, brief, percent_fields={f"unit mix {k}" for k in percents}
        )
        return {
            "request": request,
            "assumptions": assumptions,
            "missing": missing,
            "flagged": flagged,
            "unclear": [u[:120] for u in ext.unclear[:MAX_UNCLEAR]],
        }

    def _confirm(self, state: State) -> dict:
        # Re-runs from the top on resume, so nothing with side effects comes before interrupt.
        decision = interrupt(
            {
                "request": state["request"],
                "assumptions": state.get("assumptions", []),
                "missing": state.get("missing", []),
                "flagged": state.get("flagged", []),
                "unclear": state.get("unclear", []),
            }
        )
        try:
            answer = Decision.model_validate(decision)
        except ValidationError:
            log.warning("approval answer rejected: %r", decision)
            return {"status": "Stopped: the approval answer was not understood; nothing solved."}
        if answer.approve is not True:
            return {"status": "Stopped: the architect did not approve the request."}
        merged = {**state["request"], **answer.edits}
        try:
            request = LayoutRequest.model_validate(merged)
        except ValidationError as exc:
            fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
            return {"status": f"The request is incomplete or invalid ({', '.join(fields)})."}
        return {"request": request.model_dump()}

    def _solve(self, state: State) -> dict:
        request = LayoutRequest.model_validate(state["request"])
        try:
            options = run_layout(self.project, self.library, self.plot, request, self.out_dir)
        except ValueError as exc:
            return {"status": f"The solver refused the request: {exc}"}
        if not options:
            return {"status": "No tower fits inside the setbacks with the required open space."}
        return {"options": options}

    def _explain(self, state: State) -> dict:
        """The comparison is computed, not generated. A live run showed the 9B model calling
        the option with the most open space the one that 'sells the most area': every number
        it quoted was real and the claim was still false. So ranking stays in code; optional
        model commentary is shown only if it neither ranks nor invents a number."""
        keys = ("option", "towers", "total_flats", "saleable_sqft", "open_space_share_pct",
                "unit_mix_achieved", "mix_error", "rule_findings")
        facts = [{k: o[k] for k in keys} for o in state["options"]]
        comparison = compare_options(facts)
        if not self.config.model_commentary:
            return {"explanation": comparison, "explanation_source": "code"}
        messages = [
            {"role": "system", "content": COMMENTARY_PROMPT},
            {"role": "user", "content": comparison + "\n\n" + json.dumps(facts)},
        ]
        for attempt in range(1, self.config.retries + 2):
            allowance = min(
                self.meter.allowance("explain", estimate_tokens(messages)), EXPLAIN_MAX_TOKENS
            )
            text, usage = self.model.complete(messages, None, allowance)
            self.meter.charge("explain", usage)
            text = text.strip()
            bad = ungrounded_numbers(text, facts)
            ranks = RANKING_WORDS.findall(text)
            if text and not bad and not ranks:
                return {
                    "explanation": f"{comparison}\n\nModel commentary: {text}",
                    "explanation_source": "code + model commentary",
                }
            log.warning(
                "commentary rejected (attempt %d): unsourced numbers %s, ranking words %s",
                attempt, bad, ranks,
            )
        return {"explanation": comparison, "explanation_source": "code"}


def compare_options(facts: list[dict]) -> str:
    """The comparison an architect needs, computed from the solver's numbers."""
    by_sale = max(facts, key=lambda f: f["saleable_sqft"])
    by_open = max(facts, key=lambda f: f["open_space_share_pct"])
    by_mix = min(facts, key=lambda f: f["mix_error"])
    lines = [
        f"Option {by_sale['option']} sells the most: {by_sale['saleable_sqft']:,} sft in "
        f"{by_sale['total_flats']} flats.",
        f"Option {by_open['option']} leaves the most open space: "
        f"{by_open['open_space_share_pct']}% of the plot.",
        f"Option {by_mix['option']} comes closest to the requested unit mix "
        f"({by_mix['unit_mix_achieved']}).",
    ]
    for f in facts:
        fails = [r for r, s in f["rule_findings"].items() if s == "FAIL"]
        waiting = [r for r, s in f["rule_findings"].items() if s in {"NEEDS_INPUT", "NOT_CHECKED"}]
        lines.append(
            f"Option {f['option']}: {f['towers']} tower{'' if f['towers'] == 1 else 's'}, "
            f"{f['total_flats']} flats, {f['saleable_sqft']:,} sft, open space "
            f"{f['open_space_share_pct']}%; "
            + (f"FAILS {', '.join(fails)}" if fails else "no rule failures")
            + (f"; not yet checked: {', '.join(waiting)}" if waiting else "")
            + "."
        )
    return "\n".join(lines)
