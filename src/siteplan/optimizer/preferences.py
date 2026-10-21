"""The architect's soft preferences (DesignBrief.objectives.soft_preferences), scored (C4-16): how
well a layout meets each wish, from 0 to 1. A preference is never a rule: nothing fails for one,
and a layout that meets none is still an option. The objective's preference axis is the weighted
mean of the brief's preferences the engine understands, 1 for every layout when there are none.

The kinds the engine knows, and their parameters:

- orientation (`axis_deg`): the blocks' long sides run along this direction, in degrees from the
  drawing's x axis as a block's rotation is measured; a block scores the |cos| of the angle
  between its long axis and that one; when the brief requires it, `tolerance_deg` (optional, 0
  by default) says how far off the axis a block may turn, and the search keeps to that window;
- max_towers (`towers`): at most this many blocks; 1 at or under, the share of them when over;
- keep_away_from_road (`m`): every block at least this far from the entrances on the access road;
  the share of the blocks that are;
- club_near_entrance (`m`): the club house within this distance of an entrance; 1 when it is, the
  distance asked over the distance found when not, 0 with no club house;
- at_right_angles_to_road (no parameters; 2026-10-21, the user's comb): each block's long side at
  right angles to the road nearest it, the |sin| of the angle between the two, where the road's
  centre line passes nearest; the mean over the blocks. The search also lays blocks turned a
  quarter in their columns when it is asked (`wants_comb`), so the street meets each at its
  short end;
- tot_lot_few_large (`pieces` and `near_m`, optional; 2026-10-21, after the firm's Dhulapally
  plan): the tot-lot in few large pieces, one of them by the entrance: half for the share of it in
  its `pieces` largest pieces (TOT_LOT_PIECES by default), half for a piece of at least
  TOT_LOT_BIG_SHARE of it within `near_m` of an entrance (TOT_LOT_NEAR_M by default);
- tot_lot_toward (`bearing_deg`: 0 north, 90 east; 2026-10-21, the user: the tot-lot at the north
  arm's tip, as the firm laid it): the tot-lot as far that way as the plot goes, the mean of how
  far each square metre of it lies along the bearing across the layout's extent, 0 to 1; asked
  for, the layout also lays its tot-lot pockets from that end first (`tot_lot_toward`);
- club_toward (`bearing_deg`; 2026-10-21, the user: the club house out of the north arm, so the
  arm's ground goes to a tower): the club house as far that way as the layout goes, 0 to 1;
  asked for, the layout also tries the club house at that end of the open ground and keeps the
  furnishing that places it furthest that way (`club_toward`);
- club_not_beyond (`bearing_deg` and `along_m`; 2026-10-21, the user: the club house never in
  Dhulapally's north arm): the club house never stands beyond the line square to the bearing
  `along_m` along it (the survey's coordinates measured that way); unlike the others the layout
  holds to it, the club house laid only on the ground short of the line (`club_keep_out`), and a
  layout with no room for it there is not laid. Scored 1 when kept, else 0.

A preference of another kind, or one whose parameters are missing or not numbers, is not weighed
(`not_weighed`), and the search says so in its notes rather than drop it unsaid.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from siteplan.contracts import CandidateLayout
from siteplan.contracts.design_brief import SoftPreference


def _long_axis(candidate: CandidateLayout, tower) -> float:
    prototype = candidate.prototype(tower.prototype_id)
    return tower.rotation_deg + (0.0 if prototype.length_m >= prototype.depth_m else 90.0)


def _orientation(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    towers = candidate.towers
    if not towers:
        return 0.0
    axis = float(params["axis_deg"])
    return sum(abs(math.cos(math.radians(_long_axis(candidate, t) - axis)))
               for t in towers) / len(towers)


def _max_towers(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    asked, found = float(params["towers"]), len(candidate.towers)
    return 1.0 if found <= asked else max(asked, 0.0) / found


def _gates(candidate: CandidateLayout):
    return unary_union([g.shape.to_shapely() for g in candidate.circulation.gates])


def _away_from_road(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    gates, towers = _gates(candidate), candidate.towers
    if not towers or gates.is_empty:
        return 0.0
    far = float(params["m"])
    return sum(candidate.placed_footprint(t).distance(gates) >= far for t in towers) / len(towers)


def _club_near_entrance(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    club, gates = candidate.program.club_house, _gates(candidate)
    if club is None or gates.is_empty:
        return 0.0
    near, found = float(params["m"]), club.shape.to_shapely().distance(gates)
    return 1.0 if found <= near else near / found


TOT_LOT_PIECES = 2
TOT_LOT_NEAR_M = 30.0
TOT_LOT_BIG_SHARE = 0.25


def _road_lines(candidate: CandidateLayout) -> list[LineString]:
    """Every segment of every road's centre line (a road drawn without one gives none)."""
    out = []
    for road in candidate.circulation.roads:
        if road.centre_line is None:
            continue
        points = road.centre_line.points
        out += [LineString([a, b]) for a, b in zip(points, points[1:], strict=False) if a != b]
    return out


