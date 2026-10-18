"""Raising a laid layout's blocks to the tallest each one's own place allows (2026-10-12, the
architect: "taller in the middle, lower at the edges").

A configuration lays its columns for one floor count at most; a block in the middle of the plot,
further from the plot line and its neighbours than that count asks, can often stand taller. Each
block is raised, a floor class at a time, while the class it rises to keeps:

- its own setback from the plot line (the larger of its side and front figures);
- the planted strip its band asks, only where the land already has it;
- the setback zone the ring road was laid for, where the profile keeps roads out of setbacks;
- the gap to every other block that the taller of the two asks;
- the same class of building (a high-rise stays one, a block below 21 m stays below it), and a
  block reached by a rule 8(l) pathway stays within the height a pathway serves.

The block with the most room rises first, again and again, until none can. Then a block at the end
of a column that the gap to its neighbour in the column holds down is moved along its column, away
from that neighbour, as far as the gap needs and no further than its own setback and the land the
columns may stand on allow, and the raising is tried again (the nudge). Nothing here is judged:
the raised layout is laid out again (its club house, cellars and ramp for the flats it now holds)
and the validator judges it like any other.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from shapely.geometry import Polygon

from siteplan.optimizer.search import fringe
from siteplan.optimizer.search.build import placement_of
from siteplan.optimizer.search.columns import Choice, Standing
from siteplan.optimizer.search.layout import Evaluation, Run
from siteplan.optimizer.search.readings import FloorClass

TOL_M = 1e-6  # a distance this close to what is asked meets it
STRIP_SLACK = 0.01  # share of the strip all round its drawing may miss by


@dataclass
class _Block:
    standing: Standing
    path: object | None  # the fringe block's pathway centre line; None in a column or on the ring
    in_fringe: bool

    @property
    def cls(self) -> FloorClass:
        return self.standing.choice.cls


def raised(run: Run, ev: Evaluation, why: list[str] | None = None, *, nudge: bool = True
           ) -> Evaluation | None:
    """The evaluation with its blocks raised (and nudged) as far as each one's place allows, or
    None when no block can rise; `why`, when given, collects what kept each block down."""
    blocks = [_Block(s, None, False) for s in ev.standing]
    blocks += [_Block(f.standing, f.path, True) for f in ev.fringe]
    if not blocks:
        return None
    ladder = run.classes[ev.config.profile.key]
    net = run.plot.net
    strip_m = _strip_all_round(net, ev.land.strip, run.q.strip_width_m)
    zone_m = ev.land.interior.distance(net.exterior) if not ev.land.interior.is_empty else 0.0
    keep_zone = not ev.config.profile.roads_may_use_setback

    def footprint(standing: Standing) -> Polygon:
        return placement_of(standing, "T", ev.frame).footprint

    def allowed(i: int, cls: FloorClass, standing: Standing | None = None) -> bool:
        reason = _kept_down(i, cls, standing)
        if reason and why is not None:
            why.append(f"{blocks[i].standing.choice.prototype.id} to {cls.floors} floors: {reason}")
        return not reason

    def _kept_down(i: int, cls: FloorClass, standing: Standing | None) -> str:
        block = blocks[i]
        if cls.high_rise != block.cls.high_rise:
            return "another class of building"
        if cls.strip_m > strip_m + TOL_M:
            return f"its band asks a {cls.strip_m:g} m planted strip the land does not have"
        if keep_zone and cls.zone_m > zone_m + TOL_M:
            return f"its {cls.zone_m:g} m setback is deeper than the zone the ring was laid for"
        if block.path is not None and not fringe.pathway_serves(run.q, cls):
            return "a pathway serves a block up to 12 m only"
        own = footprint(standing or block.standing)
        edge = own.distance(net.exterior)
        if edge + TOL_M < cls.zone_m:
            return f"{edge:.2f} m from the plot line, {cls.zone_m:g} m asked"
        for j, other in enumerate(blocks):
            need = max(cls.gap_m, other.cls.gap_m)
            gap = own.distance(footprint(other.standing))
            if j != i and gap + TOL_M < need:
                return f"{gap:.2f} m from a neighbour, {need:g} m asked"
        return ""

    def taller(i: int) -> FloorClass | None:
        if blocks[i].standing.locked:  # Stage D: a locked block keeps its height
            return None
        current = blocks[i].cls
        above = sorted((c for c in ladder[blocks[i].standing.choice.prototype.id]
                        if c.floors > current.floors), key=lambda c: c.floors)
        return above[0] if above else None

    def rise() -> bool:
        changed = False
        moved = True
        while moved:
            moved = False
            order = sorted(range(len(blocks)), key=lambda i: -footprint(
                blocks[i].standing).distance(net.exterior))
            for i in order:
                cls = taller(i)
                if cls is not None and allowed(i, cls):
                    blocks[i].standing = _with_class(blocks[i].standing, cls)
                    moved = changed = True
        return changed

    changed = rise()
    if nudge and _nudge(blocks, ev, allowed, taller, footprint):
        changed = rise() or changed
    if not changed:
        return None
    standing = tuple(b.standing for b in blocks if not b.in_fringe)
    fringed = tuple(replace(f, standing=b.standing)
                    for f, b in zip(ev.fringe, [b for b in blocks if b.in_fringe], strict=True))
    value = sum(b.standing.choice.value for b in blocks)
    return replace(ev, standing=standing, fringe=fringed, value=value)


def _nudge(blocks: list[_Block], ev: Evaluation, allowed, taller, footprint) -> bool:
    """Move a block at the end of its column away from its neighbour in the column, along the
    column, where the gap between them alone keeps it (or the neighbour) from rising: by what the
    taller class's gap needs, kept on the land the columns may stand on."""
    land = ev.land.cluster_land
    moved_any = False
    columns: dict[int, list[int]] = {}
    for i, b in enumerate(blocks):
        if not b.in_fringe and b.standing.frame is None and not b.standing.locked:
            columns.setdefault(b.standing.column, []).append(i)
    for members in columns.values():
        members.sort(key=lambda i: blocks[i].standing.y0)
        for end, inner, sign in ((members[-1], members[-2] if len(members) > 1 else None, 1),
                                 (members[0], members[1] if len(members) > 1 else None, -1)):
            if inner is None:
                continue
            wants = [c for c in (taller(end), taller(inner)) if c is not None]
            if not wants:
                continue
            need = max(c.gap_m for c in wants)
            gap = footprint(blocks[end].standing).distance(footprint(blocks[inner].standing))
            shift = need - gap
            if shift <= TOL_M:
                continue
            moved = replace(blocks[end].standing, y0=blocks[end].standing.y0 + sign * shift)
            if not land.buffer(TOL_M).contains(footprint(moved)):
                continue
            if not allowed(end, blocks[end].cls, moved):
                continue
            blocks[end].standing = moved
            moved_any = True
    return moved_any


def _strip_all_round(net: Polygon, strip, width_m: float) -> float:
    """The planted strip's width where the land carries it all round the plot line, else 0: a
    block whose band asks the strip may rise only where it is there on every side."""
    if strip.is_empty or width_m <= 0:
        return 0.0
    whole = net.difference(net.buffer(-width_m, join_style="mitre")).area
    return width_m if strip.area + STRIP_SLACK * whole >= whole else 0.0


def _with_class(standing: Standing, cls: FloorClass) -> Standing:
    choice = standing.choice
    return replace(standing, choice=Choice(
        choice.prototype, cls, choice.length_m, choice.depth_m,
        choice.prototype.per_floor.saleable_sqft * cls.floors))
