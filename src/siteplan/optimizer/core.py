"""The optimizer core: run the strategies, judge every candidate, score what survives, and pick
the alternatives the brief asks for.

    strategies -> candidates -> guard (validator; a FAIL is never returned)
               -> objective -> Pareto front -> one alternative per Pareto point

The core knows nothing of how a strategy searches. It is deterministic for a seed (every tie
falls to the candidate id) and the brief's search budget bounds the search: a strategy that runs
out stops and says so, and what it found so far is still judged and returned. Judging is not
part of the budget (nothing is returned unjudged), so the whole run takes the budget plus one
unit of a strategy's work plus the judging of the candidates it proposed.

Each alternative is validated in its final form (scores and Pareto tag written), so its report
names exactly the candidate returned with it.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from siteplan.contracts import (
    BuildableEnvelope,
    CandidateLayout,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    TowerPrototype,
    ValidationReport,
)
from siteplan.contracts.design_brief import ParetoPoint, UnitsMode
from siteplan.optimizer.guard import Rejection, guard, inputs_of, why_refused
from siteplan.optimizer.interfaces import Budget, SearchContext, Strategy, Validator
from siteplan.optimizer.interim import InterimValidator
from siteplan.optimizer.objective import measure
from siteplan.optimizer.pareto import Scored, select


@dataclass(frozen=True)
class Alternative:
    point: ParetoPoint | None  # None: an extra option beyond the brief's Pareto points
    candidate: CandidateLayout  # scores and Pareto tag written
    report: ValidationReport  # of exactly this candidate
    on_front: bool


@dataclass(frozen=True)
class OptimizerResult:
    alternatives: tuple[Alternative, ...]
    front: tuple[str, ...]  # ids of the candidates no other dominates
    rejected: tuple[Rejection, ...]  # judged and refused, with the reasons
    unfilled: tuple[tuple[ParetoPoint, str], ...]  # a point nothing different was left for
    notes: tuple[str, ...]  # what the strategies and the core say about the run
    budget_exhausted: bool  # a strategy stopped, or was not started, because the budget ran out
    considered: int  # candidates the strategies proposed
    seed: int


def optimize(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
             strategies: Sequence[Strategy], *, validator: Validator | None = None,
             envelope: BuildableEnvelope | None = None,
             prototypes: Sequence[TowerPrototype] = (), seed: int = 0,
             clock: Callable[[], float] = time.monotonic) -> OptimizerResult:
    validator = validator or InterimValidator()
    budget = Budget(brief.objectives.search_budget_s, clock)
    context = SearchContext(site, rules, brief, envelope, tuple(prototypes), seed, budget)
    notes: list[str] = []
    exhausted = False
    candidates: list[CandidateLayout] = []
    for strategy in strategies:
        if budget.expired():
            notes.append(f"{strategy.name}: not run, the time budget was spent")
            exhausted = True
            continue
        proposal = strategy.propose(context)
        notes += [f"{proposal.strategy}: {note}" for note in proposal.notes]
        exhausted = exhausted or proposal.budget_exhausted
        candidates += proposal.candidates
    _require_unique_ids(candidates)
    if brief.program.units.mode is not UnitsMode.MAXIMISE:
        notes.append("the brief's unit target is not part of the objective yet; the program "
                     "verdict reports how far each alternative is from it")

    scores = {c.candidate_id: measure(c, brief) for c in candidates}
    guarded = guard(candidates, validator, site, rules, brief, envelope)
    selection = select([Scored(v.candidate, scores[v.candidate.candidate_id])
                        for v in guarded.passed], brief)

    inputs = inputs_of(site, rules, brief)
    alternatives, rejected = [], list(guarded.rejected)
    for pick in selection.picks:
        final = _annotated(pick.scored, pick.point)
        report = validator.validate(site, rules, brief, final, envelope)
        reasons = why_refused(final, report, inputs)
        if reasons:  # only a validator that contradicts itself gets here
            rejected.append(Rejection(final.candidate_id, final.strategy, tuple(reasons)))
            continue
        alternatives.append(Alternative(pick.point, final, report, pick.on_front))
    return OptimizerResult(
        alternatives=tuple(alternatives),
        front=tuple(s.candidate.candidate_id for s in selection.front),
        rejected=tuple(rejected), unfilled=selection.unfilled, notes=tuple(notes),
        budget_exhausted=exhausted, considered=len(candidates), seed=seed)


def _annotated(scored: Scored, point: ParetoPoint | None) -> CandidateLayout:
    candidate = scored.candidate
    return candidate.model_copy(update={
        "scores": {**candidate.scores, **scored.scores.as_dict()},
        "pareto_tag": point.value if point else None})


def _require_unique_ids(candidates: Sequence[CandidateLayout]) -> None:
    duplicated = sorted(i for i, n in Counter(c.candidate_id for c in candidates).items()
                        if n > 1)
    if duplicated:
        raise ValueError(f"strategies must give every candidate its own id; repeated: "
                         f"{duplicated}")
