"""The full search: the optimizer's second strategy, beside the legacy generator.

It searches what the legacy generator fixes: the prototype and the floor count of every block, the
direction the blocks run and where the columns start across the plot, the tallest block it allows
(which sets the setback zone for the whole plot), and the profile of readings it builds for. The
circulation is drawn from the blocks (network.py), never before them, and the open space, the club
house, the ramp and the facilities take the ground the blocks and roads leave (ground.py), at one
end of the plot kept for them when there is none to spare.

Blocks below the high-rise height (C3) stand wherever their Table III band's land allows: in the
columns, and on the ground the ring road leaves (fringe.py). Every configuration of a profile
that leaves counts open on both sides of 21 m is searched with such blocks and without, each kind
on its own quota, and the objective decides between them when they are judged. Each narrow part of
the plot is tried for such a block, and the notes say what came of it.

The search is staged so a run stays within the brief's time budget:

1. every configuration is *evaluated* cheaply: blocks in columns, the best sequence of prototypes
   and heights for each, the cluster the ground holds;
2. the best of each profile are *laid out* exactly (roads, entrance, club house, ramp, open space,
   cellars) and drawn as candidates, the next best taking the place of any the ground cannot hold;
   then the most valuable with blocks below 21 m are *repaired* (C4-07): evaluated again with the
   fringe keeping no room for the program, a block given up at a time until the exact half lays
   them out, each a layout of its own;
3. the candidates are *judged* by the independent validator: nothing it fails is proposed, and each
   proposal says which of its UNVERIFIED items rest on which reading.

Randomness comes only from `SearchContext.rng`; the same seed gives the same proposal.
"""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace

from shapely.errors import GEOSException, TopologicalError
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan import validator as independent
from siteplan.contracts import CandidateLayout, DesignBrief, ValidationReport
from siteplan.optimizer.interfaces import Budget, Proposal, SearchContext, Validator
from siteplan.optimizer.objective import Scores, measure
from siteplan.optimizer.pareto import Scored, leaders, pareto_front, same_idea, select
from siteplan.optimizer.search import fringe
from siteplan.optimizer.search.build import build_candidate
from siteplan.optimizer.search.columns import Choice
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
# The share of the time budget spent when evaluating stops and when laying out stops; judging
# may use the rest.
EVALUATE_SHARE = 0.35
LAY_OUT_SHARE = 0.75
PITCH_GAP_M = 10.0  # the least gap reckoned beside a column when offsets are spread over a pitch


