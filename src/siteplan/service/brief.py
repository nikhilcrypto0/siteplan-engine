"""The architect's brief read into a DesignBrief, and what the architect approves before a run.

Every number an Intent holds must be written in the brief (guards.ungrounded_values), a flat
category the firm's library does not have is refused, and a value neither the brief nor the
project file states is asked for, never guessed. The DesignBrief is the project's own
(adapters.brief, with the firm's standards as standards.py resolves them: the project file's,
else the workspace's, else the engine's default) with what the brief states in place of the
project's values; the architect is shown both, each with where it came from. The brief never
sets a standard.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from siteplan.adapters import brief as brief_of
from siteplan.contracts import CanonicalSiteModel, DesignBrief
from siteplan.contracts.common import Provenance, Sourced, SourceKind
from siteplan.contracts.design_brief import MIX_SUM_TOLERANCE, HeightMode
from siteplan.contracts.resolved_rules import WhenOpen
from siteplan.guards import sanitize_brief, ungrounded_values
from siteplan.intake import WorkspaceDefaults
from siteplan.legal.site import readings_of
from siteplan.library import FlatLibrary
from siteplan.project import Project
from siteplan.service import summaries
from siteplan.service.models import MAX_BRIEF_CHARS, Fact, HeightChoice, Intent, ServiceError
from siteplan.service.standards import Standard
from siteplan.site_amenities import AmenityLibrary

log = logging.getLogger("siteplan.service")


def read_brief(text: str, intent: Intent, project: Project, library: FlatLibrary
               ) -> tuple[str, list[str]]:
    """The architect's words, cleaned, and what is missing. Every number the intent holds must
    be written in them; a category the firm's library does not have is refused."""
    clean = sanitize_brief(text, MAX_BRIEF_CHARS)
    if clean.removed:
        log.info("brief sanitised: %s", "; ".join(clean.removed))  # never shown back
    if not clean.text:
        raise ServiceError("The brief is empty.")
    stated = {f"unit mix {k}": v for k, v in intent.unit_mix_percent.items()}
    if intent.floors_above_stilt is not None:
        stated["floors above the stilt"] = float(intent.floors_above_stilt)
    ungrounded = ungrounded_values(stated, clean.text,
                                   percent_fields={f"unit mix {k}"
                                                   for k in intent.unit_mix_percent})
    if ungrounded:
        raise ServiceError("The brief never states " + ", ".join(
            f"{name} {stated[name]:g}" for name in ungrounded) + ": ask the architect; a number "
            "the brief does not write is never used.")
    unknown = sorted(set(intent.unit_mix_percent) - library.categories)
    if unknown:
        raise ServiceError(f"The firm's flat library has no {unknown}; it has "
                           f"{sorted(library.categories)}.")
    missing = []
    total = sum(intent.unit_mix_percent.values())
    if intent.unit_mix_percent and abs(total / 100 - 1) > MIX_SUM_TOLERANCE:
        missing.append(f"the unit mix: the shares the brief states add up to {total:g}%")
    if project.layout is None:
        missing.append("the project's brief (floors and unit mix): start the project through "
                       "the intake flow, siteplan start")
    return clean.text, missing


