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

# The front setback, read on 2026-10-01 from the 2012 text (p.17, clause (b)): "The Front setback
# shall be as per Table-III of rule-5 & Table-IV of rule-7 for Non High Rise & High Rise
# buildings respectively." So a high-rise keeps Table IV's column 4 at the front too, and the
# engine's all-round figure is the rule as written, not a reading.
FRONT_SETBACK_CLAUSE = (
    "G.O.168 p.17, clause (b) (the front setback of a high-rise is as per Table IV of rule 7)"
)

# Setbacks are measured on the net plot, after the road-widening strip. Rule 7(a)(iii), read on
# 2026-10-01: a high-rise site "affected in road widening where there is shortfall of the net plot
# size" is considered "with the proposed height and corresponding minimum all round setbacks", so
# the all-round setback is taken on the net plot; rules 5(f)(ii) and 5's notes say the same for
# Table III ("the prescribed setback ... after the said road widening portion").
SETBACK_ON_NET_PLOT_CLAUSE = (
    "G.O.168 rule 7(a)(iii) (setbacks of a high-rise on the net plot left after road widening); "
    "rule 5(f)(ii) for Table III"
)

# Rule 2(c), read on 2026-10-01: "'Group Development Scheme' is reckoned as development of
# Residential Buildings in a Campus or Site of 4000sq.m and above in area and could be row houses,
# semi-detached, detached Houses, Apartment blocks or High-Rise buildings or mix or combination of
# the above." Rule 8 (internal roads 8(m), pathways 8(l)) governs such schemes, so below 4,000 m²
# it does not apply. The site's area is the area as per documents (the gross), the net plot when
# no gross is known.
GROUP_DEVELOPMENT_MIN_SITE_SQM = 4000.0
GROUP_DEVELOPMENT_CLAUSE = (
    "G.O.168 rule 2(c) (a Group Development Scheme is residential development on a campus or "
    "site of 4,000 m² and above); rule 8 governs it"
)


def is_group_development(site_sqm: float) -> bool:
    """Rule 2(c): residential development on a site of 4,000 m² and above. The engine plans
    residential schemes only, so the area decides."""
    return site_sqm >= GROUP_DEVELOPMENT_MIN_SITE_SQM - 1e-6
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
# The 45 t is the tender's loading in the same sub-clause, as read from the page images on
# 2026-09-30 and recorded in AGENTS.md. It is a specification of the paving, which no drawing
# shows, so the engine never checks it: ResolvedRules carries it UNVERIFIED.
FIRE_TENDER_LOAD_T = 45.0
GATE_MIN_WIDTH_M = 6.0
GATE_CLAUSE = (
    "G.O.168 rule 15(b)(iv), bringing in NBC 2016 Part 3 4.6(d) (entrance at least 6 m wide)"
)
# 4.6(c) itself, read on the page image of NBC 2016 Part 3 p.18 on 2026-09-30: "The approach to
# the building and open spaces on all its sides shall be not less than 6 m in width, and a turning
# radius of minimum 9 m shall be provided for fire tender movement ... which shall be kept free of
# obstructions and shall be motorable. The compulsory open spaces around the building shall not
# be used for parking." It does not say where the 9 m is measured. UNRESOLVED_INTERPRETATION
# (constraints.py): we take it as the tender's own turning circle, the outer edge of the 6 m lane
# (inner edge 3 m): that is what lets a lane turn round a corner inside the 7 m the state keeps
# for fire vehicles (rule 13(c)(vii)) and its 7 m high-rise minimum setback, which a 9 m
# centreline could not. The 9 m is the order's number; the 6.88 m band access.py derives from
# this reading is ours, not the order's.
FIRE_TURNING_RADIUS_M = 9.0
FIRE_ACCESS_CLAUSE = (
    "G.O.168 rule 15(b)(iv), bringing in NBC 2016 Part 3 4.6(c) (6 m of motorable open space "
    "on all sides, a 9 m turning radius, free of obstructions, never parked in)"
)
# 4.6(a): "one end of this street shall join another street not less than 12 m in width". Where
# a road leads is not on a survey, so it is the architect's to say.
FIRE_STREET_JOIN_M = 12.0
FIRE_STREET_CLAUSE = (
    "G.O.168 rule 15(b)(iv), bringing in NBC 2016 Part 3 4.6(a) (the street joins a street at "
    "least 12 m wide at one end)"
)
ENTRANCE_CLEAR_HEIGHT_M = 4.5  # 4.6(d): under anything built over the main entrance

