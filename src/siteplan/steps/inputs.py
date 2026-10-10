"""What the steps work from: the raw survey, and the project the architect's answers (or a
project file) describe, each value with where it came from. A blind run refuses anything taken
from the firm's finished plan, as acceptance does (blind.py)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import LineString

from siteplan.blind import BLIND, BlindLeak, check, finished_values
from siteplan.intake import Draft, build_project, extract, load_defaults
from siteplan.profiles import AssumptionProfile, apply_profile
from siteplan.project import Project
from siteplan.runner import read_survey
from siteplan.survey import Survey

_WORDS = ("north", "north-east", "east", "south-east", "south", "south-west", "west",
          "north-west")
_CODES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class Inputs:
    survey_path: Path
    draft: Draft  # what the survey settles before anyone is asked anything
    survey: Survey  # the sheet in metres
    water: tuple[tuple[str, LineString], ...]  # each water body the project names, its lines
    water_missing: tuple[str, ...]  # water bodies the project names that the survey does not draw
    project: Project
    sources: dict[str, str]
    status: dict[str, str]
    source_kinds: dict[str, str]
    mode: str  # 'blind' or 'debug'
    given_as: str  # 'your answers' or 'the project file'

    @property
    def site(self) -> str:
        run = "blind run" if self.mode == BLIND else (
            "DEBUG RUN: it may use the firm's finished plan, so it is not evidence")
        return f"{self.project.name}; survey `{self.survey_path.name}`; {run}"

    @property
    def water_keys(self) -> set[str]:
        """The colours or layers the project says its water is drawn in."""
        return {(w.survey_colour or w.survey_layer or "").upper()
                for w in self.project.site.water}

    def told(self, key: str) -> str:
        """Where a value came from and how far it can be trusted, in a few words."""
        source = self.sources.get(key)
        status = self.status.get(key)
        kind = self.source_kinds.get(key)
        if not source and not status:
            return f"{self.given_as} (no source recorded)"
        parts = [source or self.given_as]
        if status:
            parts.append(str(status))
        if kind == "FIRM_FINISHED_PLAN":
            parts.append("taken from the firm's finished plan")
        return ", ".join(parts)


def from_answers(survey: Path, answers: dict, workspace: Path | None = None,
                 profile: AssumptionProfile | None = None, mode: str = BLIND) -> Inputs:
    """The project the answers describe, built as `siteplan start` builds it."""
    workspace = workspace or survey.parent
    defaults = load_defaults(workspace)
    check(mode, survey, answers, profile, defaults.finished_plans)
    draft = extract(survey)
    project = build_project(draft, answers, defaults)
    if profile is not None:
        project = apply_profile(project, profile)
    return _inputs(survey, draft, project, mode, "your answers")


def from_project(survey: Path, project_file: Path, workspace: Path | None = None,
                 mode: str = BLIND) -> Inputs:
    defaults = load_defaults(workspace or survey.parent)
    check(mode, survey, {}, None, defaults.finished_plans)
    project = json.loads(project_file.read_text())
    return _inputs(survey, extract(survey), project, mode, "the project file")


def _inputs(survey: Path, draft: Draft, project: dict, mode: str, given_as: str) -> Inputs:
    leaked = finished_values(project)
    if mode == BLIND and leaked:
        raise BlindLeak("A blind run may not use the firm's finished plan: "
                        f"{', '.join(leaked)}. Run it as a debug run (--debug) instead.")
    model = Project.model_validate(project)
    water, missing = [], []
    for body in model.site.water:
        lines = read_survey(survey, body).water
        water += [(body.kind, line) for line in lines]
        if not lines:
            drawn_as = body.survey_colour or f"layer {body.survey_layer}"
            missing.append(f"{body.kind.replace('_', ' ')} ({drawn_as})")
    return Inputs(survey, draft, read_survey(survey), tuple(water), tuple(missing), model,
                  {k: str(v) for k, v in (project.get("sources") or {}).items()},
                  {k: str(v) for k, v in (project.get("status") or {}).items()},
                  {k: str(v) for k, v in (project.get("source_kinds") or {}).items()},
                  mode, given_as)


def compass(bearing_deg: float) -> str:
    """'north' to 'north-west', for a bearing clockwise from north."""
    return _WORDS[round((bearing_deg % 360) / 45) % 8]


def compass_word(code: str) -> str:
    """'W' -> 'west'."""
    return _WORDS[_CODES.index(code)] if code in _CODES else code


def bearing(origin: tuple[float, float], to: tuple[float, float]) -> float:
    """Clockwise from north (y is north)."""
    return math.degrees(math.atan2(to[0] - origin[0], to[1] - origin[1])) % 360
