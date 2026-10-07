"""The Pareto front, and the alternatives an architect is shown, one for each of the brief's
points.

A candidate is on the front when no other is at least as good on every axis of the objective
(objective.py) and better on one. From the candidates that survived the guard, the brief's Pareto
points are each filled with the best candidate for that point that is a genuinely different idea
from those already chosen:

- MAX_YIELD: the most saleable area, less what the mix misses by (the legacy generator's score);
- ROBUST: the layout that rests on the fewest open readings of the rules (none: it holds under
  every reading the validator evaluates), the most saleable between equals (C4-09). Only a
  candidate whose readings are known (its validation report read) may fill it, a different idea
  as every alternative is; it is left unfilled when a layout chosen before it already holds under
  every reading;
- CONVENTIONAL_OPEN_SPACE: the most conventional blocks with the most usable open space (C4-12:
  the part a lawn or a play area fits in, near a block), in the plainest
  scheme (the objective's quality: little road, blocks repeated and running one way, few leftover
  pieces; C4-11);
- BALANCED: the compromise nearest the best on every axis, weighted by the brief's priorities.

The extremes are filled first, the layout of least legal dependency right after the most
saleable so that no other point takes it first, and the compromise takes the best of what they
leave, so it stands between them rather than beside the first of them. The alternatives come
back in the order the brief lists its points. When the brief asks for more options than it has
points, the best remaining different ideas by yield follow, untagged. Between layouts a point's
own measure ties on, the one leaving less ground to no use is taken (site use, C4-11); the
compromise weighs site use already.

Two layouts are one idea when they have as many towers running the same way on mostly the same
ground, whatever their height: one floor less is not another scheme. A point nothing different
remains for is named, never filled with a copy. The front is preferred; a candidate the front
dominates is chosen only when no front member would be a different idea.

Which layouts are chosen is settled by that fill; the labels are then checked once. Two layouts
can tie exactly on an earlier point's measure (the same yield) and differ on a later one (open
space), and the fill alone may hand the later point's label to the layout that suits it less.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import permutations

from shapely.ops import unary_union

from siteplan.contracts import CandidateLayout, DesignBrief
from siteplan.contracts.design_brief import ParetoPoint
from siteplan.geometry import angle_gap
from siteplan.optimizer.objective import AXES, Scores, priority_weights

SAME_IDEA_OVERLAP = 0.5  # two layouts sharing this much tower ground are one idea
ANGLE_FAMILY_DEG = 10.0  # towers running within this of each other run the same way
FILL_ORDER = (ParetoPoint.MAX_YIELD, ParetoPoint.ROBUST, ParetoPoint.CONVENTIONAL_OPEN_SPACE,
              ParetoPoint.BALANCED)


@dataclass(frozen=True)
class Scored:
    candidate: CandidateLayout
    scores: Scores
    # the open questions of the rules it rests on and the checks that depend on them (0, 0: it
    # holds under every reading); None while its validation report has not been read
    rests: tuple[int, int] | None = None


Key = Callable[[Scored], tuple]  # how well a candidate serves a point: smaller is better


@dataclass(frozen=True)
class Pick:
    point: ParetoPoint | None  # None: one of the extra options asked beyond the brief's points
    scored: Scored
    on_front: bool


@dataclass(frozen=True)
class Selection:
    picks: tuple[Pick, ...]
    unfilled: tuple[tuple[ParetoPoint, str], ...]  # a point nothing different was left for
    front: tuple[Scored, ...]


def dominates(a: Scores, b: Scores) -> bool:
    better = False
    for x, y in zip(a.vector, b.vector, strict=True):
        if x < y:
            return False
        better = better or x > y
    return better


def pareto_front(pool: Sequence[Scored]) -> list[Scored]:
    """The candidates nothing else dominates, in the order given."""
    return [s for s in pool
            if not any(dominates(other.scores, s.scores) for other in pool if other is not s)]


def same_idea(a: CandidateLayout, b: CandidateLayout) -> bool:
    """Whether two candidates are one idea: as many towers, running the same way, on mostly the
    same ground (each tower as its prototype and placement make it, not the generator's copy)."""
    if len(a.towers) != len(b.towers):
        return False
    if not _same_directions([t.rotation_deg for t in a.towers],
                            [t.rotation_deg for t in b.towers]):
        return False
    ground_a, ground_b = _ground(a), _ground(b)
    union = ground_a.union(ground_b).area
    return union > 0 and ground_a.intersection(ground_b).area / union >= SAME_IDEA_OVERLAP


def _ground(candidate: CandidateLayout):
    return unary_union([candidate.placed_footprint(t) for t in candidate.towers])


def _same_directions(a: list[float], b: list[float]) -> bool:
    """Whether the towers of two layouts can be paired so that every pair runs within
    ANGLE_FAMILY_DEG. Directions are undirected (mod 180). On a circle the best pairing is the
    sorted order turned by some shift, so trying every shift is exact."""
    a, b = sorted(x % 180 for x in a), sorted(x % 180 for x in b)
    return any(all(angle_gap(x, b[(i + shift) % len(b)]) <= ANGLE_FAMILY_DEG
                   for i, x in enumerate(a)) for shift in range(len(b)))


def select(pool: Sequence[Scored], brief: DesignBrief) -> Selection:
    """The brief's alternatives from the guarded pool, and the front they come from."""
    front = pareto_front(pool)
    on_front = {id(s) for s in front}
    keys = _point_keys(pool, brief)
    ranked = {point: sorted(pool, key=lambda s, key=key: (*key(s), s.candidate.candidate_id))
              for point, key in keys.items()}
    picks: list[Pick] = []

    def next_different(order: list[Scored], front_first: bool = True) -> Scored | None:
        ranked = sorted(order, key=lambda s: id(s) not in on_front) if front_first else order
        for s in ranked:  # stable: front first, in the point's own order
            if not any(s is p.scored or same_idea(s.candidate, p.scored.candidate)
                       for p in picks):
                return s
        return None

    listed = list(dict.fromkeys(brief.objectives.pareto))
    unknown = [point for point in listed if point not in FILL_ORDER]
    if unknown:
        raise ValueError(f"the optimizer has no ranking for {unknown}")
    unfilled = []
    def least_dependent(order: list[Scored]) -> tuple[Scored | None, str]:
        """ROBUST's candidate: the different idea that rests on the least; none when a layout
        chosen already holds under every reading."""
        if any(p.scored.rests == (0, 0) for p in picks):
            return None, "a layout already chosen holds under every reading"
        known = [s for s in order if s.rests is not None]
        if not known:
            return None, "no candidate's validation report was read"
        # its own order, not the front's first: the front is drawn over the objective's axes, none
        # of them the readings a layout rests on, so the best layout that holds under every one
        # may be one the front dominates
        found = next_different(known, front_first=False)
        return (found, "") if found is not None else (None, (
            "no candidate left that is a different idea from those already chosen"))

    for point in (p for p in FILL_ORDER if p in listed):
        if point is ParetoPoint.ROBUST:
            found, why = least_dependent(ranked[point])
        else:
            found, why = next_different(ranked[point]), (
                "no candidate left that is a different idea from those already chosen")
        if found is None:
            unfilled.append((point, why if pool else "no candidate passed"))
        else:
            picks.append(Pick(point, found, id(found) in on_front))
    picks = _relabelled(picks, keys)
    picks.sort(key=lambda p: listed.index(p.point))  # the brief's order
    for _ in range(max(0, brief.objectives.options - len(listed))):
        found = next_different(ranked[ParetoPoint.MAX_YIELD])
        if found is None:
            break
        picks.append(Pick(None, found, id(found) in on_front))
    unfilled.sort(key=lambda u: listed.index(u[0]))
    return Selection(tuple(picks), tuple(unfilled), tuple(front))


def leaders(pool: Sequence[Scored], brief: DesignBrief) -> list[Scored]:
    """Before any layout is judged: for each point the brief asks for whose measure needs no
    validation report (all but ROBUST), the front's best by that point's own measure, each once,
    in fill order. The front of the objective's seven axes can be wider than a profile's quota of
    judged layouts, and taking it by yield alone passes over the most open one (C4-11)."""
    front = pareto_front(pool)
    keys = _point_keys(pool, brief)
    found: list[Scored] = []
    for point in FILL_ORDER:
        if point is ParetoPoint.ROBUST or point not in brief.objectives.pareto or not front:
            continue
        best = min(front, key=lambda s, key=keys[point]: (*key(s), s.candidate.candidate_id))
        if not any(best is f for f in found):
            found.append(best)
    return found


def _relabelled(picks: list[Pick], keys: dict[ParetoPoint, Key]) -> list[Pick]:
    """The same candidates under the labels that serve the points best, earlier points first.
    The fill gave each point its best candidate, so only an exact tie on an earlier point can
    move a label: to the point the other layout suits better."""
    points = [p.point for p in picks]
    best = min(permutations(picks), key=lambda order: [
        keys[point](p.scored) for point, p in zip(points, order, strict=True)])
    return [Pick(point, p.scored, p.on_front) for point, p in zip(points, best, strict=True)]


def _point_keys(pool: Sequence[Scored], brief: DesignBrief) -> dict[ParetoPoint, Key]:
    """How each point ranks a candidate: a tuple to sort by, smaller better."""
    best = [max(column) for column in zip(*(s.scores.vector for s in pool), strict=True)] \
        if pool else []

    def level(s: Scored) -> list[float]:
        """Each axis as a share of the best candidate's (1 for the best; every axis is
        bigger-is-better and never negative). A gap of 2% reads as 2%, not as the whole range."""
        return [v / top if top > 0 else 1.0
                for v, top in zip(s.scores.vector, best, strict=True)]

    weights = priority_weights(brief)

    def compromise(s: Scored) -> float:
        gaps = [w * (1 - x) ** 2 for w, x in zip(weights, level(s), strict=True)]
        return sum(gaps) / sum(weights)

    open_space, conventional = AXES.index("open_space"), AXES.index("conventionality")
    quality = AXES.index("quality")
    return {
        ParetoPoint.MAX_YIELD: lambda s: (-s.scores.yield_score, -s.scores.units,
                                          -s.scores.site_use),
        ParetoPoint.ROBUST: lambda s: (s.rests is None, s.rests or (0, 0),
                                       -s.scores.yield_score, -s.scores.units,
                                       -s.scores.site_use),
        ParetoPoint.BALANCED: lambda s: (compromise(s), -s.scores.yield_score),
        ParetoPoint.CONVENTIONAL_OPEN_SPACE: lambda s: (
            -(level(s)[open_space] + level(s)[conventional] + level(s)[quality]),
            -s.scores.towers, -s.scores.yield_score, -s.scores.site_use)}
