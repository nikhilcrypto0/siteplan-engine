"""The PartitionLedger, recomputed: every square metre of the net plot once, by what is drawn on it.

The candidate's own ledger is never used. This one is built from the candidate's geometry with
the validator's own priority rules: where two drawn things claim the same ground, the one that
physically has it keeps it (a building before a paved road, a road before a bay), and the claim
that lost is reported as a conflict with its area. Ground that nothing claims is UNALLOCATED and
says why, piece by piece.

A pavement that is both a road and the fire tender's route is one ROAD entry tagged FIRE_ACCESS;
ground that qualifies as open space is counted once, physically, and its qualification is a rule
layer (layers.py), never a second area.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.contracts.accounting import PartitionEntry, PartitionLedger, PhysicalUse
from siteplan.contracts.common import Shape, Status, Surface, shapes_from
from siteplan.contracts.resolved_rules import MIXED_HEIGHT_SPACING
from siteplan.contracts.validation import Check, Family
from siteplan.validator.context import Context
from siteplan.validator.fire import clear_band
from siteplan.validator.readings import plain
from siteplan.validator.shapes import NOISE_SQM, clean_pieces, union_of_all
from siteplan.validator.zones import gap_zones, green_strip_zone, setback_zone

U = PhysicalUse
# A facility's ground by the surface the brief states for it; one nobody stated is entered as an
# amenity and tagged so, never read off its name (as the adapter's ledger does).
GROUND_BY_SURFACE = {Surface.BUILT: U.OTHER_BUILT, Surface.HARD: U.HARD_AMENITY,
                     Surface.SOFT: U.SOFT_OPEN_SPACE}
SURFACE_UNSTATED = "SURFACE_UNSTATED"
# Where two drawn things claim the same ground, the earlier use keeps it: what is built stands
# where it stands; the ramp is a cut in the ground beside a road; a paved road is a road even if
# it is also the tender's route; clear hardstanding keeps a bay off it; a bay is a bay before a
# play area; planting and soft ground yield to everything laid on them; a buffer is the ground
# that is left.
PRIORITY = (U.TOWER, U.CLUB_HOUSE, U.OTHER_BUILT, U.RAMP, U.ROAD, U.FIRE_HARDSTANDING,
            U.SURFACE_PARKING, U.HARD_AMENITY, U.SOFT_OPEN_SPACE, U.GREEN_STRIP, U.BUFFER_LAND)
# Pairs of uses that may share ground without it being a conflict: a road that is also the
# tender's route, a play court on a tot-lot, open space on the planted strip, and a buffer left
# as it is under anything.
MAY_SHARE = {frozenset((U.ROAD, U.FIRE_HARDSTANDING)), frozenset((U.SOFT_OPEN_SPACE,
                                                                   U.HARD_AMENITY)),
             frozenset((U.SOFT_OPEN_SPACE, U.GREEN_STRIP))}
# Uses of which two separate things cannot stand on the same ground.
ONE_AT_A_TIME = (U.TOWER, U.OTHER_BUILT, U.HARD_AMENITY, U.SURFACE_PARKING)
CONFLICT_SQM = 0.05  # less than this of overlap is the edges of two drawn shapes meeting
PLAY_SHARE = 0.5  # an amenity this much on open space is the open space's own ground
LEFT_UNUSED = "ground the candidate draws nothing on"


@dataclass(frozen=True)
class Claim:
    use: PhysicalUse
    ref: str
    ground: BaseGeometry
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Overlap:
    """Two drawn things of different uses on the same ground, or drawn ground off the plot."""

    text: str
    sqm: float


@dataclass(frozen=True)
class Ledger:
    ledger: PartitionLedger
    conflicts: list[Overlap]  # two drawn things on the same ground, with the area
    off_plot: list[Overlap]  # drawn ground outside the net plot, with the area
    invariants: list[str]  # the ledger held to the contract's own invariants
    claims: list[Claim] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        """Where the drawing and the ledger disagree: drawn things on the same ground, drawn
        ground off the plot, and any invariant the ledger itself breaks."""
        return [*(o.text for o in self.conflicts), *(o.text for o in self.off_plot),
                *self.invariants]

    def serious(self) -> list[Overlap]:
        """The overlaps and off-plot ground larger than drawing noise."""
        return [o for o in [*self.conflicts, *self.off_plot] if o.sqm > NOISE_SQM]


def claims_of(ctx: Context) -> list[Claim]:
    """What the candidate draws, one claim per drawn thing, with the use it is."""
    d = ctx.drawn
    out = [Claim(U.TOWER, t.name, t.footprint) for t in ctx.towers]
    if not d.club.is_empty:
        out.append(Claim(U.CLUB_HOUSE, "club house", d.club))
    out += [Claim(U.RAMP, f"ramp {i}", r) for i, r in enumerate(d.ramps, 1)]
    out += [Claim(U.ROAD, f"{r.id} {r.kind.value}", r.shape, r.tags) for r in d.roads]
    if not d.fire_hardstanding.is_empty:
        out.append(Claim(U.FIRE_HARDSTANDING, "fire hardstanding", d.fire_hardstanding,
                         ("FIRE_ACCESS",)))
    out += [Claim(U.SURFACE_PARKING, f"bay {i}", b) for i, b in enumerate(d.bays, 1)]
    pockets = union_of_all(list(d.open_space))
    for a in d.amenities:
        if a.inside(d.club):
            continue  # a gym in the club house: the club house's ground, not another use
        on_open_space = (not pockets.is_empty and a.shape.area > 0
                         and a.shape.intersection(pockets).area > PLAY_SHARE * a.shape.area)
        if on_open_space and not a.hard:
            continue  # a play area on the tot-lot: the tot-lot's ground, tagged below
        use = GROUND_BY_SURFACE.get(a.surface, U.HARD_AMENITY)
        tags = {None: (SURFACE_UNSTATED,), Surface.SOFT: (f"AMENITY:{a.name}",)}.get(a.surface, ())
        out.append(Claim(use, a.name, a.shape, tags))
    for i, pocket in enumerate(d.open_space, 1):
        tags = tuple(f"AMENITY:{a.name}" for a in d.amenities
                     if not a.hard and a.shape.area > 0 and a.shape.intersection(pocket).area
                     > PLAY_SHARE * a.shape.area)
        out.append(Claim(U.SOFT_OPEN_SPACE, f"open space {i}", pocket, tags))
    if not d.green_strip.is_empty:
        out.append(Claim(U.GREEN_STRIP, "green strip", d.green_strip))
    water = ctx.land.keep_out_on_site
    if not water.is_empty:
        out.append(Claim(U.BUFFER_LAND, "water buffer", water))
    return out


def _conflicts(claims: list[Claim]) -> list[Overlap]:
    """Drawn things on the same ground: two of a use that cannot share it (two blocks, two bays),
    and two of different uses (a use is merged with itself first, so two roads that meet are one
    road)."""
    by_use = {u: union_of_all([c.ground for c in claims if c.use is u]) for u in PRIORITY}
    names = {u: ", ".join(c.ref for c in claims if c.use is u) for u in PRIORITY}
    out = []
    for use in ONE_AT_A_TIME:
        same = [c for c in claims if c.use is use]
        tree = shapely.STRtree([c.ground for c in same])  # only neighbours can overlap
        for i, a in enumerate(same):
            for j in sorted(tree.query(a.ground)):
                if j <= i:
                    continue
                b = same[j]
                area = a.ground.intersection(b.ground).area
                if area > CONFLICT_SQM:
                    out.append(Overlap(f"{use.value} {a.ref} and {use.value} {b.ref} overlap by "
                                       f"{area:,.2f} m²", area))
    for a, b in combinations([u for u in PRIORITY if u is not U.BUFFER_LAND], 2):
        if frozenset((a, b)) in MAY_SHARE or by_use[a].is_empty or by_use[b].is_empty:
            continue
        area = by_use[a].intersection(by_use[b]).area
        if area > CONFLICT_SQM:
            out.append(Overlap(f"{a.value} ({names[a]}) and {b.value} ({names[b]}) overlap by "
                               f"{area:,.2f} m²", area))
    return out


def _reason(piece: Polygon, zones: list[tuple[str, BaseGeometry]]) -> str:
    """Why a piece of ground has no use: the zone it mostly lies in, if there is one."""
    best = max(((piece.intersection(g).area / piece.area, label) for label, g in zones
                if piece.area > 0), default=(0.0, ""))
    return f"{LEFT_UNUSED}: mostly {best[1]}" if best[0] >= PLAY_SHARE else LEFT_UNUSED


def _zones(ctx: Context) -> list[tuple[str, BaseGeometry]]:
    spacing = ctx.rules.readings(MIXED_HEIGHT_SPACING)[0]
    zones: list[tuple[str, BaseGeometry]] = []
    for reading in ctx.stilt_readings:
        zone = setback_zone(ctx, reading)
        if zone is not None:
            zones.append((f"inside the setback (stilt {reading})", zone))
        lane = ctx.rules.fire.clear_width_m.value
        bands = union_of_all([clear_band(t.footprint, lane) for t in ctx.high_rise(reading)])
        zones.append(("a fire lane's clear ground", bands))
        zones.append(("a gap between blocks",
                      union_of_all([z for _, z in gap_zones(ctx, reading, spacing)])))
        strip = green_strip_zone(ctx, reading)
        if strip is not None:
            zones.append(("the green strip's place", strip))
    return zones


def recompute(ctx: Context) -> Ledger:
    net = ctx.net
    claims = claims_of(ctx)
    entries: list[PartitionEntry] = []
    off_plot: list[Overlap] = []
    taken: BaseGeometry = Polygon()
    for use in PRIORITY:
        for claim in (c for c in claims if c.use is use):
            outside = claim.ground.difference(net).area
            if outside > CONFLICT_SQM:
                off_plot.append(Overlap(f"{outside:,.1f} m² of {use.value} {claim.ref} lies "
                                        "outside the net plot", outside))
            ground = union_of_all(clean_pieces(claim.ground.intersection(net).difference(taken)))
            if ground.is_empty:
                continue
            taken = union_of_all([taken, ground])
            shapes = shapes_from(ground)
            entries.append(PartitionEntry(use=use, shapes=shapes, ref=claim.ref,
                                          tags=list(claim.tags),
                                          area_sqm=sum(s.area_sqm for s in shapes)))
    zones = _zones(ctx)
    for i, piece in enumerate(clean_pieces(net.difference(taken)), 1):
        shape = Shape.from_shapely(piece)
        entries.append(PartitionEntry(use=U.UNALLOCATED, shapes=[shape], ref=f"unallocated {i}",
                                      area_sqm=shape.area_sqm, reason=_reason(piece, zones)))
    ledger = PartitionLedger(net_area_sqm=net.area, entries=entries)
    return Ledger(ledger, _conflicts(claims), off_plot, ledger.problems(Shape.from_shapely(net)),
                  claims)


def ledger_check(ctx: Context, ledger: Ledger) -> Check:
    """Every square metre of the net plot once: nothing drawn on top of anything else, nothing
    drawn off the plot, and a ledger that sums to the net area."""
    left = [e for e in ledger.ledger.entries if e.use is U.UNALLOCATED]
    summary = (f"{ledger.ledger.total_sqm():,.1f} m² of the net {ctx.net.area:,.1f} m² accounted "
               f"for; {sum(e.area_sqm for e in left):,.1f} m² in {len(left)} unallocated "
               f"piece{'' if len(left) == 1 else 's'}")
    required = "each square metre once, by what is on it; nothing drawn on top of anything else"
    clause = "docs/ARCHITECTURE.md, the PartitionLedger (a recomputed ledger)"
    serious = ledger.serious()
    if serious:
        return plain(Family.ACCOUNTING, "Every square metre once", Status.FAIL,
                     "; ".join(o.text for o in serious), required, clause,
                     "Drawn things that share ground cannot both be there.")
    if ledger.invariants:
        return plain(Family.ACCOUNTING, "Every square metre once", Status.UNVERIFIED,
                     "; ".join(ledger.invariants), required, clause,
                     "The recomputed ledger breaks one of its own invariants.")
    return plain(Family.ACCOUNTING, "Every square metre once", Status.PASS, summary, required,
                 clause)
