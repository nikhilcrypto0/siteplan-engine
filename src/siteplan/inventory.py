"""Every rule the engine applies or knowingly leaves out, and how each one was read.

The values are read from `rules.py`, so changing a constant there changes this list. How each
rule was read is written beside it by hand, and `tests/test_inventory.py` fails when a clause in
`rules.py` has no entry here, or an entry says a module applies a rule that module never uses.

This is the list the firm reviews. INTERPRETED and ASSUMED entries are where our reading could
be wrong, and each names the evidence that would settle it: usually a sanctioned plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import groupby

from siteplan import rules


class Reading(StrEnum):
    AS_WRITTEN = "as written"  # the order's own words and numbers, applied as they stand
    INTERPRETED = "interpreted"  # the order leaves a choice open; `choice` says which we took
    ASSUMED = "assumed"  # no order says this; a default the firm should confirm
    NOT_MODELLED = "not modelled"  # in force, or possibly so, but the engine does not apply it


class Where(StrEnum):
    CHECKER = "checker"
    LAYOUT = "layout"
    LOOKUP = "height lookup"  # `siteplan rules --height` and the rules_for_height tool
    FLOORS = "floors calculator"  # `siteplan floors` and the max_floors tool


@dataclass(frozen=True)
class Entry:
    topic: str
    rule: str
    value: str
    clause: str
    reading: Reading
    applied_in: tuple[Where, ...] = ()
    uses: tuple[str, ...] = ()  # the names in rules.py this entry reports on
    choice: str = ""
    settles: str = ""


def _road_widths() -> str:
    runs = groupby(rules.TABLE_IV, key=lambda band: band.min_road_m)
    spans = [(road, list(bands)[-1].up_to_m) for road, bands in runs]
    parts = [f"{road:g} m up to {up_to:g} m" for road, up_to in spans[:-1]]
    return ", ".join([*parts, f"{spans[-1][0]:g} m above {spans[-2][1]:g} m"])


def _setbacks() -> str:
    *rows, top = rules.TABLE_IV
    parts = [f"{band.min_open_space_m:g} m up to {band.up_to_m:g} m" for band in rows]
    return ", ".join([*parts, f"{top.min_open_space_m:g} m above {top.above_m:g} m"])


_BOTH = (Where.CHECKER, Where.LAYOUT)
_TDR_LOW, _TDR_HIGH = rules.TDR_BAND_M
_TDR_SMALL, _TDR_LARGE = rules.TDR_PLOT_RANGE_SQM

INVENTORY: tuple[Entry, ...] = (
    # Height
    Entry(
        "Height", "A building is high-rise, and Table IV applies to it, from this height.",
        f"{rules.HIGH_RISE_THRESHOLD_M:g} m or more", rules.HIGH_RISE_CLAUSE,
        Reading.AS_WRITTEN, (*_BOTH, Where.FLOORS), ("HIGH_RISE_THRESHOLD_M", "HIGH_RISE_CLAUSE"),
    ),
    Entry(
        "Height", "Height is measured from the abutting road, and the stilt floor counts in it.",
        "stilt + floors x floor-to-floor height",
        "G.O.168 rule 2(e) (the stilt exclusion in rule 5(c) is written for Table III)",
        Reading.INTERPRETED, (*_BOTH, Where.FLOORS),
        choice="The stilt counts. Rule 2(e) leaves out only the parapet, staircase head room, "
               "lift room and water tank; the one stilt exclusion, rule 5(c), covers the Table III "
               "buildings below high-rise; rule 7(xvi) of 2016 leaves out only parking floors "
               "above the ground floor. The floors calculator gives the answer both ways.",
        settles="A sanctioned stilt + N floors high-rise whose approved setback or road width "
                "fits one reading and not the other. The firm's own Dhulapally drawing (not "
                "sanctioned) keeps the setbacks of its blocks without their stilt.",
    ),
    Entry(
        "Height", "Parking floors above the ground floor are left out of the height that picks "
                  "the Table IV row.",
        "left out of the height", rules.PARKING_FLOOR_HEIGHT_CLAUSE, Reading.NOT_MODELLED,
        uses=("PARKING_FLOOR_HEIGHT_CLAUSE",),
        choice="Podium and upper-floor parking are unsupported: the layout parks in the stilt, "
               "on the surface and in cellars only, so it never has a parking floor to leave "
               "out. Needed once a scheme parks on a podium or upper floors.",
    ),
    Entry(
        "Height", "Buildings below high-rise take their setbacks from Table III, by plot size "
                  "and road width.",
        "not encoded", "G.O.168 rule 5, Table III", Reading.NOT_MODELLED,
        choice="The layout refuses a building below 21 m and the checker reports it NOT_CHECKED.",
    ),
    Entry(
        "Height", "On a mid-sized plot, a building just below high-rise is allowed only through "
                  "TDR.",
        f"{_TDR_LOW:g}-{_TDR_HIGH:g} m on {_TDR_SMALL:,.0f}-{_TDR_LARGE:,.0f} m²",
        rules.TDR_BAND_CLAUSE, Reading.AS_WRITTEN, (Where.LOOKUP, Where.FLOORS),
        ("TDR_BAND_M", "TDR_PLOT_RANGE_SQM", "TDR_BAND_CLAUSE"),
        choice="Raised as a question by the height lookup; the checker does not examine "
               "buildings below 21 m.",
    ),
    # Road
    Entry(
        "Road", "The abutting road must be at least this wide for the building's height.",
        _road_widths(), rules.TABLE_IV_CLAUSE, Reading.AS_WRITTEN,
        (Where.CHECKER, Where.FLOORS),
        ("TABLE_IV", "TABLE_IV_CLAUSE", "band_for_height", "max_height_for_road"),
        choice="Table II gives the same widths up to 30 m.",
    ),
    Entry(
        "Road", "When a master-plan width is given, the road check uses it instead of the "
                "existing road.",
        "master-plan width if given, else the existing width", rules.ROAD_WIDENING_CLAUSE,
        Reading.INTERPRETED, (Where.CHECKER,), ("ROAD_WIDENING_CLAUSE",),
        choice="Assumes the strip the master plan takes is surrendered, so the scheme is sized "
               "to the widened road. Table II is headed 'minimum abutting existing road width', "
               "which would size it to the road as it stands.",
        settles="An approval letter on a road due for widening: which width did it use?",
    ),
    Entry(
        "Road", "A campus of 4,000 m² or more needs an existing black-topped road at least 12 m "
                "wide.",
        "12 m, existing", "G.O.168 rule 8(a), 8(b); Table II row B2", Reading.NOT_MODELLED,
        choice="Not checked on its own; the Table IV road check asks 12 m or more anyway, though "
               "of the master-plan width when one is given.",
    ),
    Entry(
        "Road", "A campus with no road along any side gives a 12 m public road along one edge.",
        "12 m, two lanes", "G.O.168 rule 8(k) as substituted by G.O.Ms.No.7 of 2016",
        Reading.NOT_MODELLED,
        choice="Not drawn. Where no existing road runs along any side, the campus gives a 12 m, "
               "two-lane public road along one edge, and the road-widening concessions (TDR, "
               "setback relaxation or extra floors) are granted for it. Dhulapally fits: its "
               "roads all end at the plot, and the firm's plan gives a 40 ft (12.2 m) road along "
               "the east, the 1,163 m² cut from the surveyed land.",
    ),
    Entry(
        "Road", "Internal roads of a group development scheme: a main approach road, other and "
                "looped roads, cul-de-sacs. A driveway is not one of them.",
        f"main approach {rules.MAIN_APPROACH_ROAD_M[0]:g}-{rules.MAIN_APPROACH_ROAD_M[1]:g} m, "
        f"other and looped {rules.INTERNAL_ROAD_M:g} m, cul-de-sacs {rules.CUL_DE_SAC_WIDTH_M:g} m "
        f"for {rules.CUL_DE_SAC_LENGTH_M[0]:g}-{rules.CUL_DE_SAC_LENGTH_M[1]:g} m with a "
        f"{rules.CUL_DE_SAC_HEAD_RADIUS_M:g} m radius head; on sites from "
        f"{rules.GROUP_DEVELOPMENT_MIN_SITE_SQM:,.0f} m²",
        f"{rules.INTERNAL_ROAD_CLAUSE}; {rules.GROUP_DEVELOPMENT_CLAUSE}",
        Reading.AS_WRITTEN, _BOTH,
        ("MAIN_APPROACH_ROAD_M", "INTERNAL_ROAD_M", "CUL_DE_SAC_WIDTH_M", "CUL_DE_SAC_LENGTH_M",
         "CUL_DE_SAC_HEAD_RADIUS_M", "INTERNAL_ROAD_CLAUSE", "GROUP_DEVELOPMENT_MIN_SITE_SQM",
         "GROUP_DEVELOPMENT_CLAUSE"),
        choice="Rule 2(c): a Group Development Scheme is residential development on a site of "
               "4,000 m² and above (the area as per documents), and rule 8 governs it. Below "
               "that the checker does not apply 8(m) or 8(l), and the layout stops: layouts "
               "without 8(m) roads are not supported yet. From it, the layout lays the roads "
               "before any tower: a 9 m loop road just inside the green strip, the main approach "
               "road from the entrance, and a 9 m road in every corridor between tower columns, "
               "so none is a dead end. The law gives 9 to 18 m for the main approach road; the "
               "optimiser draws 9 m (an engine choice, in constraints.py). The checker fails a "
               "road narrower than its width and a dead end without the cul-de-sac form, and "
               "never counts a driveway (rule 13(c)(viii), 4.5 m) as an internal road.",
        settles="The internal roads on a sanctioned Group Development plan, and whether the "
                "authority treats the firm's '23 ft wide driveway' (7.0 m) as an 8(m) road.",
    ),
    Entry(
        "Road", "A block above 12 m takes its access from an internal road; 6 m pathways serve "
                "only lower blocks.",
        f"blocks above {rules.PATHWAY_MAX_BLOCK_HEIGHT_M:g} m on a road", rules.PATHWAY_CLAUSE,
        Reading.AS_WRITTEN, (Where.CHECKER,),
        ("PATHWAY_MAX_BLOCK_HEIGHT_M", "PATHWAY_CLAUSE"),
        choice="Rule 8(l), read on 2026-10-01: 'In case of blocks up to 12m height, access "
               "through pathways of 6m width branching out from the internal roads / loop road "
               "would be allowed.' The permission stops at 12 m, so a taller block opens onto an "
               "internal road. Applied on a Group Development Scheme only, like the rest of "
               "rule 8.",
    ),
    Entry(
        "Road", "A residential building above this height may not stand on a road that ends at "
                "the plot.",
        f"{rules.DEAD_END_MAX_HEIGHT_M:g} m, the stilt included", rules.DEAD_END_CLAUSE,
        Reading.AS_WRITTEN, (Where.FLOORS, Where.CHECKER, Where.LAYOUT),
        ("DEAD_END_MAX_HEIGHT_M", "DEAD_END_CLAUSE"),
        choice="A survey does not show where a road leads, so the architect says whether it ends "
               "at the plot: then every answer, TDR floors included, stops at 30 m; left unsaid, "
               "the floors calculator warns, and the height search and the checker report a "
               "height above 30 m UNVERIFIED, never PASS. Dhulapally's survey draws its roads "
               "ending at the plot; whether the 40 ft road along the east will run on is a site "
               "fact.",
    ),
    Entry(
        "Road", "The street a high-rise stands on joins a street at least 12 m wide at one end.",
        f"{rules.FIRE_STREET_JOIN_M:g} m", rules.FIRE_STREET_CLAUSE, Reading.AS_WRITTEN,
        (Where.CHECKER,), ("FIRE_STREET_JOIN_M", "FIRE_STREET_CLAUSE"),
        choice="Where a road leads is not on a survey, so the architect answers yes, no or "
               "unknown; unknown is reported UNVERIFIED, never PASS.",
    ),
    # Plot
    Entry(
        "Plot", "A high-rise needs a plot of at least this size.",
        f"{rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m²", rules.MIN_HIGH_RISE_PLOT_CLAUSE,
        Reading.INTERPRETED, (Where.CHECKER, Where.FLOORS),
        ("MIN_HIGH_RISE_PLOT_SQM", "MIN_HIGH_RISE_PLOT_CLAUSE"),
        choice="Tested on the net plot (after road widening) when one is given, otherwise the "
               "gross.",
        settles="A sanctioned high-rise whose net plot is under 2,000 m² and gross above.",
    ),
    Entry(
        "Plot", "A high-rise site left short of the minimum by road widening may be short by "
                "up to this much.",
        f"{rules.ROAD_WIDENING_SHORTFALL_ALLOWANCE:.0%}", rules.ROAD_WIDENING_SHORTFALL_CLAUSE,
        Reading.NOT_MODELLED,
        uses=("ROAD_WIDENING_SHORTFALL_ALLOWANCE", "ROAD_WIDENING_SHORTFALL_CLAUSE"),
        choice="Defined in rules.py but never applied, so such a site fails. The text does not "
               "say 10% of what.",
    ),
    Entry(
        "Plot", "Setbacks are measured from the plot line left after the road-widening strip, "
                "not the surveyed boundary.",
        "net plot line", rules.SETBACK_ON_NET_PLOT_CLAUSE, Reading.AS_WRITTEN, _BOTH,
        ("SETBACK_ON_NET_PLOT_CLAUSE",),
        choice="Rule 7(a)(iii), read on 2026-10-01, considers a widened high-rise site 'with the "
               "proposed height and corresponding minimum all round setbacks' on its net plot. "
               "Where the strip lies is a site input, asked and never guessed from the area.",
    ),
    Entry(
        "Plot", "No building within a water body's buffer, which may be open space but never "
                "the setback.",
        ", ".join(f"{kind.replace('_', ' ')} {m:g} m" for kind, m in rules.WATER_BUFFER_M.items()),
        rules.WATER_BUFFER_CLAUSE, Reading.INTERPRETED, _BOTH,
        ("WATER_BUFFER_M", "WATER_BUFFER_CLAUSE"),
        choice="The architect names the water body's class and the colour or layer the survey "
               "draws it in. The buffer is measured from the lines drawn, kept free of towers, "
               "facilities and parking, and not counted as tot-lot, though the rule allows it. "
               "It is also treated as not motorable, which the rule does not say: so towers "
               "keep the fire band clear of it, and the loop road's width runs beside it. The "
               "buffer and the setback are a union, never added. The firm's unsanctioned "
               "Suchitra drawing keeps a 9.4 m strip beside a 9.6 m channel: a test fixture.",
        settles="A sanctioned plan beside a nala or lake: which class, what it deducted, and "
                "whether a road or fire lane runs inside the buffer.",
    ),
    Entry(
        "Plot", "A building keeps its distance, vertical and horizontal, from an electricity "
                "line.",
        f"{rules.ELECTRICAL_HT_CLEARANCE_M:g} m from a high-tension line, "
        f"{rules.ELECTRICAL_LT_CLEARANCE_M:g} m from a low-tension line",
        rules.ELECTRICAL_CLAUSE, Reading.NOT_MODELLED,
        uses=("ELECTRICAL_HT_CLEARANCE_M", "ELECTRICAL_LT_CLEARANCE_M", "ELECTRICAL_CLAUSE"),
        choice="The prototype's layout and checker do not model it. The value is carried in "
               "ResolvedRules for the legal envelope and the validator, which can hold a "
               "building to it only where the survey draws the line; a line that is only "
               "marked is reported UNVERIFIED. Rule 3(c)(ii), the green belt and 10 m roads "
               "under a tower line, is not modelled at all.",
    ),
    Entry(
        "Plot", "No building within the buffers of railways, power lines and protected "
                "monuments.",
        "e.g. 3 m clear of a high-tension line; 100 m from a protected monument",
        "G.O.168 rule 3, as amended by G.O.Ms.No.7 of 2016", Reading.NOT_MODELLED,
        choice="The survey reader does not look for these features, so their buffers are not "
               "checked.",
    ),
    # Setbacks
    Entry(
        "Setbacks", "Open space to be left around each building, by its height.",
        _setbacks(), rules.TABLE_IV_CLAUSE, Reading.AS_WRITTEN, (*_BOTH, Where.FLOORS),
        ("TABLE_IV", "TABLE_IV_CLAUSE", "band_for_height"),
        choice="A building's length does not add to it. The note G.O.Ms.No.50 put under the "
               "table for buildings longer than 40 m was deleted by G.O.Ms.No.65 of 31.05.2019, "
               "five weeks later; the engine applied it until 2026-09-29.",
    ),
    Entry(
        "Setbacks", "The table figure is kept on every side, the front included.",
        "Table IV column 4 all round", rules.FRONT_SETBACK_CLAUSE, Reading.AS_WRITTEN, _BOTH,
        ("FRONT_SETBACK_CLAUSE",),
        choice="Read on 2026-10-01: 'The Front setback shall be as per Table-III of rule-5 & "
               "Table-IV of rule-7 for Non High Rise & High Rise buildings respectively.' The "
               "Table III building line is for buildings below high-rise.",
    ),
    Entry(
        "Setbacks", "Balconies may project into the open space from 6 m height up.",
        "up to 2 m", "G.O.168 rule 7(a)(xiv)", Reading.NOT_MODELLED,
        choice="Not used: the engine keeps whole footprints, balconies included, out of the "
               "setback, stricter than the rule by up to 2 m a side, because its flat library "
               "does not record balcony depths. The setback is measured to the wall. Where a "
               "side takes the 2019 note's 1 m reduction, no further projection is allowed.",
    ),
    Entry(
        "Setbacks", "Up to 30 m, up to 2 m of setback may move from one side to another, keeping "
                    "7 m everywhere.",
        "2 m moved, 7 m minimum", "G.O.168 rule 7(a)(xiii)", Reading.NOT_MODELLED,
        choice="Not used: every side must meet the full figure.",
    ),
    Entry(
        "Setbacks", "An owner who surrenders land for road widening may take setback concessions "
                    "instead of TDR or extra floors.",
        "high-rise: down to 7 m clear on all sides",
        "G.O.168 rule 16(b) as substituted by G.O.Ms.No.7 of 2016 (Amendment 16); cap in 16(c)",
        Reading.NOT_MODELLED,
        choice="Not modelled. The owner picks one of the three rewards, and the built-up area "
               "after a concession may not exceed what the whole site allowed plus the "
               "equivalent of the land given up. The likeliest reason a surrendering scheme's "
               "towers stand 7 m from the boundary.",
    ),
    Entry(
        "Setbacks", "Through TDR, a high-rise's setbacks may be relaxed by up to 10%.",
        "10%, keeping 7 m all round", "G.O.Ms.No.95 of 2026, rule 17(d)(x)",
        Reading.NOT_MODELLED, choice="Not modelled: an option the owner buys.",
    ),
    Entry(
        "Setbacks", "A side from which no room takes light and air may keep 1 m less open space.",
        "column 4 less 1 m, at least 3 m and at most 8 m",
        "G.O.Ms.No.50 of 2019, first note under Table IV", Reading.NOT_MODELLED,
        choice="Not used: the engine does not know which sides have windows.",
    ),
    Entry(
        "Setbacks", "Tower-on-podium blocks and stepped blocks have their own open-space rules.",
        "podium 7 m all round; stepped 9 m, +1 m per 5 floors", "G.O.168 rule 7(b), 7(c)",
        Reading.NOT_MODELLED, choice="The engine draws straight slabs on a stilt only.",
    ),
    # Spacing
    Entry(
        "Spacing", "Two high-rise blocks stand at least their setback apart, and the gap is not "
                   "counted as tot-lot.",
        "the larger of the two blocks' setbacks",
        rules.BLOCK_SPACING_CLAUSE, Reading.INTERPRETED, _BOTH,
        ("BLOCK_SPACING_CLAUSE", "band_for_height"),
        choice="The text asks for 'the open space mentioned in Col. 4' without saying which block "
               "sets it when their heights differ. The engine takes the larger.",
        settles="A sanctioned plan with two blocks of different heights. Dhulapally spaces its "
                "blocks 8 m apart, the table figure for its blocks without their stilt.",
    ),
    # Open space
    Entry(
        "Open space", "Organised open space (tot-lot) over and above the setbacks, open to the "
                      "sky at ground level.",
        f"{rules.OPEN_SPACE_MIN_FRACTION:.0%} of the site area; pockets at least "
        f"{rules.OPEN_SPACE_MIN_WIDTH_M:g} m wide and {rules.OPEN_SPACE_MIN_POCKET_SQM:g} m²",
        rules.OPEN_SPACE_CLAUSE, Reading.INTERPRETED, _BOTH,
        ("OPEN_SPACE_MIN_FRACTION", "OPEN_SPACE_MIN_WIDTH_M", "OPEN_SPACE_MIN_POCKET_SQM",
         "OPEN_SPACE_CLAUSE"),
        choice="The text says 'total site area' without saying gross or net. The layout meets "
               "10% of the larger of the two, so it passes on either reading; the checker tests "
               "both. The tot-lot keeps off the roads, the fire lanes and the block gaps.",
        settles="A sanctioned plan's tot-lot share and the site area it was taken of.",
    ),
    Entry(
        "Open space", "Part of the open space as permeable softscape, and a cap on paved area.",
        "softscape 30% of open space (10% of the plot at least); paving at most 25% of the site",
        "NBC 2016 Part 11, 6.2.4 and 7.4.1", Reading.NOT_MODELLED,
        choice="Not applied. G.O.168 adopts NBC 2005 (rule 15(a)(i)); whether HMDA enforces "
               "these 2016 figures is not shown by any document we hold.",
    ),
    Entry(
        "Open space", "A continuous green planting strip inside the setback.",
        f"{rules.PERIPHERAL_GREEN_STRIP_M:g} m wide, where the setback is "
        f"{rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M:g} m or more",
        rules.PERIPHERAL_GREEN_STRIP_CLAUSE, Reading.AS_WRITTEN, _BOTH,
        ("PERIPHERAL_GREEN_STRIP_M", "PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M",
         "PERIPHERAL_GREEN_STRIP_CLAUSE"),
        choice="Reserved along the whole boundary where the setback is 9 m or more, broken only "
               "by the entrance; nothing drives, parks or is built on it, and the loop road runs "
               "just inside it.",
    ),
    # Access and fire
    Entry(
        "Access", "Minimum driveway width, where a driveway is drawn.",
        f"{rules.DRIVEWAY_MIN_WIDTH_M:g} m", rules.DRIVEWAY_CLAUSE, Reading.AS_WRITTEN,
        (Where.CHECKER,), ("DRIVEWAY_MIN_WIDTH_M", "DRIVEWAY_CLAUSE"),
        choice="The layout needs none: every stilt and the ramp open straight onto an internal "
               "road. A driveway is never counted as an internal road.",
    ),
    Entry(
        "Access", "The main entrance is wide enough for a fire engine, with room under anything "
                  "built over it.",
        f"{rules.GATE_MIN_WIDTH_M:g} m wide; {rules.ENTRANCE_CLEAR_HEIGHT_M:g} m clear",
        rules.GATE_CLAUSE, Reading.AS_WRITTEN, (Where.CHECKER,),
        ("GATE_MIN_WIDTH_M", "ENTRANCE_CLEAR_HEIGHT_M", "GATE_CLAUSE"),
        choice="The entrance is the 9 m main approach road, on the side the access road runs, "
               "with nothing built over it. The gate folding back against the compound wall is "
               "a detail drawing.",
    ),
    Entry(
        "Access", "Fire tenders reach and drive round every high-rise: 6 m of motorable open "
                  "space on all its sides, a 9 m turning radius, nothing built or parked in it, "
                  "a 45 t hard surface.",
        f"{rules.FIRE_TENDER_MIN_WIDTH_M:g} m on all sides; a {rules.FIRE_TURNING_RADIUS_M:g} m "
        "turn at every corner and every bend; 45 t",
        rules.FIRE_ACCESS_CLAUSE, Reading.INTERPRETED, _BOTH,
        ("FIRE_TENDER_MIN_WIDTH_M", "FIRE_TENDER_LOAD_T", "FIRE_TURNING_RADIUS_M",
         "FIRE_ACCESS_CLAUSE"),
        choice="Every high-rise keeps 6.88 m of clear, motorable ground on every side, a road or "
               "a fire lane, which is what a 6 m lane needs to turn round a square corner on our "
               "reading of the 9 m; the order gives the 9 m and the 6 m, never the 6.88 m. The "
               "turns at every tower corner and every bend of the loop road are checked as the "
               "swept sectors themselves, and the lanes as one network from the entrance. No "
               "bay, facility, ramp or tot-lot stands in them. The order does not say where the "
               "9 m is measured: read as the tender's turning circle, the outer edge of the "
               "lane, which fits the state's 7 m minimum setback and the 7 m rule 13(c)(vii) "
               "keeps for fire vehicles (a 9 m centreline would need 7.76 m). Asked once a block "
               "is a high-rise in the state's sense (21 m); NBC's own starts at 15 m. The 45 t "
               "surface is a specification and is reported UNVERIFIED.",
        settles="The fire NOC of a sanctioned high-rise, or the layout agreed with the Chief "
                "Fire Officer, which 4.6(c) asks for.",
    ),
    # Parking
    Entry(
        "Parking", "Parking area as a share of the total built-up area.",
        f"{rules.PARKING_PERCENT_GHMC:g}% inside GHMC or anywhere in CURE, "
        f"{rules.PARKING_PERCENT_ELSEWHERE:g}% elsewhere in HMDA",
        f"{rules.PARKING_CLAUSE}; {rules.CURE_RULES_CLAUSE}", Reading.AS_WRITTEN, _BOTH,
        ("PARKING_PERCENT_GHMC", "PARKING_PERCENT_ELSEWHERE", "PARKING_CLAUSE",
         "CURE_RULES_CLAUSE", "parking_percent"),
        choice="The share is the order's. When whose rules apply is not established and it "
               "changes the share, a normal run stops and asks; only the conservative test mode "
               "plans the GHMC column, labelled CONSERVATIVE_ASSUMPTION. How the stilt, surface "
               "and cellars are measured, and the bay sizes, are the engine's method "
               "(constraints.py), not this rule. Inside CURE the GHMC column applies whichever "
               "corporation the site now falls in (Cyberabad, since G.O.Ms.No.55 of 2026, for "
               "Qutbullapur zone).",
    ),
    Entry(
        "Parking", "Visitors' parking, marked on the ground.",
        f"at least {rules.VISITOR_PARKING_FRACTION:.0%} of the Table V area",
        rules.VISITOR_PARKING_CLAUSE, Reading.INTERPRETED, (Where.CHECKER,),
        ("VISITOR_PARKING_FRACTION", "VISITOR_PARKING_CLAUSE"),
        choice="Read as parking at ground level, the stilt or the surface, which a visitor can "
               "reach from the entrance; which bays are marked for visitors is for the detailed "
               "drawing.",
        settles="The visitors' parking on a sanctioned plan: marked in the stilt or only in "
                "the open.",
    ),
    Entry(
        "Parking", "Visitors' parking may be accommodated in the mandatory side and rear "
                   "setbacks.",
        "where such a setback is more than 6 m, the green strip left out; never the front "
        "setback, never where setback was transferred", rules.VISITOR_PARKING_CLAUSE,
        Reading.NOT_MODELLED,
        choice="Read on 2026-10-03 on p.19 of the 2012 text: rule 13(c)(xii) lets visitors' "
               "parking use the mandatory setbacks other than the front one where they are more "
               "than 6 m wide, the green strip excluded. The engine never uses it: every bay "
               "stays out of every setback, which is also what NBC 4.6(c) asks of a high-rise "
               "('The compulsory open spaces around the building shall not be used for "
               "parking'). ResolvedRules carries it as the open reading "
               "visitor_parking_in_setback, so a layout that used the allowance is judged "
               "against both.",
        settles="A sanctioned high-rise plan with visitors' bays in a side or rear setback, or "
                "the fire department's reading.",
    ),
    Entry(
        "Parking", "Cellar ramps.",
        f"one ramp of {rules.RAMP_SINGLE_MIN_WIDTH_M:g} m or two of "
        f"{rules.RAMP_PAIR_MIN_WIDTH_M:g} m at 1 in 8; never in the front setback or building "
        f"line, and in a side or rear setback only after leaving {rules.RAMP_FIRE_CLEARANCE_M:g} "
        "m for fire vehicles",
        rules.RAMP_CLAUSE, Reading.AS_WRITTEN, _BOTH,
        ("RAMP_SINGLE_MIN_WIDTH_M", "RAMP_PAIR_MIN_WIDTH_M", "RAMP_MAX_GRADIENT",
         "RAMP_FIRE_CLEARANCE_M", "RAMP_CLAUSE"),
        choice="The layout draws the single 5.4 m ramp, as long as the cellar storey times 8, "
               "with its top on a road, outside every setback (stricter than the side and rear "
               "allowance) and out of the fire lanes. Each cellar level loses one ramp's "
               "footprint.",
    ),
    Entry(
        "Parking", "How far a cellar keeps from the property line.",
        "1.5, 2 or 3 m for sites up to 1,000, up to 2,000 and above 2,000 m²; 0.5 m more for "
        "every cellar beyond the first",
        rules.CELLAR_SETBACK_CLAUSE, Reading.INTERPRETED, _BOTH,
        ("CELLAR_SETBACK_BY_SITE_SQM", "CELLAR_EXTRA_SETBACK_PER_LEVEL_M",
         "CELLAR_SETBACK_CLAUSE", "cellar_setback_m"),
        choice="The text fixes 1.5, 2 or 3 m and 0.5 m more 'for every additional cellar floor', "
               "but not whether the upper floors keep the smaller figure. The extra is applied to "
               "every level, since the cellars are one box: the stricter reading, which matters "
               "only from two cellars. Measured from the net plot line.",
        settles="The cellar section on a sanctioned plan with two or more cellars.",
    ),
    Entry(
        "Parking", "Part of a cellar may hold utilities rather than cars.",
        f"up to {rules.CELLAR_UTILITIES_MAX_FRACTION:.0%}", rules.CELLAR_UTILITIES_CLAUSE,
        Reading.ASSUMED, _BOTH,
        ("CELLAR_UTILITIES_MAX_FRACTION", "CELLAR_UTILITIES_CLAUSE"),
        choice="Taken in full (the STP, DG sets and electrical rooms have to go somewhere), so "
               "the parking a cellar gives is not overstated. The firm can set its own share.",
        settles="The utilities the firm puts in its cellars.",
    ),
    Entry(
        "Parking", "Cellar ventilation openings.",
        "at least 2.5% of each cellar floor", "G.O.168 rule 13(c)(iii)", Reading.NOT_MODELLED,
        choice="Not drawn: the openings do not take parking floor, only a detail of the "
               "cellar's edge.",
    ),
    Entry(
        "Parking", "A cellar storey's height, which sets the ramp's length, and the most cellars "
                   "the search will dig.",
        "3 m; 3 levels", "none (the firm's standards in siteplan.workspace.json)",
        Reading.ASSUMED, (Where.LAYOUT,),
        choice="Engine defaults until the firm sets its own, and reported ASSUMED_FOR_TEST. No "
               "order limits the number of cellars.",
        settles="The firm's cellar sections.",
    ),
    Entry(
        "Parking", "Size of a parking bay and its aisle.",
        "2.5 x 5 m bays, 6 m aisles", "none (parking.py)", Reading.ASSUMED, (Where.LAYOUT,),
        choice="ENGINE_DESIGN_ASSUMPTION: no order we hold gives a bay or aisle size, so these "
               "are the engine's parking standards, not the firm's and not law. Used to lay out "
               "the surface bays and to count the cars each floor holds.",
        settles="The bay size on the firm's drawings, or a primary source that fixes one.",
    ),
    # Towers
    Entry(
        "Towers", "How long a block may be.",
        "no limit: whole stretches, 60 m and 45 m blocks are all tried",
        "none (G.O.Ms.No.65 of 2019 deleted the 40 m note)", Reading.INTERPRETED,
        (Where.LAYOUT,),
        choice="No order limits a block's length and the firm has set no standard, so the "
               "search explores lengths and keeps what the rules and the ground allow. A firm "
               "standard, once set in the workspace, is used instead.",
        settles="The firm's longest block, if it has one (max_tower_length_m in the workspace).",
    ),
    # Amenities
    Entry(
        "Amenities", "From 100 units, common amenities in a block of their own.",
        f"{rules.AMENITY_MIN_BUILT_UP_FRACTION:.0%} of the built-up area planned as a minimum "
        f"(ASSUMED_FOR_TEST), from {rules.AMENITY_MIN_UNITS} units; the 2016 cap of "
        f"{rules.AMENITY_CAP_SQFT_2016:,.0f} sft reported, not applied",
        rules.AMENITY_CLAUSE, Reading.INTERPRETED, _BOTH,
        ("AMENITY_MIN_BUILT_UP_FRACTION", "AMENITY_MIN_UNITS", "AMENITY_CAP_SQFT_2016",
         "AMENITY_CLAUSE"),
        choice="UNRESOLVED_INTERPRETATION, not settled law. Planned and checked as a minimum of "
               "3% with no cap, which is the 2012 wording, so the test is conservative. Since "
               "2016 the rule reads 'upto 3% ... (or) 50,000 Sft. whichever is lower': that "
               "adds a cap (it binds above about 1.67 million sft built-up) and may make 3% a "
               "ceiling rather than a floor. The checker says so on its finding and reports a "
               "block above the cap UNVERIFIED.",
        settles="The amenities area on a sanctioned plan of 100 units or more, against its "
                "built-up area.",
    ),
    Entry(
        "Amenities", "In a very large project, common amenities take a share of the site area.",
        f"{rules.LARGE_PROJECT_AMENITY_SHARE_OF_SITE:.0%} of the site area, in projects of more "
        f"than {rules.LARGE_PROJECT_FROM_ACRES:g} acres",
        rules.LARGE_PROJECT_AMENITY_CLAUSE, Reading.NOT_MODELLED,
        uses=("LARGE_PROJECT_FROM_ACRES", "LARGE_PROJECT_AMENITY_SHARE_OF_SITE",
              "LARGE_PROJECT_AMENITY_CLAUSE"),
        choice="Read on 2026-10-03 on p.16 of the 2012 text, where it stands under row housing "
               "(rule 9(o)) and cluster housing (rule 10(i)). Rule 8, group development, has no "
               "such clause, so it is not applied to a group scheme, whose amenities are rule "
               "15(a)(x)'s. Carried in ResolvedRules as an open reading.",
    ),
    # Handover, fees and options
    Entry(
        "Handover and fees", "Part of the built-up area is handed over by notarised affidavit "
                             "before the sanction is released.",
        f"{rules.MORTGAGE_FRACTION:.0%} of the built-up area, on the ground, first or second "
        "floor",
        rules.MORTGAGE_CLAUSE, Reading.NOT_MODELLED,
        uses=("MORTGAGE_FRACTION", "MORTGAGE_CLAUSE"),
        choice="Defined in rules.py but not used: it decides which flats sell first, not the "
               "drawing.",
    ),
    Entry(
        "Handover and fees", "Group housing on more than 3,000 m² pays a shelter fee for EWS "
                             "housing.",
        "a fee on 20% of the site area, Rs 400-750 per m² by authority",
        "G.O.168 rule 11 as substituted by G.O.Ms.No.7 of 2016 (Amendment 12)",
        Reading.NOT_MODELLED,
        choice="A fee, so nothing on the drawing. It replaced the 2012 rule's 20% of the land.",
    ),
    Entry(
        "Handover and fees", "On plots over 2,000 m², TDR buys extra floors by road width.",
        "up to 3, 4 or 5 floors on 40, 60 or 80 ft roads", rules.TDR_EXTRA_FLOORS_CLAUSE,
        Reading.INTERPRETED, (Where.FLOORS,),
        ("TDR_EXTRA_FLOORS_BY_ROAD_M", "TDR_EXTRA_FLOORS_ABOVE_PLOT_SQM",
         "TDR_EXTRA_FLOORS_CLAUSE", "tdr_extra_floors"),
        choice="Shown by the floors calculator beside its answer, never in it: an option the "
               "owner buys. The 40, 60 and 80 ft roads are taken as Table IV's 12, 18 and 24 m, "
               "as Hyderabad names them. The rule modifies earlier provisions that are unread.",
        settles="A sanctioned scheme that used TDR floors, and the provisions this one modifies.",
    ),
)


def counts(entries: tuple[Entry, ...] = INVENTORY) -> dict[Reading, int]:
    return {reading: sum(e.reading is reading for e in entries) for reading in Reading}


def _summary(entries: tuple[Entry, ...]) -> str:
    tally = ", ".join(f"{n} {reading.value}" for reading, n in counts(entries).items())
    return f"{len(entries)} rules: {tally}."


def render_text(entries: tuple[Entry, ...] = INVENTORY) -> str:
    lines = []
    for topic, group in groupby(entries, key=lambda e: e.topic):
        lines += ["", topic.upper()]
        for e in group:
            where = ", ".join(w.value for w in e.applied_in) or "not applied"
            lines.append(f"  [{e.reading.value}] {e.rule}")
            lines.append(f"      value:   {e.value}")
            lines.append(f"      clause:  {e.clause}  ({where})")
            if e.choice:
                lines.append(f"      reading: {e.choice}")
            if e.settles:
                lines.append(f"      settles: {e.settles}")
    return "\n".join([*lines, "", _summary(entries)]).lstrip("\n")


def render_markdown(entries: tuple[Entry, ...] = INVENTORY) -> str:
    def cell(text: str) -> str:
        return text.replace("|", "/")

    lines = [
        "| Topic | Rule | Value | Clause | Reading | Our choice / what settles it |",
        "|---|---|---|---|---|---|",
    ]
    for e in entries:
        note = " ".join(part for part in (e.choice, e.settles and f"Settled by: {e.settles}")
                        if part)
        lines.append(" | ".join(["", *map(cell, (e.topic, e.rule, e.value, e.clause,
                                                  e.reading.value, note)), ""]).strip())
    return "\n".join([*lines, "", _summary(entries)])
