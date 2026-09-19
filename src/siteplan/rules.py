"""Telangana building rules, as data with their source clause attached.

Every number here was read from the consolidated Telangana Building Rules 2012
(G.O.Ms.No.168, MA&UD, 07-04-2012) as hosted by HMDA at
lrsbrs.hmda.gov.in/hmdaLMS/data/168.pdf, on 2026-09-18, unless marked otherwise.
Amendments after that text (notably G.O.Ms.No.95 of 21-03-2026) are only known from
news reports, so the conservative base values are the defaults.
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


def band_for_height(height_m: float) -> HeightBand | None:
    """The Table IV row for a building height, or None above 55 m (not encoded yet)."""
    return next((band for band in TABLE_IV if band.contains(height_m)), None)