def design(project: Project, defaults: WorkspaceDefaults, amenities: AmenityLibrary | None,
           intent: Intent, words: str) -> DesignBrief:
    """The project's DesignBrief with what the brief states in place of its own values."""
    base = brief_of(project, defaults, amenities=amenities)
    height = base.height_intent
    if intent.height is HeightChoice.MOST_THE_RULES_ALLOW:
        height = height.model_copy(update={"mode": HeightMode.MAX_LEGAL,
                                           "floors_above_stilt": None})
    elif intent.height is HeightChoice.FLOORS_ABOVE_STILT:
        height = height.model_copy(update={"mode": HeightMode.FIXED,
                                           "floors_above_stilt": intent.floors_above_stilt})
    program = base.program
    if intent.unit_mix_percent:
        total = sum(intent.unit_mix_percent.values())
        program = program.model_copy(update={"unit_mix": Sourced[dict[str, float]](
            value={k: v / total for k, v in intent.unit_mix_percent.items()},
            status=Provenance.USER_CONFIRMED, source_kind=SourceKind.ARCHITECT,
            source=f"the architect's brief, approved before the run: {_percent(intent)}")})
    objectives = base.objectives
    if intent.massing is not None:
        order = [intent.massing, *(p for p in objectives.pareto if p is not intent.massing)]
        objectives = objectives.model_copy(update={"pareto": order})
    made = base.model_copy(update={"words": words, "height_intent": height, "program": program,
                                   "objectives": objectives})
    return DesignBrief.model_validate(made.model_dump())  # held to the contract whole


def _percent(intent: Intent) -> str:
    return ", ".join(f"{k} {v:g}%" for k, v in sorted(intent.unit_mix_percent.items()))


def brief_facts(project: Project) -> list[Fact]:
    layout = project.layout
    if layout is None:
        return []

    def of(name: str, key: str, value) -> Fact:
        return Fact(name=name, value=value, status=project.status.get(key),
                    source=project.sources.get(key, "project file"))

    mix = ", ".join(f"{k} {v * 100:g}%" for k, v in sorted(layout.unit_mix.items()))
    return [of("floors above the stilt", "floors", "max" if layout.maximise else layout.floors),
            of("unit mix", "unit_mix", mix), of("club house", "club_house", layout.club_house)]


def _said(f: Fact) -> str:
    value = "not known" if f.value is None else f"{f.value}{' ' + f.unit if f.unit else ''}"
    how = ", ".join(str(x) for x in (f.status, f.source_kind) if x)
    return f"{f.name}: {value}" + (f" [{how}]" if how else "")


def approval_lines(*, debug: bool, finished: tuple[str, ...], project_file: str,
                   survey: Path | None, project: Project, standards: Sequence[Standard],
                   left_out: Sequence[str], site: CanonicalSiteModel, brief: DesignBrief,
                   intent: Intent) -> list[str]:
    """What the architect is shown before anything runs: the site facts that drive the rules,
    each with how it is known (the access road's legal width and the land given up among them),
    the readings and test mode the project states, the firm's standards (and any prototype the
    firm's longest block leaves out), and what the brief asks, saying where each came from."""
    selections, when_open = readings_of(project)
    h, mix = brief.height_intent, brief.program.unit_mix.value
    run = ("Blind: the firm's finished plans are refused" if not debug else
           "DEBUG RUN: " + ("; ".join(finished) if finished else
                            "no input comes from the firm's finished plan"))
    lines = [run,
             f"Project file {project_file}; survey {survey.name if survey else 'none'}",
             *(_said(f) for f in summaries.site_facts(site)),
             "Readings the project file states: " + (", ".join(
                 f"{k} = {v}" for k, v in selections.items()) or "none (every reading of every "
                 "open question is evaluated)")]
    if when_open is WhenOpen.CONSERVATIVE:
        lines.append("The project's conservative test mode: the GHMC parking column while whose "
                     "rules apply is open")
    lines += [s.line() for s in standards]
    lines += list(left_out)
    height = ("the most the rules allow" if h.mode is HeightMode.MAX_LEGAL
              else f"stilt + {h.floors_above_stilt} floors")
    lines += [f"Height ({'the brief' if intent.height else 'the project file'}): {height}",
              f"Unit mix ({'the brief' if intent.unit_mix_percent else 'the project file'}): "
              + ", ".join(f"{k} {v * 100:g}%" for k, v in sorted(mix.items()))]
    if intent.massing is not None:
        lines.append(f"Shown first (the brief): {intent.massing.value}")
    lines.append(f"Brief: {brief.words}")
    return lines
