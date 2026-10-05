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

from siteplan.units import M_PER_FT

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


def high_rise_plot_met(net_sqm: float, surrendered: bool, tol_sqm: float = 0.0) -> bool | None:
    """Rule 7(a)(ii) on the net plot, read with rule 7(a)(iii): True when the net plot reaches
    the high-rise minimum; None when it falls short by no more than the allowance and the site
    gave up land for road widening, so that rule 7(a)(iii) may count the shortfall but nothing
    settles whether it does here; False otherwise. The resolver and the independent validator
    both read the minimum this way, so neither turns that open question into a refusal."""
    if net_sqm + tol_sqm >= MIN_HIGH_RISE_PLOT_SQM:
        return True
    if surrendered and net_sqm + tol_sqm >= MIN_HIGH_RISE_PLOT_SQM * (
            1 - ROAD_WIDENING_SHORTFALL_ALLOWANCE):
        return None
    return False

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

# The front setback of a high-rise, rule 7(a)(xi), p.14: "The front open space shall be on the
# basis of the abutting road width and shall be either as given in Col. 4 of above Table - IV or
# the Building Line given in Table - III of rule-5 whichever is higher." Table IV's column 4 all
# round, the front included, is therefore the rule except where the Building Line is higher: a
# block of exactly 21 m on a road above 30 m (7.5 m against 7 m). The engine first read the front
# on 2026-10-01 from p.17, clause (b), "The Front setback shall be as per Table-III of rule-5 &
# Table-IV of rule-7 for Non High Rise & High Rise buildings respectively", which is rule 12(b),
# written for 'U' type commercial buildings with a central courtyard; the citation was corrected
# on 2026-10-03 (stream A2) and the figure it gave stands.
FRONT_SETBACK_CLAUSE = (
    "G.O.168 rule 7(a)(xi), p.14 (a high-rise's front open space is the higher of Table IV "
    "column 4 and the Building Line of Table III, on the basis of the abutting road width)"
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
PATHWAY_WIDTH_M = 6.0  # "pathways of 6m width", p.15, the same sentence as the 12 m
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

# Rule 3(c)(i), read from the 2012 text (pp.4-5) on 2026-10-03: "In case of sites in the vicinity
# of High Tension Electricity Transmission Lines besides taking other safety precautions, a
# minimum safety distance (both vertical and horizontal) of 3m shall be maintained between the
# building and the High Tension Electricity Lines and 1.5m shall be maintained between the
# building and the Low Tension Electricity Lines." Rule 3(c)(ii), a green belt as wide as the
# tower base under a tower line with 10 m roads either side, is not modelled.
ELECTRICAL_HT_CLEARANCE_M = 3.0
ELECTRICAL_LT_CLEARANCE_M = 1.5
ELECTRICAL_CLAUSE = (
    "G.O.168 rule 3(c)(i), pp.4-5 (3 m from a high-tension line and 1.5 m from a low-tension "
    "line, vertical and horizontal)"
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
RAMP_FIRE_CLEARANCE_M = 7.0  # what a ramp in a side or rear setback leaves for fire vehicles
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


# --- Non-high-rise buildings: Table III of rule 5 (stream A2) ---------------------------------
#
# Read on 2026-10-03 from the page images of the 2012 order (pp.9-10) and checked against its text
# layer. Rule 5 is "PERMISSIBLE SETBACKS & HEIGHT STIPULATIONS FOR ALL TYPES OF NON-HIGH RISE
# BUILDINGS (Buildings below 18m in height inclusive of Stilt / Parking Floor)". Table III has a
# line for every permissible height (column 4) in a plot-size class (column 2). A line gives the
# Building Line, or minimum front setback, by the width of the abutting road (columns 5 to 9) and
# the minimum setback on the remaining sides (column 10). G.O.Ms.No.7 of 2016, Amendment 6 (p.3),
# put 'Stilt floor' in column 3 of rows 1 to 3. No order read after 2012 changes a figure.


@dataclass(frozen=True)
class TableIIILine:
    """One line of Table III: a plot-size class and one permissible height in it."""

    row: int  # Sl.No., column 1
    above_sqm: float  # plot size above this ...
    up_to_sqm: float  # ... and up to this, column 2 (row 1 is 'Less than 50')
    parking: str  # column 3: the parking provision the row is written for
    up_to_m: float  # column 4: permissible height up to this, the stilt left out (rule 5(c))
    below: bool  # the '18**' lines: above 15 m and below 18 m, so 18 m itself is not reached
    front_m: tuple[float, float, float, float, float]  # columns 5-9: Building Line by road width
    side_m: float | None  # column 10: setback on the remaining sides; None where the order has '-'

    def covers(self, height_m: float, tol_m: float = 1e-6) -> bool:
        """Whether a height, the stilt left out, is within this line's permissible height."""
        return height_m < self.up_to_m - tol_m if self.below else height_m <= self.up_to_m + tol_m


TABLE_III = (
    TableIIILine(1, 0, 50, "Stilt floor", 7, False, (1.5, 1.5, 3, 3, 3), None),
    TableIIILine(2, 50, 100, "Stilt floor", 7, False, (1.5, 1.5, 3, 3, 3), None),
    TableIIILine(2, 50, 100, "Stilt floor", 10, False, (1.5, 1.5, 3, 3, 3), 0.5),
    TableIIILine(3, 100, 200, "Stilt floor", 10, False, (1.5, 1.5, 3, 3, 3), 1.0),
    TableIIILine(4, 200, 300, "Stilt floor", 7, False, (2, 3, 3, 4, 5), 1.0),
    TableIIILine(4, 200, 300, "Stilt floor", 10, False, (2, 3, 3, 5, 6), 1.5),
    TableIIILine(5, 300, 400, "Stilt floor", 7, False, (3, 4, 5, 6, 7.5), 1.5),
    TableIIILine(5, 300, 400, "Stilt floor", 12, False, (3, 4, 5, 6, 7.5), 2.0),
    TableIIILine(6, 400, 500, "Stilt floor", 7, False, (3, 4, 5, 6, 7.5), 2.0),
    TableIIILine(6, 400, 500, "Stilt floor", 12, False, (3, 4, 5, 6, 7.5), 2.5),
    TableIIILine(7, 500, 750, "Stilt floor", 7, False, (3, 4, 5, 6, 7.5), 2.5),
    TableIIILine(7, 500, 750, "Stilt floor", 12, False, (3, 4, 5, 6, 7.5), 3.0),
    TableIIILine(7, 500, 750, "Stilt floor", 15, False, (3, 4, 5, 6, 7.5), 3.5),
    TableIIILine(8, 750, 1000, "Stilt + One Cellar floor", 7, False, (3, 4, 5, 6, 7.5), 3.0),
    TableIIILine(8, 750, 1000, "Stilt + One Cellar floor", 12, False, (3, 4, 5, 6, 7.5), 3.5),
    TableIIILine(8, 750, 1000, "Stilt + One Cellar floor", 15, False, (3, 4, 5, 6, 7.5), 4.0),
    TableIIILine(9, 1000, 1500, "Stilt + 2 Cellar floors", 7, False, (3, 4, 5, 6, 7.5), 3.5),
    TableIIILine(9, 1000, 1500, "Stilt + 2 Cellar floors", 12, False, (3, 4, 5, 6, 7.5), 4.0),
    TableIIILine(9, 1000, 1500, "Stilt + 2 Cellar floors", 15, False, (3, 4, 5, 6, 7.5), 5.0),
    TableIIILine(9, 1000, 1500, "Stilt + 2 Cellar floors", 18, True, (3, 4, 5, 6, 7.5), 6.0),
    TableIIILine(10, 1500, 2500, "Stilt + 2 Cellar floors", 7, False, (3, 4, 5, 6, 7.5), 4.0),
    TableIIILine(10, 1500, 2500, "Stilt + 2 Cellar floors", 15, False, (3, 4, 5, 6, 7.5), 5.0),
    TableIIILine(10, 1500, 2500, "Stilt + 2 Cellar floors", 18, True, (3, 4, 5, 6, 7.5), 6.0),
    TableIIILine(11, 2500, math.inf, "Stilt + 2 or more Cellar floors", 7, False,
                 (3, 4, 5, 6, 7.5), 5.0),
    TableIIILine(11, 2500, math.inf, "Stilt + 2 or more Cellar floors", 15, False,
                 (3, 4, 5, 6, 7.5), 6.0),
    TableIIILine(11, 2500, math.inf, "Stilt + 2 or more Cellar floors", 18, True,
                 (3, 4, 5, 6, 7.5), 7.0),
)
# Columns 5 to 9 are by the abutting road's width: up to 12 m, above 12 and up to 18, above 18 and
# up to 24, above 24 and up to 30, above 30. These are the upper edges of the first four.
TABLE_III_ROAD_UP_TO_M = (12.0, 18.0, 24.0, 30.0)
TABLE_III_CLAUSE = (
    "G.O.168 rule 5, Table III, pp.9-10 (non-high-rise setbacks and permissible height, by plot "
    "size and abutting road); parking column as amended by G.O.Ms.No.7 of 2016, Amendment 6"
)

# Rule 5(c), p.10: "Stilt Floor meant for parking is excluded from the permissible height in the
# above Table. Height of stilt floor shall not be less than 2.5m. In case of parking floors where
# mechanical system and lift are provided, height of such parking floor shall not be less than
# 4.5m." G.O.Ms.No.7 of 2016, Amendment 7 (p.3), adds that a stilt floor is used for parking only.
# So Table III's height is read with the stilt left out, whatever the open reading of the stilt
# for Table IV and the high-rise class says: rule 5's own heading calls the buildings it governs
# "below 18m in height inclusive of Stilt / Parking Floor", which leans the other way for the class.
STILT_MIN_HEIGHT_M = 2.5
MECHANICAL_PARKING_FLOOR_MIN_HEIGHT_M = 4.5
TABLE_III_STILT_CLAUSE = (
    "G.O.168 rule 5(c), p.10, with G.O.Ms.No.7 of 2016, Amendment 7 (a stilt floor meant for "
    "parking is left out of Table III's permissible height; not under 2.5 m high, 4.5 m where a "
    "mechanical parking system and lift are provided)"
)
# Rule 5(e), p.10: "**Buildings of height above 15m and below 18m in Sl.Nos.9, 10 and 11 above,
# shall be permitted only if such plots abut minimum 12m wide roads only."
TABLE_III_TOP_TIER_MIN_ROAD_M = 12.0
TABLE_III_TOP_TIER_CLAUSE = (
    "G.O.168 rule 5(e), p.10 (above 15 m and below 18 m, in rows 9, 10 and 11 only, if the plot "
    "abuts a road at least 12 m wide)"
)
# Rule 5(f)(iii), p.10: "Where a site abuts more than one road, then the front setback should be
# insisted towards the bigger road width and for the remaining side or sides, the setback as at
# Column-10 shall be insisted."
TABLE_III_BIGGER_ROAD_CLAUSE = (
    "G.O.168 rule 5(f)(iii), p.10 (a site on more than one road keeps the front setback towards "
    "the bigger road and Column 10 on the other sides)"
)
# Rule 5(f)(xiii), p.11: "The space between 2 blocks shall not be less than the side setback of the
# tallest block as mentioned in Table - III and this shall not be considered for organised open
# space (tot lot)." And rule 8(j), p.15, for a Group Development Scheme: "The open space to be left
# between two blocks also shall be equivalent to the setback mentioned in Column -10 of Table-III of
# rule-5 and Column - 4 of Table- IV of rule-7 as the case may be." Neither says what a block below
# 21 m and a high-rise keep between them: that is the open reading MIXED_HEIGHT_SPACING.
NON_HIGH_RISE_SPACING_CLAUSE = (
    "G.O.168 rule 5(f)(xiii), p.11 (the space between two blocks is at least the side setback of "
    "the tallest block in Table III, and is not counted as organised open space)"
)
GROUP_SCHEME_SPACING_CLAUSE = (
    "G.O.168 rule 8(j), p.15 (in a Group Development Scheme the space between two blocks equals "
    "Column 10 of Table III or Column 4 of Table IV, as the case may be)"
)
# Rule 7(a)(xi), p.14, quoted at FRONT_SETBACK_CLAUSE above, of which this is the other name: the
# high-rise front, as the resolver and the bands carry it. The 2012 order's rule 12(b), p.17, which
# says the front setback is "as per Table-III of rule-5 & Table-IV of rule-7 for Non High Rise &
# High Rise buildings respectively", is for 'U' type commercial buildings with a central
# courtyard, so it is not the front rule for apartments.
BUILDING_LINE_HIGH_RISE_CLAUSE = FRONT_SETBACK_CLAUSE
# Rule 5(f)(xvii), the second paragraph so numbered, p.11: "For the purpose of these Rules, the
# following conversion from M.K.S. and F.P.S. system shall be reckoned for the road widths only".
# The pairs are the order's own (metres, feet); a width the engine converted from feet (units.py,
# 0.3048 m a foot) is reckoned as the metre figure, so a 60 ft road is 18 m, not 18.288 m. The
# tolerance only says how close to the conversion a width has to be to be taken as one given in
# feet; it is the engine's, not the order's.
ROAD_WIDTH_FEET = ((3.0, 10), (6.0, 20), (7.5, 25), (9.0, 30), (12.0, 40), (15.0, 50),
                   (18.0, 60), (24.0, 80), (30.0, 100), (45.0, 150), (60.0, 200))
ROAD_FEET_TOLERANCE_M = 0.005
ROAD_WIDTH_CONVERSION_CLAUSE = (
    "G.O.168 rule 5(f)(xvii), the second so numbered, p.11 (road widths in feet are reckoned as "
    "3 m = 10 ft, 6 m = 20 ft, 7.5 m = 25 ft, 9 m = 30 ft, 12 m = 40 ft, 15 m = 50 ft, 18 m = 60 "
    "ft, 24 m = 80 ft, 30 m = 100 ft, 45 m = 150 ft, 60 m = 200 ft)"
)

# Rule 4(a), Table II, pp.7-8: the least abutting existing road a use needs. The engine's sites lie
# in category B (new areas, approved layouts); category A (old built-up areas) takes B1's rows for
# group housing, so the figures are the same. B1: non-high-rise residential buildings, group
# housing included, "Cellar and/or Stilt as permissible + maximum up to 5 floors": 9 m. B2: "Non
# High Rise Group Housing (Cellars as applicable + 6 floors), Group Housing with more than 100
# units, Group Development Scheme ... Others not specified in the Table and all Non High-Rise
# buildings up to 18m height": 12 m. B3 and B4 are high-rise rows and agree with Table IV.
# Rule 8(b), p.14: "The minimum abutting existing road width shall be 12m and black topped."
TABLE_II_B1_ROAD_M = 9.0
TABLE_II_B1_MAX_FLOORS = 5
TABLE_II_B2_ROAD_M = 12.0
TABLE_II_B2_UNITS_OVER = 100
TABLE_II_CLAUSE = (
    "G.O.168 rule 4(a), Table II, pp.7-8, category B (new areas and approved layouts): B1, "
    "non-high-rise residential with stilt or cellar and up to 5 floors, 9 m; B2, six floors, "
    "group housing of more than 100 units, a Group Development Scheme, other non-high-rise up "
    "to 18 m, 12 m"
)
GROUP_DEVELOPMENT_MIN_ROAD_M = 12.0
GROUP_DEVELOPMENT_ROAD_CLAUSE = (
    "G.O.168 rule 8(b), p.14 (a Group Development Scheme needs an existing black-topped abutting "
    "road at least 12 m wide), with Table II row B2"
)
# Rule 4(f), p.8: "In case of single plot sub-division approved by the competent authority, a means
# of independent access of minimum 3.6m pathway may be considered for Individual Residential
# Building and 6m for Non-High-Rise Group Housing Building."
SUBDIVISION_PATHWAY_M = (3.6, 6.0)
SUBDIVISION_PATHWAY_CLAUSE = (
    "G.O.168 rule 4(f), p.8 (single plot sub-division: independent access of at least 3.6 m for "
    "an individual residential building, 6 m for non-high-rise group housing)"
)

# Rule 5(f)(xvi), p.11: "As per the provisions of the Andhra Pradesh Fire Service Act, 1999,
# Residential buildings of height more than 18 m, Commercial buildings of height 15m and above and
# buildings of public congregation ... are required to obtain prior clearance from Andhra Pradesh
# State Disasters Response & Fire Services Department from fire safety point of view." The only
# number the order gives for fire below 21 m. Rule 15(a)(i), as substituted by G.O.Ms.No.50 of
# 2019 (p.1, Amendment-1), holds a non-high-rise building to "the building requirements and
# standards other than heights and setbacks specified in the National Building Code 2016": it
# gives no figure itself, and leaves out the NBC's open spaces, which are setbacks.
FIRE_CLEARANCE_RESIDENTIAL_ABOVE_M = 18.0
FIRE_CLEARANCE_CLAUSE = (
    "G.O.168 rule 5(f)(xvi), p.11 (residential buildings above 18 m need the prior clearance of "
    "the State Disasters Response & Fire Services Department)"
)
NON_HIGH_RISE_NBC_CLAUSE = (
    "G.O.168 rule 15(a)(i) as substituted by G.O.Ms.No.50 of 2019, Amendment-1 (a non-high-rise "
    "building keeps the National Building Code 2016's requirements other than heights and "
    "setbacks; IGBC Green Homes norms for the ventilation of rooms)"
)

# Rule 5(f), p.10. The order's numbering of this list is irregular: its (iiii) and (ivi) stand
# where (iv) and (v) belong. "(iiii) A strip of at least 1m greenery / lawn along the frontage of
# the site within the front setback shall be developed and maintained with greenery." "(ivi) For
# Plots above 300sq.m in addition to (iii) above, a minimum 1m wide continuous green planting
# strip in the periphery on remaining sides are required to be developed and maintained within
# the setback." G.O.Ms.No.7 of 2016 does not touch them (its Amendment 8 is rule 7(viii), the
# high-rise strip), nor does any later order read.
NON_HIGH_RISE_FRONTAGE_STRIP_M = 1.0
NON_HIGH_RISE_PERIPHERY_STRIP_M = 1.0
NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM = 300.0
NON_HIGH_RISE_GREEN_STRIP_CLAUSE = (
    "G.O.168 rule 5(f)(iiii) and (ivi), p.10 (a 1 m strip of greenery along the frontage within "
    "the front setback; on a plot above 300 m² a continuous 1 m planting strip on the remaining "
    "sides within the setback)"
)
# Rule 5(f)(vi), p.10: "For all residential / institutional / industrial plots above 750sq.m, in
# addition to (iii) and (iv) above, 5% of the site area to be developed as organized open space
# and be utilized as greenery, tot lot or soft landscaping etc., and shall be provided over and
# above the mandatory setbacks. Such organized open space could be in more than one location and
# shall be of a minimum width of 3m with a minimum area of 15sq.m at each location." A group
# development scheme (rule 8(g)) and a high-rise site (rule 7(a)(vii)) keep 10%.
NON_HIGH_RISE_OPEN_SPACE_FRACTION = 0.05
NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM = 750.0
NON_HIGH_RISE_OPEN_SPACE_MIN_WIDTH_M = 3.0
NON_HIGH_RISE_OPEN_SPACE_MIN_POCKET_SQM = 15.0
NON_HIGH_RISE_OPEN_SPACE_CLAUSE = (
    "G.O.168 rule 5(f)(vi), p.10 (residential, institutional and industrial plots above 750 m²: "
    "5% of the site as organised open space over and above the setbacks, pockets at least 3 m "
    "wide and 15 m²)"
)
# Rule 5(f)(viii), p.10: "In all plots 750sq.m and above, provision shall be made for earmarking
# an area of 3m X 3m for the purpose of setting of public utilities like distribution
# transformer, etc. within the owner's site subject to mandated public safety requirements."
PUBLIC_UTILITY_AREA_M = (3.0, 3.0)
PUBLIC_UTILITY_AREA_FROM_SQM = 750.0
PUBLIC_UTILITY_AREA_CLAUSE = (
    "G.O.168 rule 5(f)(viii), p.10 (plots of 750 m² and above earmark 3 m x 3 m of the site for "
    "public utilities such as a distribution transformer)"
)
# Rule 5(f)(viiii) and (ixi), p.10, setback transfers, design options and never applied here:
# "In case of plots 300 - 750sq.m, it is permitted to transfer up to 1m of setback from any one
# side to any other side without exceeding overall permissible plinth area. The transfer of
# setback from front setback is not allowed." "In case of plots above 750sq.m, it is permitted to
# transfer up to 2m of setback from any one side to any other side without exceeding overall
# permissible plinth area, subject to maintaining of a minimum 2.5m setback on other side and a
# minimum building line. The transfer of setback from front setback is not allowed."
SETBACK_TRANSFER_300_TO_750_M = 1.0
SETBACK_TRANSFER_ABOVE_750_M = 2.0
SETBACK_TRANSFER_MIN_OTHER_SIDE_M = 2.5
SETBACK_TRANSFER_CLAUSE = (
    "G.O.168 rule 5(f)(viiii) and (ixi), p.10 (a plot of 300-750 m² may move up to 1 m of setback "
    "from one side to another, a plot above 750 m² up to 2 m, keeping 2.5 m on the other side and "
    "a minimum building line; never from the front)"
)
# Rule 5(f)(xi), pp.10-11: "For narrow plots having extent not more than 400sq.m and where the
# length is 4 times of the width of the plot, the setbacks on sides may be compensated in front
# and rear setbacks so as to ensure that the overall aggregate setbacks are maintained in the
# site, subject to maintaining a minimum of side setback of 1m in case of buildings of height up
# to 10m and minimum of 2m in case of buildings of height above 10m and up to 15m without
# exceeding overall permissible plinth area. (This Rule shall not be applicable for made-up
# plots)." The minimum sides are (height up to, metres).
NARROW_PLOT_MAX_SQM = 400.0
NARROW_PLOT_LENGTH_TO_WIDTH = 4.0
NARROW_PLOT_MIN_SIDE_M = ((10.0, 1.0), (15.0, 2.0))
NARROW_PLOT_CLAUSE = (
    "G.O.168 rule 5(f)(xi), pp.10-11 (a plot of up to 400 m² four times as long as wide may move "
    "side setbacks into the front and rear, keeping 1 m of side up to 10 m of height and 2 m up "
    "to 15 m)"
)
# Rule 16(b) as substituted by G.O.Ms.No.7 of 2016, Amendment 16 (p.5): an owner who surrenders
# land for road widening may take "concessions in setbacks including the front set-back (subject
# to ensuring a building line of 6 m in respect of roads 30m and above; 3m in respect of roads 18m
# and below 30m and 2m in respect of roads less than 18m and subject to ensuring minimum side and
# rear setback of 2m in case of buildings of height up to 12m and 2.5m in case of buildings of
# height above 12m and upto 15m and 3m for buildings of height above 15m and up to 18m)". The
# building lines are (road at least, metres); the side and rear setbacks (height up to, metres).
# G.O.Ms.No.95 of 2026, rule 17(d)(ix) (p.2) lets a non-high-rise building relax its setbacks
# through TDR "subject to maintaining minimum setbacks as prescribed in cases of road widening",
# which are these. Options the owner takes, never applied here.
ROAD_WIDENING_NON_HIGH_RISE_BUILDING_LINE_M = ((30.0, 6.0), (18.0, 3.0), (0.0, 2.0))
ROAD_WIDENING_NON_HIGH_RISE_SIDE_REAR_M = ((12.0, 2.0), (15.0, 2.5), (18.0, 3.0))
ROAD_WIDENING_NON_HIGH_RISE_CLAUSE = (
    "G.O.168 rule 16(b) as substituted by G.O.Ms.No.7 of 2016, Amendment 16, p.5 (a surrendering "
    "owner may take setback concessions: a building line of 6, 3 or 2 m for a road of 30 m or "
    "more, 18 m to under 30 m, or under 18 m; side and rear of 2, 2.5 or 3 m up to 12, 15 or 18 m "
    "of height)"
)
TDR_NON_HIGH_RISE_SETBACK_CLAUSE = (
    "G.O.Ms.No.95 of 2026, rule 17(d)(ix), p.2 (a non-high-rise building may relax its setbacks "
    "through TDR, keeping the minimums of road widening)"
)


def table_iii_lines(plot_sqm: float) -> tuple[TableIIILine, ...]:
    """The lines of the Table III row a plot falls in. Column 2 reads 'Above - Up to', so a plot is
    in the row it is above the lower edge of and up to the upper edge of. Row 1 is 'Less than 50'
    and row 2 starts at 50, so a plot of exactly 50 m² is between them by the labels: row 2."""
    first = TABLE_III[0].row
    if plot_sqm < TABLE_III[0].up_to_sqm:
        row = first
    else:
        row = next(line.row for line in TABLE_III
                   if line.row > first and plot_sqm <= line.up_to_sqm)
    return tuple(line for line in TABLE_III if line.row == row)


def table_iii_line(plot_sqm: float, height_m: float) -> TableIIILine | None:
    """The line a building takes its setbacks from: the lowest permissible height of the plot's
    row that reaches the building's height, the stilt left out (rule 5(c)); None above the last."""
    return next((line for line in table_iii_lines(plot_sqm) if line.covers(height_m)), None)


def reckoned_road_width_m(width_m: float) -> float:
    """A road width as the order reckons it: one that is a listed number of feet (rule 5(f)(xvii))
    is the listed metres, so a 60 ft road, 18.288 m, is 18 m."""
    return next((metres for metres, feet in ROAD_WIDTH_FEET
                 if abs(width_m - feet * M_PER_FT) <= ROAD_FEET_TOLERANCE_M), width_m)


def building_line_m(line: TableIIILine, road_m: float) -> float:
    """Table III's Building Line, or minimum front setback, for the abutting road's legal width."""
    reckoned = reckoned_road_width_m(road_m)
    return float(line.front_m[sum(reckoned > edge for edge in TABLE_III_ROAD_UP_TO_M)])


def height_rules(height_m: float, plot_sqm: float | None = None,
                 road_m: float | None = None) -> dict:
    """What the rules require of a building of this height, with the clause for each value. Below
    the high-rise height Table III answers, given the plot (its row) and the road (the front)."""
    if height_m < HIGH_RISE_THRESHOLD_M:
        answer = (f"Below {HIGH_RISE_THRESHOLD_M:g} m the Table III setbacks of rule 5 apply: they "
                  "go by the plot size and the abutting road, which were not given, so they are "
                  "not encoded here without them.")
        out = {"height_m": height_m, "class": "not high-rise", "answer": answer,
               "clause": HIGH_RISE_CLAUSE}
        if plot_sqm is not None:
            line = table_iii_line(plot_sqm, height_m)
            out["clause"] = TABLE_III_CLAUSE
            out["also"] = [TABLE_III_STILT_CLAUSE]
            if line is None:
                top = table_iii_lines(plot_sqm)[-1]
                out["answer"] = (
                    f"Table III permits no building of {height_m:g} m (the stilt left out) on a "
                    f"plot of {plot_sqm:,.0f} m²: its row {top.row} stops at {top.up_to_m:g} m"
                    f"{' (below it)' if top.below else ''}.")
            else:
                out["answer"] = (
                    f"Table III row {line.row}, up to {line.up_to_m:g} m"
                    f"{' (below it)' if line.below else ''}, the stilt left out.")
                out["table_iii_row"] = line.row
                out["min_side_setback_m"] = line.side_m or 0.0
                out["min_gap_between_blocks_m"] = line.side_m or 0.0
                out["also"].append(NON_HIGH_RISE_SPACING_CLAUSE)
                if line.below:
                    out["min_abutting_road_m"] = TABLE_III_TOP_TIER_MIN_ROAD_M
                    out["also"].append(TABLE_III_TOP_TIER_CLAUSE)
                if road_m is not None:
                    out["building_line_m"] = building_line_m(line, road_m)
        low, high = TDR_BAND_M
        small, large = TDR_PLOT_RANGE_SQM
        if low <= height_m < high and (plot_sqm is None or small <= plot_sqm <= large):
            out["watch"] = (
                f"A building of {low:g} to {high:g} m is permitted only through TDR on a plot of "
                f"{small:g} to {large:g} m². Confirm the plot extent and the TDR."
            )
            out["also"] = [*out.get("also", []), TDR_BAND_CLAUSE]
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
