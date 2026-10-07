"""The architect's soft preferences (DesignBrief.objectives.soft_preferences), scored (C4-16): how
well a layout meets each wish, from 0 to 1. A preference is never a rule: nothing fails for one,
and a layout that meets none is still an option. The objective's preference axis is the weighted
mean of the brief's preferences the engine understands, 1 for every layout when there are none.

The kinds the engine knows, and their parameters:

- orientation (`axis_deg`): the blocks' long sides run along this direction, in degrees from the
  drawing's x axis as a block's rotation is measured; a block scores the |cos| of the angle
  between its long axis and that one;
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
