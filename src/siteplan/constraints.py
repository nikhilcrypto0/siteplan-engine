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

Values are read from the modules that hold them, so this list cannot drift from the code.
`tests/test_constraints.py` holds every module under src/siteplan either to this audit or to an
exemption with its reason (rendering, survey reading, the model's transport, the command line):
a module in an audited package (legal, optimizer, validator, prototypes, adapters, contracts,
service) is audited without being named, and the test fails when a named number in an audited
module, or a numeric default on one of its request, standards or config models, has no entry
here. Inline literals cannot be caught that way: in the new stages the ones that shape a result
are named constants; in the prototype's own modules they are listed here by hand.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import groupby

from siteplan import (
    access,
    access_checks,
    checks,
    flat_import,
    geometry,
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
from siteplan.adapters import legacy_site
from siteplan.basis import Basis  # lives in basis.py so the contracts need not import this module
from siteplan.contracts import accounting as ledger
from siteplan.contracts import design_brief, prototype, resolved_rules, site_model
from siteplan.legal import frontage, widths
from siteplan.optimizer import floors as optimizer_floors
from siteplan.optimizer.search import (
    build,
    columns,
    fringe,
    network,
    parking_plan,
    road_graph,
    strategy,
)
from siteplan.optimizer.search import fit as search_fit
from siteplan.optimizer.search import ground as search_ground
from siteplan.optimizer.search import land as search_land
from siteplan.optimizer.search import layout as search_layout
from siteplan.prototypes import compose
from siteplan.prototypes import library as prototype_library
from siteplan.validator import (
    accounting,
    clubhouse,
    context,
    cross_checks,
    fire,
    land_checks,
    open_space,
    program,
    refusals,
    shapes,
)
from siteplan.validator import network as validator_network
from siteplan.validator import parking as validator_parking
from siteplan.validator import roads as validator_roads


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


def _share(fraction: float) -> str:
    """A share as a percentage that keeps its decimals: 0.005 is 0.5%, not 0%."""
    return f"{fraction * 100:g}%"


_setback_rows = ", ".join(f"{b.min_open_space_m:g} m up to {b.up_to_m:g} m" if b.up_to_m < 1000
                          else f"{b.min_open_space_m:g} m above {b.above_m:g} m"
                          for b in rules.TABLE_IV)
_road_rows = ", ".join(f"{b.min_road_m:g} m up to {b.up_to_m:g} m" if b.up_to_m < 1000
                       else f"{b.min_road_m:g} m above {b.above_m:g} m" for b in rules.TABLE_IV)
def _table_iii_by_row(describe) -> str:
    """Table III a row at a time, `describe` saying what one row's lines give."""
    rows = []
    for row in sorted({line.row for line in rules.TABLE_III}):
        lines = [line for line in rules.TABLE_III if line.row == row]
        first = lines[0]
        size = (f"above {first.above_sqm:,.0f} m²" if math.isinf(first.up_to_sqm)
                else f"under {first.up_to_sqm:,.0f} m²" if first.above_sqm == 0
                else f"{first.above_sqm:,.0f}-{first.up_to_sqm:,.0f} m²")
        rows.append(f"row {row} ({size}): {describe(lines)}")
    return "; ".join(rows)


_table_iii_heights = _table_iii_by_row(
    lambda lines: ", ".join(f"{t.up_to_m:g}{'**' if t.below else ''}" for t in lines) + " m")
_table_iii_sides = _table_iii_by_row(
    lambda lines: ", ".join("none" if t.side_m is None else f"{t.side_m:g}" for t in lines) + " m")
_front_edges = rules.TABLE_III_ROAD_UP_TO_M
_front_rows = ", ".join(
    f"{front:g} m for a road {where}" for front, where in zip(
        rules.TABLE_III[-1].front_m,
        [f"up to {_front_edges[0]:g} m",
         *(f"above {a:g} and up to {b:g} m" for a, b in zip(_front_edges, _front_edges[1:],
                                                           strict=False)),
         f"above {_front_edges[-1]:g} m"], strict=True))
_lr = layout.LayoutRequest.model_fields
_ws = intake.WorkspaceDefaults.model_fields
_fl = library.FlatLibrary.model_fields
_ps = parking.ParkingStandards()
_lim = strategy.Limits()
_mix = design_brief.Program.model_fields["mix_tolerance"].default
_own = ledger.OwnershipReconciliation.model_fields["tolerance"].default
_ledger = ledger.PartitionLedger.model_fields["tolerance"].default
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
             "not counted. Rule 5's heading calls the buildings below the class 'below 18m in "
             "height inclusive of Stilt / Parking Floor' (p.9), which leans to counting it, "
             "while rule 5(c) leaves the stilt out of Table III's own heights (not open). The "
             "floors calculator gives both answers. A test profile may set "
             "stilt_in_rule_height false; NBC's fire height (the 30 m dead-end limit) counts the "
             "stilt either way.",
        settles="A sanctioned stilt + N high-rise whose approved setback fits one reading only.",
    ),
    Constraint(
        "Height", "Where no limit stops the floor count (a road of 30 m or more), how high the "
                  "optimizer assesses counts.",
        f"up to {optimizer_floors.CEILING_M:g} m, the top of Table IV's last bounded row",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (optimizer.floors)", ("optimizer.floors.CEILING_M",),
        note="A search bound, not a rule: from a 30 m road Table IV sets no height limit. The "
             "figure is read from rules.TABLE_IV, so the bound follows the table.",
        settles="Nothing: a search bound; a firm that builds higher would raise it.",
    ),
    Constraint(
        "Setbacks", "The Table IV figure is kept on every side, the front included.",
        "column 4 all round", Basis.LEGAL_RULE, rules.FRONT_SETBACK_CLAUSE,
        note="Read on 2026-10-01 from p.17, clause (b), 'The Front setback shall be as per "
             "Table-III of rule-5 & Table-IV of rule-7 for Non High Rise & High Rise buildings "
             "respectively'; corrected on 2026-10-03 (A2): that sentence is rule 12(b), for "
             "'U' type commercial buildings with a central courtyard. The high-rise front is "
             "rule 7(a)(xi), p.14 (the clause now cited): the higher of column 4 and the Table "
             "III Building Line, which differs only for exactly 21 m on a road above 30 m "
             "(7.5 m, not 7 m); the legacy layout and checker keep column 4, and the bands "
             "carry the front.",
    ),
    Constraint(
        "Setbacks", "Whether internal roads, driveways and fire lanes may run inside the Table "
                    "IV setback band.",
        "no by default: the 9 m loop road runs outside the setback; a test profile may set "
        "circulation_in_setback", Basis.UNRESOLVED_INTERPRETATION,
        f"{rules.TABLE_IV_CLAUSE}; {rules.RAMP_CLAUSE} (7 m of setback 'for movement of "
        "fire-fighting vehicles')",
        note="Rule 13(c)(vii) suggests fire vehicles may move inside a setback, and the firm's "
             "Dhulapally drawing runs 7 m driveways inside 8 m setbacks. With the switch on, "
             "towers stand at the setback and the ring inside it is a perimeter lane, held to "
             "the 6 m fire lane and reported UNVERIFIED against 8(m)'s 9 m loop.",
        settles="The architect, or a sanctioned plan whose roads run inside the setback.",
    ),
    Constraint(
        "Setbacks", "The gap between two blocks of different heights is the larger block's "
                    "figure.", "the larger of the two", Basis.UNRESOLVED_INTERPRETATION,
        rules.BLOCK_SPACING_CLAUSE,
        note="The text asks for 'the open space mentioned in Col. 4' without saying which block "
             "sets it. The club house keeps the same gap from every tower. Two blocks below "
             "21 m are not open: rule 5(f)(xiii) says the tallest block's side setback. What "
             "a block below 21 m and a high-rise keep between them is open here too (rule "
             "8(j): Table III column 10 or Table IV column 4, 'as the case may be').",
        settles="A sanctioned plan with two blocks of different heights.",
    ),
    Constraint(
        "Setbacks", "Which stretches of the plot line face the access road, where a block's band "
                    "keeps its Building Line apart from its side setback (the full search and "
                    "the validator), and where the envelope lets a gate open.",
        f"a stretch whose outward side is within {geometry.FACING_DEG:g} degrees of the access "
        f"side ({geometry.FACING_DEG + geometry.DIAGONAL_SLOP_DEG:g} for a diagonal label such "
        f"as SW), the limit included; in the full search, within "
        f"{search_land.FACING_DOUBT_DEG:g} degree of either limit the larger of the two "
        "setbacks is kept",
        Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (geometry.faces, read by legal.frontage, optimizer.search.land.setback_land and "
        "validator.zones)",
        ("geometry.FACING_DEG", "geometry.DIAGONAL_SLOP_DEG",
         "optimizer.search.land.FACING_DOUBT_DEG"),
        note="One reading, in one place: the envelope's frontage (the access zones a gate may "
             "open in, the front zone and the frontage strip), the full search's setbacks and "
             "the validator's front all take it, so a diagonal label stands for either side it "
             "lies between everywhere; where the access side is not known the larger figure is "
             "kept all round. The legacy entrance (access._faces) and the road-widening strip "
             "(geometry.strip_along_side, which places the net plot itself) keep a strict 45 "
             "degrees for every label, so neither the regression results nor the net plot "
             "move.",
        settles="The architect's word on which edge is the frontage, or a sanctioned plan.",
    ),
    Constraint(
        "Height", "The tallest a building below high-rise may be, by plot size (Table III "
                  "column 4), the stilt left out.", _table_iii_heights, Basis.LEGAL_RULE,
        rules.TABLE_III_CLAUSE, ("rules.TABLE_III",),
        note="'**' is above 15 m and below 18 m, and needs a road of 12 m (rule 5(e)). Above a "
             "row's last height, and between 18 and 21 m, the orders read give no line: "
             "G.O.Ms.No.95 of 2026 allows 18-21 m on plots of 750-2,000 m² through TDR and gives "
             "no setback. Read from the page images of pp.9-10 on 2026-10-03.",
    ),
    Constraint(
        "Setbacks", "The Building Line, the front setback of a block below high-rise, by the "
                    "abutting road's legal width (Table III columns 5-9).", _front_rows,
        Basis.LEGAL_RULE, rules.TABLE_III_CLAUSE, ("rules.TABLE_III_ROAD_UP_TO_M",),
        note="The figures from 300 m² up; smaller plots have their own (1.5 and 3 m, or 2 to 6 m "
             "on rows 1 to 4). A high-rise's front is the higher of Table IV column 4 and this "
             f"line ({rules.BUILDING_LINE_HIGH_RISE_CLAUSE}).",
    ),
    Constraint(
        "Setbacks", "The setback on the other sides of a block below high-rise, and the gap "
                    "between two such blocks, by plot size and height (Table III column 10).",
        _table_iii_sides, Basis.LEGAL_RULE,
        f"{rules.TABLE_III_CLAUSE}; {rules.NON_HIGH_RISE_SPACING_CLAUSE}",
        note="Measured on the net plot (rule 5(f)(ii)). The gap is the taller block's figure.",
    ),
    Constraint(
        "Road", "A road width given in feet is reckoned as the order's round metres.",
        ", ".join(f"{feet} ft = {metres:g} m" for metres, feet in rules.ROAD_WIDTH_FEET),
        Basis.LEGAL_RULE, rules.ROAD_WIDTH_CONVERSION_CLAUSE, ("rules.ROAD_WIDTH_FEET",),
        note="Rule 5(f)(xvii) reckons these 'for the road widths only'. The order's conversion is "
             "0.3 m a foot; the engine's own is 0.3048.",
    ),
    Constraint(
        "Road", "How close a road width has to be to a listed number of feet to be reckoned as "
                "the order's metres.", _m(rules.ROAD_FEET_TOLERANCE_M),
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (the engine's own)",
        ("rules.ROAD_FEET_TOLERANCE_M",),
        note="So that a road the architect gave as 60 ft (18.288 m) is the order's 18 m, and one "
             "typed as 18.3 m stays above it.",
        settles="The project's own record of the unit the architect gave the width in.",
    ),
    Constraint(
        "Height", "A stilt floor's least height, and a mechanical parking floor's (rule 5(c)).",
        f"{_m(rules.STILT_MIN_HEIGHT_M)}; {_m(rules.MECHANICAL_PARKING_FLOOR_MIN_HEIGHT_M)}",
        Basis.LEGAL_RULE, rules.TABLE_III_STILT_CLAUSE,
        ("rules.STILT_MIN_HEIGHT_M", "rules.MECHANICAL_PARKING_FLOOR_MIN_HEIGHT_M"),
        note="Written for non-high-rise buildings; the stilt itself is left out of Table III's "
             "height. Not applied by generation or the checker.",
    ),
    Constraint(
        "Road", "Above 15 m and below 18 m, the road a block needs (the '**' lines of Table "
                "III).", _m(rules.TABLE_III_TOP_TIER_MIN_ROAD_M), Basis.LEGAL_RULE,
        rules.TABLE_III_TOP_TIER_CLAUSE, ("rules.TABLE_III_TOP_TIER_MIN_ROAD_M",),
    ),
    Constraint(
        "Road", "The road a block below high-rise needs by its use (Table II, category B), and "
                "a Group Development Scheme's (rule 8(b)).",
        f"{_m(rules.TABLE_II_B1_ROAD_M)} up to {rules.TABLE_II_B1_MAX_FLOORS} floors; "
        f"{_m(rules.TABLE_II_B2_ROAD_M)} for six floors, more than "
        f"{rules.TABLE_II_B2_UNITS_OVER} units, a group development scheme or up to 18 m; "
        f"{_m(rules.GROUP_DEVELOPMENT_MIN_ROAD_M)} for a Group Development Scheme",
        Basis.LEGAL_RULE, f"{rules.TABLE_II_CLAUSE}; {rules.GROUP_DEVELOPMENT_ROAD_CLAUSE}",
        ("rules.TABLE_II_B1_ROAD_M", "rules.TABLE_II_B1_MAX_FLOORS", "rules.TABLE_II_B2_ROAD_M",
         "rules.TABLE_II_B2_UNITS_OVER", "rules.GROUP_DEVELOPMENT_MIN_ROAD_M"),
        note="Table II counts floors and units, which ResolvedRules never holds: the resolver "
             "reads 'up to 5 floors' as up to 15 m, the line Table III draws. A scheme of more "
             "than 100 units needs 12 m whatever its height.",
    ),
    Constraint(
        "Road", "A 6 m pathway serves a block up to 12 m high (rule 8(l)); a sub-divided plot's "
                "independent access is 3.6 m, or 6 m for non-high-rise group housing "
                "(rule 4(f)).",
        f"{_m(rules.PATHWAY_WIDTH_M)}; {_m(rules.SUBDIVISION_PATHWAY_M[0])} and "
        f"{_m(rules.SUBDIVISION_PATHWAY_M[1])}", Basis.LEGAL_RULE,
        f"{rules.PATHWAY_CLAUSE}; {rules.SUBDIVISION_PATHWAY_CLAUSE}",
        ("rules.PATHWAY_WIDTH_M", "rules.SUBDIVISION_PATHWAY_M"),
    ),
    Constraint(
        "Setbacks", "The planting strips of a block below high-rise: along the frontage within "
                    "the front setback, and on a plot above 300 m² on the remaining sides.",
        f"{_m(rules.NON_HIGH_RISE_FRONTAGE_STRIP_M)} along the frontage; "
        f"{_m(rules.NON_HIGH_RISE_PERIPHERY_STRIP_M)} on the other sides above "
        f"{rules.NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM:g} m²", Basis.LEGAL_RULE,
        rules.NON_HIGH_RISE_GREEN_STRIP_CLAUSE,
        ("rules.NON_HIGH_RISE_FRONTAGE_STRIP_M", "rules.NON_HIGH_RISE_PERIPHERY_STRIP_M",
         "rules.NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM"),
        note="Within the setback, never added to it. A high-rise's strip is rule 7(viii)'s 2 m "
             "where the setback is 9 m or more. Not applied by generation or the checker.",
    ),
    Constraint(
        "Open space", "Organised open space on a residential plot above 750 m² (rule 5(f)(vi)).",
        f"{_pct(rules.NON_HIGH_RISE_OPEN_SPACE_FRACTION)} of the site above "
        f"{rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM:g} m²; pockets "
        f"{_m(rules.NON_HIGH_RISE_OPEN_SPACE_MIN_WIDTH_M)} wide and "
        f"{rules.NON_HIGH_RISE_OPEN_SPACE_MIN_POCKET_SQM:g} m²", Basis.LEGAL_RULE,
        rules.NON_HIGH_RISE_OPEN_SPACE_CLAUSE,
        ("rules.NON_HIGH_RISE_OPEN_SPACE_FRACTION", "rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM",
         "rules.NON_HIGH_RISE_OPEN_SPACE_MIN_WIDTH_M",
         "rules.NON_HIGH_RISE_OPEN_SPACE_MIN_POCKET_SQM"),
        note="A group development scheme and a high-rise site keep 10%. Not applied by "
             "generation or the checker.",
    ),
    Constraint(
        "Plot", "The corner of a plot of 750 m² and above earmarked for public utilities.",
        f"{rules.PUBLIC_UTILITY_AREA_M[0]:g} x {_m(rules.PUBLIC_UTILITY_AREA_M[1])}, from "
        f"{rules.PUBLIC_UTILITY_AREA_FROM_SQM:g} m²", Basis.LEGAL_RULE,
        rules.PUBLIC_UTILITY_AREA_CLAUSE,
        ("rules.PUBLIC_UTILITY_AREA_M", "rules.PUBLIC_UTILITY_AREA_FROM_SQM"),
        note="Not applied by generation or the checker.",
    ),
    Constraint(
        "Setbacks", "Setback a block below high-rise may move from one side to another (a design "
                    "option), and what a narrow plot may compensate in its front and rear.",
        f"{_m(rules.SETBACK_TRANSFER_300_TO_750_M)} on 300-750 m², "
        f"{_m(rules.SETBACK_TRANSFER_ABOVE_750_M)} above, keeping "
        f"{_m(rules.SETBACK_TRANSFER_MIN_OTHER_SIDE_M)}; narrow plots up to "
        f"{rules.NARROW_PLOT_MAX_SQM:g} m² four times as long as wide keep "
        f"{_m(rules.NARROW_PLOT_MIN_SIDE_M[0][1])} of side up to "
        f"{_m(rules.NARROW_PLOT_MIN_SIDE_M[0][0])}, {_m(rules.NARROW_PLOT_MIN_SIDE_M[1][1])} up to "
        f"{_m(rules.NARROW_PLOT_MIN_SIDE_M[1][0])}", Basis.LEGAL_RULE,
        f"{rules.SETBACK_TRANSFER_CLAUSE}; {rules.NARROW_PLOT_CLAUSE}",
        ("rules.SETBACK_TRANSFER_300_TO_750_M", "rules.SETBACK_TRANSFER_ABOVE_750_M",
         "rules.SETBACK_TRANSFER_MIN_OTHER_SIDE_M", "rules.NARROW_PLOT_MAX_SQM",
         "rules.NARROW_PLOT_LENGTH_TO_WIDTH", "rules.NARROW_PLOT_MIN_SIDE_M"),
        note="Never from the front. Not applied: every side keeps its full Table III figure.",
    ),
    Constraint(
        "Setbacks", "The concessions a block below high-rise may take when its owner surrenders "
                    "land for road widening, and the minimums TDR relaxation keeps.",
        "building line 6, 3 or 2 m for a road of 30 m or more, 18 m to under 30 m, under 18 m; "
        "side and rear 2, 2.5 or 3 m up to 12, 15 or 18 m", Basis.LEGAL_RULE,
        f"{rules.ROAD_WIDENING_NON_HIGH_RISE_CLAUSE}; {rules.TDR_NON_HIGH_RISE_SETBACK_CLAUSE}",
        ("rules.ROAD_WIDENING_NON_HIGH_RISE_BUILDING_LINE_M",
         "rules.ROAD_WIDENING_NON_HIGH_RISE_SIDE_REAR_M"),
        note="An option the owner takes in place of TDR or extra floors. Not applied.",
    ),
    Constraint(
        "Fire", "Residential buildings above this height need the Fire Services Department's "
                "prior clearance.", _m(rules.FIRE_CLEARANCE_RESIDENTIAL_ABOVE_M),
        Basis.LEGAL_RULE, rules.FIRE_CLEARANCE_CLAUSE,
        ("rules.FIRE_CLEARANCE_RESIDENTIAL_ABOVE_M",),
        note="The only figure the order gives for fire below 21 m. Rule 15(a)(i) gives none "
             f"({rules.NON_HIGH_RISE_NBC_CLAUSE}).",
    ),
    Constraint(
        "Setbacks", "Setbacks and cellars are measured from the net plot line, after the "
                    "road-widening strip.", "net plot line", Basis.LEGAL_RULE,
        rules.SETBACK_ON_NET_PLOT_CLAUSE,
        note="Rule 7(a)(iii) takes a widened high-rise site's 'corresponding minimum all round "
             "setbacks' on its net plot; rule 5 says the same for Table III.",
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
        note="Never applied as a pass: the text does not say 10% of what. The resolved rules "
             "(legal/resolve.py) call a site that surrendered land and falls short by less than "
             "this UNVERIFIED rather than failed.",
    ),
    Constraint(
        "Plot", "Drawing tolerances for the net plot: a survey outline this close to the stated "
                "net area is taken as the net plot, and a strip the architect describes may "
                "differ from the stated deduction by this much.",
        f"{runner.NET_AREA_TOLERANCE_SQM:g} m²; the larger of that and "
        f"{runner.STRIP_AREA_TOLERANCE:.0%} of the deduction; the site model refuses a net "
        f"outline more than {_share(site_model.NET_PLOT_TOLERANCE)} off the stated net area; "
        f"the adapter takes a net within {legacy_site.NET_GROSS_TOLERANCE_SQM:g} m² of the gross "
        "as no deduction", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (runner.load_plot, contracts.site_model, adapters.legacy_site)",
        ("runner.NET_AREA_TOLERANCE_SQM", "runner.STRIP_AREA_TOLERANCE",
         "contracts.site_model.NET_PLOT_TOLERANCE", "adapters.legacy_site.NET_GROSS_TOLERANCE_SQM"),
        note="The engine never places a strip from the area alone: without the strip's side "
             "and width, its outline or the net plot outline, the run stops and asks.",
        settles="Nothing: tolerances; the strip's location is a site input.",
    ),
    Constraint(
        "Plot", "How the envelope reports the land's widths: where a narrow region is split "
                "off, the widths it reports land narrower than, and the noise it ignores.",
        f"regions split below {widths.REGION_SPLIT_M:g} m; land narrower than "
        f"{', '.join(f'{w:g}' for w in widths.REPORTED_WIDTHS_M)} m reported; pieces under "
        f"{widths.MIN_REGION_SQM:g} m² and hairlines under {widths.HAIRLINE_M:g} m ignored; "
        f"corners sharper than 60 degrees cut (mitre limit {widths.MITRE_LIMIT:g}); the widest "
        f"circle's centre found to {widths.CENTRE_TOLERANCE_M:g} m",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (legal.widths)",
        ("legal.widths.REGION_SPLIT_M", "legal.widths.REPORTED_WIDTHS_M",
         "legal.widths.MIN_REGION_SQM", "legal.widths.HAIRLINE_M", "legal.widths.MITRE_LIMIT",
         "legal.widths.CENTRE_TOLERANCE_M"),
        note="Reported, never judged: nothing removes land for being narrow. The split is about "
             "a tower's depth.",
        settles="Nothing: how the report groups the land; the optimizer decides what fits where.",
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
        f"{grounds.TRIM_MARGIN:g} x it; the piece cut keeps {_share(search_fit.TRIM_WIDE_SHARE)} "
        "of itself at the full width", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (grounds._trim, optimizer.search.fit._trim)",
        ("grounds.TRIM_ABOVE", "grounds.TRIM_MARGIN", "optimizer.search.fit.TRIM_ABOVE",
         "optimizer.search.fit.TRIM_MARGIN", "optimizer.search.fit.TRIM_WIDE_SHARE"),
        note="The piece kept must still be a pocket the rule accepts. The full search keeps its "
             "own copies; the legacy _trim writes the 0.98 inline, the same tolerance as "
             "findings.narrower_than.",
        settles="Nothing: a search choice that only moves where the tot-lot is drawn.",
    ),
    Constraint(
        "Open space", "When a facility stands on a piece of ground in the area accounting: a "
                      "soft facility mostly on an open-space pocket is the pocket's own ground.",
        f"more than {_pct(accounting.PLAY_SHARE)} of it", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (validator.accounting, optimizer.search.build, adapters.legacy_layout)",
        ("validator.accounting.PLAY_SHARE", "optimizer.search.build.ON_POCKET_SHARE",
         "adapters.legacy_layout.ON_GROUND_SHARE"),
        note="Whether a facility's ground counts as organised open space is the resolved rules', "
             "by its use and surface; this only says which ground it stands on, so the "
             "PartitionLedger counts it once. The validator also names the zone unused ground "
             "mostly lies in by the same share.",
        settles="Nothing that the rule decides: a way of counting ground once.",
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
        "Open space", "The distance, vertical and horizontal, a building keeps from an "
                      "electricity line.",
        f"{rules.ELECTRICAL_HT_CLEARANCE_M:g} m high-tension, "
        f"{rules.ELECTRICAL_LT_CLEARANCE_M:g} m low-tension", Basis.LEGAL_RULE,
        rules.ELECTRICAL_CLAUSE,
        ("rules.ELECTRICAL_HT_CLEARANCE_M", "rules.ELECTRICAL_LT_CLEARANCE_M"),
        note="Carried in ResolvedRules; the prototype's layout does not model it.",
    ),
    Constraint(
        "Open space", "The water buffer is measured from the lines the surveyor drew for the "
                      "water body, which stand in for its Full Tank Level or defined boundary.",
        "from the drawn lines", Basis.ENGINE_DESIGN_ASSUMPTION, "none (runner.load_water)",
        note="Rule 3(a)(ii) measures from the FTL or the defined boundary, which a survey rarely "
             "marks; a drawn channel's own width is kept inside the buffer.",
        settles="The FTL or defined boundary marked on the survey or by the irrigation "
                "department.",
    ),
    Constraint(
        "Open space", "Whether a road or a fire lane may run inside a water buffer.",
        f"not motorable: towers keep the {access.FIRE_BAND_M:.2f} m fire band clear of it",
        Basis.UNRESOLVED_INTERPRETATION, rules.WATER_BUFFER_CLAUSE,
        ("grounds.WATER_FIRE_CLEARANCE_M",),
        note="Rule 3(a)(ii) forbids buildings in the buffer and 3(a)(iii)(3) lets it count as "
             "open space; neither says whether vehicles may use it. The buffer, the Table IV "
             "setback and this clearance are a union, never added together.",
        settles="A sanctioned plan with a road or fire lane inside a water buffer, or HMDA's or "
                "the irrigation department's word.",
    ),
    Constraint(
        "Open space", "Beyond the fire band, towers keep the rest of a road's width off a water "
                      "buffer so the loop road runs along the water instead of ending at it.",
        f"{grounds.WATER_LOOP_ROAD_EXTRA_M:.2f} m more (a {rules.INTERNAL_ROAD_M:g} m road in "
        "all)", Basis.ENGINE_DESIGN_ASSUMPTION, "none (grounds.frame)",
        ("grounds.WATER_LOOP_ROAD_EXTRA_M",),
        note="The loop road is the engine's road pattern; a road stopping at the water would be "
             "a dead end rule 8(m) allows only as a cul-de-sac. Another pattern could drop it.",
        settles="The firm's road pattern beside water; the sanctioned plans.",
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
        "Roads", "The optimiser draws the main approach road at the least of the 9 to 18 m the "
                 "order allows, unless something requires more.",
        _m(access.APPROACH_M), Basis.ENGINE_DESIGN_ASSUMPTION, "none (access.APPROACH_M)",
        ("access.APPROACH_M",),
        note="The law is the 9 to 18 m range (the internal-roads entry); taking the minimum "
             "frees land for towers. The report says the authority may ask for more.",
        settles="The firm's or the authority's preferred approach width.",
    ),
    Constraint(
        "Roads", "Rule 8's internal roads and pathways apply to a Group Development Scheme: "
                 "residential development on a site of at least this area.",
        f"{rules.GROUP_DEVELOPMENT_MIN_SITE_SQM:,.0f} m²", Basis.LEGAL_RULE,
        rules.GROUP_DEVELOPMENT_CLAUSE, ("rules.GROUP_DEVELOPMENT_MIN_SITE_SQM",),
        note="Tested on the site area as per documents (the gross), the net plot when no gross "
             "is known. Below it the checker does not apply rule 8, and the layout stops: "
             "layouts without 8(m) roads are not supported yet.",
    ),
    Constraint(
        "Roads", "A block above this height takes its access from an internal road; 6 m "
                 "pathways may serve only lower blocks.",
        _m(rules.PATHWAY_MAX_BLOCK_HEIGHT_M), Basis.LEGAL_RULE, rules.PATHWAY_CLAUSE,
        ("rules.PATHWAY_MAX_BLOCK_HEIGHT_M",),
        note="Rule 8(l): 'In case of blocks up to 12m height, access through pathways of 6m "
             "width branching out from the internal roads / loop road would be allowed.' The "
             "permission stops at 12 m. What 'opens onto' a road means is the next entry.",
    ),
    Constraint(
        "Roads", "How much of a block must face a road for it to open onto one.",
        f"a touch (within {validator_network.TOUCH_M:g} m), or an unbroken "
        f"{_m(rules.PATHWAY_WIDTH_M)} of the block, the pathway's width",
        Basis.UNRESOLVED_INTERPRETATION, rules.PATHWAY_CLAUSE,
        note="Rule 8(l) and (m) give a taller block its access from a road without saying how "
             "much of it must face one: a block that only touches a road at a corner opens onto "
             "it under one reading and not the other. Both are evaluated (opens_onto_road). The "
             "6 m is the least access the rule gives any block, a pathway; using it as a length "
             "of frontage is the reading's.",
        settles="A sanctioned plan with a block that only touches a road at a corner, or the "
                "authority's reading of rule 8(l) and (m).",
    ),
    Constraint(
        "Roads", "The paved pathway from a road to a building it serves is no longer than this.",
        _m(rules.PATHWAY_MAX_LENGTH_M), Basis.LEGAL_RULE, rules.PATHWAY_LENGTH_CLAUSE,
        ("rules.PATHWAY_MAX_LENGTH_M",),
        note="NBC 2016 Part 3 4.3.2.2, brought to a block below 21 m by rule 15(a)(i). Measured "
             "along a straight pathway; one of any other shape is bounded between the straight "
             "line and half its outline, UNVERIFIED in between.",
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
             "loop sits outside the setback, so at 27 m towers stand 11 m back where Table IV "
             "asks 9: the setback and the road are added. Rule 13(c)(vii) leaves '7m of setback "
             "for movement of fire-fighting vehicles', which suggests vehicles may run inside a "
             "setback. The firm's Dhulapally drawing runs 7 m driveways instead.",
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
        f"ends {access.END_M:g} m deep; joined within {access.TOUCH_M:g} m; a block, ramp or "
        f"fire lane within {towers.TOUCH_M:g} m of a road or the entrance opens onto it; roads "
        f"meeting over less than {validator_network.JOIN_SQM:g} m² touch at a corner only; a "
        f"lane meeting a block's band over less than {fire.REACH_MIN_SQM:g} m² does not reach "
        f"it; pieces drawn to meet may miss by {shapes.HEAL_M:g} m; a gate within "
        f"{context.GATE_ON_BOUNDARY_M:g} m of the boundary, or a shape within "
        f"{shapes.EDGE_REACH_M:g} m of the plot's edge, stands in it",
        Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (access.through_roads, towers.corridor_roads, access_checks; the full search's "
        "and the validator's own copies)",
        ("access.END_M", "access.TOUCH_M", "towers.TOUCH_M", "access_checks.TOUCH_M",
         "optimizer.search.layout.TOUCH_M", "optimizer.search.network.TOUCH_M",
         "validator.network.TOUCH_M", "validator.parking.RAMP_TOUCH_M",
         "validator.fire.GATE_TOUCH_M", "validator.network.JOIN_SQM",
         "validator.fire.REACH_MIN_SQM", "validator.shapes.HEAL_M",
         "validator.context.GATE_ON_BOUNDARY_M", "validator.shapes.EDGE_REACH_M"),
        note="Drawing tolerances for 'joins' and 'on a road'. The full search and the validator "
             "keep their own copies of the 0.5 m; the legacy access.healed closes the same "
             "0.05 m cracks inline.",
        settles="Nothing: measurement tolerances.",
    ),
    Constraint(
        "Roads", "How the full search draws its roads from the blocks: the shortest street, how "
                 "much of a corner the ring road may lose to a slanted boundary, where the "
                 "entrance is tried and how far the approach may run, how many clusters of "
                 "blocks stand round rings of their own and how a further one's ring is joined.",
        f"streets at least {network.MIN_STREET_LENGTH_M:g} m long; the ring may lose "
        f"{network.RING_TIP_SQM:g} m² at a corner; gates every {network.GATE_STEP_M:g} m, the "
        f"{network.ENTRANCES_TRIED} shortest approaches checked, each up to "
        f"{network.APPROACH_LONGEST_M:g} m deep and running {network.APPROACH_REACH_SQM:g} m² "
        f"into the ring; an approach of under {network.MIN_APPROACH_SQM:g} m² beyond the ring "
        f"is the ring itself; the gate at least {network.GATE_DEPTH_M:g} m deep; at most "
        f"{search_layout.MAX_CLUSTERS} clusters, a further one's ring joined by the shortest "
        f"link found every {network.LINK_STEP_M:g} m along it, and tried in "
        f"{search_layout.ZONE_ANGLES} directions at most (its configuration's and its own "
        "ground's)",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (optimizer.search.network)",
        ("optimizer.search.network.MIN_STREET_LENGTH_M", "optimizer.search.network.RING_TIP_SQM",
         "optimizer.search.network.GATE_STEP_M", "optimizer.search.network.ENTRANCES_TRIED",
         "optimizer.search.network.APPROACH_LONGEST_M",
         "optimizer.search.network.APPROACH_REACH_SQM",
         "optimizer.search.network.MIN_APPROACH_SQM", "optimizer.search.network.GATE_DEPTH_M",
         "optimizer.search.layout.MAX_CLUSTERS", "optimizer.search.network.LINK_STEP_M",
         "optimizer.search.layout.ZONE_ANGLES"),
        note="The shortest street is rule 8(m)'s 9 m road width and the gate's depth the 2 m "
             "planted strip, both read from rules.py; using them as a length and a depth is the "
             "engine's. The legacy layout tries its entrance its own way (access.ENTRANCE_STEP_M, "
             f"and an approach of up to {access.APPROACH_MAX_M:g} m). The validator measures "
             "every road the search draws.",
        settles="The firm's road pattern; the sanctioned plans.",
    ),
    # ----------------------------------------------------------------- fire access
    Constraint(
        "Fire access", "Motorable open space on all sides of a high-rise, the turning radius, "
                       "the entrance, the street join and the dead end.",
        f"{rules.FIRE_TENDER_MIN_WIDTH_M:g} m on all sides; {rules.FIRE_TURNING_RADIUS_M:g} m "
        f"turning radius; entrance {rules.GATE_MIN_WIDTH_M:g} m wide and "
        f"{rules.ENTRANCE_CLEAR_HEIGHT_M:g} m clear; the street joins one of "
        f"{rules.FIRE_STREET_JOIN_M:g} m; no dead end above {rules.DEAD_END_MAX_HEIGHT_M:g} m; "
        f"a {rules.FIRE_TENDER_LOAD_T:g} t surface (never checked)",
        Basis.LEGAL_RULE, f"{rules.FIRE_ACCESS_CLAUSE}; {rules.GATE_CLAUSE}; "
        f"{rules.FIRE_STREET_CLAUSE}; {rules.DEAD_END_CLAUSE}",
        ("rules.FIRE_TENDER_MIN_WIDTH_M", "rules.FIRE_TENDER_LOAD_T", "rules.FIRE_TURNING_RADIUS_M",
         "rules.GATE_MIN_WIDTH_M",
         "rules.ENTRANCE_CLEAR_HEIGHT_M", "rules.FIRE_STREET_JOIN_M", "rules.DEAD_END_MAX_HEIGHT_M",
         "access.LANE_M", "access.R_OUT", "access_checks.LANE_M"),
        note="NBC 2016 Part 3 4.6, brought in by rule 15(b)(iv); read from the page images. The "
             "45 t surface is a specification and is reported UNVERIFIED.",
    ),
    Constraint(
        "Fire access", "NBC 4.6 holds a special building whatever its height: a block over a "
                       "cellar of more than this area, or of this many levels or more.",
        f"one level over {rules.NBC_SPECIAL_BASEMENT_SQM:g} m², or "
        f"{rules.NBC_SPECIAL_BASEMENT_LEVELS} levels", Basis.LEGAL_RULE,
        rules.NBC_SPECIAL_BUILDING_CLAUSE,
        ("rules.NBC_SPECIAL_BASEMENT_SQM", "rules.NBC_SPECIAL_BASEMENT_LEVELS"),
        note="NBC 2016 Part 4 1.2(b)(6) with Part 3 4.6, brought to a block below 21 m by rule "
             "15(a)(i): read as law on 2026-10-06, 4.6 being a provision of means of access and "
             "neither a height nor a setback. A block over a shared cellar has it as its "
             "basement. The generator lays no fire band round a block below 21 m and keeps its "
             "cellar out from under every such block (optimizer.search.parking_plan).",
    ),
    Constraint(
        "Fire access", "NBC's own high-rise line, the stilt included: whether 4.6 reaches a block "
                       "of this height that the state calls non-high-rise.",
        _m(rules.NBC_HIGH_RISE_M), Basis.UNRESOLVED_INTERPRETATION, rules.NBC_HIGH_RISE_CLAUSE,
        ("rules.NBC_HIGH_RISE_M",),
        note="NBC 2016 Part 4 2.38 gives 15 m; the state's line is 21 m. Both readings are "
             "evaluated (nbc_fire_height): a block of 15 to 21 m over no large cellar that fails "
             "4.6 is UNVERIFIED, never FAIL.",
        settles="The fire NOC of a sanctioned 15 to 21 m block over no large cellar, or the fire "
                "department's written reading.",
    ),
    Constraint(
        "Fire access", "Where the 9 m turning radius is measured, and the clear band beside each "
                       "face of a block that follows from it.",
        f"the outer edge of the {access.LANE_M:g} m lane (inner edge {access.R_IN:g} m), so "
        f"{access.FIRE_BAND_M:.2f} m clear beside each face", Basis.UNRESOLVED_INTERPRETATION,
        rules.FIRE_ACCESS_CLAUSE,
        ("access.R_IN", "access.FIRE_BAND_M", "access_checks.FIRE_BAND_M",
         "optimizer.search.quantities.QUARTER_TURN"),
        note="The order gives the 9 m, not where it is measured. The outer-edge reading is the "
             "one that fits the state's 7 m minimum setback and the 7 m rule 13(c)(vii) keeps "
             "for fire vehicles; a 9 m centreline would need 7.76 m. The 6.88 m is derived from "
             "this reading and is nowhere written in the rule. Kept as the conservative test. "
             "The full search takes both readings from the resolved rules and keeps the larger "
             "band, outer radius less inner radius x sin 45 degrees for a square corner "
             "(optimizer.search.quantities.QUARTER_TURN).",
        settles="The fire NOC of a sanctioned high-rise, or the layout agreed with the Chief "
                "Fire Officer, which 4.6(c) asks for.",
    ),
    Constraint(
        "Fire access", "How a turn is drawn and judged: the sector's resolution, how much of it "
                       "may fall outside free ground before the turn is blocked, and how sharp a "
                       "bend must be to count as a turn.",
        f"{access.SECTOR_STEPS} chords; {access.SECTOR_TOLERANCE_SQM:g} m² outside allowed; "
        f"bends under {access.MIN_TURN_DEG:g} degrees are straight",
        Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (access.sector, access.blocked, access._corners; optimizer.search.turns; "
        "validator.turning)",
        ("access.SECTOR_STEPS", "access.SECTOR_TOLERANCE_SQM", "access.MIN_TURN_DEG",
         "optimizer.search.turns.ARC_STEPS", "optimizer.search.turns.MIN_TURN_DEG",
         "validator.turning.ARC_STEPS", "validator.turning.MIN_TURN_DEG"),
        note="Drawing tolerances; the 0.05 m healing of hairline cracks between road pieces "
             "(access.healed) is the same kind. The full search and the validator draw their "
             "turns with their own copies.",
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
        Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (grounds._club_item; layout.LayoutRequest; optimizer.search.ground, "
        "optimizer.search.layout)",
        ("grounds.CLUB_ASPECT", "layout.LayoutRequest.club_house_floors",
         "optimizer.search.ground.CLUB_ASPECT", "optimizer.search.layout.CLUB_FLOORS"),
        note="A firm gives its club house as club_house_sqm on the request; the storeys are "
             "not yet a workspace standard. The full search takes the same when the brief "
             "gives no storeys.",
        settles="The firm's club house drawings.",
    ),
    Constraint(
        "Amenities", "Walking room kept round the club house, the ramp and each facility.",
        _m(grounds.CLEARANCE_M), Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (grounds, site_amenities, optimizer.search.ground)",
        ("grounds.CLEARANCE_M", "site_amenities.CLEARANCE_M",
         "optimizer.search.ground.CLEARANCE_M"),
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
        "none (site_amenities._fit, optimizer.search.fit.fit_rectangle)",
        ("site_amenities.SCAN_STEP_M", "optimizer.search.fit.SCAN_STEP_M"),
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
        "Parking", "Conservative test mode: when whose rules apply is not established and it "
                   "changes the share, plan the stricter GHMC column.",
        f"{rules.PARKING_PERCENT_GHMC:g}%, only with --conservative-parking",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (parking.parking_percent, conservative=True)",
        note="Labelled CONSERVATIVE_ASSUMPTION wherever it is used. A normal run stops and asks "
             "for the jurisdiction instead; when the answer would not change the share (GHMC, "
             "or anywhere inside CURE), nothing is asked.",
        settles="The authority and CURE answers, confirmed (site inputs).",
    ),
    Constraint(
        "Parking", "Where the required parking may be provided: the stilt, the open space over "
                   "and above the setbacks, and cellars, in any combination.",
        "stilt, surface beyond the setbacks, cellars", Basis.LEGAL_RULE,
        "G.O.168 rule 13(b)",
        note="Podium parking is unsupported. Fire lanes are never parked in (NBC 4.6(c)).",
    ),
    Constraint(
        "Parking", "How each part is measured: the stilt less its lift and stair cores; each "
                   "cellar level less the cores, the ramp's footprint on every level and the "
                   "utilities share.", "as measured from the drawing",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (parking.stilt_area, grounds._level_area)",
        note="No order says what is deducted; the engine deducts what cannot hold a car, which "
             "is the conservative choice. An authority may count ramps or circulation in.",
        settles="The parking statement on a sanctioned plan, or the firm's own method.",
    ),
    Constraint(
        "Parking", "A layout must also physically fit cars whose bays and half-aisles come to "
                   "the Table V area, besides the floor area itself.",
        f"cars x {parking.LAID_OUT_SQM_PER_CAR:g} m² >= the required area",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (grounds.firm_up, parking_checks._table_v)",
        note="A second test the law does not set: Table V asks for parking area. It can make a "
             "layout stricter than the rule.",
        settles="The firm, deciding whether to keep the physical-fit test.",
    ),
    Constraint(
        "Parking", "A stilt counts as parking only where a car can drive in: an unbroken "
                   "driveway's width of the block faces a road, a fire lane or a pathway.",
        f"{_m(rules.DRIVEWAY_MIN_WIDTH_M)} of unbroken frontage on motorable ground",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (validator.parking.stilt_reached)",
        note="No order says how a stilt is entered; the driveway width (rule 13(c)(viii)) is the "
             "least a car needs, and a rule 8(l) pathway, 6 m wide, is the block's access. Only "
             "the validator applies it: the generator still counts every stilt, so a layout it "
             "plans can fall short here.",
        settles="The firm's stilt entrances on a sanctioned plan.",
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
        f"at 1 in {round(1 / rules.RAMP_MAX_GRADIENT)}; in a side or rear setback only leaving "
        f"{rules.RAMP_FIRE_CLEARANCE_M:g} m for fire vehicles", Basis.LEGAL_RULE,
        rules.RAMP_CLAUSE,
        ("rules.RAMP_SINGLE_MIN_WIDTH_M", "rules.RAMP_PAIR_MIN_WIDTH_M", "rules.RAMP_MAX_GRADIENT",
         "rules.RAMP_FIRE_CLEARANCE_M"),
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
        note="Re-read on 2026-10-01: '0.5m additional setback for every additional cellar floor "
             "shall be insisted' fixes the amounts, not whether the upper floors keep the "
             "smaller setback. The stricter reading is taken; it matters only from two cellars.",
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
        "Parking", "Where the first bay of a row and the first row of a floor are tried when the "
                   "cars a parking floor holds are counted.",
        f"bays from {', '.join(f'{x:g}' for x in parking_plan.OFFSETS_ALONG)} m along; rows "
        f"from {', '.join(f'{y:g}' for y in parking_plan.OFFSETS_ACROSS)} m across",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (optimizer.search.parking_plan, validator.cars)",
        ("optimizer.search.parking_plan.OFFSETS_ALONG",
         "optimizer.search.parking_plan.OFFSETS_ACROSS", "validator.cars.OFFSETS_ALONG",
         "validator.cars.OFFSETS_ACROSS"),
        note="The full search and the validator count with the same offsets, each in its own "
             "copy. More offsets could only find more cars.",
        settles="Nothing: a search breadth; the count is what physically fits.",
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
         "layout.LayoutRequest.stilt_height_m", "layout.LayoutRequest.common_area_pct",
         "area_statement.TowerGroup.common_area_pct", "assistant.DEFAULTS"),
        note="ASSUMED_FOR_TEST until the firm sets them. The area statement takes the same "
             "loading when a project leaves it out (area_statement.TowerGroup), and the assistant "
             "names the same three when a brief leaves them out (assistant.DEFAULTS).",
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
        "Towers", "Design margins: what is kept in hand above each legal minimum (setbacks, the "
                  "gap between blocks, road widths, organised open space, parking), so that a "
                  "layout is not planned on a legal cliff.",
        "none set: " + ", ".join(f"{name} {field.default:g}"
                                 for name, field in intake.WorkspaceMargins.model_fields.items()),
        Basis.FIRM_STANDARD, f"{_WORKSPACE}, design_margins",
        tuple(f"intake.WorkspaceMargins.{name}" for name in intake.WorkspaceMargins.model_fields),
        note="Never law. The optimizer aims at the legal minimum plus the margin; every check "
             "goes on judging against the legal minimum alone, and a report shows the legal "
             "minimum, the target and what is provided. A margin the firm leaves out is no "
             "margin. The prototype generator plans on the legal minimum and applies none.",
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
        "none (layout.same_idea, layout._massing, optimizer.pareto)",
        ("layout.ANGLE_FAMILY_DEG", "layout.SAME_IDEA_OVERLAP", "optimizer.pareto.ANGLE_FAMILY_DEG",
         "optimizer.pareto.SAME_IDEA_OVERLAP"),
        note="The new stages' Pareto selection keeps its own copy (optimizer.pareto).",
        settles="Nothing: how the options are chosen for variety, not whether one passes.",
    ),
    Constraint(
        "Towers", "The three massing strategies shown: maximum yield with no limit; balanced, "
                  "medium blocks of up to this many cores and this length; conventional, "
                  "compact towers of this many cores.",
        f"A: no limit; B: up to {layout.BALANCED_MAX_CORES} cores and "
        f"{layout.BALANCED_MAX_LENGTH_M:g} m, the largest more than one core; C: "
        f"{layout.CONVENTIONAL_MAX_CORES} core per tower", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (layout.STRATEGIES, layout.fits_strategy, layout.pick_strategies)",
        ("layout.BALANCED_MAX_CORES", "layout.BALANCED_MAX_LENGTH_M",
         "layout.CONVENTIONAL_MAX_CORES", "layout.STRATEGIES"),
        note="Design categories, not law: no order limits a block's length or cores since "
             "G.O.Ms.No.65 of 2019. A strategy no layout passes for is reported missing, never "
             "filled in. Each option reports every tower's length, width, flats per floor, "
             "cores and flats per core.",
        settles="The firm's own block types (its longest block, cores per block).",
    ),
    Constraint(
        "Towers", "How many options are returned.", f"{_lr['options'].default}",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (layout.LayoutRequest, design_brief.Objectives)",
        ("layout.LayoutRequest.options", "contracts.design_brief.Objectives.options"),
        settles="Nothing: the architect asks for more.",
    ),
    Constraint(
        "Towers", "How close the flats must come to the brief to meet it: the unit mix, and a "
                  "number of units asked.",
        f"a mix error within {_mix:g}, unless the brief sets its own; units within "
        f"{_pct(program.UNITS_TARGET_TOLERANCE)} of the number asked",
        Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (contracts.design_brief.Program, validator.program)",
        ("contracts.design_brief.Program.mix_tolerance",
         "validator.program.UNITS_TARGET_TOLERANCE"),
        note="The brief's program, judged by the validator; neither is law.",
        settles="The architect's brief, which may set its own tolerance.",
    ),
    Constraint(
        "Towers", "The tower prototypes composed from the firm's flats: the cores a block has, "
                  "the flats each core serves on a side, and what a core holds.",
        "; ".join(f"{family.value} {plan.cores} x {plan.flats_per_core_per_side}"
                  for family, plan in compose.FAMILY_PLANS.items())
        + f" (cores x flats a side); {compose.LIFTS_PER_CORE} lifts and "
        f"{compose.STAIRS_PER_CORE} stair to a core", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (prototypes.compose)",
        ("prototypes.compose.FAMILY_PLANS", "prototypes.compose.LIFTS_PER_CORE",
         "prototypes.compose.STAIRS_PER_CORE"),
        note="Design choices, not law: no order limits a block's cores or flats a floor, and a "
             "family the library's flats_per_core_per_side cannot serve is not composed. The "
             "lifts and stair are placeholders until egress is modelled (the validator reports "
             "egress NOT_CHECKED).",
        settles="The firm's own block types and core drawings.",
    ),
    Constraint(
        "Towers", "How much the full search looks at: where the columns start, the floor counts "
                  "tried, the configurations laid out, tried, judged and proposed for each set "
                  "of readings, and how the time budget is shared.",
        f"{_lim.offsets} column offsets over one pitch (a block's depth and the larger of the "
        f"road and {strategy.PITCH_GAP_M:g} m); positions along a column every "
        f"{columns.STEP_M:g} m, a gap kept at the figure asked plus {columns.GAP_SLACK_M:g} m; "
        f"the {_lim.heights} tallest counts; for each profile {_lim.laid_per_profile} laid of "
        f"up to {_lim.attempts_per_profile} tried, {_lim.judged_per_profile} judged and "
        f"{_lim.per_profile_proposed} proposed; evaluating stops at "
        f"{_pct(strategy.EVALUATE_SHARE)} of the time budget and laying out at "
        f"{_pct(strategy.LAY_OUT_SHARE)}", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (optimizer.search.strategy.Limits, optimizer.search.columns)",
        ("optimizer.search.strategy.Limits.offsets", "optimizer.search.strategy.Limits.heights",
         "optimizer.search.strategy.Limits.laid_per_profile",
         "optimizer.search.strategy.Limits.attempts_per_profile",
         "optimizer.search.strategy.Limits.judged_per_profile",
         "optimizer.search.strategy.Limits.per_profile_proposed",
         "optimizer.search.strategy.PITCH_GAP_M", "optimizer.search.strategy.EVALUATE_SHARE",
         "optimizer.search.strategy.LAY_OUT_SHARE", "optimizer.search.columns.STEP_M",
         "optimizer.search.columns.GAP_SLACK_M"),
        note="Search bounds, never rules: a wider search can only add options, and the "
             "validator judges every candidate. A firm's design margin on the gap is added "
             "apart (design_margins.tower_gap_extra_m).",
        settles="Nothing: search breadth.",
    ),
    Constraint(
        "Towers", "When the plot has no room to spare, the end of it the full search keeps for "
                  "the open space, the club house, the ramp and the facilities, and how big it "
                  "is reckoned.",
        f"{search_layout.RESERVE_OPEN_FACTOR:g} x the open space, "
        f"{search_layout.RESERVE_CLUB_FACTOR:g} x twice a club house of "
        f"{search_layout.CLUB_ASSUMED_SHARE_OF_NET:g} x the net plot over its storeys, "
        f"{search_layout.RAMP_RESERVE_SQM:g} m² for the ramp and "
        f"{search_layout.FACILITY_ROOM_SQM:g} m² for the facilities; an end too small is tried "
        f"again {strategy.RETRY_SCALE:g} times bigger", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (optimizer.search.layout.Run.reserve_target_sqm, optimizer.search.strategy)",
        ("optimizer.search.layout.RESERVE_OPEN_FACTOR",
         "optimizer.search.layout.RESERVE_CLUB_FACTOR",
         "optimizer.search.layout.CLUB_ASSUMED_SHARE_OF_NET",
         "optimizer.search.layout.RAMP_RESERVE_SQM", "optimizer.search.layout.FACILITY_ROOM_SQM",
         "optimizer.search.strategy.RETRY_SCALE"),
        note="Estimates that only decide which configurations are tried; the exact laying "
             "decides whether one fits. The club house's figure folds the 3% share into a "
             "built-up area reckoned at 1.25 times the net plot, so it would not follow a change "
             "to the rule's share.",
        settles="Nothing that passes a layout: the exact laying decides.",
    ),
    Constraint(
        "Towers", "Reading the firm's flats from its floor-plan DXF: carpet to built-up, how far "
                  "a room may lie from its flat's kitchen, and what a plausible flat is.",
        f"built-up = carpet x {flat_import.BUILT_UP_FROM_CARPET:g}; rooms within "
        f"{flat_import.ROOM_REACH_M:g} m of a kitchen; at least "
        f"{flat_import.MIN_CARPET_PER_BEDROOM_SQM:g} m² of carpet a bedroom; "
        f"{flat_import.PLAUSIBLE_ROOMS.start} to {flat_import.PLAUSIBLE_ROOMS.stop - 1} rooms and "
        f"{flat_import.PLAUSIBLE_BEDROOMS.start} to {flat_import.PLAUSIBLE_BEDROOMS.stop - 1} "
        "bedrooms a flat", Basis.ENGINE_DESIGN_ASSUMPTION, "none (flat_import)",
        ("flat_import.BUILT_UP_FROM_CARPET", "flat_import.ROOM_REACH_M",
         "flat_import.MIN_CARPET_PER_BEDROOM_SQM", "flat_import.PLAUSIBLE_ROOMS",
         "flat_import.PLAUSIBLE_BEDROOMS"),
        note="The importer writes the firm's flat library, which generation then reads as the "
             "firm's standard, so these shape what the library says.",
        settles="The firm's own built-up and saleable figures for its flats, in its library file.",
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
         "checks.WATER_OVERLAP_SQM", "max_floors._EPS", "validator.parking.AREA_SLACK_SQM",
         "validator.land_checks.WATER_OVERLAP_SQM"),
        note="findings.narrower_than calls a shape narrower when removing every part thinner "
             "than the width loses more than 2% of its area. The validator keeps its own copies "
             "of the area slack and the water-buffer overlap.",
        settles="Nothing: tolerances, all well under a drawing's precision.",
    ),
    Constraint(
        "Tolerances", "The new stages' drawing tolerances: the slivers and noise the envelope, "
                      "the full search and the adapters ignore, the hair a block keeps inside "
                      "its ground, and the floating point epsilons of heights and targets.",
        f"heights to {resolved_rules.HEIGHT_TOL_M:g} m; a block {search_layout.EPS_LAND_M:g} m "
        f"inside its ground; slivers under {build.SLIVER_SQM:g} m² to "
        f"{network.RING_CLIP_SQM:g} m² ignored; frontage under {frontage.MIN_ZONE_M:g} m is "
        "noise", Basis.ENGINE_DESIGN_ASSUMPTION, "none",
        ("contracts.resolved_rules.HEIGHT_TOL_M", "contracts.validation.TARGET_TOL",
         "legal.non_high_rise.WIDTH_TOL_M", "legal.frontage.MIN_ZONE_M",
         "optimizer.floors.EPS_M", "optimizer.search.build.SLIVER_SQM",
         "optimizer.search.build.GRID_M",
         "optimizer.search.columns.EPS", "optimizer.search.fit.EPS_M",
         "optimizer.search.ground.MIN_PIECE_SQM", "optimizer.search.layout.EPS_LAND_M",
         "optimizer.search.fringe.TIE_M", "optimizer.search.fringe.CONTAIN_TOL_M",
         "optimizer.search.road_graph.FILL_SLIVER_SQM",
         "optimizer.search.road_graph.NODE_SNAP_M", "optimizer.search.network.RING_CLIP_SQM",
         "optimizer.search.network.APPROACH_OUTSIDE_SQM", "optimizer.search.network.EPS_M",
         "optimizer.search.parking_plan.EPS_M", "optimizer.search.parking_plan.EDGE_M",
         "prototypes.legacy.SNAP_M", "adapters.legacy_layout.SLIVER_SQM"),
        note="A height sums floor heights, so 21.000000000000004 m is 21 m. A legacy tower is "
             "snapped to a micrometre when it becomes a prototype, so shared edges are one. The "
             f"fringe ranks distances and places within {fringe.TIE_M:g} m as equal and counts a "
             f"block within {fringe.CONTAIN_TOL_M:g} m of its ground as on it, so the last digits "
             "of the geometry never choose between equals. Two road ends within "
             f"{road_graph.NODE_SNAP_M:g} m are one node of the full search's road graph. The "
             f"search's ledger is drawn on the validator's {build.GRID_M:g} m grid.",
        settles="Nothing: tolerances, all well under a drawing's precision.",
    ),
    Constraint(
        "Tolerances", "The validator's drawing tolerances: the noise it ignores, the grid it "
                      "snaps to and how finely it finds a circle.",
        f"shapes snapped to {shapes.GRID_M:g} m; edges within {shapes.EPS_M:g} m are one; "
        f"overlaps under {shapes.NOISE_SQM:g} m² are noise, two claims on ground under "
        f"{accounting.CONFLICT_SQM:g} m² are their edges meeting; pockets within "
        f"{open_space.CRACK_M:g} m are one; the widest circle's centre found to "
        f"{shapes.CENTRE_TOLERANCE_M:g} m", Basis.ENGINE_DESIGN_ASSUMPTION, "none (validator)",
        ("validator.shapes.GRID_M", "validator.shapes.EPS_M", "validator.shapes.FLAW_SQM",
         "validator.shapes.NOISE_SQM", "validator.shapes.CENTRE_TOLERANCE_M",
         "validator.accounting.CONFLICT_SQM", "validator.layers.SAME_ZONE_SQM",
         "validator.measure.TOL_M", "validator.open_space.CRACK_M", "validator.zones.DEPTH_EPS_M",
         "validator.cars.EPS_M", "validator.cars.EDGE_M"),
        note="The circle's centre decides the radius a cul-de-sac's head is measured at.",
        settles="Nothing: tolerances, all well under a drawing's precision.",
    ),
    Constraint(
        "Tolerances", "The validator's slack on a verdict: how far a measured width, size or "
                      "share may fall short of what it declares or the rule asks and still meet "
                      "it, and what it takes for a shape to be a bay or a bend.",
        f"a gate {fire.GATE_SLACK_M:g} m and a road {validator_roads.DECLARED_SLACK_M:g} m "
        f"under the width it declares; a cul-de-sac's head {validator_roads.HEAD_SLACK_M:g} m "
        f"under its radius; a part {shapes.OPENING_SLACK_M:g} m under the width asked; a bay "
        f"{validator_parking.BAY_SLACK_M:g} m and a ramp {validator_parking.RAMP_SLACK_M:g} m "
        f"short of their size, a cellar {validator_parking.CELLAR_SLACK_M:g} m short of its "
        f"setback; the planted strip {_share(land_checks.STRIP_SLACK)} short of its area or "
        f"{land_checks.STRIP_WIDTH_SLACK_M:g} m of its width; a club house "
        f"{clubhouse.SIZE_SLACK_SQM:g} m² under the share it needs or "
        f"{program.SIZE_SLACK_SQM:g} m² under the size the brief states; a bay is one when it "
        f"fills {_share(validator_parking.BAY_FILL)} of its box and on other ground when over "
        f"{validator_parking.BAY_OVERLAP_SQM:g} m² of it lies there; a strip "
        f"{_share(shapes.BEND_RATIO - 1)} longer along its middle than its box is bent",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (validator)",
        ("validator.fire.GATE_SLACK_M", "validator.roads.DECLARED_SLACK_M",
         "validator.roads.HEAD_SLACK_M", "validator.roads.HEAD_CUT_M",
         "validator.parking.BAY_SLACK_M", "validator.parking.RAMP_SLACK_M",
         "validator.parking.CELLAR_SLACK_M", "validator.parking.BAY_FILL",
         "validator.parking.BAY_OVERLAP_SQM", "validator.shapes.OPENING_SLACK_M",
         "validator.shapes.BEND_RATIO", "validator.land_checks.STRIP_SLACK",
         "validator.land_checks.STRIP_WIDTH_SLACK_M", "validator.clubhouse.SIZE_SLACK_SQM",
         "validator.program.SIZE_SLACK_SQM"),
        note="Each can turn a verdict at the margin, always by a drawing's rounding: a road "
             "drawn as chords of an arc is a centimetre narrower than the arc. A bent "
             "cul-de-sac's length is UNVERIFIED rather than failed; its stem is what is left "
             f"once the head's circle is cut {validator_roads.HEAD_CUT_M:g} m wider.",
        settles="Nothing: measurement tolerances, each under a drawing's precision.",
    ),
    Constraint(
        "Tolerances", "How far the generator's own figures may differ from the validator's "
                      "measure before the validator says they disagree.",
        f"footprints by {cross_checks.FOOTPRINT_SQM:g} m² or "
        f"{_share(cross_checks.FOOTPRINT_SHARE)}; a figure by "
        f"{_share(cross_checks.METRIC_SHARE)}, a ledger use by "
        f"{_share(cross_checks.PARTITION_SHARE)} of the net area, cars by "
        f"{_share(cross_checks.CARS_SHARE)}; a setback by {cross_checks.SETBACK_SLACK_M:g} m; "
        f"the open space the rules and the site ask by {_share(open_space.AGREEMENT_SHARE)}",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (validator.cross_checks, validator.open_space)",
        ("validator.cross_checks.FOOTPRINT_SQM", "validator.cross_checks.FOOTPRINT_SHARE",
         "validator.cross_checks.METRIC_SHARE", "validator.cross_checks.PARTITION_SHARE",
         "validator.cross_checks.CARS_SHARE", "validator.cross_checks.SETBACK_SLACK_M",
         "validator.cross_checks.BAND_SLACK_M", "validator.open_space.AGREEMENT_SHARE"),
        note="A disagreement is reported against the generator's claim; the verdicts rest on "
             "the validator's own measure.",
        settles="Nothing: tolerances on the generator's arithmetic.",
    ),
    Constraint(
        "Tolerances", "What the full search keeps in hand above what it is asked, so rounding "
                      "never leaves a layout short.",
        f"claims {_share(build.OPEN_SPACE_CLAIM)} of the open space drawn; the club house "
        f"{search_ground.CLUB_SIZE_SLACK_SQM:g} m² over its share; parking "
        f"{parking_plan.SAFETY_SQM:g} m² over the need", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (optimizer.search.build, optimizer.search.ground, optimizer.search.parking_plan)",
        ("optimizer.search.build.OPEN_SPACE_CLAIM", "optimizer.search.ground.CLUB_SIZE_SLACK_SQM",
         "optimizer.search.parking_plan.SAFETY_SQM"),
        settles="Nothing that passes a layout: the validator measures each one again.",
    ),
    Constraint(
        "Tolerances", "What the validator refuses to measure at all, so a broken candidate gets "
                      "one check that can never pass instead of a guess.",
        f"a whole number above {refusals.MAX_COUNT:.0e}; ground drawn more than "
        f"{refusals.EXTENT_FACTOR} plot-widths away (never within {refusals.EXTENT_FLOOR_M:g} "
        f"m); a parking bay narrower than {refusals.MIN_BAY_M:g} m",
        Basis.ENGINE_DESIGN_ASSUMPTION, "none (validator.refusals)",
        ("validator.refusals.MAX_COUNT", "validator.refusals.EXTENT_FACTOR",
         "validator.refusals.EXTENT_FLOOR_M", "validator.refusals.MIN_BAY_M"),
        settles="Nothing: guards against input no site could give.",
    ),
    Constraint(
        "Tolerances", "What the contracts and the prototype loader refuse: how far a stated "
                      "figure may miss what is drawn, or shares what they must add up to.",
        f"ownership arithmetic within {_share(_own)} of the gross; a ledger within "
        f"{_share(_ledger)} of the net, its entries overlapping by at most "
        f"{ledger.OVERLAP_TOLERANCE_SQM:g} m² and a shape's stated area within "
        f"{ledger.AREA_TOLERANCE_SQM:g} m²; a prototype's per-floor areas within "
        f"{_share(prototype.AREA_TOLERANCE)} and its saleable area within "
        f"{prototype.SALEABLE_TOLERANCE_SQFT:g} sft a flat; its parts within "
        f"{_share(prototype_library.BALANCE_TOLERANCE)} of the footprint and "
        f"{prototype_library.FRAME_TOLERANCE_M:g} m of its frame; a unit mix adding up to 1 "
        f"within {design_brief.MIX_SUM_TOLERANCE:g}", Basis.ENGINE_DESIGN_ASSUMPTION,
        "none (contracts, prototypes.library)",
        ("contracts.accounting.OwnershipReconciliation.tolerance",
         "contracts.accounting.PartitionLedger.tolerance",
         "contracts.accounting.OVERLAP_TOLERANCE_SQM", "contracts.accounting.AREA_TOLERANCE_SQM",
         "contracts.prototype.AREA_TOLERANCE", "contracts.prototype.SALEABLE_TOLERANCE_SQFT",
         "prototypes.library.BALANCE_TOLERANCE", "prototypes.library.SLIVER_SQM",
         "prototypes.library.FRAME_TOLERANCE_M", "contracts.design_brief.MIX_SUM_TOLERANCE",
         "prototypes.compose.MIX_SUM_TOLERANCE"),
        note="The prototype composer checks a unit mix with its own copy of the brief's "
             "tolerance.",
        settles="Nothing: tolerances on figures the engine itself states; the drawing decides.",
    ),
    # ----------------------------------------------------------------- site inputs
    Constraint(
        "Site", "The plot: its outline and net area, the gross area, and the land given up for "
                "road widening and where it lies.", "per site", Basis.SITE_INPUT,
        "the survey (EXTRACTED) and the project file's net_plot_m, net_area, gross_area, and "
        "road_strip_side with road_strip_width_m or road_strip_m, with their status",
        note="Where the strip lies is asked, never guessed from the area: without it the run "
             "stops and says what to give.",
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
        "Not used by generation", "In a project of more than this many acres, common amenities "
                                  "take this share of the site area.",
        f"{rules.LARGE_PROJECT_FROM_ACRES:g} acres; "
        f"{_pct(rules.LARGE_PROJECT_AMENITY_SHARE_OF_SITE)}",
        Basis.LEGAL_RULE, rules.LARGE_PROJECT_AMENITY_CLAUSE,
        ("rules.LARGE_PROJECT_FROM_ACRES", "rules.LARGE_PROJECT_AMENITY_SHARE_OF_SITE"),
        note="Written for row and cluster housing (rules 9(o) and 10(i)); rule 8, group "
             "development, has no such clause, so it is not applied to the apartment schemes "
             "planned here. Carried in ResolvedRules as an open reading, never as a requirement.",
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
