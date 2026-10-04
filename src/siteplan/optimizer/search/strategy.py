"""The full search: the optimizer's second strategy, beside the legacy generator.

It searches what the legacy generator fixes: the prototype and the floor count of every block, the
direction the blocks run and where the columns start across the plot, the tallest block it allows
(which sets the setback zone for the whole plot), and the profile of readings it builds for. The
circulation is drawn from the blocks (network.py), never before them, and the open space, the club
house, the ramp and the facilities take the ground the blocks and roads leave (ground.py), at one end
of the plot kept for them when there is none to spare.

The search is staged so a run stays within the brief's time budget:

1. every configuration is *evaluated* cheaply: blocks in columns, the best sequence of prototypes
   and heights for each, the cluster the ground holds;
2. the best of each profile are *laid out* exactly (roads, entrance, club house, ramp, open space,
   cellars) and drawn as candidates, the next best taking the place of any the ground cannot hold;
3. the candidates are *judged* by the independent validator: nothing it fails is proposed, and each
   proposal says which of its UNVERIFIED items rest on which reading.

Randomness comes only from `SearchContext.rng`; the same seed gives the same proposal.
"""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from shapely.errors import GEOSException, TopologicalError

from siteplan import validator as independent
from siteplan.contracts import CandidateLayout, ValidationReport
from siteplan.optimizer.interfaces import Budget, Proposal, SearchContext, Validator
from siteplan.optimizer.objective import Scores, measure
from siteplan.optimizer.pareto import Scored, select
from siteplan.optimizer.search.build import build_candidate
from siteplan.optimizer.search.layout import (
    SIDES,
    Config,
    Evaluation,
    Failure,
    Run,
    evaluate,
    lay_out,
    make_run,
)
from siteplan.optimizer.search.readings import Profile, profiles
from siteplan.optimizer.search.verdicts import RestsOn, caveats, failed, rests_on
from siteplan.towers import orientations

NAME = "FULL"
ROOM_FAILURES = ("no room", "open space", "no approach", "no road touches", "the ring road")
RETRY_SCALE = 1.3


@dataclass(frozen=True)
class Limits:
    """What bounds a run, besides the time budget: how many of each thing is looked at. They are
    search bounds, never rules."""

    offsets: int = 8  # where the columns start, across one pitch
    heights: int = 3  # the tallest block a configuration allows: this many floor counts, top down
    laid_per_profile: int = 14  # configurations laid out exactly, for each profile
    attempts_per_profile: int = 60  # and the most tried to get them
    judged_per_profile: int = 6  # candidates the validator judges, for each profile
    per_profile_proposed: int = 4  # the most proposed for each profile


@dataclass(frozen=True)
class Judged:
    candidate: CandidateLayout
    report: ValidationReport
    scores: Scores
    rests: RestsOn
    profile: Profile


@dataclass
class Tally:
    evaluated: int = 0
    laid: int = 0
    judged: int = 0
    reasons: Counter = field(default_factory=Counter)
    rejected: list[str] = field(default_factory=list)
    exhausted: bool = False


class _Stage:
    """The share of the time budget a stage may use: it expires when the share is spent. With no
    budget nothing expires."""

    def __init__(self, budget: Budget, share: float):
        self.budget, self.share = budget, share

    def expired(self) -> bool:
        seconds = self.budget.seconds
        return seconds is not None and self.budget.elapsed() >= self.share * seconds


