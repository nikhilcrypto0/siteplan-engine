"""What a search strategy and a validator look like to the optimizer core.

A strategy proposes candidates from the site, the law, the brief and, when it has them, the
buildable envelope and the tower prototypes. The core never looks inside one: today's generator
(legacy.py) is one strategy, and the full search over prototypes and positions (stream C2) is
another. A validator judges one candidate independently and returns the contract's report.

Three promises live here so every strategy keeps them:
- Deterministic for a seed. A strategy draws randomness only from `SearchContext.rng()`, never
  from global state, so the same inputs and seed give the same candidates.
- A time budget on the search (`DesignBrief.objectives.search_budget_s`). A strategy asks
  `budget.expired()` before each unit of work it can stop between, and says so in its proposal
  when it stopped early. It never starts a unit once the budget is gone, so it may overrun by at
  most one unit. What it found so far it still returns.
- Nothing is returned unjudged: the core runs every candidate through the validator (guard.py),
  outside the budget, so a strategy should propose its best candidates, not all it looked at.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from siteplan.contracts import (
    BuildableEnvelope,
    CandidateLayout,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    TowerPrototype,
    ValidationReport,
)


class Budget:
    """A wall-clock allowance for one run; no seconds means no limit. The clock is injectable so
    a test can make time pass deterministically."""

    def __init__(self, seconds: float | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.seconds = seconds
        self._clock = clock
        self._started = clock()

    def elapsed(self) -> float:
        return self._clock() - self._started

    def expired(self) -> bool:
        return self.seconds is not None and self.elapsed() >= self.seconds


@dataclass(frozen=True)
class SearchContext:
    """Everything a strategy may use. The envelope and prototypes are optional: the legacy
    generator needs neither, the full search needs both."""

    site: CanonicalSiteModel
    rules: ResolvedRules
    brief: DesignBrief
    envelope: BuildableEnvelope | None = None
    prototypes: tuple[TowerPrototype, ...] = ()
    seed: int = 0
    budget: Budget = field(default_factory=Budget)

    def rng(self, stream: str = "") -> random.Random:
        """A generator seeded from the run's seed (and a name, for a strategy that wants
        several independent streams): the same seed always gives the same numbers."""
        return random.Random(f"{self.seed}:{stream}")


@dataclass(frozen=True)
class Proposal:
    """What one strategy brings back: candidates, and what it says about its own run (why it
    found nothing, what it left untried)."""

    strategy: str
    candidates: tuple[CandidateLayout, ...] = ()
    notes: tuple[str, ...] = ()
    budget_exhausted: bool = False  # it stopped early because the budget ran out


class Strategy(Protocol):
    name: str

    def propose(self, context: SearchContext) -> Proposal: ...


class Validator(Protocol):
    def validate(self, site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
                 candidate: CandidateLayout, envelope: BuildableEnvelope | None = None
                 ) -> ValidationReport: ...