@dataclass(frozen=True)
class Limits:
    """What bounds a run, besides the time budget: how many of each thing is looked at. They are
    search bounds, never rules."""

    offsets: int = 8  # where the columns start, across one pitch
    heights: int = 3  # the tallest block a configuration allows: this many floor counts, top down
    # configurations laid out exactly for each profile, and the most tried to get them: for each
    # kind of configuration, with blocks below 21 m and without
    laid_per_profile: int = 14
    attempts_per_profile: int = 60
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
    low_blocks: list[list[Polygon]] = field(default_factory=list)  # of each layout laid out


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
                        tuple(notes + _notes(run, tally, found, chosen)
                              + (_region_notes(run, tally, chosen) if run else [])),
                        budget_exhausted=tally.exhausted)

    # --- the three stages -------------------------------------------------------------------

    def _search(self, context: SearchContext, run: Run, wanted: Sequence[Profile], tally: Tally
                ) -> list[Judged]:
        budget = context.budget
        queues = self._evaluate(context, run, wanted, tally, _Stage(budget, EVALUATE_SHARE))
        laid = self._lay_out(context, run, queues, tally, _Stage(budget, LAY_OUT_SHARE))
        laid += self._improve(run, laid, tally, _Stage(budget, LAY_OUT_SHARE))
        return self._judge(context, run, laid, tally, _Stage(budget, 1.0))

    def _evaluate(self, context: SearchContext, run: Run, wanted: Sequence[Profile],
                  tally: Tally, stage: _Stage) -> dict[str, list[Evaluation]]:
        """Every configuration, evaluated, grouped by profile. The order is the seed's, so a
        budget that stops the stage early stops it on a different part of the search for another
        seed and the same part for the same seed. The configurations that let blocks below 21 m
        stand come after the rest, in their own order, so the others are evaluated as they were
        before such blocks could stand."""
        angles = orientations(run.plot.net)
        configs: dict[bool, list[tuple]] = {False: [], True: []}
        for profile in wanted:
            floors = sorted({c.floors for found in run.classes[profile.key].values()
                             for c in found}, reverse=True)[:self.limits.heights]
            for angle in angles:
                for tallest in floors:
                    for step in range(self.limits.offsets):
                        for low in _low_blocks(run, profile):
                            configs[low].append((profile, angle, tallest, step, low))
        context.rng("evaluate").shuffle(configs[False])
        context.rng("evaluate-low").shuffle(configs[True])
        # each again with further clusters on the ground the first leaves (C4-02), after all of
        # the others and in an order of its own, so those are evaluated as they were before
        more = [*configs[False], *configs[True]]
        context.rng("evaluate-clusters").shuffle(more)
        plans = [*((c, False, False) for c in [*configs[False], *configs[True]]),
                 *((c, True, False) for c in more)]
        if run.other_depths:
            # each again with columns of the kit's other depths too (C4-04), where it has any:
            # after all of the others and in an order of its own, as further clusters are
            mixed = [(c, clusters, True) for c, clusters, _ in plans]
            context.rng("evaluate-depths").shuffle(mixed)
            plans += mixed
        queues: dict[str, list[Evaluation]] = {p.key: [] for p in wanted}
        for (profile, angle, tallest, step, low), clusters, depths in plans:
            if stage.expired():
                tally.exhausted = True
                break
            pitch = run.depth_m + max(run.q.road_m, PITCH_GAP_M)
            ev = _guarded(evaluate, run, Config(profile, angle, step * pitch / self.limits.offsets,
                                                tallest, None, low_blocks=low,
                                                more_clusters=clusters, mixed_depths=depths))
            tally.evaluated += 1
            if isinstance(ev, Failure):
                tally.reasons[ev.reason] += 1
            else:
                queues[profile.key].append(ev)
        return queues

    def _lay_out(self, context: SearchContext, run: Run, queues: dict[str, list[Evaluation]],
                 tally: Tally, stage: _Stage) -> list[tuple[Profile, Config, object]]:
        """The best configurations of each profile, laid out exactly. Those that let blocks below
        21 m stand have their own quota beside the others', so neither crowds out the other: the
        objective decides between them when they are judged. Those whose columns may be of the
        kit's other depths (C4-04) are laid out after all of the others, with quotas of their own,
        so they take neither the others' place nor their time, and the others keep their
        numbers."""
        laid: list[tuple[Profile, Config, object]] = []
        by_key = {p.key: p for p in run.profiles}
        for mixed in (False, True):
            for key, evaluations in queues.items():
                laid += self._lay_out_profile(
                    run, by_key[key], [ev for ev in evaluations
                                       if ev.config.mixed_depths == mixed], tally, stage)
        return laid

    def _improve(self, run: Run, laid: list[tuple[Profile, Config, object]], tally: Tally,
                 stage: _Stage) -> list[tuple[Profile, Config, object]]:
        """Iterative repair of what was laid out (C4-07). The most valuable layouts of each
        profile whose configuration lets blocks below 21 m stand are evaluated again with the
        fringe keeping no room for the program, so that the exact half alone says whether the club
        house, the ramp and the open space still have room; one that has none gives up its last
        block on the fringe, then the next, until it lays out or stands no more than the layout it
        came from. What lays out is a layout of its own, after all the others, and the validator
        judges it like any other."""
        found: list[tuple[Profile, Config, object]] = []
        seen = {_signature(ev) for _, _, (ev, _) in laid}
        by_profile: dict[str, list[tuple[Profile, Config, Evaluation]]] = {}
        for profile, config, (ev, _) in laid:
            if config.low_blocks and config.fringe_room:
                by_profile.setdefault(profile.key, []).append((profile, config, ev))
        for items in by_profile.values():
            items.sort(key=lambda item: -item[2].value)  # stable: between equals, as laid
            for profile, config, ev in items[:self.limits.judged_per_profile]:
                if stage.expired():
                    tally.exhausted = True
                    return found
                more = _guarded(evaluate, run, replace(config, fringe_room=False))
                if isinstance(more, Failure):
                    continue
                for cut in _cuts(more, ev.value):
                    signature = _signature(cut)
                    if signature in seen:
                        break
                    seen.add(signature)
                    result, why = _guarded(lay_out, run, cut, failed=(None, ""))
                    if result is not None:
                        tally.laid += 1
                        tally.low_blocks.append([p.footprint for p in result.placements
                                                 if not p.standing.choice.cls.high_rise])
                        found.append((profile, cut.config, (cut, result)))
                        break
                    tally.reasons[why] += 1
                    if not why.startswith(ROOM_FAILURES):
                        break
        return found

    def _lay_out_profile(self, run: Run, profile: Profile, evaluations: list[Evaluation],
                         tally: Tally, stage: _Stage) -> list[tuple[Profile, Config, object]]:
        """One profile's configurations, the most valuable first, laid out exactly until its
        quotas are met; one that has no room for the club house or the open space is tried again
        with an end of the plot kept for them."""
        laid: list[tuple[Profile, Config, object]] = []
        limits = self.limits
        heap = [(-ev.value, i, ev) for i, ev in enumerate(evaluations)]
        heapq.heapify(heap)
        counter = len(evaluations)
        seen: set[tuple] = set()
        made, attempts = Counter(), Counter()

        def open_(low: bool) -> bool:
            return (made[low] < limits.laid_per_profile
                    and attempts[low] < limits.attempts_per_profile)

        while heap and (open_(False) or open_(True)):
            if stage.expired():
                tally.exhausted = True
                break
            _, _, ev = heapq.heappop(heap)
            signature = _signature(ev)
            if signature in seen or not open_(ev.config.low_blocks):
                continue
            seen.add(signature)
            result, why = _guarded(lay_out, run, ev, failed=(None, ""))
            attempts[ev.config.low_blocks] += 1
            if result is None:
                tally.reasons[why] += 1
                if ev.config.reserve is None and why.startswith(ROOM_FAILURES):
                    # the same with an end kept, and with blocks below 21 m too (whose own
                    # configuration may have had no room to place one); never the other way
                    kinds = [low for low in _low_blocks(run, ev.config.profile)
                             if low or not ev.config.low_blocks]
                    for side in SIDES:
                        for low in kinds:
                            variant = _guarded(evaluate, run, _reserved(
                                ev.config, side, 1.0, low))
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
            made[ev.config.low_blocks] += 1
            tally.laid += 1
            tally.low_blocks.append([p.footprint for p in result.placements
                                     if not p.standing.choice.cls.high_rise])
            laid.append((profile, ev.config, (ev, result)))
        return laid

    def _judge(self, context: SearchContext, run: Run, laid, tally: Tally, stage: _Stage
               ) -> list[Judged]:
        site, rules, brief = context.site, context.rules, context.brief
        drawn = []
        for number, (profile, _, (_, result)) in enumerate(laid, 1):
            candidate = build_candidate(
                result, site=site, rules=rules, brief=brief, plot=run.plot, q=run.q,
                profile=profile, envelope=run.envelope,
                candidate_id=f"{NAME.lower()}-{profile.key}-{number}", seed=context.seed,
                notes=_planning_notes(run))
            drawn.append((measure(candidate, brief), profile, candidate))
        order = []
        for key in dict.fromkeys(profile.key for _, profile, _ in drawn):  # a quota each
            order += _to_judge([d for d in drawn if d[1].key == key],
                               self.limits.judged_per_profile, brief)
        order.sort(key=lambda d: (-d[0].yield_score, d[2].candidate_id))  # the best first
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
            selection = select([Scored(j.candidate, j.scores,
                                       (len(j.rests.readings), len(j.rests.checks)))
                                for j in pool], brief)
            chosen += [by_id[p.scored.candidate.candidate_id]
                       for p in selection.picks][:self.limits.per_profile_proposed]
        robust = [j for j in found if j.rests.holds_under_every_reading]
        if robust and not any(j.rests.holds_under_every_reading for j in chosen):
            chosen.append(max(robust, key=lambda j: (j.scores.yield_score,
                                                     j.candidate.candidate_id)))
        unique = {j.candidate.candidate_id: j for j in chosen}
        return sorted(unique.values(),
                      key=lambda j: (-j.scores.yield_score, j.candidate.candidate_id))


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


