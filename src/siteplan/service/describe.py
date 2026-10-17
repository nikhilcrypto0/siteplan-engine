"""One plain line for each layout shown, so the architect can tell them apart, and its verdict
with what it rests on (2026-10-16, the architect). Every figure in a line is measured from the
candidate and its report by this code; nothing here is the model's.

A description says the blocks (how many of each kind, at what heights), which way they run,
where the open space and the club house are in the plot, and how it differs from the most alike
of the others shown. Where in the plot is a cell of the net plot's bounds cut in three each way
(the centre, or one of the eight compass points), never a rule."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts import CandidateLayout, ValidationReport
from siteplan.contracts.common import Status
from siteplan.contracts.validation import DependsOn
from siteplan.geometry import angle_between, bearing_to, compass_of
from siteplan.prototypes.plates import PLATE_SOURCE

PLOT_CELLS = 3  # the net plot's bounds are cut in this many each way to say where a thing is
AXES = {0: "north-south", 45: "north-east to south-west", 90: "east-west",
        135: "north-west to south-east"}  # a block's long side, by bearing modulo 180
KINDS = {DependsOn.READING: "open readings of the rules",
         DependsOn.SITE_FACT: "site facts not yet confirmed",
         DependsOn.RULE_GAP: "gaps in the rules read",
         DependsOn.MEASUREMENT: "measurements the drawing does not settle"}


def describe(candidate: CandidateLayout, net: Polygon,
             others: Sequence[CandidateLayout] = ()) -> str:
    """The layout in one line, and how it differs from the most alike of `others`."""
    parts = [_blocks(candidate), f"running {_running(candidate)}", _open_space(candidate, net),
             _club(candidate, net)]
    alike = _most_alike(candidate, others)
    if alike is not None:
        parts.append(_differs(candidate, alike))
    return "; ".join(p for p in parts if p)


def verdict_line(report: ValidationReport) -> str:
    """The legal verdict under every reading the law leaves open, what it rests on, and the
    verdict under the study's selections where they differ."""
    verdict = report.verdict.legal.value
    if verdict == "FAIL":
        failed = sorted({c.finding.rule for c in report.legal
                         if c.finding.status is Status.FAIL})
        line = "FAIL: " + "; ".join(failed) if failed else "FAIL: a blocking discrepancy"
    elif verdict == "CONDITIONAL":
        line = "CONDITIONAL, resting on " + _rests(report)
    else:
        line = "PASS"
    study = report.verdict.study
    if study is not None and study is not report.verdict.legal:
        line += f" (under the readings selected for this study: {study.value})"
    return line


def _rests(report: ValidationReport) -> str:
    found: dict[DependsOn, list[str]] = {}
    for check in report.legal:
        if check.finding.status is not Status.CONDITIONAL:
            continue
        for dependency in check.rests_on:
            names = found.setdefault(dependency.kind, [])
            if dependency.id not in names:
                names.append(dependency.id)
    return "; ".join(f"{KINDS[kind]}: {', '.join(found[kind])}" for kind in KINDS if kind in found)


def _blocks(candidate: CandidateLayout) -> str:
    kinds = Counter((t.prototype_id, t.floors_above_stilt) for t in candidate.towers)
    words = []
    for (prototype_id, floors), n in sorted(kinds.items(), key=lambda k: (-k[1], k[0])):
        plate = candidate.prototype(prototype_id).source.startswith(PLATE_SOURCE)
        words.append(f"{n} x {prototype_id}{' (plate, PRELIMINARY)' if plate else ''} "
                     f"at S+{floors}")
    count = len(candidate.towers)
    return f"{count} block{'s' if count != 1 else ''}: " + ", ".join(words)


def _axis(footprint: Polygon) -> int:
    """The compass axis a block's long side runs along, by bearing modulo 180."""
    box = list(footprint.minimum_rotated_rectangle.exterior.coords)
    sides = [(box[i], box[i + 1]) for i in range(2)]
    a, b = max(sides, key=lambda s: Point(s[0]).distance(Point(s[1])))
    bearing = bearing_to(a, b) % 180
    return min(AXES, key=lambda axis: min(angle_between(bearing, axis),
                                          angle_between(bearing, axis + 180)))