class FullSearchStrategy:
    name = NAME

    def __init__(self, *, validator: Validator | None = None, limits: Limits | None = None):
        self.validator = validator or independent
        self.limits = limits or Limits()

    def propose(self, context: SearchContext) -> Proposal:
        site, rules, brief = context.site, context.rules, context.brief
        stop = _cannot_run(context)
        if stop:
            return Proposal(NAME, notes=(stop,))
        envelope = context.envelope or _envelope(site, rules)
        found: list[Judged] = []
        tally = Tally()
        run: Run | None = None
        notes: list[str] = []
        passes = (True, False) if brief.design_margins.any_set else (False,)
        for with_margins in passes:
            kit = list(context.prototypes)
            wanted = profiles(rules, brief, kit)
            run = make_run(site, rules, brief, envelope, kit, wanted, with_margins)
            if not any(run.classes[p.key][pid] for p in wanted for pid in run.classes[p.key]):
                return Proposal(NAME, notes=(_no_floors(),))
            tally = Tally()
            found = self._search(context, run, wanted, tally)
            if found:
                if brief.design_margins.any_set and not with_margins:
                    notes.append("the design margins could not all be kept on this site: the "
                                 "layouts keep the legal minimums, and each says what it misses")
                break
        chosen = self._choose(found, brief)
        return Proposal(NAME, tuple(j.candidate for j in chosen),
                        tuple(notes + _notes(run, tally, found, chosen)),
                        budget_exhausted=tally.exhausted)

    # --- the three stages -------------------------------------------------------------------

    def _search(self, context: SearchContext, run: Run, wanted: Sequence[Profile], tally: Tally
                ) -> list[Judged]:
        budget = context.budget
        queues = self._evaluate(context, run, wanted, tally, _Stage(budget, 0.35))
        laid = self._lay_out(context, run, queues, tally, _Stage(budget, 0.75))
        return self._judge(context, run, laid, tally, _Stage(budget, 1.0))

    def _evaluate(self, context: SearchContext, run: Run, wanted: Sequence[Profile],
                  tally: Tally, stage: _Stage) -> dict[str, list[Evaluation]]:
        """Every configuration, evaluated, grouped by profile. The order is the seed's, so a
        budget that stops the stage early stops it on a different part of the search for another
        seed and the same part for the same seed."""
        angles = orientations(run.plot.net)
        configs = []
        for profile in wanted:
            floors = sorted({c.floors for found in run.classes[profile.key].values()
                             for c in found}, reverse=True)[:self.limits.heights]
            for angle in angles:
                for tallest in floors:
                    for step in range(self.limits.offsets):
                        configs.append((profile, angle, tallest, step))
        context.rng("evaluate").shuffle(configs)
        queues: dict[str, list[Evaluation]] = {p.key: [] for p in wanted}
        for profile, angle, tallest, step in configs:
            if stage.expired():
                tally.exhausted = True
                break
            pitch = run.depth_m + max(run.q.road_m, 10.0)
            ev = _guarded(evaluate, run, Config(profile, angle, step * pitch / self.limits.offsets,
                                                tallest, None))
            tally.evaluated += 1
            if isinstance(ev, Failure):
                tally.reasons[ev.reason] += 1
            else:
                queues[profile.key].append(ev)
        return queues

    def _lay_out(self, context: SearchContext, run: Run, queues: dict[str, list[Evaluation]],
                 tally: Tally, stage: _Stage) -> list[tuple[Profile, Config, object]]:
        laid: list[tuple[Profile, Config, object]] = []
        by_key = {p.key: p for p in run.profiles}
        for key, evaluations in queues.items():
            heap = [(-ev.value, i, ev) for i, ev in enumerate(evaluations)]
            heapq.heapify(heap)
            counter = len(evaluations)
            seen: set[tuple] = set()
            made = attempts = 0
            while heap and made < self.limits.laid_per_profile \
                    and attempts < self.limits.attempts_per_profile:
                if stage.expired():
                    tally.exhausted = True
                    break
                _, _, ev = heapq.heappop(heap)
                signature = _signature(ev)
                if signature in seen:
                    continue
                seen.add(signature)
                result, why = _guarded(lay_out, run, ev, failed=(None, ""))
                attempts += 1
                if result is None:
                    tally.reasons[why] += 1
                    if ev.config.reserve is None and why.startswith(ROOM_FAILURES):
                        for side in SIDES:
                            variant = _guarded(evaluate, run, _reserved(ev.config, side, 1.0))
                            if not isinstance(variant, Failure):
                                counter += 1
                                heapq.heappush(heap, (-variant.value, counter, variant))
                    elif ev.config.reserve and ev.config.reserve_scale == 1.0 \
                            and why.startswith(ROOM_FAILURES):
                        variant = _guarded(evaluate, run, _reserved(
                            ev.config, ev.config.reserve, RETRY_SCALE))
                        if not isinstance(variant, Failure):
                            counter += 1
                            heapq.heappush(heap, (-variant.value, counter, variant))
                    continue
                made += 1
                tally.laid += 1
                laid.append((by_key[key], ev.config, (ev, result)))
        return laid

    def _judge(self, context: SearchContext, run: Run, laid, tally: Tally, stage: _Stage
               ) -> list[Judged]:
        site, rules, brief = context.site, context.rules, context.brief
        drawn = []
        for number, (profile, config, (ev, result)) in enumerate(laid, 1):
            candidate = build_candidate(
                result, site=site, rules=rules, brief=brief, plot=run.plot, q=run.q,
                profile=profile, envelope=run.envelope,
                candidate_id=f"{NAME.lower()}-{profile.key}-{number}", seed=context.seed,
                notes=_planning_notes(run))
            drawn.append((measure(candidate, brief), profile, candidate))
        drawn.sort(key=lambda d: (-d[0].yield_score, d[2].candidate_id))
        taken: Counter = Counter()
        order = []
        for scores, profile, candidate in drawn:  # each profile has its own quota
            if taken[profile.key] < self.limits.judged_per_profile:
                taken[profile.key] += 1
                order.append((scores, profile, candidate))
        judged: list[Judged] = []
        for scores, profile, candidate in order:
            if stage.expired() and judged:
                tally.exhausted = True
                break
            report = self.validator.validate(site, rules, brief, candidate, run.envelope)
            tally.judged += 1
            problems = failed(report)
            if report.verdict.legal.value == "FAIL":
                tally.rejected.append(f"{candidate.candidate_id}: "
                                      + ("; ".join(problems) or "a blocking discrepancy"))
                continue
            noted = candidate.model_copy(update={
                "caveats": [*candidate.caveats, *caveats(report)]})
            judged.append(Judged(noted, report, scores, rests_on(report), profile))
        return judged

    # --- the proposal -----------------------------------------------------------------------

    def _choose(self, found: Sequence[Judged], brief) -> list[Judged]:
        """The best distinct ideas of each profile (the brief's Pareto points among them), and the
        best layout that holds under every reading if the profiles did not give one."""
        chosen: list[Judged] = []
        for key in dict.fromkeys(j.profile.key for j in found):
            pool = [j for j in found if j.profile.key == key]
            by_id = {j.candidate.candidate_id: j for j in pool}
            selection = select([Scored(j.candidate, j.scores) for j in pool], brief)
            chosen += [by_id[p.scored.candidate.candidate_id]
                       for p in selection.picks][:self.limits.per_profile_proposed]
        robust = [j for j in found if j.rests.holds_under_every_reading]
        if robust and not any(j.rests.holds_under_every_reading for j in chosen):
            chosen.append(max(robust, key=lambda j: (j.scores.yield_score, j.candidate.candidate_id)))
        unique = {j.candidate.candidate_id: j for j in chosen}
        return sorted(unique.values(), key=lambda j: (-j.scores.yield_score, j.candidate.candidate_id))