def _to_judge(pool: list[tuple], quota: int, brief: DesignBrief) -> list[tuple]:
    """Which of one profile's layouts the validator judges (C4-09): the front of the objective's
    axes first, and of it first the best for each point the brief asks for (pareto.leaders: the
    most saleable, the most open and conventional, the compromise; C4-11, where the front grew
    wider than the quota), then the rest of the front by yield, then the rest by yield; a layout
    that is the same idea as one already taken (pareto.same_idea) waits until no other is left.
    The six judged were the six most saleable, which a profile could fill with copies of one
    scheme a step apart."""
    scored = [Scored(c, sc) for sc, _, c in pool]
    front = {id(s.candidate) for s in pareto_front(scored)}
    first = [id(s.candidate) for s in leaders(scored, brief)]
    ranked = sorted(pool, key=lambda d: (first.index(id(d[2])) if id(d[2]) in first
                                         else len(first), id(d[2]) not in front,
                                         -d[0].yield_score, d[2].candidate_id))
    taken: list[tuple] = []
    waiting: list[tuple] = []
    for d in ranked:
        if len(taken) >= quota:
            break
        (waiting if any(same_idea(d[2], t[2]) for t in taken) else taken).append(d)
    return (taken + waiting)[:quota]


def _cuts(ev: Evaluation, least: float) -> Iterator[Evaluation]:
    """The evaluation, then the same with its last block on the fringe given up, and the next,
    while it stands more than `least` (C4-07)."""
    columns = sum(s.choice.value for s in ev.standing)
    for kept in range(len(ev.fringe), -1, -1):
        value = columns + sum(f.standing.choice.value for f in ev.fringe[:kept])
        if value <= least:
            return
        yield replace(ev, fringe=ev.fringe[:kept], value=value)


