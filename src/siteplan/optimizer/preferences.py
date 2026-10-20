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
  distance asked over the distance found when not, 0 with no club house.

A preference of another kind, or one whose parameters are missing or not numbers, is not weighed
(`not_weighed`), and the search says so in its notes rather than drop it unsaid.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

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


KINDS: dict[str, tuple[Callable[[CandidateLayout, Mapping[str, Any]], float], tuple[str, ...]]] = {
    "orientation": (_orientation, ("axis_deg",)),
    "max_towers": (_max_towers, ("towers",)),
    "keep_away_from_road": (_away_from_road, ("m",)),
    "club_near_entrance": (_club_near_entrance, ("m",)),
}


def understood(preference: SoftPreference) -> bool:
    """Whether the engine knows this preference's kind and has every parameter it needs."""
    known = KINDS.get(preference.kind)
    if known is None:
        return False
    for name in known[1]:
        value = preference.params.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float) \
                or not math.isfinite(value):
            return False
    return True


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
