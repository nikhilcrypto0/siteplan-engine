"""The most floors a plot can legally take, and the rule that stops it there.

The road the plot takes its access from caps the height (Table IV column 3), and a plot under
2,000 m² cannot take a high-rise at all (rule 7(a)(ii)). Floors follow from that height, the
stilt and the floor-to-floor height. Whether the stilt counts in the height is still open (see
the inventory): the text reads as counting it, while the firm's own Dhulapally drawing behaves
as if it does not, so both answers are given until a sanctioned plan settles it. Heights leave
out the parapet, staircase head room, lift room and water tank (rule 2(e)).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from siteplan import rules
from siteplan.units import M_PER_FT

_EPS = 1e-9
_ROAD_NOTE = (
    "Road: give the legal width of the road the site takes its access from. A drawn width may "
    "be the carriageway alone; Table II speaks of the existing road, and a master-plan width "
    "counts once its strip is surrendered (our reading)."
)
_STILT_NOTE = (
    "Stilt: our reading of rule 2(e) counts it in the height, which gives the fewer floors; the "
    "firm's own Dhulapally drawing behaves as if it is not counted. A sanctioned plan settles it."
)
_UNCHECKED_NOTE = (
    "Not checked: airport height limits and clearances (G.O.168 rule 3(d)); lakes, nalas, "
    "railways, power lines and monuments (rule 3); the fire NOC."
)


@dataclass(frozen=True)
class FloorLimit:
    plot_sqm: float
    road_m: float
    floor_height_m: float
    stilt_height_m: float
    high_rise: bool
    max_height_m: float | None  # None when the road sets no limit (30 m of road and more)
    limited_by: str
    floors_stilt_counted: int | None  # None when the road sets no limit
    floors_stilt_not_counted: int | None
    setback_m: float | None  # Table IV all round, and between blocks, at the maximum height
    tdr_extra_floors: int
    notes: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "plot_sqm": round(self.plot_sqm, 1),
            "road_m": round(self.road_m, 2),
            "road_ft": round(self.road_m / M_PER_FT, 1),
            "floor_height_m": self.floor_height_m,
            "stilt_height_m": self.stilt_height_m,
            "high_rise": self.high_rise,
            "max_height_m": self.max_height_m,
            "limited_by": self.limited_by,
            "floors_above_stilt": {
                "stilt counted in the height (our reading of the rules)":
                    self.floors_stilt_counted,
                "stilt not counted (as the firm's Dhulapally drawing behaves)":
                    self.floors_stilt_not_counted,
            },
            "setback_all_round_m": self.setback_m,
            "extra_floors_through_tdr": self.tdr_extra_floors,
            "notes": list(self.notes),
        }


def _floors_up_to(height_m: float, floor_m: float, stilt_m: float) -> tuple[int, int]:
    """Floors above the stilt whose top stays at or under height_m: stilt counted, then not."""
    return (math.floor((height_m - stilt_m) / floor_m + _EPS),
            math.floor(height_m / floor_m + _EPS))


def _floors_under(height_m: float, floor_m: float, stilt_m: float) -> tuple[int, int]:
    """The same, strictly under height_m: a building of exactly 21 m is already high-rise."""
    return (math.floor((height_m - stilt_m - _EPS) / floor_m),
            math.floor((height_m - _EPS) / floor_m))


def _not_high_rise(plot_sqm, road_m, floor_m, stilt_m, why: str) -> FloorLimit:
    counted, not_counted = _floors_under(rules.HIGH_RISE_THRESHOLD_M, floor_m, stilt_m)
    notes = [
        f"Under {rules.HIGH_RISE_THRESHOLD_M:g} m, Table III (rule 5) sets the height by plot size "
        "and road width, and it is not encoded: the floors shown are only the most that stay "
        f"under {rules.HIGH_RISE_THRESHOLD_M:g} m.",
    ]
    small, large = rules.TDR_PLOT_RANGE_SQM
    if small <= plot_sqm <= large:
        low, high = rules.TDR_BAND_M
        notes.append(f"On a plot of {small:,.0f} to {large:,.0f} m², {low:g} to {high:g} m is "
                     f"allowed only through TDR ({rules.TDR_BAND_CLAUSE}).")
    return FloorLimit(plot_sqm, road_m, floor_m, stilt_m, high_rise=False,
                      max_height_m=None, limited_by=why, floors_stilt_counted=counted,
                      floors_stilt_not_counted=not_counted, setback_m=None, tdr_extra_floors=0,
                      notes=(*notes, _ROAD_NOTE, _STILT_NOTE, _UNCHECKED_NOTE))


def max_floors(plot_sqm: float, road_m: float, floor_height_m: float = 3.0,
               stilt_height_m: float = 3.0) -> FloorLimit:
    """The tallest building the rules allow on this plot and road, in metres and floors."""
    if min(plot_sqm, road_m, floor_height_m) <= 0 or stilt_height_m < 0:
        raise ValueError("Plot area, road width and floor height must be positive.")
    if plot_sqm < rules.MIN_HIGH_RISE_PLOT_SQM:
        why = (f"a plot under {rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m² cannot take a high-rise "
               f"({rules.MIN_HIGH_RISE_PLOT_CLAUSE})")
        return _not_high_rise(plot_sqm, road_m, floor_height_m, stilt_height_m, why)
    height = rules.max_height_for_road(road_m)
    if height is None:
        first = rules.TABLE_IV[0].min_road_m
        why = f"a road under {first:g} m cannot serve a high-rise ({rules.TABLE_IV_CLAUSE})"
        return _not_high_rise(plot_sqm, road_m, floor_height_m, stilt_height_m, why)

    extra = rules.tdr_extra_floors(plot_sqm, road_m)
    notes = [_ROAD_NOTE, _STILT_NOTE]
    if extra:
        notes.append(f"With TDR: up to {extra} more floors ({rules.TDR_EXTRA_FLOORS_CLAUSE}), "
                     "subject to fire, airport and other norms. It modifies earlier provisions "
                     "that have not been read, so confirm before promising them.")
    if math.isinf(height):
        why = (f"no height limit from the road: Table IV asks {rules.TABLE_IV[-1].min_road_m:g} m "
               "of road for any height, so setbacks, fire and airport norms decide instead")
        return FloorLimit(plot_sqm, road_m, floor_height_m, stilt_height_m, True, None, why,
                          None, None, None, extra, (*notes, _UNCHECKED_NOTE))

    beyond = next(band for band in rules.TABLE_IV if band.above_m >= height)
    why = (f"the {road_m:.2f} m road serves buildings up to {height:g} m; up to "
           f"{beyond.up_to_m:g} m needs {beyond.min_road_m:g} m of road ({rules.TABLE_IV_CLAUSE})")
    setback = rules.band_for_height(height).min_open_space_m
    notes.append(f"At {height:g} m each tower needs {setback:g} m open all round and between "
                 f"blocks ({rules.TABLE_IV_CLAUSE}), whatever its length.")
    counted, not_counted = _floors_up_to(height, floor_height_m, stilt_height_m)
    return FloorLimit(plot_sqm, road_m, floor_height_m, stilt_height_m, True, height, why,
                      counted, not_counted, setback, extra, (*notes, _UNCHECKED_NOTE))


def describe(limit: FloorLimit) -> str:
    """The answer first, then why it stops there, then what it leaves to the architect."""
    head = (f"Plot {limit.plot_sqm:,.0f} m², road {limit.road_m:.2f} m "
            f"({limit.road_m / M_PER_FT:.0f} ft), floors {limit.floor_height_m:g} m, "
            f"stilt {limit.stilt_height_m:g} m")
    if not limit.high_rise:
        answer = [f"High-rise: no. Staying under {rules.HIGH_RISE_THRESHOLD_M:g} m:"]
    elif limit.max_height_m is None:
        answer = ["High-rise: yes, with no height limit from the road."]
    else:
        answer = [f"High-rise: yes, up to {limit.max_height_m:g} m:"]
    if limit.floors_stilt_counted is not None:
        answer += [
            f"  stilt + {limit.floors_stilt_counted} floors if the stilt counts in the height",
            f"  stilt + {limit.floors_stilt_not_counted} floors if it does not",
        ]
    if limit.tdr_extra_floors:
        answer.append(f"  with TDR: up to {limit.tdr_extra_floors} more floors")
    lines = [head, "", *answer, "", f"Stopped by: {limit.limited_by}.", ""]
    lines += [f"- {note}" for note in limit.notes]
    return "\n".join(lines)
