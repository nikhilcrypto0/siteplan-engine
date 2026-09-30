"""Telangana building rules, as data with their source clause attached.

Every number here was read from a primary document, and each carries the clause it came from.
The base text is the Telangana Building Rules 2012 (G.O.Ms.No.168, MA&UD, 07-04-2012), read
on 2026-09-18. Three amendments were read from the orders themselves: G.O.Ms.No.7
(05-01-2016), which rewrites the green strip, road-widening concessions, amenities and EWS
rules; G.O.Ms.No.50 (22-04-2019), which substitutes Table IV; G.O.Ms.No.65 (31-05-2019), which
deletes the note G.O.Ms.No.50 had put under it for buildings longer than 40 m; and
G.O.Ms.No.95 (21-03-2026), which makes a high-rise 21 m.

`inventory.py` lists how each rule here was read, including those the engine leaves out.
Still unread: G.O.Ms.No.245 of 2012, G.O.Ms.No.103 of 2021 and G.O.Ms.No.16 of 2026.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RULES_SOURCE = "Telangana Building Rules 2012, G.O.Ms.No.168 (HMDA consolidated text)"


@dataclass(frozen=True)
class HeightBand:
    above_m: float
    up_to_m: float
    min_road_m: float
    min_open_space_m: float  # all-round setback, and the gap between two blocks

    def contains(self, height_m: float) -> bool:
        return self.above_m < height_m <= self.up_to_m


# Table IV as substituted by G.O.Ms.No.50 (MA&UD, 22-04-2019), Amendment-6: "In Rule 7, the
# Table IV under sub-rule (a)(x) shall be substituted with the following". Read from the order
# itself on 2026-09-20. The rows up to 55 m are unchanged from 2012; the three above it are new
# and replace the older "0.5 m for every 5 m above 55 m" note.
TABLE_IV = (
    HeightBand(0, 21, 12, 7),
    HeightBand(21, 24, 12, 8),
    HeightBand(24, 27, 18, 9),
    HeightBand(27, 30, 18, 10),
    HeightBand(30, 35, 24, 11),
    HeightBand(35, 40, 24, 12),
    HeightBand(40, 45, 24, 13),
    HeightBand(45, 50, 30, 14),
    HeightBand(50, 55, 30, 16),
    HeightBand(55, 70, 30, 17),
    HeightBand(70, 120, 30, 18),
    HeightBand(120, 10_000, 30, 20),
)
TABLE_IV_CLAUSE = "G.O.168 rule 7(a)(x), Table IV as substituted by G.O.Ms.No.50 of 2019"

# G.O.Ms.No.50 of 2019 also put a note under Table IV adding setback for a building longer than
# 40 m. G.O.Ms.No.65 (MA&UD, 31-05-2019) deleted it five weeks later: "The foot note under the
# Table IV ... which stipulates that 'If the length or depth of the building exceeds 40 m, add to
# Col (4) ten percent of length or depth of building minus 4.0 m subject to maximum requirement
# of 20 m' is deleted." Read from the order on 2026-09-29. The engine applied it until then,
# asking up to 3.3 m more of every long block than the law does. A building's length no longer
# changes its setback.

# Rule 2(f) as substituted by G.O.Ms.No.95 (MA&UD, 21-03-2026), amendment 5(i): "High-Rise
# Building means a building with 21m or more in height." Read from the order on 2026-09-20.
HIGH_RISE_THRESHOLD_M = 21.0
HIGH_RISE_CLAUSE = "G.O.168 rule 2(f) as substituted by G.O.Ms.No.95 of 2026 (21 m)"

# Same order, 5(ii), inserting rule 17(d)(viii): on plots of 750 to 2000 sq.m a building of
# 18 to 21 m is permitted only through TDR, so that band is a question, not a pass.
TDR_BAND_M = (18.0, 21.0)
TDR_PLOT_RANGE_SQM = (750.0, 2000.0)
TDR_BAND_CLAUSE = "G.O.Ms.No.95 of 2026, rule 17(d)(viii) (18-21 m on 750-2000 m² needs TDR)"

# Same order, 5(v), inserting rule 17(d)(xii): "In plots above 2000 sq.m: (a) Up to 3
# additional floors may be permitted in plots abutting 40 ft road (b) Up to 4 additional floors
# in plots abutting 60 ft road (c) Up to 5 additional floors in plots abutting 80 ft road
# subject to utilization of TDR and compliance with Fire, Airport and other norms." Read from
# the scanned order on 2026-09-29. It "modifies existing provisions", which are unread. The
# 40, 60 and 80 ft roads are taken as the 12, 18 and 24 m of Table IV, as Hyderabad names them.
TDR_EXTRA_FLOORS_BY_ROAD_M = ((24.0, 5), (18.0, 4), (12.0, 3))
TDR_EXTRA_FLOORS_ABOVE_PLOT_SQM = 2000.0
TDR_EXTRA_FLOORS_CLAUSE = (
    "G.O.Ms.No.95 of 2026, rule 17(d)(xii) (up to 3, 4 or 5 more floors through TDR on plots "
    "above 2000 m² abutting 40, 60 or 80 ft roads)"
)

MIN_HIGH_RISE_PLOT_SQM = 2000.0
MIN_HIGH_RISE_PLOT_CLAUSE = "G.O.168 rule 7(a)(ii)"
ROAD_WIDENING_SHORTFALL_ALLOWANCE = 0.10  # rule 7(a)(iii): up to 10% net-plot shortfall
ROAD_WIDENING_SHORTFALL_CLAUSE = "G.O.168 rule 7(a)(iii)"

OPEN_SPACE_MIN_FRACTION = 0.10
OPEN_SPACE_MIN_WIDTH_M = 3.0
OPEN_SPACE_MIN_POCKET_SQM = 50.0
OPEN_SPACE_CLAUSE = "G.O.168 rule 7(a)(vii)"

# Rule 7(viii) as substituted by G.O.Ms.No.7 of 05-01-2016, Amendment-8: the strip is required
# "where the setback is 9m and above", which the 2012 text did not qualify.
PERIPHERAL_GREEN_STRIP_M = 2.0
PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M = 9.0
PERIPHERAL_GREEN_STRIP_CLAUSE = (
    "G.O.168 rule 7(a)(viii) as substituted by G.O.Ms.No.7 of 2016 (setbacks of 9 m and above)"
)

# Rule 7(xvi), added by the same order: "Where parking floors are provided above ground floor,
# the height of the parking floors shall be excluded while reckoning the height of the building
# for the purpose of deciding the setbacks as per the Table IV." A stilt sits at ground level,
# so this code counts it in the height, which is the stricter reading. Whether the firm's
# authority treats a stilt the same way is a question for them, not for us to assume.
PARKING_FLOOR_HEIGHT_CLAUSE = (
    "G.O.168 rule 7(xvi), added by G.O.Ms.No.7 of 2016 (parking floors above the ground floor "
    "are left out of the height that decides the Table IV setback)"
)

BLOCK_SPACING_CLAUSE = "G.O.168 rule 7(a)(xii) (same as Table IV column 4)"
ROAD_WIDENING_CLAUSE = (
    "G.O.168 rule 16 as substituted by G.O.Ms.No.7 of 2016 (surrender free of cost; TDR, extra "
    "floors or setback concessions)"
)

MORTGAGE_FRACTION = 0.10  # of built-up area, handed over by notarised affidavit
MORTGAGE_CLAUSE = "G.O.168 rule 25(d), p.28 (10% of built-up area handed over by affidavit)"

DRIVEWAY_MIN_WIDTH_M = 4.5
DRIVEWAY_CLAUSE = "G.O.168 rule 13(c)(viii) (minimum drive way width 4.5 m)"

# Rule 15(b)(iv) holds a high-rise to NBC's fire protection requirements, and NBC 2016 Part 4
# (3.4.4.1, note) leaves fire-vehicle clearances to Part 3, section 4.6:
# (b) the road may end in a dead end only for a residential building up to 30 m, the height being
#     NBC's own (Part 3 2.10: from the ground to the terrace of the top floor, stilt included);
# (c) the approach and the open space on all sides at least 6 m wide, motorable for a 45 t
#     tender, with a 9 m turning radius and no parking in it;
# (d) an entrance of at least 6 m, a gate that folds back against the compound wall, and 4.5 m
#     clear under anything built over the entrance.
DEAD_END_MAX_HEIGHT_M = 30.0
DEAD_END_CLAUSE = (
    "G.O.168 rule 15(b)(iv), bringing in NBC 2016 Part 3 4.6(b) (no dead-end road for a "
    "residential building above 30 m)"
)
FIRE_TENDER_MIN_WIDTH_M = 6.0
FIRE_TENDER_CLAUSE = (
    "G.O.168 rule 15(b)(iv), bringing in NBC 2016 Part 3 4.6(c) (fire-tender approach at least "
    "6 m wide)"
)
GATE_MIN_WIDTH_M = 6.0
GATE_CLAUSE = (
    "G.O.168 rule 15(b)(iv), bringing in NBC 2016 Part 3 4.6(d) (entrance at least 6 m wide)"
)

# Rule 3(a)(ii): no building within these distances of a water body, measured from a lake's Full
# Tank Level or a nala's or river's defined boundary; the river clause is the one G.O.Ms.No.7 of
# 2016 substituted (50 m within municipal, HMDA and UDA limits). The buffer may count as tot-lot
# or organised open space, never as the setback (rule 3(a)(iii)(3)). Which class a water body is
# in (a nala wider than 10 m, a lake of 10 ha or more) is the architect's to say.
WATER_BUFFER_M = {
    "river": 50.0,
    "lake_10ha_or_more": 30.0,
    "lake_under_10ha": 9.0,
    "nala_over_10m": 9.0,
    "nala_up_to_10m": 2.0,
}
WATER_BUFFER_CLAUSE = (
    "G.O.168 rule 3(a)(ii), the river clause as substituted by G.O.Ms.No.7 of 2016; rule "
    "3(a)(iii)(3)"
)

# Rule 15(a)(x) is the group-housing one: 3% of built-up area, in a block of its own. (Rule 9(o)
# asks 5% of site area but sits in the row-housing section, so it is not used as the check here.)
# G.O.Ms.No.7 of 2016, Amendment 15, rewrote it as "upto 3% of the total built up area (or)
# 50,000 Sft. whichever is lower". The check still applies the 2012 minimum of 3% with no cap
# until a sanctioned plan shows how the new wording is read (inventory.py flags it).
AMENITY_MIN_BUILT_UP_FRACTION = 0.03
AMENITY_MIN_UNITS = 100
AMENITY_CLAUSE = (
    "G.O.168 rule 15(a)(x) as substituted by G.O.Ms.No.7 of 2016 (group housing of 100 units "
    "or more: 'upto 3% of the total built up area (or) 50,000 Sft. whichever is lower', in a "
    "block that is not part of the residential blocks)"
)

# Table V row 4 covers Residential Apartment Complexes: 30% inside GHMC, 20% in every other
# column (HMDA area, corporations, UDA areas, municipalities), so the default is the 20%.
PARKING_PERCENT_GHMC = 30.0
PARKING_PERCENT_ELSEWHERE = 20.0
PARKING_CLAUSE = "G.O.168 rule 13, Table V row 4 (Residential Apartment Complexes)"


def parking_percent(authority: str | None) -> float:
    """The Table V percentage of built-up area to be provided as parking."""
    inside_ghmc = (authority or "").upper() == "GHMC"
    return PARKING_PERCENT_GHMC if inside_ghmc else PARKING_PERCENT_ELSEWHERE


def band_for_height(height_m: float) -> HeightBand | None:
    """The Table IV row for a building height."""
    return next((band for band in TABLE_IV if band.contains(height_m)), None)


def max_height_for_road(road_m: float) -> float | None:
    """The tallest high-rise a road this wide can serve, from Table IV column 3.

    None when the road is narrower than even the first row asks (no high-rise at all), and
    infinity when it meets every row: from 30 m of road the table sets no height limit.
    """
    served = [band for band in TABLE_IV if road_m >= band.min_road_m]
    if not served:
        return None
    if len(served) == len(TABLE_IV):
        return math.inf
    return served[-1].up_to_m


def tdr_extra_floors(plot_sqm: float, road_m: float) -> int:
    """How many more floors TDR may buy (rule 17(d)(xii)); 0 when the plot or road is too small."""
    if plot_sqm <= TDR_EXTRA_FLOORS_ABOVE_PLOT_SQM:
        return 0
    return next((n for width, n in TDR_EXTRA_FLOORS_BY_ROAD_M if road_m >= width), 0)


def height_rules(height_m: float, plot_sqm: float | None = None) -> dict:
    """What the rules require of a building of this height, with the clause for each value."""
    if height_m < HIGH_RISE_THRESHOLD_M:
        answer = (f"Below {HIGH_RISE_THRESHOLD_M:g} m the Table III setbacks of rule 5 apply, "
                  "and those are not encoded here yet.")
        out = {"height_m": height_m, "class": "not high-rise", "answer": answer,
               "clause": HIGH_RISE_CLAUSE}
        low, high = TDR_BAND_M
        small, large = TDR_PLOT_RANGE_SQM
        if low <= height_m < high and (plot_sqm is None or small <= plot_sqm <= large):
            out["watch"] = (
                f"A building of {low:g} to {high:g} m is permitted only through TDR on a plot of "
                f"{small:g} to {large:g} m². Confirm the plot extent and the TDR."
            )
            out["also"] = [TDR_BAND_CLAUSE]
        return out
    band = band_for_height(height_m)
    return {
        "height_m": height_m,
        "class": "high-rise",
        "band": f"{band.above_m:g} to {band.up_to_m:g} m",
        "min_abutting_road_m": band.min_road_m,
        "min_all_round_setback_m": band.min_open_space_m,
        "min_gap_between_blocks_m": band.min_open_space_m,
        "clause": TABLE_IV_CLAUSE,
        "also": [BLOCK_SPACING_CLAUSE, OPEN_SPACE_CLAUSE, PERIPHERAL_GREEN_STRIP_CLAUSE],
        "note": "A building's length does not change its setback: the 2019 note that added "
                "setback above 40 m was deleted by G.O.Ms.No.65 of 31.05.2019.",
    }
