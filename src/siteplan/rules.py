"""Telangana building rules, as data with their source clause attached.

Every number here was read from a primary document, and each carries the clause it came from.
The base text is the Telangana Building Rules 2012 (G.O.Ms.No.168, MA&UD, 07-04-2012), read
on 2026-09-18. Two amendments were read from the orders themselves on 2026-09-20 and are
applied here: G.O.Ms.No.50 (22-04-2019), which substitutes Table IV and adds the note on
buildings longer than 40 m, and G.O.Ms.No.95 (21-03-2026), which makes a high-rise 21 m.

Known gap: G.O.Ms.No.7 of 05-01-2016 has not been read, so nothing here can be called a
complete account of the amendments between 2012 and 2019.
"""

from __future__ import annotations

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

# The second note under the substituted Table IV: "If the length of depth of the building
# exceeds 40 m add to Col (4) ten percent of length or depth of building minus 4.0 m subject to
# maximum requirement of 20 m." At exactly 40 m the addition is zero, which is how we read it.
LONG_BUILDING_FROM_M = 40.0
LONG_BUILDING_FRACTION = 0.10
LONG_BUILDING_DEDUCTION_M = 4.0
SETBACK_CAP_M = 20.0
LONG_BUILDING_CLAUSE = "G.O.Ms.No.50 of 2019, note under Table IV (buildings longer than 40 m)"

# Rule 2(f) as substituted by G.O.Ms.No.95 (MA&UD, 21-03-2026), amendment 5(i): "High-Rise
# Building means a building with 21m or more in height." Read from the order on 2026-09-20.
HIGH_RISE_THRESHOLD_M = 21.0
HIGH_RISE_CLAUSE = "G.O.168 rule 2(f) as substituted by G.O.Ms.No.95 of 2026 (21 m)"

# Same order, 5(ii), inserting rule 17(d)(viii): on plots of 750 to 2000 sq.m a building of
# 18 to 21 m is permitted only through TDR, so that band is a question, not a pass.
TDR_BAND_M = (18.0, 21.0)
TDR_PLOT_RANGE_SQM = (750.0, 2000.0)
TDR_BAND_CLAUSE = "G.O.Ms.No.95 of 2026, rule 17(d)(viii) (18-21 m on 750-2000 m² needs TDR)"

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
ROAD_WIDENING_CLAUSE = "G.O.168 rule 16 (surrender free of cost; TDR, extra floor or setbacks)"

MORTGAGE_FRACTION = 0.10  # of built-up area, handed over by notarised affidavit
MORTGAGE_CLAUSE = "G.O.168 (mortgage clause (d), p.28)"

DRIVEWAY_MIN_WIDTH_M = 4.5
DRIVEWAY_CLAUSE = "G.O.168 rule 13(viii) (minimum drive way width 4.5 m)"

# Rule 15(a)(x) is the group-housing one: 3% of built-up area, in a block of its own. (Rule 9(o)
# asks 5% of site area but sits in the row-housing section, so it is not used as the check here.)
AMENITY_MIN_BUILT_UP_FRACTION = 0.03
AMENITY_MIN_UNITS = 100
AMENITY_CLAUSE = (
    "G.O.168 rule 15(a)(x) (group housing of 100 units or more: amenities of at least 3% of "
    "total built-up area, in a block that is not part of the residential blocks)"
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


def setback_for(band: HeightBand, longest_side_m: float | None = None) -> float:
    """The all-round setback: the Table IV figure, plus the addition a long building attracts.

    A 56 m slab needs 1.6 m more than the table alone, which is the difference between a
    layout an authority accepts and one it returns.
    """
    setback = band.min_open_space_m
    if longest_side_m and longest_side_m > LONG_BUILDING_FROM_M:
        setback += LONG_BUILDING_FRACTION * longest_side_m - LONG_BUILDING_DEDUCTION_M
    return min(setback, SETBACK_CAP_M)


def height_rules(height_m: float, longest_side_m: float | None = None,
                 plot_sqm: float | None = None) -> dict:
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
    setback = setback_for(band, longest_side_m)
    out = {
        "height_m": height_m,
        "class": "high-rise",
        "band": f"{band.above_m:g} to {band.up_to_m:g} m",
        "min_abutting_road_m": band.min_road_m,
        "min_all_round_setback_m": setback,
        "min_gap_between_blocks_m": setback,
        "clause": TABLE_IV_CLAUSE,
        "also": [BLOCK_SPACING_CLAUSE, OPEN_SPACE_CLAUSE, PERIPHERAL_GREEN_STRIP_CLAUSE],
    }
    if longest_side_m and longest_side_m > LONG_BUILDING_FROM_M:
        out["note"] = (
            f"{band.min_open_space_m:g} m from the table, plus "
            f"{setback - band.min_open_space_m:.2f} m because the building is "
            f"{longest_side_m:g} m long."
        )
        out["also"] = [LONG_BUILDING_CLAUSE, *out["also"]]
    elif longest_side_m is None:
        out["note"] = ("Give the building's length to include the addition a building longer "
                       f"than {LONG_BUILDING_FROM_M:g} m attracts.")
    return out
