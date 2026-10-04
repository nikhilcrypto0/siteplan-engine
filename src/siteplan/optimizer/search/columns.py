"""Blocks in columns: which prototype, how many floors and where, one column at a time.

In the turned frame (frame.py) a column is a strip one block deep, running along y. Along it the
search chooses a sequence of blocks (a prototype at a floor count, each its own height) so that each
lies wholly on the ground its height allows and each keeps from the next the gap Table IV asks of
the taller of the two. That is a one-dimensional problem, solved exactly on a grid of `step_m`:
the best total saleable area over every sequence, so a lower block stands where only a lower
height fits, a block is lowered when that lets its neighbour stand, and no height is chosen for
being the legal maximum.

The ground a height allows is its own (a taller block keeps a larger setback and a wider gap), so
the stretches of a column are worked out for each floor count. A block is held to a strip of full
width: `free_stretches` is exact for a rectangle across the whole strip.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from siteplan.contracts import TowerPrototype
from siteplan.optimizer.search.land import polygons
from siteplan.optimizer.search.readings import FloorClass

STEP_M = 1.0  # the grid the positions along a column are searched on
EPS = 1e-9
GAP_SLACK_M = 0.0  # a gap is exactly the figure asked; the grid only ever rounds it up


def ground_key(cls: FloorClass) -> float:
    """What a floor count asks of the ground: its setback. Counts that ask the same share stretches."""
    return cls.setback_m


def class_key(cls: FloorClass) -> tuple[int, float, float]:
    return cls.floors, cls.setback_m, cls.gap_m


@dataclass(frozen=True)
class Choice:
    """A block that may stand in a column: a prototype at a floor count."""

    prototype: TowerPrototype
    cls: FloorClass
    length_m: float  # along the column
    depth_m: float  # across it
    value: float  # saleable sqft the block adds

    @property
    def key(self) -> tuple[str, int, float, float]:
        return self.prototype.id, *class_key(self.cls)


@dataclass(frozen=True)
class Standing:
    """A block placed: its choice, its column and where it starts along y."""

    choice: Choice
    column: int
    x0: float  # the column's left edge, in the turned frame
    y0: float

    @property
    def y1(self) -> float:
        return self.y0 + self.choice.length_m

    @property
    def x1(self) -> float:
        return self.x0 + self.choice.depth_m


def choices_for(prototypes: Sequence[TowerPrototype],
                classes: Mapping[str, Sequence[FloorClass]]) -> list[Choice]:
    """Every block that may stand, for the prototypes and the floor counts each leaves open. Of the
    floor counts that ask the same of the ground (the same setback and gap) only the tallest is
    kept: the others add nothing but a lower yield."""
    found = []
    for prototype in prototypes:
        by_ground: dict[tuple[float, float], FloorClass] = {}
        for cls in classes[prototype.id]:
            by_ground[(cls.setback_m, cls.gap_m)] = cls  # lowest first: the tallest wins
        for cls in by_ground.values():
            found.append(Choice(prototype, cls, prototype.length_m, prototype.depth_m,
                                prototype.per_floor.saleable_sqft * cls.floors))
    return found


def free_stretches(land: BaseGeometry, x0: float, width_m: float) -> list[tuple[float, float]]:
    """The ranges of y where a strip of this width, starting at x0, lies wholly on the land. A
    piece of the strip off the land blocks the whole of its extent along y, which is exact for a
    block that spans the strip."""
    if land.is_empty:
        return []
    _, miny, _, maxy = land.bounds
    strip = box(x0, miny - 1.0, x0 + width_m, maxy + 1.0)
    blocked = sorted((p.bounds[1], p.bounds[3]) for p in polygons(strip.difference(land)))
    stretches, cursor = [], miny - 1.0
    for low, high in blocked:
        if low > cursor + EPS:
            stretches.append((cursor, low))
        cursor = max(cursor, high)
    if cursor < maxy + 1.0 - EPS:
        stretches.append((cursor, maxy + 1.0))
    return [(a, b) for a, b in stretches if b - a > EPS and a >= miny - EPS and b <= maxy + EPS]


@dataclass(frozen=True)
class Column:
    standing: tuple[Standing, ...]
    value: float


def plan_column(stretches: Mapping[float, Sequence[tuple[float, float]]],
                choices: Sequence[Choice], gap: Callable[[FloorClass, FloorClass], float],
                column: int, x0: float, step_m: float = STEP_M) -> Column:
    """The sequence of blocks that adds the most saleable area to one column. `stretches` gives,
    for each setback (`ground_key`), the ranges of y where a block asking it may stand."""
    spans = [s for found in stretches.values() for s in found]
    usable = [c for c in choices if stretches.get(ground_key(c.cls))]
    if not spans or not usable:
        return Column((), 0.0)
    lo = min(a for a, _ in spans)
    hi = max(b for _, b in spans)
    starts = int(math.floor((hi - lo) / step_m + EPS)) + 1
    longest = max(math.ceil(c.length_m / step_m - EPS) for c in usable)
    slots = starts + longest + 2
    classes = sorted({class_key(c.cls) for c in usable})
    cls_of = {class_key(c.cls): c.cls for c in usable}
    gap_slots = {(a, b): math.ceil((gap(cls_of[a], cls_of[b]) + GAP_SLACK_M) / step_m - EPS)
                 for a in classes for b in classes}

    valid: dict[tuple, list[bool]] = {}
    for choice in usable:
        ok = [False] * starts
        for a, b in stretches[ground_key(choice.cls)]:
            first = max(0, math.ceil((a - lo) / step_m - EPS))
            last = min(starts - 1, math.floor((b - choice.length_m - lo) / step_m + EPS))
            for j in range(first, last + 1):
                ok[j] = True
        valid[choice.key] = ok

    nothing = (-math.inf, -1)  # prefix maximum: value and the end slot it was reached at
    best_end: dict[tuple, list[tuple[float, tuple | None, Choice | None, int] | None]] = {
        c: [None] * slots for c in classes}
    prefix: dict[tuple, list[tuple[float, int]]] = {c: [nothing] * slots for c in classes}
    for j in range(slots):
        for c in classes:  # the blocks ending at or before j are final: they started before j
            here = best_end[c][j]
            before = prefix[c][j - 1] if j else nothing
            prefix[c][j] = (here[0], j) if here is not None and here[0] > before[0] else before
        if j >= starts:
            continue
        for choice in usable:
            if not valid[choice.key][j]:
                continue
            c = class_key(choice.cls)
            value, pred = choice.value, None
            for b in classes:
                index = j - gap_slots[(b, c)]
                if index < 0:
                    continue
                got, end = prefix[b][index]
                if got > -math.inf and got + choice.value > value:
                    value, pred = got + choice.value, (b, end)
            end = j + math.ceil(choice.length_m / step_m - EPS)
            if best_end[c][end] is None or value > best_end[c][end][0]:
                best_end[c][end] = (value, pred, choice, j)

    best = max(((best_end[c][e][0], c, e) for c in classes for e in range(slots)
                if best_end[c][e] is not None), default=None)
    if best is None:
        return Column((), 0.0)
    sequence: list[Choice] = []
    state: tuple[tuple, int] | None = (best[1], best[2])
    while state is not None:
        _, pred, choice, _ = best_end[state[0]][state[1]]
        sequence.append(choice)
        state = pred
    sequence.reverse()
    placed = _left_justified(sequence, stretches, gap)
    if placed is None:  # cannot happen on the grid's own answer; kept so a rounding case is skipped
        return Column((), 0.0)
    return Column(tuple(Standing(c, column, x0, y) for c, y in zip(sequence, placed, strict=True)),
                  sum(c.value for c in sequence))


def _left_justified(sequence: Sequence[Choice],
                    stretches: Mapping[float, Sequence[tuple[float, float]]],
                    gap: Callable[[FloorClass, FloorClass], float]) -> list[float] | None:
    """The sequence as close to the start of the column as it can stand, with the exact gaps."""
    placed: list[float] = []
    previous: Choice | None = None
    for choice in sequence:
        floor = -math.inf if previous is None else (
            placed[-1] + previous.length_m + gap(previous.cls, choice.cls))
        for a, b in sorted(stretches[ground_key(choice.cls)]):
            y = max(floor, a)
            if y + choice.length_m <= b + EPS:
                placed.append(y)
                break
        else:
            return None
        previous = choice
    return placed
