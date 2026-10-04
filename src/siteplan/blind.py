"""Blind acceptance: the generator sees the raw survey, the architect's answers and the firm's
standard libraries, never the firm's finished plan for the site.

A finished plan may serve a debug run (its outline as the net plot, say), but nothing taken from
it may reach a blind run: not a debug profile, not a value tagged FIRM_FINISHED_PLAN in a profile
or the answers, and not the finished drawing itself given as the survey. `blind_leaks` names
every such input; acceptance refuses a blind run that has any, and a debug run must say so.
"""

from __future__ import annotations

from pathlib import Path

from siteplan.contracts.common import SourceKind

DEBUG, BLIND = "debug", "blind"


class BlindLeak(ValueError):
    """A blind acceptance run was given something taken from the firm's finished plan."""


def blind_leaks(survey: Path, answers: dict, profile=None,
                finished_plans: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Every input that would let the firm's finished plan into a blind run."""
    found = []
    if survey.name in set(finished_plans):
        found.append(f"the survey {survey.name} is one of the firm's finished plans")
    if profile is not None and profile.debug_fixture:
        found.append(f"the profile '{profile.name}' is a debug fixture")
    if profile is not None:
        for section, values in (("site", profile.site), ("layout", profile.layout)):
            found += [f"profile {section}.{key} comes from the firm's finished plan"
                      for key, item in values.items()
                      if item.source_kind is SourceKind.FIRM_FINISHED_PLAN]
    found += [f"answer '{key}' comes from the firm's finished plan"
              for key, kind in (answers.get("_source_kind") or {}).items()
              if SourceKind(kind) is SourceKind.FIRM_FINISHED_PLAN]
    return found


def finished_values(project: dict) -> list[str]:
    """Values in a built project recorded as coming from the firm's finished plan."""
    return sorted(key for key, kind in (project.get("source_kinds") or {}).items()
                  if SourceKind(kind) is SourceKind.FIRM_FINISHED_PLAN)


def check(mode: str, survey: Path, answers: dict, profile=None,
          finished_plans: tuple[str, ...] | list[str] = ()) -> None:
    if mode not in (BLIND, DEBUG):
        raise ValueError(f"mode is '{BLIND}' or '{DEBUG}', not {mode!r}")
    leaks = blind_leaks(survey, answers, profile, finished_plans)
    if mode == BLIND and leaks:
        raise BlindLeak("A blind acceptance run may not use the firm's finished plan: "
                        + "; ".join(leaks) + ". Run it as a debug run (--debug) instead.")
