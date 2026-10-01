"""Every numeric constraint generation uses, and what kind of fact each one is.

The layout, the height search and the checker that accepts or rejects their output are built
from numbers. Not all of them are law. Each one here is classified as one of:

- LEGAL_RULE: a number read from an order and applied as written, with its clause;
- FIRM_STANDARD: the firm's choice, set in its workspace or library files, with the engine's
  default standing in (and reported ASSUMED_FOR_TEST) until the firm sets it;
- ENGINE_DESIGN_ASSUMPTION: a number the engine fixes with no file to set it in and no order
  behind it (search steps, tolerances, bay sizes, how roads are placed);
- UNRESOLVED_INTERPRETATION: an order gives the number or the rule but leaves open how it is
  applied, or two orders word it differently, and the engine has taken one reading for the
  test; a sanctioned plan or the architect settles it;
- SITE_INPUT: a per-site fact from the survey or the architect, carrying its own provenance in
  the project file.

Values are read from the modules that hold them, so this list cannot drift from the code, and
`tests/test_constraints.py` fails when a numeric constant in a generation module, or a numeric
default on a request or standards model, has no entry here. Inline literals (a bisection step,
a 45 degree test) cannot be caught that way; the ones that shape a result are listed by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import groupby

from siteplan import (
    access,
    access_checks,
    checks,
    grounds,
    intake,
    layout,
    library,
    max_floors,
    parking,
    parking_checks,
    rules,
    runner,
    site_amenities,
    towers,
)


class Basis(StrEnum):
    LEGAL_RULE = "LEGAL_RULE"
    FIRM_STANDARD = "FIRM_STANDARD"
    ENGINE_DESIGN_ASSUMPTION = "ENGINE_DESIGN_ASSUMPTION"
    UNRESOLVED_INTERPRETATION = "UNRESOLVED_INTERPRETATION"
    SITE_INPUT = "SITE_INPUT"


@dataclass(frozen=True)
class Constraint:
    topic: str
    what: str  # the constraint, in a sentence
    value: str  # as the code holds it now
    basis: Basis
    source: str  # the clause, the file the firm sets it in, or "none"
    symbols: tuple[str, ...] = ()  # module.NAME, or module.Model.field, that carry the number
    note: str = ""
    settles: str = ""  # the evidence that would settle it, where it is not law


def _m(value: float) -> str:
    return f"{value:g} m"


def _pct(fraction: float) -> str:
    return f"{fraction:.0%}"


_setback_rows = ", ".join(f"{b.min_open_space_m:g} m up to {b.up_to_m:g} m" if b.up_to_m < 1000
                          else f"{b.min_open_space_m:g} m above {b.above_m:g} m"
                          for b in rules.TABLE_IV)
_road_rows = ", ".join(f"{b.min_road_m:g} m up to {b.up_to_m:g} m" if b.up_to_m < 1000
                       else f"{b.min_road_m:g} m above {b.above_m:g} m" for b in rules.TABLE_IV)
_lr = layout.LayoutRequest.model_fields
_ws = intake.WorkspaceDefaults.model_fields
_fl = library.FlatLibrary.model_fields
_ps = parking.ParkingStandards()
_WORKSPACE = "the firm's siteplan.workspace.json (intake.WorkspaceDefaults)"
_LIBRARY = "the firm's flat library file (library.FlatLibrary)"
_SANCTIONED = "a sanctioned plan, or the architect"

REGISTRY: tuple[Constraint, ...] = (
    # ----------------------------------------------------------------- height and setbacks
    Constraint(
        "Height", "A building is high-rise, and Table IV applies, from this height.",
        _m(rules.HIGH_RISE_THRESHOLD_M), Basis.LEGAL_RULE, rules.HIGH_RISE_CLAUSE,
        ("rules.HIGH_RISE_THRESHOLD_M",),
    ),
    Constraint(
        "Height", "The road a height needs (Table IV column 3).", _road_rows, Basis.LEGAL_RULE,
        rules.TABLE_IV_CLAUSE, ("rules.TABLE_IV",),
        note="The same table gives the setbacks; the rows are one tuple.",
    ),
    Constraint(
        "Setbacks", "Open space all round each block, and the gap between two blocks, by height "
                    "(Table IV column 4).", _setback_rows, Basis.LEGAL_RULE,
        f"{rules.TABLE_IV_CLAUSE}; {rules.BLOCK_SPACING_CLAUSE}", ("rules.TABLE_IV",),
        note="A block's length does not add to it (G.O.Ms.No.65 of 2019 deleted the 40 m note).",
    ),
    Constraint(
        "Height", "The building's height, which picks the Table IV row, counts the stilt.",
        "stilt + floors x floor height", Basis.UNRESOLVED_INTERPRETATION,
        "G.O.168 rule 2(e); rule 5(c) excludes the stilt for Table III only",
        note="The stricter reading; the firm's own Dhulapally drawing behaves as if the stilt is "
             "not counted. The floors calculator gives both answers.",
        settles="A sanctioned stilt + N high-rise whose approved setback fits one reading only.",
    ),
    Constraint(
        "Setbacks", "The Table IV figure is kept on every side, the front included.",
        "column 4 all round", Basis.UNRESOLVED_INTERPRETATION,
        "G.O.168 rule 7(a)(xi); G.O.Ms.No.50 of 2019 heads column 4 'side and rear'",
        note="Rule 7(a)(xi) makes the front the larger of column 4 and the Table III building "
             "line (3 to 7.5 m), which exceeds column 4 only up to 21 m on a road over 30 m.",
        settles="A sanctioned plan on a road wider than 30 m.",
    ),
    Constraint(
        "Setbacks", "The gap between two blocks of different heights is the larger block's "
                    "figure.", "the larger of the two", Basis.UNRESOLVED_INTERPRETATION,
        rules.BLOCK_SPACING_CLAUSE,
        note="The text asks for 'the open space mentioned in Col. 4' without saying which block "
             "sets it. The club house keeps the same gap from every tower.",
        settles="A sanctioned plan with two blocks of different heights.",
    ),
    Constraint(
        "Setbacks", "Setbacks and cellars are measured from the net plot line, after the "
                    "road-widening strip.", "net plot line", Basis.UNRESOLVED_INTERPRETATION,
        "G.O.168 rule 5(f)(ii), written for buildings below high-rise",
        note="Applied to high-rise too; the surveyed boundary is never planned on when a net "
             "area is stated.",
        settles="A sanctioned plan on a widened road: from which line are its setbacks drawn?",
    ),
    Constraint(
        "Plot", "A high-rise needs a plot of at least this size, tested on the net plot.",
        f"{rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m²", Basis.LEGAL_RULE,
        rules.MIN_HIGH_RISE_PLOT_CLAUSE, ("rules.MIN_HIGH_RISE_PLOT_SQM",),
        note="The 10% shortfall allowance of rule 7(a)(iii) is defined and not applied.",
    ),
    Constraint(
        "Plot", "A site short of the minimum through road widening may be short by this much.",
        _pct(rules.ROAD_WIDENING_SHORTFALL_ALLOWANCE), Basis.LEGAL_RULE,
        rules.ROAD_WIDENING_SHORTFALL_CLAUSE, ("rules.ROAD_WIDENING_SHORTFALL_ALLOWANCE",),
        note="Not applied by generation or the checker: the text does not say 10% of what.",
    ),
    Constraint(
        "Plot", "Without a drawn net plot, the stated deduction comes off one side as a strip, "
                "when the survey's area exceeds the stated net area by more than this.",
        f"{runner.NET_AREA_TOLERANCE_SQM:g} m² of drafting slop", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (runner.load_plot, geometry.less_road_strip)", ("runner.NET_AREA_TOLERANCE_SQM",),
        note="Cut at an even width along the side the architect names, else the longest run. "
             "On Dhulapally neither matched the drawn strip; the site-plan DXF is better.",
        settles="The road-widening line on the survey or the sanction plan.",
    ),
    # ----------------------------------------------------------------- open space
    Constraint(
        "Open space", "Organised open space (tot-lot) over and above the setbacks, with the "
                      "least width and size of a pocket.",
        f"{_pct(rules.OPEN_SPACE_MIN_FRACTION)} of the site; pockets at least "
        f"{rules.OPEN_SPACE_MIN_WIDTH_M:g} m wide and {rules.OPEN_SPACE_MIN_POCKET_SQM:g} m²",
        Basis.LEGAL_RULE, rules.OPEN_SPACE_CLAUSE,
        ("rules.OPEN_SPACE_MIN_FRACTION", "rules.OPEN_SPACE_MIN_WIDTH_M",
         "rules.OPEN_SPACE_MIN_POCKET_SQM"),
    ),
    Constraint(
        "Open space", "The site area the 10% is taken of.",
        "the larger of the net and the gross", Basis.UNRESOLVED_INTERPRETATION,
        rules.OPEN_SPACE_CLAUSE,
        note="The text says 'total site area' without saying gross or net; the layout meets "
             "the larger so it passes either way, and the checker tests both.",
        settles="A sanctioned plan's tot-lot share and the site area it was taken of.",
    ),
    Constraint(
        "Open space", "A tot-lot pocket much bigger than what is still needed is cut down, a "
                      "little over, so the rest stays free for facilities and bays.",
        f"cut when {grounds.TRIM_ABOVE:g} x what is needed; cut to "
        f"{grounds.TRIM_MARGIN:g} x it", Basis.ENGINE_DESIGN_ASSUMPTION, "none (grounds._trim)",
        ("grounds.TRIM_ABOVE", "grounds.TRIM_MARGIN"),
        note="The piece kept must still be a pocket the rule accepts; the 0.98 width test in "
             "_trim is the same tolerance as findings.narrower_than.",
        settles="Nothing: a search choice that only moves where the tot-lot is drawn.",
    ),
    Constraint(
        "Open space", "The green planting strip inside the boundary, where the setback is at "
                      "least this.",
        f"{rules.PERIPHERAL_GREEN_STRIP_M:g} m wide from a "
        f"{rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M:g} m setback", Basis.LEGAL_RULE,
        rules.PERIPHERAL_GREEN_STRIP_CLAUSE,
        ("rules.PERIPHERAL_GREEN_STRIP_M", "rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M"),
    ),
    Constraint(
        "Open space", "No building within a water body's buffer, by its class.",
        ", ".join(f"{k.replace('_', ' ')} {v:g} m" for k, v in rules.WATER_BUFFER_M.items()),
        Basis.LEGAL_RULE, rules.WATER_BUFFER_CLAUSE, ("rules.WATER_BUFFER_M",),
    ),
    Constraint(
        "Open space", "The buffer is measured from the lines the surveyor drew, and towers keep "
                      "a road's width off it so the loop road can run along it.",
        f"from the drawn lines; towers {rules.INTERNAL_ROAD_M:g} m further off",
        Basis.UNRESOLVED_INTERPRETATION, rules.WATER_BUFFER_CLAUSE,
        note="A drawn channel does not show a nala's defined width (the class is a site input). "
             "The extra road's width is the engine's, so the loop can pass; no crossing over "
             "water is drawn.",
        settles="A sanctioned plan beside a nala or lake: which class, and what it deducted.",
    ),
    # ----------------------------------------------------------------- roads
    Constraint(
        "Roads", "Internal roads of a group development scheme, and the cul-de-sac form.",
        f"main approach {rules.MAIN_APPROACH_ROAD_M[0]:g}-{rules.MAIN_APPROACH_ROAD_M[1]:g} m; "
        f"other and looped roads {rules.INTERNAL_ROAD_M:g} m; cul-de-sacs "
        f"{rules.CUL_DE_SAC_WIDTH_M:g} m for {rules.CUL_DE_SAC_LENGTH_M[0]:g}-"
        f"{rules.CUL_DE_SAC_LENGTH_M[1]:g} m with a {rules.CUL_DE_SAC_HEAD_RADIUS_M:g} m head",
        Basis.LEGAL_RULE, rules.INTERNAL_ROAD_CLAUSE,
        ("rules.MAIN_APPROACH_ROAD_M", "rules.INTERNAL_ROAD_M", "rules.CUL_DE_SAC_WIDTH_M",
         "rules.CUL_DE_SAC_LENGTH_M", "rules.CUL_DE_SAC_HEAD_RADIUS_M", "access.ROAD_M",
         "towers.ROAD_M", "grounds.ROAD_M"),
    ),
    Constraint(
        "Roads", "The main approach road is drawn at the least of the 9 to 18 m the order gives.",
        _m(access.APPROACH_M), Basis.UNRESOLVED_INTERPRETATION, rules.INTERNAL_ROAD_CLAUSE,
        ("access.APPROACH_M",),
        note="The order gives no test for where in 9 to 18 m a main approach road falls; the "
             "report says the authority may ask for more.",
        settles="The main approach road on a sanctioned group development plan.",
    ),
    Constraint(
        "Roads", "Rule 8(m) roads are drawn on every site, without testing the 4,000 m² campus "
                 "threshold of rule 2(c).", "always", Basis.UNRESOLVED_INTERPRETATION,
        "G.O.168 rule 2(c) (a campus of 4,000 m² or more with apartment blocks is a Group "
        "Development Scheme); rule 8(m)",
        note="Every high-rise site this engine has seen is above 4,000 m²; a smaller one would "
             "be given 8(m) roads it may not need. The 4,000 m² is not in rules.py.",
        settles="A sanctioned high-rise plan under 4,000 m², and its roads.",
    ),
    Constraint(
        "Roads", "A block above this height opens onto an internal road, not a pathway.",
        _m(rules.PATHWAY_MAX_BLOCK_HEIGHT_M), Basis.UNRESOLVED_INTERPRETATION,
        rules.PATHWAY_CLAUSE, ("rules.PATHWAY_MAX_BLOCK_HEIGHT_M",),
        note="Rule 8(l) allows 6 m pathways for blocks up to 12 m; read the other way, a taller "
             "block needs a road. Every tower the layout places touches one.",
        settles="A sanctioned high-rise plan whose blocks are reached only by pathways.",
    ),
    Constraint(
        "Roads", "Minimum driveway width, where one is drawn; never counted as an internal road.",
        _m(rules.DRIVEWAY_MIN_WIDTH_M), Basis.LEGAL_RULE, rules.DRIVEWAY_CLAUSE,
        ("rules.DRIVEWAY_MIN_WIDTH_M",),
    ),
    Constraint(
        "Roads", "Where the roads go: a loop road just inside the green strip ringing the "
                 "towers' land, a road in every corridor between tower columns from loop to "
                 "loop, towers inset the Table IV setback or the strip plus the road.",
        f"loop {access.ROAD_M:g} m inside the strip; corridor = max(setback, "
        f"{access.ROAD_M:g} m); inset = max(setback, strip + {access.ROAD_M:g} m)",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (access.tower_inset, grounds.frame)",
        note="One way to meet 8(m) with no dead end; a firm may run its roads otherwise. The "
             "firm's Dhulapally drawing runs 7 m driveways instead.",
        settles="The firm's own road pattern, once set as a standard; the sanctioned plans.",
    ),
    Constraint(
        "Roads", "The towers' land keeps nothing narrower than two turning radii and rounds its "
                 "corners to one, so the loop can always turn; a narrow arm is left to open "
                 "space.", f"opened by {access.R_OUT:g} m", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (grounds.frame: land.buffer(-R_OUT).buffer(R_OUT))",
        note="Derived from the 9 m turning radius, but the choice to shape the land this way is "
             "the engine's.",
        settles="Nothing: a search choice; a sanctioned plan with towers in a narrow arm would "
                "show it costs flats.",
    ),
    Constraint(
        "Roads", "Where the entrance is tried along the access side, and how far the approach "
                 "may run to reach the loop.",
        f"at {', '.join(f'{p:g}' for p in access.ENTRANCE_POSITIONS)} of the side without a "
        f"loop; every {access.ENTRANCE_STEP_M:g} m with one; approach up to "
        f"{access.APPROACH_MAX_M:g} m deep; joined to the loop by "
        f"{access.LOOP_OVERLAP_SQM:g} m² of overlap; gate {rules.PERIPHERAL_GREEN_STRIP_M:g} m "
        "deep (1 m with no strip)", Basis.ENGINE_DESIGN_ASSUMPTION, "none (access.entrance)",
        ("access.ENTRANCE_POSITIONS", "access.ENTRANCE_STEP_M", "access.APPROACH_MAX_M",
         "access.LOOP_OVERLAP_SQM"),
        note="A side 'faces' the named compass point within 45 degrees (access._faces); the "
             "plot's straight runs are found with geometry.straight_runs's 3 degree tolerance.",
        settles="The firm's preference for where its gate goes; the sanctioned plans.",
    ),
    Constraint(
        "Roads", "A road's two ends, and what counts as joining the network or touching a road.",
        f"ends {access.END_M:g} m deep; joined within {access.TOUCH_M:g} m; a block or ramp "
        f"within {towers.TOUCH_M:g} m of a road opens onto it", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (access.through_roads, towers.corridor_roads, access_checks)",
        ("access.END_M", "access.TOUCH_M", "towers.TOUCH_M", "access_checks.TOUCH_M"),
        note="Drawing tolerances for 'joins' and 'on a road'.",
        settles="Nothing: measurement tolerances.",
    ),
    # ----------------------------------------------------------------- fire access
    Constraint(
        "Fire access", "Motorable open space on all sides of a high-rise, the turning radius, "
                       "the entrance, the street join and the dead end.",
        f"{rules.FIRE_TENDER_MIN_WIDTH_M:g} m on all sides; {rules.FIRE_TURNING_RADIUS_M:g} m "
        f"turning radius; entrance {rules.GATE_MIN_WIDTH_M:g} m wide and "
        f"{rules.ENTRANCE_CLEAR_HEIGHT_M:g} m clear; the street joins one of "
        f"{rules.FIRE_STREET_JOIN_M:g} m; no dead end above {rules.DEAD_END_MAX_HEIGHT_M:g} m",
        Basis.LEGAL_RULE, f"{rules.FIRE_ACCESS_CLAUSE}; {rules.GATE_CLAUSE}; "
        f"{rules.FIRE_STREET_CLAUSE}; {rules.DEAD_END_CLAUSE}",
        ("rules.FIRE_TENDER_MIN_WIDTH_M", "rules.FIRE_TURNING_RADIUS_M", "rules.GATE_MIN_WIDTH_M",
         "rules.ENTRANCE_CLEAR_HEIGHT_M", "rules.FIRE_STREET_JOIN_M", "rules.DEAD_END_MAX_HEIGHT_M",
         "access.LANE_M", "access.R_OUT", "access_checks.LANE_M"),
        note="NBC 2016 Part 3 4.6, brought in by rule 15(b)(iv); read from the page images. The "
             "45 t surface is a specification and is reported UNVERIFIED.",
    ),
    Constraint(
        "Fire access", "Where the 9 m turning radius is measured, and the clear band beside each "
                       "face of a block that follows from it.",
        f"the outer edge of the {access.LANE_M:g} m lane (inner edge {access.R_IN:g} m), so "
        f"{access.FIRE_BAND_M:.2f} m clear beside each face", Basis.UNRESOLVED_INTERPRETATION,
        rules.FIRE_ACCESS_CLAUSE,
        ("access.R_IN", "access.FIRE_BAND_M", "access_checks.FIRE_BAND_M"),
        note="The order gives the 9 m, not where it is measured. The outer-edge reading is the "
             "one that fits the state's 7 m minimum setback and the 7 m rule 13(c)(vii) keeps "
             "for fire vehicles; a 9 m centreline would need 7.76 m. The 6.88 m is derived from "
             "this reading and is nowhere written in the rule. Kept as the conservative test.",
        settles="The fire NOC of a sanctioned high-rise, or the layout agreed with the Chief "
                "Fire Officer, which 4.6(c) asks for.",
    ),
    Constraint(
        "Fire access", "How a turn is drawn and judged: the sector's resolution, how much of it "
                       "may fall outside free ground before the turn is blocked, and how sharp a "
                       "bend must be to count as a turn.",
        f"{access.SECTOR_STEPS} chords; {access.SECTOR_TOLERANCE_SQM:g} m² outside allowed; "
        f"bends under {access.MIN_TURN_DEG:g} degrees are straight",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (access.sector, access.blocked, access._corners)",
        ("access.SECTOR_STEPS", "access.SECTOR_TOLERANCE_SQM", "access.MIN_TURN_DEG"),
        note="Drawing tolerances; the 0.05 m healing of hairline cracks between road pieces "
             "(access.healed) is the same kind.",
        settles="Nothing: measurement tolerances.",
    ),
    # ----------------------------------------------------------------- amenities
    Constraint(
        "Amenities", "From this many units, common amenities go in a block of their own.",
        f"{rules.AMENITY_MIN_UNITS} units", Basis.LEGAL_RULE, rules.AMENITY_CLAUSE,
        ("rules.AMENITY_MIN_UNITS",),
    ),
    Constraint(
        "Amenities", "The amenities (club house) area as a share of the built-up area, the "
                     "block itself counted.",
        f"{_pct(rules.AMENITY_MIN_BUILT_UP_FRACTION)} planned as a minimum, no cap applied; "
        f"the 2016 wording's cap of {rules.AMENITY_CAP_SQFT_2016:,.0f} sft is reported only",
        Basis.UNRESOLVED_INTERPRETATION, rules.AMENITY_CLAUSE,
        ("rules.AMENITY_MIN_BUILT_UP_FRACTION", "rules.AMENITY_CAP_SQFT_2016",
         "grounds.AMENITY_SHARE"),
        note="The 3% minimum is the 2012 wording, kept as the planning target and "
             "ASSUMED_FOR_TEST. G.O.Ms.No.7 of 2016 rewrote the clause as 'upto 3% of the total "
             "built up area (or) 50,000 Sft. whichever is lower', which may make 3% a ceiling "
             "and adds a cap (it binds above about 1.67 million sft built-up). Not settled "
             "law: the checker labels its finding so, and reports a block above the cap "
             "UNVERIFIED.",
        settles="The amenities area on a sanctioned plan of 100 units or more against its "
                "built-up area, or the architect's reading of the 2016 wording.",
    ),
    Constraint(
        "Amenities", "The club house footprint's proportion, and its storeys, when the firm "
                     "gives no size.",
        f"{grounds.CLUB_ASPECT:g}:1; {_lr['club_house_floors'].default} storeys",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (grounds._club_item; layout.LayoutRequest)",
        ("grounds.CLUB_ASPECT", "layout.LayoutRequest.club_house_floors"),
        note="A firm gives its club house as club_house_sqm on the request; the storeys are "
             "not yet a workspace standard.",
        settles="The firm's club house drawings.",
    ),
    Constraint(
        "Amenities", "Walking room kept round the club house, the ramp and each facility.",
        _m(grounds.CLEARANCE_M), Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (grounds, site_amenities)", ("grounds.CLEARANCE_M", "site_amenities.CLEARANCE_M"),
        settles="The firm's site plans.",
    ),
    Constraint(
        "Amenities", "The facilities (pool, courts, play area, cabin) and their sizes.",
        "the firm's list", Basis.FIRM_STANDARD,
        "the firm's amenities file (site_amenities.AmenityLibrary), named in the workspace",
        note="Sizes are the firm's, never law; one with no room is named, never forced in. The "
             "example file is illustrative.",
    ),
    Constraint(
        "Amenities", "How finely a facility's position is searched.",
        f"every {site_amenities.SCAN_STEP_M:g} m", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (site_amenities._fit)", ("site_amenities.SCAN_STEP_M",),
        settles="Nothing: a search step.",
    ),
    # ----------------------------------------------------------------- parking
    Constraint(
        "Parking", "Parking area as a share of the total built-up area (Table V row 4).",
        f"{rules.PARKING_PERCENT_GHMC:g}% inside GHMC or anywhere in CURE; "
        f"{rules.PARKING_PERCENT_ELSEWHERE:g}% elsewhere", Basis.LEGAL_RULE,
        f"{rules.PARKING_CLAUSE}; {rules.CURE_RULES_CLAUSE}",
        ("rules.PARKING_PERCENT_GHMC", "rules.PARKING_PERCENT_ELSEWHERE"),
    ),
    Constraint(
        "Parking", "When whose rules apply is not settled, the stricter GHMC column is planned.",
        f"{rules.PARKING_PERCENT_GHMC:g}% until the jurisdiction is confirmed",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (parking.parking_percent)",
        note="A conservative policy, so a PASS holds either way; a layout short only at 30% is "
             "reported UNVERIFIED, not FAIL.",
        settles="The authority and CURE answers, confirmed (site inputs).",
    ),
    Constraint(
        "Parking", "What counts as parking provided: the stilt less its cores, the surface bays "
                   "laid out, and each cellar level less its cores, the ramp and the utilities "
                   "share.", "stilt + surface + cellars, as measured",
        Basis.UNRESOLVED_INTERPRETATION, "G.O.168 rule 13(b); Table V",
        note="Rule 13(b) names the stilt, the open space over and above the setbacks, and "
             "cellars; what is deducted from each is the engine's reading. Podium parking is "
             "unsupported.",
        settles="The parking statement on a sanctioned plan.",
    ),
    Constraint(
        "Parking", "Visitors' parking share, read as parking at ground level.",
        f"{_pct(rules.VISITOR_PARKING_FRACTION)} of the Table V area", Basis.LEGAL_RULE,
        rules.VISITOR_PARKING_CLAUSE, ("rules.VISITOR_PARKING_FRACTION",),
        note="The share is the order's; reading 'on ground' as the stilt or the surface is an "
             "interpretation the inventory records.",
    ),
    Constraint(
        "Parking", "Cellar ramps: the single ramp's width, the pair's, and the gradient.",
        f"one of {rules.RAMP_SINGLE_MIN_WIDTH_M:g} m or two of {rules.RAMP_PAIR_MIN_WIDTH_M:g} m "
        f"at 1 in {round(1 / rules.RAMP_MAX_GRADIENT)}", Basis.LEGAL_RULE, rules.RAMP_CLAUSE,
        ("rules.RAMP_SINGLE_MIN_WIDTH_M", "rules.RAMP_PAIR_MIN_WIDTH_M", "rules.RAMP_MAX_GRADIENT"),
        note="The layout draws the single ramp, outside every setback (stricter than the side "
             "and rear allowance) and out of the fire lanes, with its top on a road.",
    ),
    Constraint(
        "Parking", "How far a cellar keeps from the property line, by site size and depth.",
        ", ".join(f"{m:g} m up to {s:,.0f} m²" if s != float('inf') else f"{m:g} m above that"
                  for s, m in rules.CELLAR_SETBACK_BY_SITE_SQM)
        + f"; {rules.CELLAR_EXTRA_SETBACK_PER_LEVEL_M:g} m more for every cellar beyond the "
        "first", Basis.LEGAL_RULE, rules.CELLAR_SETBACK_CLAUSE,
        ("rules.CELLAR_SETBACK_BY_SITE_SQM", "rules.CELLAR_EXTRA_SETBACK_PER_LEVEL_M"),
    ),
    Constraint(
        "Parking", "The extra cellar setback is applied to every level, not only the deeper "
                   "ones.", "every level keeps the deepest's setback",
        Basis.UNRESOLVED_INTERPRETATION, rules.CELLAR_SETBACK_CLAUSE,
        note="The cellars are one box, which is the stricter reading.",
        settles="The cellar section on a sanctioned plan with two or more cellars.",
    ),
    Constraint(
        "Parking", "The most of a cellar that may hold utilities rather than cars.",
        f"up to {_pct(rules.CELLAR_UTILITIES_MAX_FRACTION)}", Basis.LEGAL_RULE,
        rules.CELLAR_UTILITIES_CLAUSE, ("rules.CELLAR_UTILITIES_MAX_FRACTION",),
    ),
    Constraint(
        "Parking", "The share of each cellar the firm keeps for utilities; the engine takes the "
                   "whole allowance until the firm sets its own.",
        f"{_ws['cellar_utilities_pct'].default:g}%", Basis.FIRM_STANDARD, _WORKSPACE,
        ("intake.WorkspaceDefaults.cellar_utilities_pct",
         "layout.LayoutRequest.cellar_utilities_pct",
         "parking.ParkingStandards.utilities_fraction"),
        note="Taken in full so the parking a cellar gives is not overstated; ASSUMED_FOR_TEST "
             "until the firm sets it.",
    ),
    Constraint(
        "Parking", "A cellar storey's height, which sets the ramp's length (height x 8).",
        _m(_ws["cellar_floor_height_m"].default), Basis.FIRM_STANDARD, _WORKSPACE,
        ("intake.WorkspaceDefaults.cellar_floor_height_m",
         "layout.LayoutRequest.cellar_floor_height_m",
         "parking.ParkingStandards.cellar_floor_height_m"),
        note="ASSUMED_FOR_TEST until the firm sets it.",
    ),
    Constraint(
        "Parking", "The most cellar levels the search will dig; no order limits the number.",
        f"{_ws['max_cellars'].default} levels", Basis.FIRM_STANDARD, _WORKSPACE,
        ("intake.WorkspaceDefaults.max_cellars", "layout.LayoutRequest.max_cellars",
         "parking.ParkingStandards.max_cellars"),
        note="A search bound, not a rule; ASSUMED_FOR_TEST until the firm sets it.",
    ),
    Constraint(
        "Parking", "The size of a parking bay and its aisle, used to lay out the surface bays "
                   "and to count the cars each floor holds.",
        f"{parking.BAY_WIDTH_M:g} x {parking.BAY_DEPTH_M:g} m bays, {parking.AISLE_M:g} m "
        f"aisles; {parking.LAID_OUT_SQM_PER_CAR:g} m² per car laid out (a bay and half its "
        "aisle)", Basis.ENGINE_DESIGN_ASSUMPTION, "none (parking.py)",
        ("parking.BAY_WIDTH_M", "parking.BAY_DEPTH_M", "parking.AISLE_M",
         "parking.LAID_OUT_SQM_PER_CAR"),
        note="No order we hold gives a bay or aisle size; these are the engine's parking "
             "standards. A firm's own go in parking.ParkingStandards once it sets them.",
        settles="The bay size on the firm's drawings, or a primary source that fixes one.",
    ),
    Constraint(
        "Parking", "The share of a parking floor that bays and aisles are expected to fill, for "
                   "sizing the cellars before the cars are counted.",
        _pct(grounds.LAYOUT_SHARE), Basis.ENGINE_DESIGN_ASSUMPTION, "none (grounds._attempt)",
        ("grounds.LAYOUT_SHARE",),
        note="Only a first estimate: the cars are then counted on every floor and a level added "
             "or taken away until the count meets the need.",
        settles="Nothing that changes a result: the count decides.",
    ),
    Constraint(
        "Parking", "The quick ranking's allowance for the club house and the ramp when it "
                   "checks by area alone that the tot-lot, club and ramp fit the pockets.",
        "club footprint x 1.15; ramp x 1.3", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (grounds._attempt, quick=True)",
        note="Inline literals; the shortlisted placements are then laid exactly, so these only "
             "rank, never pass, a layout.",
        settles="Nothing that changes a result: the exact laying decides.",
    ),
    Constraint(
        "Parking", "The most surface bays drawn, and how finely a ramp's position is searched.",
        f"{parking.MAX_BAYS} bays; every {parking.RAMP_STEP_M:g} m along a road edge",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (parking.surface_bays, parking.place_ramp)",
        ("parking.MAX_BAYS", "parking.RAMP_STEP_M"),
        settles="Nothing: search bounds.",
    ),
    # ----------------------------------------------------------------- towers
    Constraint(
        "Towers", "The firm's flats: each type's frontage, depth and sale area; the core width; "
                  "the corridor width; flats per core per side.",
        f"the flat library; corridor {_fl['corridor_width_m'].default:g} m and "
        f"{_fl['flats_per_core_per_side'].default} flats per core per side when the file leaves "
        "them out", Basis.FIRM_STANDARD, _LIBRARY,
        ("library.FlatLibrary.corridor_width_m", "library.FlatLibrary.flats_per_core_per_side"),
        note="A library sized from the site's own plan leaks the answer; an acceptance run uses "
             "flats measured from another project. The example library is illustrative.",
    ),
    Constraint(
        "Towers", "Floor-to-floor height, the stilt's height, and the common-area loading on "
                  "the area statement.",
        f"{_ws['floor_height_m'].default:g} m; stilt {_ws['stilt_height_m'].default:g} m; "
        f"loading {_ws['common_area_pct'].default:g}%", Basis.FIRM_STANDARD, _WORKSPACE,
        ("intake.WorkspaceDefaults.floor_height_m", "intake.WorkspaceDefaults.stilt_height_m",
         "intake.WorkspaceDefaults.common_area_pct", "layout.LayoutRequest.floor_height_m",
         "layout.LayoutRequest.stilt_height_m", "layout.LayoutRequest.common_area_pct"),
        note="ASSUMED_FOR_TEST until the firm sets them.",
    ),
    Constraint(
        "Towers", "The longest block the firm builds, if it has one; else lengths are explored.",
        "none set: whole stretches, "
        + " and ".join(f"{cap:g} m" for cap in layout.EXPLORED_TOWER_LENGTHS_M if cap)
        + " are all tried", Basis.FIRM_STANDARD, f"{_WORKSPACE}, max_tower_length_m",
        ("layout.EXPLORED_TOWER_LENGTHS_M",),
        note="No order limits a block's length since G.O.Ms.No.65 of 2019; the two shorter caps "
             "explored are the engine's choice of what to try.",
    ),
    Constraint(
        "Towers", "The fewest flats per side a tower may have.",
        f"{_lr['min_flats_per_side'].default}", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (layout.LayoutRequest)", ("layout.LayoutRequest.min_flats_per_side",),
        note="A smaller block is not composed; not yet a workspace standard.",
        settles="The firm's smallest block.",
    ),
    Constraint(
        "Towers", "Which directions, column offsets and placements are searched, and how many "
                  "are laid exactly.",
        f"along and across the plot's three longest edges (directions over 5 degrees apart); "
        f"offsets every {layout.SWEEP_STEP_M:g} m across one pitch; the best "
        f"{layout.SHORTLIST} placements (or 3 per option asked) laid exactly",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (towers.orientations, layout._rank, _shortlist)",
        ("layout.SWEEP_STEP_M", "layout.SHORTLIST"),
        note="Hundreds of placements are ranked by area; only the shortlist reaches the checker.",
        settles="Nothing: search breadth; more search can only add options.",
    ),
    Constraint(
        "Towers", "What makes two layouts one idea: as many towers running the same way on "
                  "mostly the same ground.",
        f"directions within {layout.ANGLE_FAMILY_DEG:g} degrees; tower ground overlapping by "
        f"{_pct(layout.SAME_IDEA_OVERLAP)} or more", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (layout.same_idea, layout._massing)",
        ("layout.ANGLE_FAMILY_DEG", "layout.SAME_IDEA_OVERLAP"),
        settles="Nothing: how the options are chosen for variety, not whether one passes.",
    ),
    Constraint(
        "Towers", "How many options are returned.", f"{_lr['options'].default}",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (layout.LayoutRequest)",
        ("layout.LayoutRequest.options",), settles="Nothing: the architect asks for more.",
    ),
    # ----------------------------------------------------------------- tolerances
    Constraint(
        "Tolerances", "Drawing and measurement tolerances: a hair between pieces drawn to meet, "
                      "the overlap or shortfall that counts as a real one, and the floating "
                      "point epsilon of the floors calculator.",
        f"{access.EPS_M:g} m geometry epsilon; {access_checks.OVERLAP_SQM:g} m² of overlap; "
        f"{parking_checks.AREA_SLACK_SQM:g} m² of area slack; {checks.WATER_OVERLAP_SQM:g} m² "
        f"inside a water buffer; widths tested 0.02 m under the rule; {max_floors._EPS:g} on "
        "a floor count", Basis.ENGINE_DESIGN_ASSUMPTION, "none",
        ("access.EPS_M", "towers.EPS_M", "grounds.EPS_M", "parking.EPS_M", "layout.EPS_M",
         "site_amenities.EPS_M", "access_checks.OVERLAP_SQM", "parking_checks.AREA_SLACK_SQM",
         "checks.WATER_OVERLAP_SQM", "max_floors._EPS"),
        note="findings.narrower_than calls a shape narrower when removing every part thinner "
             "than the width loses more than 2% of its area.",
        settles="Nothing: tolerances, all well under a drawing's precision.",
    ),
    # ----------------------------------------------------------------- site inputs
    Constraint(
        "Site", "The plot: its outline and net area, the gross area, and the land given up for "
                "road widening.", "per site", Basis.SITE_INPUT,
        "the survey (EXTRACTED) and the project file's net_plot_m, net_area and gross_area, "
        "with their status",
    ),
    Constraint(
        "Site", "The abutting road's legal width, how it is known, the side it runs along, "
                "whether it ends at the plot, and whether it joins a 12 m street.", "per site",
        Basis.SITE_INPUT,
        "the architect's answers (abutting_road with abutting_road_status, access_side, "
        "road_dead_end, street_joins_12m); the survey's measured_carriageway_m is reported "
        "beside it and never used by the rules",
        note="UNVERIFIED answers leave the dead end, the street join and any height above 30 m "
             "UNVERIFIED, never PASS.",
    ),
    Constraint(
        "Site", "Whose rules apply: the authority and whether the site is inside CURE.",
        "per site", Basis.SITE_INPUT, "the architect's answers (authority, inside_cure)",
        note="Unsettled, parking is planned to the GHMC column (see Parking).",
    ),
    Constraint(
        "Site", "Each water body the survey draws: its class and the colour or layer it is "
                "drawn in.", "per site", Basis.SITE_INPUT, "the project file's site.water",
    ),
    Constraint(
        "Site", "Site coordinates, for the airport and Air Force height limits.", "per site",
        Basis.SITE_INPUT, "the project file's site_coordinates",
        note="Without them the airport height is UNVERIFIED and nothing else is blocked.",
    ),
    Constraint(
        "Site", "The brief: floors above the stilt (or 'max'), the unit mix, whether a club "
                "house is wanted and its size if the firm fixes it.", "per site",
        Basis.SITE_INPUT, "the architect's answers (layout.floors, unit_mix, club_house, "
        "club_house_sqm, maximise)",
        note="'max' means every height from one above the legal limit down is tried.",
    ),
    # ----------------------------------------------------------------- not generation
    Constraint(
        "Not used by generation", "TDR: the band that needs it on a mid-sized plot, and the "
                                  "extra floors it buys on a large one by road width.",
        f"{rules.TDR_BAND_M[0]:g}-{rules.TDR_BAND_M[1]:g} m on "
        f"{rules.TDR_PLOT_RANGE_SQM[0]:,.0f}-{rules.TDR_PLOT_RANGE_SQM[1]:,.0f} m²; up to "
        + ", ".join(f"{n} floors on {w:g} m"
                    for w, n in reversed(rules.TDR_EXTRA_FLOORS_BY_ROAD_M))
        + f" above {rules.TDR_EXTRA_FLOORS_ABOVE_PLOT_SQM:,.0f} m²", Basis.LEGAL_RULE,
        f"{rules.TDR_BAND_CLAUSE}; {rules.TDR_EXTRA_FLOORS_CLAUSE}",
        ("rules.TDR_BAND_M", "rules.TDR_PLOT_RANGE_SQM", "rules.TDR_EXTRA_FLOORS_BY_ROAD_M",
         "rules.TDR_EXTRA_FLOORS_ABOVE_PLOT_SQM"),
        note="Shown by the floors calculator beside its answer, never in a layout: an option the "
             "owner buys. The 40, 60 and 80 ft roads are taken as Table IV's 12, 18 and 24 m.",
    ),
    Constraint(
        "Not used by generation", "The share of built-up area handed over by affidavit before "
                                  "the sanction is released.",
        _pct(rules.MORTGAGE_FRACTION), Basis.LEGAL_RULE, rules.MORTGAGE_CLAUSE,
        ("rules.MORTGAGE_FRACTION",),
        note="Defined and not applied: it decides which flats sell first, not the drawing.",
    ),
)


def by_basis(basis: Basis, registry: tuple[Constraint, ...] = REGISTRY) -> list[Constraint]:
    return [c for c in registry if c.basis is basis]


def counts(registry: tuple[Constraint, ...] = REGISTRY) -> dict[Basis, int]:
    return {basis: sum(c.basis is basis for c in registry) for basis in Basis}


def _summary(registry: tuple[Constraint, ...]) -> str:
    tally = ", ".join(f"{n} {basis.value}" for basis, n in counts(registry).items())
    return f"{len(registry)} constraints: {tally}."


def render_text(registry: tuple[Constraint, ...] = REGISTRY, only: Basis | None = None) -> str:
    """Grouped by basis, then by topic."""
    lines: list[str] = []
    for basis in Basis:
        if only is not None and basis is not only:
            continue
        group = by_basis(basis, registry)
        if not group:
            continue
        lines += ["", basis.value]
        for topic, items in groupby(group, key=lambda c: c.topic):
            lines.append(f"  {topic}")
            for c in items:
                lines.append(f"    - {c.what}")
                lines.append(f"        value:   {c.value}")
                lines.append(f"        source:  {c.source}")
                if c.symbols:
                    lines.append(f"        code:    {', '.join(c.symbols)}")
                if c.note:
                    lines.append(f"        note:    {c.note}")
                if c.settles:
                    lines.append(f"        settles: {c.settles}")
    return "\n".join([*lines, "", _summary(registry)]).lstrip("\n")


def render_markdown(registry: tuple[Constraint, ...] = REGISTRY) -> str:
    def cell(text: str) -> str:
        return text.replace("|", "/")

    lines = ["| Basis | Topic | Constraint | Value | Source | Note / what settles it |",
             "|---|---|---|---|---|---|"]
    for c in registry:
        note = " ".join(p for p in (c.note, c.settles and f"Settled by: {c.settles}") if p)
        lines.append(" | ".join(["", *map(cell, (c.basis.value, c.topic, c.what, c.value,
                                                  c.source, note)), ""]).strip())
    return "\n".join([*lines, "", _summary(registry)])


def open_items(registry: tuple[Constraint, ...] = REGISTRY) -> list[Constraint]:
    """What is neither law, the firm's standard nor a site fact: the engine's readings and its
    own assumptions, for the acceptance report."""
    return [c for c in registry
            if c.basis in (Basis.UNRESOLVED_INTERPRETATION, Basis.ENGINE_DESIGN_ASSUMPTION)]