def _guarded(step, run: Run, argument, failed=None):
    """One step of the search, with a shape the geometry library cannot resolve counted as a
    configuration that lays nothing, never as a stop: the validator would refuse such a layout
    anyway, and the other configurations are still worth their turn."""
    try:
        return step(run, argument)
    except (GEOSException, TopologicalError) as error:
        reason = f"the geometry library could not resolve a shape ({type(error).__name__})"
        return Failure(reason) if failed is None else (failed[0], reason)


def _planning_notes(run: Run) -> list[str]:
    """What the layout assumed that nothing in the inputs settles."""
    if run.plot.access_assumed:
        return ["ASSUMED: nobody has said which side the access road runs along, so the entrance "
                "stands where the approach to the ring road is shortest; the architect confirms it"]
    return []


def _reserved(config: Config, side: str, scale: float) -> Config:
    return Config(config.profile, config.angle_deg, config.offset_m, config.max_floors, side,
                  scale)


def _signature(ev: Evaluation) -> tuple:
    return (round(ev.config.angle_deg, 2), ev.config.reserve, ev.config.reserve_scale,
            tuple(sorted((round(s.x0, 1), round(s.y0, 1), s.choice.key) for s in ev.standing)))


def _cannot_run(context: SearchContext) -> str | None:
    site, rules = context.site, context.rules
    if site.net_plot is None:
        return ("the net plot is not known (where the surrendered land lies is the architect's to "
                "say): nothing can be laid out")
    if not context.prototypes:
        return "the full search needs the tower prototypes: none were given"
    if not rules.circulation.applies.value:
        return ("the site is not a Group Development Scheme (rule 2(c)): rule 8(m)'s internal "
                "roads do not apply, and layouts without them are not supported yet")
    return None


def _no_floors() -> str:
    return ("the law leaves no high-rise floor count open to these prototypes within the brief's "
            "height intent: nothing is laid out (below the high-rise height Table III applies, and "
            "it is not encoded yet)")


def _envelope(site, rules):
    from siteplan.legal.envelope import envelope  # noqa: PLC0415

    return envelope(site, rules)


def _notes(run: Run | None, tally: Tally, found: Sequence[Judged], chosen: Sequence[Judged]
           ) -> list[str]:
    if run is None:
        return []
    notes = [f"{tally.evaluated} configurations evaluated, {tally.laid} laid out, {tally.judged} "
             f"judged by the validator, {len(chosen)} proposed"]
    if tally.exhausted:
        notes.append("stopped on the time budget: part of the search was not tried")
    if tally.rejected:
        notes.append(f"the validator failed {len(tally.rejected)} layout(s): "
                     + "; ".join(tally.rejected[:3]))
    if not found:
        common = "; ".join(f"{reason} (x{n})" for reason, n in tally.reasons.most_common(3))
        notes.append("no layout was laid that the ground and the rules allow"
                     + (f": {common}" if common else ""))
    held = sum(1 for j in chosen if j.rests.holds_under_every_reading)
    notes.append(f"{held} of {len(chosen)} proposed hold under every reading of the open questions"
                 "; the others each name the readings they rest on")
    notes.append("every layout leaves the height above sea level and the 45 t loading of the "
                 "paving UNVERIFIED")
    return notes


__all__ = ["FullSearchStrategy", "Limits", "NAME"]