def _reserved(config: Config, side: str, scale: float, low_blocks: bool | None = None) -> Config:
    return Config(config.profile, config.angle_deg, config.offset_m, config.max_floors, side,
                  scale, config.low_blocks if low_blocks is None else low_blocks,
                  config.more_clusters, config.mixed_depths, config.fringe_room)


def _low_blocks(run: Run, profile: Profile) -> tuple[bool, ...]:
    """Whether a configuration lets blocks below the high-rise height stand: both ways where the
    profile leaves counts open on both sides of it, so the objective decides between layouts with
    them and without; the one way there is otherwise."""
    low, high = run.has_low(profile), run.has_high(profile)
    return (False, True) if low and high else (low,)


def _signature(ev: Evaluation) -> tuple:
    blocks = [*ev.standing, *(f.standing for f in ev.fringe)]
    return (round(ev.config.angle_deg, 2), ev.config.reserve, ev.config.reserve_scale,
            ev.config.low_blocks,
            tuple(sorted((round(s.x0, 1), round(s.y0, 1), s.choice.key,
                          round(s.frame.angle_deg, 2) if s.frame else -1.0) for s in blocks)))


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
    return ("the law leaves no floor count open to these prototypes within the brief's height "
            "intent, neither a high-rise nor a block below 21 m on a band that may stand here: "
            "nothing is laid out")


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


def _region_notes(run: Run, tally: Tally, chosen: Sequence[Judged]) -> list[str]:
    """Whether each narrow part of the plot (a region of the envelope's width profile beside its
    main body, no smaller than the smallest block) can take a block below 21 m, and whether the
    layouts proposed use one there: an arm the ring road cannot reach is the optimizer's
    question, never dropped unasked."""
    choices = _low_options(run)
    smallest = min((c.length_m * c.depth_m for c in choices), default=0.0)
    regions = [r for r in _narrow_regions(run) if r.area >= smallest]  # a sliver holds none
    if not regions or not choices:
        return []
    below = run.rules.height.high_rise_from_m.value
    notes = []
    for tried in fringe.try_regions(run.plot, regions, choices, orientations(run.plot.net), run.q):
        centre = tried.shape.centroid
        where = (f"the narrow part of the plot at ({centre.x:,.0f}, {centre.y:,.0f}), "
                 f"{tried.area_sqm:,.0f} m² and {tried.width_m:.1f} m wide, was tried for a block "
                 f"below {below:g} m and ")
        if tried.fits is None:
            notes.append(f"{where}none fits: a block that low keeps its Table III setbacks there "
                         f"and is left at most {tried.land_width_m:.1f} m, less than the narrowest "
                         f"prototype ({tried.narrowest_m:.2f} m deep)")
            continue
        used = sum(1 for j in chosen if any(
            _mostly_in(j.candidate.placed_footprint(t), tried.shape) for t in j.candidate.towers))
        laid = sum(1 for blocks in tally.low_blocks
                   if any(_mostly_in(b, tried.shape) for b in blocks))
        text = (f"{where}one fits ({tried.fits.prototype.id} at {tried.fits.cls.floors} floors): "
                f"{used} of the {len(chosen)} layouts proposed stand one there")
        if not used:
            text += (f"; {laid} of the layouts laid out did, and the objective ranked them lower"
                     if laid else "; no layout laid out could stand one there with a road or a "
                     "pathway reaching it and the ground the rest of the layout needs left free")
        notes.append(text)
    return notes


def _narrow_regions(run: Run) -> list[Polygon]:
    """The regions of the net plot's width profile beside its largest, the main body."""
    profile = next((p for p in run.envelope.width_profiles if p.applies_to == "net plot"), None)
    if profile is None:
        return []
    shapes = sorted((r.shape.to_shapely() for r in profile.regions), key=lambda s: -s.area)
    return shapes[1:]


def _low_options(run: Run) -> list[Choice]:
    """Every block below 21 m the kit makes under any profile searched, once each."""
    found: dict[tuple[str, int], Choice] = {}
    for profile in run.profiles:
        classes = run.classes[profile.key]
        tallest = max((c.floors for cs in classes.values() for c in cs), default=0)
        for choice in fringe.options(run.fringe_kit, classes, tallest, run.q):
            found.setdefault((choice.prototype.id, choice.cls.floors), choice)
    return list(found.values())


def _mostly_in(footprint: BaseGeometry, region: BaseGeometry) -> bool:
    return footprint.area > 0 and footprint.intersection(region).area > footprint.area / 2


__all__ = ["FullSearchStrategy", "Limits", "NAME"]
