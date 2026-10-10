"""Contract fixtures on made-up land (see build.py): one JSON instance of every contract for each
of four plots, so every stream can start against the contracts with the same data."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from siteplan import rules as law
from siteplan.contracts import ALL_CONTRACTS, ResolvedRules
from siteplan.contracts.common import Basis
from siteplan.contracts.resolved_rules import STILT_RAISE, RuleValue

HERE = Path(__file__).parent
SITES = ("rectangle", "l_plot_with_arm", "nala_plot", "small_plot")


def load(site: str, contract: str) -> BaseModel:
    """One fixture, validated against its contract."""
    return ALL_CONTRACTS[contract].model_validate_json((HERE / site / f"{contract}.json")
                                                        .read_text())


def with_raise(rules: ResolvedRules) -> ResolvedRules:
    """The hand-built rules carry no raise, as a contract stored before 2026-10-10 does, so the
    tests written on them keep their heights; this gives them the stilt floor's raise and the
    plinth the resolver now carries (NBC Part 3 12.1), to test what the raise changes."""
    height = rules.height.model_copy(update={
        "stilt_raise_m": RuleValue[float](value=law.COVERED_PARKING_RAISE_M, unit="m",
                                          clause=law.COVERED_PARKING_RAISE_CLAUSE,
                                          basis=Basis.UNRESOLVED_INTERPRETATION),
        "plinth_m": RuleValue[float](value=law.PLINTH_MIN_M, unit="m", clause=law.PLINTH_CLAUSE),
        "raise_interpretation": STILT_RAISE})
    return rules.model_copy(update={"height": height})