# Rule 8(m), read from the 2012 text on 2026-09-30 (G.O.Ms.No.7 of 2016 substituted 8(k) and
# 8(n), not 8(m)): "9m to 18m for main internal approach roads; 9m for other internal roads and
# also for looped roads. 8m for cul-de-sacs roads (with a minimum radius 9m.) between 50-100m
# length." The law is the 9 to 18 m range; drawing the main approach at 9 m is the optimiser's
# choice (access.APPROACH_M), not a reading of the rule. Rule 8(l), read on 2026-10-01: "In case
# of blocks up to 12m height, access through pathways of 6m width branching out from the internal
# roads / loop road would be allowed": the pathway is a permission for blocks up to 12 m only, so a
# taller block takes its access from an internal road. Both apply to a Group Development Scheme.
MAIN_APPROACH_ROAD_M = (9.0, 18.0)
INTERNAL_ROAD_M = 9.0
CUL_DE_SAC_WIDTH_M = 8.0
CUL_DE_SAC_LENGTH_M = (50.0, 100.0)
CUL_DE_SAC_HEAD_RADIUS_M = 9.0
INTERNAL_ROAD_CLAUSE = (
    "G.O.168 rule 8(m) (internal roads of a group development scheme: main approach 9-18 m, "
    "other and looped roads 9 m, cul-de-sacs 8 m for 50-100 m with a 9 m radius head)"
)
PATHWAY_MAX_BLOCK_HEIGHT_M = 12.0
PATHWAY_CLAUSE = "G.O.168 rule 8(l) (6 m pathways only for blocks up to 12 m high)"

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
# 50,000 Sft. whichever is lower". UNRESOLVED_INTERPRETATION (constraints.py): the 3% minimum is
# the 2012 wording, kept as the planning target and ASSUMED_FOR_TEST; the 2016 wording may make
# 3% a ceiling and adds a cap. It is not settled law. The cap is recorded here as read, and only
# reported, never applied, until a sanctioned plan or the architect shows how the clause is read.
AMENITY_MIN_BUILT_UP_FRACTION = 0.03
AMENITY_MIN_UNITS = 100
AMENITY_CAP_SQFT_2016 = 50_000.0
AMENITY_CLAUSE = (
    "G.O.168 rule 15(a)(x) as substituted by G.O.Ms.No.7 of 2016 (group housing of 100 units "
    "or more: 'upto 3% of the total built up area (or) 50,000 Sft. whichever is lower', in a "
    "block that is not part of the residential blocks)"
)

# A second amenities rule, read from the 2012 text on 2026-10-03 (p.16): "In case of very large
# projects more than 5 acres, common amenities and facilities like shopping center, community
# hall/club house etc. are required to be provided in minimum 5 % of the site area." It stands
# twice, as rule 9(o) under ROW TYPE HOUSING and as rule 10(i) under CLUSTER HOUSING. It is not
# rule 8(o): in the 2012 text rule 8, Group Development Schemes, runs (a) to (n) with no such
# clause (the 2016 order substitutes 8(k) and 8(n), as noted at rule 8(m) below, and is not known
# to add an (o)), and a group scheme's amenities are rule 15(a)(x)'s 3% of the built-up area
# above. So it is recorded here and never applied to the apartment schemes this engine plans;
# whether the authority holds a very large group scheme to it is an open reading
# (legal/readings.py).
LARGE_PROJECT_FROM_ACRES = 5.0
LARGE_PROJECT_AMENITY_SHARE_OF_SITE = 0.05
LARGE_PROJECT_AMENITY_CLAUSE = (
    "G.O.168 rule 9(o) (row type housing) and rule 10(i) (cluster housing), p.16 (projects of "
    "more than 5 acres: common amenities in minimum 5% of the site area); not in rule 8"
)

# Table V row 4 covers Residential Apartment Complexes: 30% inside GHMC, 20% in every other
# column (HMDA area, corporations, UDA areas, municipalities), so the default is the 20%.
PARKING_PERCENT_GHMC = 30.0
PARKING_PERCENT_ELSEWHERE = 20.0
PARKING_CLAUSE = "G.O.168 rule 13, Table V row 4 (Residential Apartment Complexes)"

