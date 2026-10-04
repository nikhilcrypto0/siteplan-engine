"""The Pareto front, and the three alternatives an architect is shown.

A candidate is on the front when no other is at least as good on every axis of the objective
(objective.py) and better on one. From the candidates that survived the guard, the brief's Pareto
points are each filled with the best candidate for that point that is a genuinely different idea
from those already chosen:

- MAX_YIELD: the most saleable area, less what the mix misses by (the legacy generator's score);
- CONVENTIONAL_OPEN_SPACE: the most conventional blocks with the most open space;
- BALANCED: the compromise nearest the best on every axis, weighted by the brief's priorities.

The two extremes are filled first and the compromise takes the best of what they leave, so it
stands between them rather than beside the first of them. The alternatives come back in the
order the brief lists its points. When the brief asks for more options than it has points, the
best remaining different ideas by yield follow, untagged.

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
FILL_ORDER = (ParetoPoint.MAX_YIELD, ParetoPoint.CONVENTIONAL_OPEN_SPACE, ParetoPoint.BALANCED)


@dataclass(frozen=True)
class Scored:
    candidate: CandidateLayout
    scores: Scores


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

    def next_different(order: list[Scored]) -> Scored | None:
        for s in sorted(order, key=lambda s: id(s) not in on_front):  # stable: front first
            if not any(s is p.scored or same_idea(s.candidate, p.scored.candidate)
                       for p in picks):
                return s
        return None

    listed = list(dict.fromkeys(brief.objectives.pareto))
    unknown = [point for point in listed if point not in FILL_ORDER]
    if unknown:
        raise ValueError(f"the optimizer has no ranking for {unknown}")
    unfilled = []
    for point in (p for p in FILL_ORDER if p in listed):
        found = next_different(ranked[point])
        if found is None:
            unfilled.append((point, "no candidate left that is a different idea from those "
                                    "already chosen" if pool else "no candidate passed"))
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
    return {
        ParetoPoint.MAX_YIELD: lambda s: (-s.scores.yield_score, -s.scores.units),
        ParetoPoint.BALANCED: lambda s: (compromise(s), -s.scores.yield_score),
        ParetoPoint.CONVENTIONAL_OPEN_SPACE: lambda s: (
            -(level(s)[open_space] + level(s)[conventional]), -s.scores.towers,
            -s.scores.yield_score)}
