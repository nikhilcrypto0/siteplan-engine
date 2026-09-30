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
        choice="The engine draws no parking above the ground floor, so it never has one to leave "
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
        "Road", "Internal roads of a campus scheme.",
        "9-18 m main approach, 9 m other and loop roads, 8 m cul-de-sacs",
        "G.O.168 rule 8(m); rule 2(c) (a campus of 4,000 m² or more)", Reading.INTERPRETED,
        _BOTH,
        choice="Rule 2(c) settles that a campus of 4,000 m² or more with apartment blocks or "
               "high-rises is a Group Development Scheme, so rule 8(m) applies. The engine still "
               "draws a driveway ring to rule 13(c)(viii) (at least 4.5 m, or 6 m round a "
               "high-rise; 6 m by default). Open: "
               "whether the firm's '23 ft wide driveway' (7.0 m) is a rule 8(m) internal road, a "
               "driveway, or the 7 m rule 13(c)(vii) keeps for fire vehicles.",
        settles="The internal road widths on a sanctioned Group Development plan.",
    ),
    Entry(
        "Road", "A residential building above this height may not stand on a road that ends at "
                "the plot.",
        f"{rules.DEAD_END_MAX_HEIGHT_M:g} m, the stilt included", rules.DEAD_END_CLAUSE,
        Reading.AS_WRITTEN, (Where.FLOORS,), ("DEAD_END_MAX_HEIGHT_M", "DEAD_END_CLAUSE"),
        choice="A survey does not show where a road leads, so the architect says whether it ends "
               "at the plot: then every answer, TDR floors included, stops at 30 m; left unsaid, "
               "the floors calculator warns whenever an answer passes 30 m. Dhulapally's survey "
               "draws its roads ending at the plot; whether the 40 ft road along the east will "
               "run on is a site fact.",
    ),
    Entry(
        "Road", "The street a high-rise stands on joins a street at least 12 m wide at one end.",
        "12 m", "G.O.168 rule 15(b)(iv), bringing in NBC 2016 Part 3 4.6(a)",
        Reading.NOT_MODELLED,
        choice="Where a road leads is not on a survey, so it is not checked; Table IV already "
               "asks 12 m or more of the road a high-rise stands on.",
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
        "net plot line", "G.O.168 rule 5(f)(ii)", Reading.INTERPRETED, _BOTH,
        choice="Rule 5(f)(ii) sits in the rule for buildings below high-rise; the engine applies "
               "it to high-rise too.",
        settles="A sanctioned plan on a widened road: from which line are its setbacks drawn?",
    ),
    Entry(
        "Plot", "Without a drawn net plot, the deducted area comes off the longest boundary as "
                "a strip.",
        "longest straight run of the boundary", "none (runner.load_plot)", Reading.ASSUMED,
        (Where.LAYOUT,),
        choice="The longest side is taken as the road frontage; the gates assume the same.",
        settles="The road-widening line on the survey or the sanction plan.",
    ),
    Entry(
        "Plot", "No building within a water body's buffer, which may be open space but never "
                "the setback.",
        ", ".join(f"{kind.replace('_', ' ')} {m:g} m" for kind, m in rules.WATER_BUFFER_M.items()),
        rules.WATER_BUFFER_CLAUSE, Reading.INTERPRETED, _BOTH,
        ("WATER_BUFFER_M", "WATER_BUFFER_CLAUSE"),
        choice="The architect names the water body's class and the colour or layer the survey "
               "draws it in: a drawn channel does not show a nala's defined width, and surveyors "
               "use no standard colour. The buffer is measured from the lines drawn (a centreline "
               "would understate it by half the channel) and kept free of towers, facilities and "
               "parking; it is not counted as tot-lot, though the rule allows it. The firm's "
               "unsanctioned Suchitra drawing keeps a 9.4 m strip beside a 9.6 m channel, which "
               "looks like the 9 m class: a test fixture, not evidence.",
        settles="A sanctioned plan beside a nala or lake: which class, and what it deducted.",
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
        "Table IV column 4 all round",
        "G.O.168 rule 7(a)(xi); G.O.Ms.No.50 of 2019 heads column 4 'side and rear'",
        Reading.INTERPRETED, _BOTH,
        choice="Rule 7(a)(xi) makes the front the larger of column 4 and the Table III building "
               "line for the road (3 to 7.5 m). That exceeds column 4 only for a building up to "
               "21 m on a road wider than 30 m (7.5 m against 7), which the engine misses.",
        settles="A sanctioned plan on a road wider than 30 m.",
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
        choice="The text says 'total site area' without saying gross or net. The checker tests "
               "both and asks when they disagree; the layout aims at 10% of the net plot.",
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
        rules.PERIPHERAL_GREEN_STRIP_CLAUSE, Reading.AS_WRITTEN, (Where.CHECKER,),
        ("PERIPHERAL_GREEN_STRIP_M", "PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M",
         "PERIPHERAL_GREEN_STRIP_CLAUSE"),
        choice="The checker says whether it applies but does not look for the strip on the "
               "drawing.",
    ),
    # Access and fire
    Entry(
        "Access", "Minimum driveway width.", f"{rules.DRIVEWAY_MIN_WIDTH_M:g} m",
        rules.DRIVEWAY_CLAUSE, Reading.AS_WRITTEN, _BOTH,
        ("DRIVEWAY_MIN_WIDTH_M", "DRIVEWAY_CLAUSE"),
    ),
    Entry(
        "Access", "The layout draws the driveway wider than the minimum.",
        "6 m", "none (layout.DEFAULT_DRIVEWAY_WIDTH_M)", Reading.ASSUMED, (Where.LAYOUT,),
        choice="Wider than the 4.5 m minimum, as the firm's drives are, and the width NBC asks "
               "of the fire-tender approach round a high-rise; the firm's own drawings run 23 ft "
               "(7.0 m), so this is still narrower than theirs.",
        settles="The drive width on the firm's sanctioned plans.",
    ),
    Entry(
        "Access", "The entry and exit gates are wide enough for a fire engine.",
        f"{rules.GATE_MIN_WIDTH_M:g} m", rules.GATE_CLAUSE, Reading.AS_WRITTEN, (Where.LAYOUT,),
        ("GATE_MIN_WIDTH_M", "GATE_CLAUSE"),
        choice="The gates are drawn at the minimum on every scheme. The gate folding back "
               "against the compound wall, and 4.5 m clear under anything built over the "
               "entrance, are not drawn.",
    ),
    Entry(
        "Access", "A high-rise's drive is wide enough for fire tenders.",
        f"{rules.FIRE_TENDER_MIN_WIDTH_M:g} m", rules.FIRE_TENDER_CLAUSE, Reading.INTERPRETED,
        (Where.CHECKER,), ("FIRE_TENDER_MIN_WIDTH_M", "FIRE_TENDER_CLAUSE"),
        choice="Asked of the drive once any block is a high-rise in the state's sense (21 m), "
               "where rule 15(b)(iv) brings NBC in (NBC Part 4 3.4.4.1's note leaves "
               "fire-vehicle clearances to Part 3). NBC's own high-rise starts at 15 m, and rule "
               "15(a)(i) may bring 4.6 in from there.",
        settles="The drive on a sanctioned building of 15 to 21 m, and the fire NOC of a "
                "sanctioned high-rise.",
    ),
    Entry(
        "Access", "Fire tenders drive round a high-rise: the open space on all its sides stays "
                  "motorable, carries a 45 t tender, turns at 9 m and is never parked in.",
        "all sides; 9 m turning radius; 45 t",
        "G.O.168 rule 15(b)(iv), bringing in NBC 2016 Part 3 4.6(c)", Reading.NOT_MODELLED,
        choice="Setbacks of 7 m or more with no parking in them give the width all round, and "
               "G.O.168's own figure is wider still: a ramp may take a side or rear setback only "
               "after leaving 7 m for fire vehicles (rule 13(c)(vii)). The 9 m turn and the 45 t "
               "loading are not drawn.",
        settles="The fire NOC of a sanctioned high-rise.",
    ),
    # Parking
    Entry(
        "Parking", "Parking area as a share of the total built-up area.",
        f"{rules.PARKING_PERCENT_GHMC:g}% inside GHMC or anywhere in CURE, "
        f"{rules.PARKING_PERCENT_ELSEWHERE:g}% elsewhere in HMDA",
        f"{rules.PARKING_CLAUSE}; {rules.CURE_RULES_CLAUSE}", Reading.INTERPRETED,
        (Where.CHECKER,),
        ("PARKING_PERCENT_GHMC", "PARKING_PERCENT_ELSEWHERE", "PARKING_CLAUSE",
         "CURE_RULES_CLAUSE", "parking_percent"),
        choice="Counts the whole stilt footprint and the surface bays as parking. The text does "
               "not say whether the built-up area it is a share of includes the stilt. Inside "
               "CURE the GHMC column applies whichever corporation the site now falls in "
               "(Cyberabad, since G.O.Ms.No.55 of 2026, for Qutbullapur zone).",
        settles="The parking statement on a sanctioned plan.",
    ),
    Entry(
        "Parking", "Visitors' parking, marked on the ground.",
        "at least 10% of the Table V area", "G.O.168 rule 13(c)(xii)", Reading.NOT_MODELLED,
        choice="Not counted separately.",
    ),
    Entry(
        "Parking", "Cellars and ramps.",
        "cellar 3 m from the property line on sites over 2,000 m², +0.5 m per extra cellar; "
        "ramps 2 x 3.6 m or 1 x 5.4 m at 1 in 8, never in the front setback or building line, "
        "and in a side or rear setback only after leaving 7 m for fire vehicles",
        "G.O.168 rule 13(c)(vii), 13(c)(x)", Reading.NOT_MODELLED,
        choice="Cellar and podium parking are not modelled, so a parking shortfall is reported "
               "as NEEDS_INPUT.",
    ),
    Entry(
        "Parking", "Size of a surface parking bay and its aisle.",
        "2.5 x 5 m bays, 6 m aisles", "none (parking.py)", Reading.ASSUMED, (Where.LAYOUT,),
        choice="The rules give no bay or aisle size.",
        settles="The bay size on the firm's drawings.",
    ),
    # Amenities
    Entry(
        "Amenities", "From 100 units, common amenities in a block of their own.",
        f"at least {rules.AMENITY_MIN_BUILT_UP_FRACTION:.0%} of the built-up area, from "
        f"{rules.AMENITY_MIN_UNITS} units",
        rules.AMENITY_CLAUSE, Reading.INTERPRETED, _BOTH,
        ("AMENITY_MIN_BUILT_UP_FRACTION", "AMENITY_MIN_UNITS", "AMENITY_CLAUSE"),
        choice="Applied as a minimum of 3% with no cap, which is the 2012 wording. Since 2016 the "
               "rule reads 'upto 3% ... (or) 50,000 Sft. whichever is lower': that adds a cap "
               "(it binds above about 1.67 million sft built-up) and may make 3% a ceiling "
               "rather than a floor.",
        settles="The amenities area on a sanctioned plan of 100 units or more, against its "
                "built-up area.",
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