def _right_angles_to_road(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    towers, segments = candidate.towers, _road_lines(candidate)
    if not towers or not segments:
        return 0.0
    total = 0.0
    for tower in towers:
        foot = candidate.placed_footprint(tower)
        near = min(segments, key=foot.distance)
        (x0, y0), (x1, y1) = near.coords
        road = math.degrees(math.atan2(y1 - y0, x1 - x0))
        total += abs(math.sin(math.radians(_long_axis(candidate, tower) - road)))
    return total / len(towers)


def _tot_lot_few_large(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    pieces = sorted((g for s in candidate.program.open_space
                     for g in getattr(s.to_shapely(), "geoms", [s.to_shapely()])
                     if isinstance(g, Polygon)), key=lambda g: -g.area)
    whole = sum(g.area for g in pieces)
    if whole <= 0:
        return 0.0
    many = int(params.get("pieces", TOT_LOT_PIECES))
    near = float(params.get("near_m", TOT_LOT_NEAR_M))
    gates = _gates(candidate)
    by_gate = not gates.is_empty and any(
        g.area >= TOT_LOT_BIG_SHARE * whole and g.distance(gates) <= near for g in pieces)
    return 0.5 * sum(g.area for g in pieces[:max(many, 1)]) / whole + 0.5 * by_gate


def toward_of(bearing_deg: float) -> tuple[float, float]:
    """A compass bearing (0 north, 90 east; the survey's +y is north) as a unit vector."""
    turn = math.radians(bearing_deg)
    return math.sin(turn), math.cos(turn)


def _tot_lot_toward(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    pieces = [g for s in candidate.program.open_space
              for g in getattr(s.to_shapely(), "geoms", [s.to_shapely()]) if isinstance(g, Polygon)]
    whole = sum(g.area for g in pieces)
    if whole <= 0:
        return 0.0
    ux, uy = toward_of(float(params["bearing_deg"]))
    lo, hi = _extent(candidate, ux, uy)
    if hi - lo <= 0:
        return 0.0
    return sum(g.area * ((g.centroid.x * ux + g.centroid.y * uy) - lo) / (hi - lo)
               for g in pieces) / whole


def _extent(candidate: CandidateLayout, ux: float, uy: float) -> tuple[float, float]:
    ground = unary_union([*(s.to_shapely() for s in candidate.program.open_space),
                          *(candidate.placed_footprint(t) for t in candidate.towers),
                          *(s.to_shapely() for r in candidate.circulation.roads
                            for s in r.shapes)])
    along = [x * ux + y * uy for x, y in ground.convex_hull.exterior.coords]
    return min(along), max(along)


def _club_toward(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    club = candidate.program.club_house
    if club is None:
        return 0.0
    ux, uy = toward_of(float(params["bearing_deg"]))
    lo, hi = _extent(candidate, ux, uy)
    c = club.shape.to_shapely().centroid
    return 0.0 if hi - lo <= 0 else min(1.0, max(0.0, (c.x * ux + c.y * uy - lo) / (hi - lo)))


def _club_not_beyond(candidate: CandidateLayout, params: Mapping[str, Any]) -> float:
    club = candidate.program.club_house
    if club is None:
        return 0.0
    ux, uy = toward_of(float(params["bearing_deg"]))
    far = max(x * ux + y * uy for x, y in club.shape.to_shapely().exterior.coords)
    return 1.0 if far <= float(params["along_m"]) + KEEP_OUT_SLACK_M else 0.0


def club_keep_out(preferences: Sequence[SoftPreference]
                  ) -> tuple[tuple[float, float], float] | None:
    """The line the club house never stands beyond, when the brief draws one: the way (a unit
    vector) and how far along it."""
    for p in preferences:
        if p.kind == "club_not_beyond" and p.weight > 0 and understood(p):
            return toward_of(float(p.params["bearing_deg"])), float(p.params["along_m"])
    return None


def club_toward(preferences: Sequence[SoftPreference]) -> tuple[float, float] | None:
    """The way the brief asks the club house placed (a unit vector), when it asks."""
    for p in preferences:
        if p.kind == "club_toward" and p.weight > 0 and understood(p):
            return toward_of(float(p.params["bearing_deg"]))
    return None


def tot_lot_toward(preferences: Sequence[SoftPreference]) -> tuple[float, float] | None:
    """The way the brief asks the tot-lot laid from (a unit vector), when it asks."""
    for p in preferences:
        if p.kind == "tot_lot_toward" and p.weight > 0 and understood(p):
            return toward_of(float(p.params["bearing_deg"]))
    return None


KINDS: dict[str, tuple[Callable[[CandidateLayout, Mapping[str, Any]], float], tuple[str, ...]]] = {
    "orientation": (_orientation, ("axis_deg",)),
    "max_towers": (_max_towers, ("towers",)),
    "keep_away_from_road": (_away_from_road, ("m",)),
    "club_near_entrance": (_club_near_entrance, ("m",)),
    "at_right_angles_to_road": (_right_angles_to_road, ()),
    "tot_lot_few_large": (_tot_lot_few_large, ()),
    "tot_lot_toward": (_tot_lot_toward, ("bearing_deg",)),
    "club_toward": (_club_toward, ("bearing_deg",)),
    "club_not_beyond": (_club_not_beyond, ("bearing_deg", "along_m")),
}
KEEP_OUT_SLACK_M = 0.01  # the club house's edge on the line is short of it
OPTIONAL: dict[str, tuple[str, ...]] = {"tot_lot_few_large": ("pieces", "near_m")}


def understood(preference: SoftPreference) -> bool:
    """Whether the engine knows this preference's kind and has every parameter it needs."""
    known = KINDS.get(preference.kind)
    if known is None:
        return False
    given = [*known[1], *(n for n in OPTIONAL.get(preference.kind, ())
                          if n in preference.params)]
    for name in given:
        value = preference.params.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float) \
                or not math.isfinite(value):
            return False
    return True


def wants_comb(preferences: Sequence[SoftPreference]) -> bool:
    """Whether the brief asks for blocks at right angles to their road (the search then also lays
    blocks turned a quarter in their columns)."""
    return any(p.kind == "at_right_angles_to_road" and p.weight > 0 and understood(p)
               for p in preferences)


@dataclass(frozen=True)
class Orientation:
    """The way the brief requires every block to run (2026-10-19, the client's requirement, never
    law): its long axis within `tolerance_deg` of `axis_deg`, both in degrees from the survey's x
    axis, modulo 180."""

    axis_deg: float
    tolerance_deg: float = 0.0

    def off_deg(self, angle_deg: float) -> float:
        """How far a direction turns from the axis, 0 to 90."""
        turn = (angle_deg - self.axis_deg) % 180.0
        return min(turn, 180.0 - turn)

    def clamp(self, angle_deg: float) -> float:
        """The allowed direction nearest the one given: itself when within the tolerance, else
        the window's nearer edge."""
        turn = (angle_deg - self.axis_deg + 90.0) % 180.0 - 90.0  # signed, -90 to 90
        return (self.axis_deg + max(-self.tolerance_deg, min(self.tolerance_deg, turn))) % 180.0

    def allowed(self, angles: Sequence[float]) -> list[float]:
        """The directions to try: the axis, each given direction brought into the window, and the
        window's edges, no two the same (within DISTINCT_DEG, finer than the search's own five
        degrees, so a window of five degrees is not taken for the axis)."""
        tried = [self.axis_deg, *(self.clamp(a) for a in angles)]
        if self.tolerance_deg > 0:
            tried += [self.axis_deg - self.tolerance_deg, self.axis_deg + self.tolerance_deg]
        kept: list[float] = []
        for angle in (a % 180.0 for a in tried):
            if all(Orientation(other).off_deg(angle) > DISTINCT_DEG for other in kept):
                kept.append(angle)
        return kept


DISTINCT_DEG = 0.5  # two allowed directions nearer than this are one


def required_orientation(preferences: Sequence[SoftPreference]) -> Orientation | None:
    """The orientation every block must keep when the brief requires one (the search lays every
    block in the allowed window alone); None when the brief requires none."""
    for p in preferences:
        if p.required and p.kind == "orientation" and understood(p):
            return Orientation(float(p.params["axis_deg"]) % 180.0,
                               float(p.params.get("tolerance_deg", 0.0)))
    return None


def not_weighed(preferences: Sequence[SoftPreference]) -> list[str]:
    """The preferences given that are not weighed, named by their kind."""
    return [p.kind for p in preferences if not understood(p)]


def preference_score(candidate: CandidateLayout, preferences: Sequence[SoftPreference]) -> float:
    """The weighted mean of how well the candidate meets each preference understood; 1 when the
    brief gives none (or none it understands, or only weights of 0)."""
    weighed = [(p.weight, KINDS[p.kind][0](candidate, p.params)) for p in preferences
               if understood(p) and p.weight > 0]
    total = sum(weight for weight, _ in weighed)
    return sum(weight * score for weight, score in weighed) / total if total else 1.0