# Rule 13(c), read from the 2012 text on 2026-09-30 (G.O.Ms.No.7 of 2016 does not amend rule 13).
# (vii): "at least two ramps of minimum 3.6m width or one ramp of minimum 5.4m width and adequate
# slope 1 in 8 ... not allowed in mandatory setbacks including building line, however they may be
# permitted in the side and rear setbacks after leaving minimum 7m of setback for movement of
# fire-fighting vehicles."
RAMP_SINGLE_MIN_WIDTH_M = 5.4
RAMP_PAIR_MIN_WIDTH_M = 3.6
RAMP_MAX_GRADIENT = 1 / 8
RAMP_CLAUSE = "G.O.168 rule 13(c)(vii) (ramps: one of 5.4 m or two of 3.6 m, 1 in 8)"
# (x): "Cellar shall be with a setback of at least 1.5m in the sites of extent of up to 1000sq.m,
# 2m ... more than 1000sq.m and up to 2000sq.m, and 3m in the sites of extent of more than
# 2000sq.m from the property line. In case of more than one cellar, 0.5m additional setback for
# every additional cellar floor shall be insisted." Re-read on 2026-10-01: the text fixes the
# amounts but not whether the extra applies to the whole cellar or only to the deeper floors, so
# that stays an UNRESOLVED_INTERPRETATION (constraints.py); it matters only from two cellars.
CELLAR_SETBACK_BY_SITE_SQM = ((1000.0, 1.5), (2000.0, 2.0), (math.inf, 3.0))
CELLAR_EXTRA_SETBACK_PER_LEVEL_M = 0.5
CELLAR_SETBACK_CLAUSE = "G.O.168 rule 13(c)(x) (cellar setback from the property line)"
# (xi): "Up to 10% of cellar may be utilised for utilities and non-habitation purpose".
CELLAR_UTILITIES_MAX_FRACTION = 0.10
CELLAR_UTILITIES_CLAUSE = "G.O.168 rule 13(c)(xi) (up to 10% of a cellar for utilities)"
# (xii): "Visitors' parking shall be provided with minimum 10% of the parking area mentioned in
# Table-V ... properly demarcated on ground."
VISITOR_PARKING_FRACTION = 0.10
VISITOR_PARKING_CLAUSE = "G.O.168 rule 13(c)(xii) (visitors' parking, 10% of the Table V area)"


def cellar_setback_m(site_sqm: float, levels: int) -> float:
    """How far every cellar floor stays from the property line (rule 13(c)(x)). The order adds
    0.5 m for every cellar beyond the first; the extra is applied to all of them, since the
    cellars are one box, which is the stricter reading."""
    base = next(m for up_to, m in CELLAR_SETBACK_BY_SITE_SQM if site_sqm <= up_to)
    return base + CELLAR_EXTRA_SETBACK_PER_LEVEL_M * max(0, levels - 1)


# G.O.Ms.No.45 of 05.02.2026 brought the Core Urban Region (CURE) under GHMC: "Building Rules ...
# as applicable for GHMC area, shall be applicable to the entire CURE area". G.O.Ms.No.55 of
# 11.02.2026 then made the Cyberabad Municipal Corporation out of CURE zones, so a site inside
# CURE takes Table V's GHMC column whichever corporation it now falls in.
CURE_RULES_CLAUSE = "G.O.Ms.No.45 of 2026 (GHMC's building rules across the Core Urban Region)"


def parking_percent(authority: str | None, inside_cure: bool | None = None) -> float:
    """The Table V percentage of built-up area to be provided as parking: the GHMC column in
    GHMC or anywhere in CURE, the 20% column elsewhere. Callers must first know the jurisdiction
    (parking_columns); with an authority or CURE not known this returns the 20% column."""
    inside_ghmc = (authority or "").upper() == "GHMC" or bool(inside_cure)
    return PARKING_PERCENT_GHMC if inside_ghmc else PARKING_PERCENT_ELSEWHERE


def parking_columns(authority: str | None, inside_cure: bool | None) -> set[float]:
    """Every Table V percentage the site could take on what is known: one when the jurisdiction
    settles it, both when it does not. GHMC, or anywhere inside CURE, is 30% either way."""
    if (authority or "").upper() == "GHMC" or inside_cure is True:
        return {PARKING_PERCENT_GHMC}
    if authority is None or inside_cure is None:
        return {PARKING_PERCENT_GHMC, PARKING_PERCENT_ELSEWHERE}
    return {PARKING_PERCENT_ELSEWHERE}


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
