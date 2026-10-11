"""Step 2: the main road and the height it allows. The main road is step 1's; its legal width,
reckoned as the order reckons a width given in feet, picks the tallest Table IV row it can serve,
and the floors are counted in the shortest storeys the files allow, the stilt separate (the
architect's rule of 2026-10-11: "Stilt + 8" is eight floors and a stilt, and the stilt is not
counted in the height). What else bears on the height is shown beside it: a road that ends at the
plot (NBC's 30 m), and the floors TDR may add (shown, none taken)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from siteplan import rules
from siteplan.steps.inputs import Inputs
from siteplan.steps.survey_copy import RoadSeen, SurveyCopy

SLAB_M = 0.15  # a floor slab: no rule gives it; with NBC's 2.75 m room it makes a 2.9 m storey
FIT_M = 1e-6  # a height this close to a limit is at it
LEGAL, DRAWN = "legal", "drawn"  # where the width that sets the height came from
TABLE_IV_WAY, TABLE_III_WAY = "Table IV", "Table III"  # which table the height came from


@dataclass(frozen=True)
class Storeys:
    """A storey's height, floor to floor, and the stilt's."""

    floor_m: float
    stilt_m: float
    raise_m: float  # the stilt floor above the ground

    def counted_m(self, floors: int) -> float:
        """The height the rules count: the floors only, the stilt and its raise left out."""
        return floors * self.floor_m

    def physical_m(self, floors: int) -> float:
        """From the ground to the terrace: the raise, the stilt and the floors."""
        return self.raise_m + self.stilt_m + floors * self.floor_m

    def most_floors(self, limit_m: float, below: bool = False) -> int:
        """The most floors whose counted height reaches the limit (stays under it, for a limit
        that is not itself reached)."""
        floors = math.floor(limit_m / self.floor_m + FIT_M)
        if below and math.isclose(self.counted_m(floors), limit_m, abs_tol=FIT_M):
            floors -= 1
        return floors


# The shortest storey the files allow (the architect's rule of 2026-10-11; the middle of a range
# where a file gives one, and none does): the room and the stilt, each with its slab.
STOREYS = Storeys(rules.ROOM_HEIGHT_MIN_M + SLAB_M, rules.STILT_MIN_HEIGHT_M + SLAB_M,
                  rules.COVERED_PARKING_RAISE_M)


@dataclass(frozen=True)
class Band:
    """One row of the table the height came from, as this step shows it."""

    heights: str  # 'above 27 up to 30 m'
    road_m: float | None  # the road the row asks; None where it asks none
    open_space_m: float | None  # Table IV column 4; None for a Table III line
    floors: tuple[int, ...]  # the floors whose counted height falls in it
    served: bool  # this road may serve it


@dataclass
class Height:
    inputs: Inputs
    copy: SurveyCopy
    stopped: str | None = None
    ask: str | None = None
    road: RoadSeen | None = None
    width_m: float = 0.0  # the width the height is read from
    width_from: str = ""  # LEGAL or DRAWN
    reckoned_m: float = 0.0  # as rule 5(f)(xvii) reckons it
    plot_sqm: float = 0.0  # the plot's area as per documents
    way: str = ""  # TABLE_IV_WAY or TABLE_III_WAY
    limit_m: float = 0.0  # the tallest counted height; infinity when the road sets none
    below: bool = False  # the limit itself is not reached (Table III's '18**' lines)
    floors: int | None = None  # the most floors the road allows; None when it sets no limit
    dead_end: bool = False  # only when the project says so: a road not said to be one is not
    dead_end_floors: int = 0  # the most floors on a road that ends at the plot
    tdr_floors: int = 0  # the most floors TDR may add (shown, none taken)
    bands: tuple[Band, ...] = ()
    storeys: Storeys = STOREYS

    @property
    def allowed_floors(self) -> int | None:
        """The most floors, with what the project says of a dead end applied."""
        if self.dead_end and self.floors is not None:
            return min(self.floors, self.dead_end_floors)
        return self.floors

    @property
    def high_rise(self) -> bool:
        floors = self.allowed_floors
        return floors is None or (
            self.storeys.counted_m(floors) >= rules.HIGH_RISE_THRESHOLD_M - FIT_M)


def height_for(inputs: Inputs, copy: SurveyCopy) -> Height:
    road = copy.access
    if road is None:
        return Height(inputs, copy, stopped="no road was found as the main road",
                      ask="Which road is the main road? Step 1 found none that is named and "
                          "meets the plot (see step 1's list of roads).")
    width, source = ((road.legal_width_m, LEGAL) if road.legal_width_m
                     else (road.drawn_width_m, DRAWN))
    reckoned = rules.reckoned_road_width_m(width)
    plot = copy.written_sqm or copy.drawn_sqm
    top = rules.max_height_for_road(reckoned)
    if top is not None and plot >= rules.MIN_HIGH_RISE_PLOT_SQM:
        way, limit, below = TABLE_IV_WAY, top, False
        bands = _table_iv_bands(reckoned)
    else:
        line = _table_iii_top(plot, reckoned)
        way, limit, below = TABLE_III_WAY, line.up_to_m, line.below
        bands = _table_iii_bands(plot, reckoned)
    storeys = STOREYS
    return Height(
        inputs, copy, road=road, width_m=width, width_from=source, reckoned_m=reckoned,
        plot_sqm=plot, way=way, limit_m=limit, below=below,
        floors=None if math.isinf(limit) else storeys.most_floors(limit, below),
        dead_end=inputs.project.site.road_dead_end is True,  # the architect's rule, 2026-10-11
        dead_end_floors=math.floor((rules.DEAD_END_MAX_HEIGHT_M - storeys.raise_m
                                    - storeys.stilt_m) / storeys.floor_m + FIT_M),
        tdr_floors=rules.tdr_extra_floors(plot, reckoned) if way == TABLE_IV_WAY else 0,
        bands=bands, storeys=storeys)


def _floors_in(above_m: float, up_to_m: float, below: bool = False) -> tuple[int, ...]:
    """The floors whose counted height is above the one figure and up to the other."""
    first = STOREYS.most_floors(above_m) + 1
    return tuple(range(first, STOREYS.most_floors(up_to_m, below) + 1))


def _table_iv_bands(road_m: float) -> tuple[Band, ...]:
    """Table IV's rows up to the first this road cannot serve, which shows what the next width
    of road would allow."""
    out, last = [], rules.TABLE_IV[-1]
    for band in rules.TABLE_IV:
        served = road_m >= band.min_road_m - FIT_M
        if band.above_m == 0:
            heights = f"up to {band.up_to_m:g} m"
        elif band is last:  # 'Above 120': no upper figure
            heights = f"above {band.above_m:g} m"
        else:
            heights = f"above {band.above_m:g} up to {band.up_to_m:g} m"
        floors = () if band is last else _floors_in(band.above_m, band.up_to_m)
        out.append(Band(heights, band.min_road_m, band.min_open_space_m, floors, served))
        if not served:
            break
    return tuple(out)


def _table_iii_top(plot_sqm: float, road_m: float) -> rules.TableIIILine:
    """The tallest line of the plot's Table III row this road allows (rule 5(e): the '18**'
    lines only on a road of 12 m or more)."""
    lines = [line for line in rules.table_iii_lines(plot_sqm)
             if not line.below or road_m >= rules.TABLE_III_TOP_TIER_MIN_ROAD_M - FIT_M]
    return max(lines, key=lambda line: line.up_to_m)


def _table_iii_bands(plot_sqm: float, road_m: float) -> tuple[Band, ...]:
    out, above = [], 0.0
    for line in rules.table_iii_lines(plot_sqm):
        top = rules.TABLE_III_TOP_TIER_MIN_ROAD_M if line.below else None
        heights = (f"above {above:g}, below {line.up_to_m:g} m" if line.below
                   else f"above {above:g} up to {line.up_to_m:g} m")
        out.append(Band(heights, top, None, _floors_in(above, line.up_to_m, line.below),
                        top is None or road_m >= top - FIT_M))
        above = line.up_to_m
    return tuple(out)
