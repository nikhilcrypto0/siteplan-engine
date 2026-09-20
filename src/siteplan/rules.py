"""Telangana building rules, as data with their source clause attached.

Every number here was read from the consolidated Telangana Building Rules 2012
(G.O.Ms.No.168, MA&UD, 07-04-2012) as hosted by HMDA at
lrsbrs.hmda.gov.in/hmdaLMS/data/168.pdf, on 2026-09-18, unless marked otherwise.
Amendments after that text (notably G.O.Ms.No.95 of 21-03-2026) are only known from
news reports, so the conservative base values are the defaults.
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


# Table IV of rule 7(a)(x): "above / up to" height, min. abutting road, all-round open space.
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
)
TABLE_IV_CLAUSE = "G.O.168 rule 7(a)(x), Table IV"

# Rule 2(f): high-rise means 18 m or more including stilt. G.O.Ms.No.95 (2026) reportedly
# raises this to 21 m; that text was not available, so 18 m (the stricter value) is the default.
HIGH_RISE_THRESHOLD_M = 18.0
HIGH_RISE_CLAUSE = "G.O.168 rule 2(f); G.O.Ms.No.95 (2026) reportedly 21 m, unverified"

MIN_HIGH_RISE_PLOT_SQM = 2000.0
MIN_HIGH_RISE_PLOT_CLAUSE = "G.O.168 rule 7(a)(ii)"
ROAD_WIDENING_SHORTFALL_ALLOWANCE = 0.10  # rule 7(a)(iii): up to 10% net-plot shortfall
ROAD_WIDENING_SHORTFALL_CLAUSE = "G.O.168 rule 7(a)(iii)"

OPEN_SPACE_MIN_FRACTION = 0.10
OPEN_SPACE_MIN_WIDTH_M = 3.0
OPEN_SPACE_MIN_POCKET_SQM = 50.0
OPEN_SPACE_CLAUSE = "G.O.168 rule 7(a)(vii)"

PERIPHERAL_GREEN_STRIP_M = 2.0
PERIPHERAL_GREEN_STRIP_CLAUSE = "G.O.168 rule 7(a)(viii)"

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


TALLEST_BAND_M = 55.0
ABOVE_TABLE_STEP_M = 5.0
ABOVE_TABLE_EXTRA_M = 0.5
ABOVE_TABLE_CLAUSE = (
    "G.O.168 Table IV note (after 55 m, 0.5 m additional setback for every 5 m of height)"
)


def band_for_height(height_m: float) -> HeightBand | None:
    """The Table IV row for a building height, or None above 55 m (not encoded yet)."""
    return next((band for band in TABLE_IV if band.contains(height_m)), None)


def height_rules(height_m: float) -> dict:
    """What the rules require of a building of this height, with the clause for each value."""
    if height_m < HIGH_RISE_THRESHOLD_M:
        return {
            "height_m": height_m,
            "class": "not high-rise",
            "answer": f"Below {HIGH_RISE_THRESHOLD_M:g} m the Table III setbacks of rule 5 apply, "
                      "and those are not encoded here yet.",
            "clause": HIGH_RISE_CLAUSE,
        }
    band = band_for_height(height_m)
    if band is not None:
        return {
            "height_m": height_m,
            "class": "high-rise",
            "band": f"{band.above_m:g} to {band.up_to_m:g} m",
            "min_abutting_road_m": band.min_road_m,
            "min_all_round_setback_m": band.min_open_space_m,
            "min_gap_between_blocks_m": band.min_open_space_m,
            "clause": TABLE_IV_CLAUSE,
            "also": [BLOCK_SPACING_CLAUSE, OPEN_SPACE_CLAUSE, PERIPHERAL_GREEN_STRIP_CLAUSE],
        }
    steps = math.ceil((height_m - TALLEST_BAND_M) / ABOVE_TABLE_STEP_M)
    tallest = TABLE_IV[-1]
    return {
        "height_m": height_m,
        "class": "high-rise above the last Table IV row",
        "min_abutting_road_m": tallest.min_road_m,
        "min_all_round_setback_m": tallest.min_open_space_m + steps * ABOVE_TABLE_EXTRA_M,
        "clause": ABOVE_TABLE_CLAUSE,
        "note": f"The extra setback is worked out from the note under Table IV: "
                f"{tallest.min_open_space_m:g} m at {TALLEST_BAND_M:g} m plus "
                f"{ABOVE_TABLE_EXTRA_M:g} m for each {ABOVE_TABLE_STEP_M:g} m above it. The road "
                f"width is the last row's; the note does not widen it.",
    }