def _running(candidate: CandidateLayout) -> str:
    axes = Counter(_axis(candidate.placed_footprint(t)) for t in candidate.towers)
    if len(axes) == 1:
        return AXES[next(iter(axes))]
    return ", ".join(f"{AXES[axis]} ({n})" for axis, n in axes.most_common())


def where(point: Point, net: Polygon) -> str:
    """Which ninth of the net plot's bounds a point is in: 'the centre' or a compass point."""
    x0, y0, x1, y1 = net.bounds
    col = min(PLOT_CELLS - 1, max(0, int((point.x - x0) / max(x1 - x0, 1e-9) * PLOT_CELLS)))
    row = min(PLOT_CELLS - 1, max(0, int((point.y - y0) / max(y1 - y0, 1e-9) * PLOT_CELLS)))
    middle = PLOT_CELLS // 2
    if (col, row) == (middle, middle):
        return "the centre"
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    cell = (x0 + (col + 0.5) * (x1 - x0) / PLOT_CELLS, y0 + (row + 0.5) * (y1 - y0) / PLOT_CELLS)
    return "the " + compass_of(bearing_to(centre, cell))


def _open_space(candidate: CandidateLayout, net: Polygon) -> str:
    pockets = [s.to_shapely() for s in candidate.program.open_space]
    if not pockets:
        return "no open space laid"
    largest = max(pockets, key=lambda p: p.area)
    total = unary_union(pockets).area
    return (f"open space {total:,.0f} m² in {len(pockets)} piece{'s' if len(pockets) != 1 else ''}"
            f", the largest in {where(largest.centroid, net)}")


def _club(candidate: CandidateLayout, net: Polygon) -> str:
    club = candidate.program.club_house
    if club is None:
        return "no club house"
    shape = club.shape.to_shapely()
    gates = [g.shape.to_shapely() for g in candidate.circulation.gates]
    gate = f", {shape.distance(unary_union(gates)):,.0f} m from the gate" if gates else ""
    return f"club house in {where(shape.centroid, net)}{gate}"


def _ground(candidate: CandidateLayout) -> BaseGeometry:
    return unary_union([candidate.placed_footprint(t) for t in candidate.towers])


def _shared(a: CandidateLayout, b: CandidateLayout) -> float:
    ground_a, ground_b = _ground(a), _ground(b)
    union = ground_a.union(ground_b).area
    return ground_a.intersection(ground_b).area / union if union > 0 else 0.0


def _most_alike(candidate: CandidateLayout, others: Sequence[CandidateLayout]
                ) -> CandidateLayout | None:
    rest = [o for o in others if o.candidate_id != candidate.candidate_id]
    return max(rest, key=lambda o: (_shared(candidate, o), o.candidate_id), default=None)


def _differs(candidate: CandidateLayout, alike: CandidateLayout) -> str:
    """How it differs from the most alike layout shown: what is not the same of the block count,
    the kinds of block, the heights, the way they run, and how much ground they share."""
    said = []
    if len(candidate.towers) != len(alike.towers):
        said.append(f"{len(candidate.towers)} blocks, not {len(alike.towers)}")
    kinds = {t.prototype_id for t in candidate.towers}
    if kinds != {t.prototype_id for t in alike.towers}:
        said.append("other kinds of block")
    heights = sorted({t.floors_above_stilt for t in candidate.towers})
    theirs = sorted({t.floors_above_stilt for t in alike.towers})
    if heights != theirs:
        said.append(f"heights S+{'/'.join(map(str, heights))}, not "
                    f"S+{'/'.join(map(str, theirs))}")
    if _running(candidate) != _running(alike):
        said.append(f"running {_running(candidate)}, not {_running(alike)}")
    said.append(f"{_shared(candidate, alike):.0%} of the same block ground")
    return f"unlike {alike.candidate_id}, the most alike shown: " + ", ".join(said)
