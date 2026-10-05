"""Every rule the engine applies or knowingly leaves out, and how each one was read.

The values are read from `rules.py`, so changing a constant there changes this list. How each
rule was read is written beside it by hand, and `tests/test_inventory.py` fails when a clause in
`rules.py` has no entry here, when an entry says a module applies a rule that module never uses,
or when any module, in any package, names a rule its entry says is not applied, outside the
places the entry says carry it as data.

This is the list the firm reviews. INTERPRETED and ASSUMED entries are where our reading could
be wrong, and each names the evidence that would settle it: usually a sanctioned plan.
"""

from __future__ import annotations

import math
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
    RESOLVER = "resolved rules"  # legal/: the bands, limits and values the validator, the
    # optimizer and `siteplan envelope` read (the legacy layout and checker do not)


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
    # Where a rule that is not applied is still carried as data and reported (a value in
    # ResolvedRules, a clause cited as a source), with nothing decided by it.
    carried_in: tuple[Where, ...] = ()


def _road_widths() -> str:
    runs = groupby(rules.TABLE_IV, key=lambda band: band.min_road_m)
    spans = [(road, list(bands)[-1].up_to_m) for road, bands in runs]
    parts = [f"{road:g} m up to {up_to:g} m" for road, up_to in spans[:-1]]
    return ", ".join([*parts, f"{spans[-1][0]:g} m above {spans[-2][1]:g} m"])


def _setbacks() -> str:
    *rows, top = rules.TABLE_IV
    parts = [f"{band.min_open_space_m:g} m up to {band.up_to_m:g} m" for band in rows]
    return ", ".join([*parts, f"{top.min_open_space_m:g} m above {top.above_m:g} m"])


def _plot_class(first: rules.TableIIILine) -> str:
    if math.isinf(first.up_to_sqm):
        return f"above {first.above_sqm:,.0f} m²"
    return (f"under {first.up_to_sqm:,.0f} m²" if first.above_sqm == 0
            else f"{first.above_sqm:,.0f}-{first.up_to_sqm:,.0f} m²")


def _table_iii_heights() -> str:
    """Table III's permissible heights, a row at a time (** is above 15 m and below 18 m)."""
    rows = []
    for row in sorted({line.row for line in rules.TABLE_III}):
        lines = [line for line in rules.TABLE_III if line.row == row]
        heights = ", ".join(f"{line.up_to_m:g}{'**' if line.below else ''}" for line in lines)
        rows.append(f"row {row} ({_plot_class(lines[0])}): {heights} m")
    return "; ".join(rows)


_BOTH = (Where.CHECKER, Where.LAYOUT)
_TDR_LOW, _TDR_HIGH = rules.TDR_BAND_M
_TDR_SMALL, _TDR_LARGE = rules.TDR_PLOT_RANGE_SQM
# The smallest net plot the resolver leaves UNVERIFIED rather than short (rule 7(a)(iii)).
_NEAR_MISS_SQM = rules.MIN_HIGH_RISE_PLOT_SQM * (1 - rules.ROAD_WIDENING_SHORTFALL_ALLOWANCE)

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
               "above the ground floor. Rule 5's own heading calls the buildings it governs "
               "'below 18m in height inclusive of Stilt / Parking Floor' (p.9), which leans to "
               "counting the stilt for the class. The floors calculator gives the answer both "
               "ways.",
        settles="A sanctioned stilt + N floors high-rise whose approved setback or road width "
                "fits one reading and not the other. The firm's own Dhulapally drawing (not "
                "sanctioned) keeps the setbacks of its blocks without their stilt.",
    ),
    Entry(
        "Height", "Parking floors above the ground floor are left out of the height that picks "
                  "the Table IV row.",
        "left out of the height", rules.PARKING_FLOOR_HEIGHT_CLAUSE, Reading.NOT_MODELLED,
        uses=("PARKING_FLOOR_HEIGHT_CLAUSE",), carried_in=(Where.RESOLVER,),
        choice="Podium and upper-floor parking are unsupported: the layout parks in the stilt, "
               "on the surface and in cellars only, so it never has a parking floor to leave "
               "out. Needed once a scheme parks on a podium or upper floors. The resolved rules "
               "cite the clause as one source of the open stilt reading (stilt_in_rule_height), "
               "with nothing decided by it: it leaves out parking floors above the ground floor, "
               "and a stilt is at ground level.",
    ),
    Entry(
        "Height", "A building below high-rise stands at most as tall as its plot size lets it, "
                  "and takes its setbacks from the Table III line of its height.",
        _table_iii_heights(), rules.TABLE_III_CLAUSE, Reading.AS_WRITTEN,
        (Where.LOOKUP, Where.RESOLVER),
        ("TABLE_III", "TABLE_III_CLAUSE", "TABLE_III_ROAD_UP_TO_M", "table_iii_line",
         "table_iii_lines"),
        choice="Read on 2026-10-03 from the page images of the 2012 order (pp.9-10), the parking "
               "column of rows 1 to 3 as G.O.Ms.No.7 of 2016 amended it; no later order read "
               "changes a figure (G.O.Ms.No.245 of 2012 is unread). The resolver gives every "
               "height below 21 m a band, the lines of the plot's row, each with its setbacks, "
               "road and permission; the lookup (`siteplan rules`, the rules_for_height tool) "
               "answers for a plot and a road; the legacy layout still refuses a building "
               "below 21 m and the legacy checker reports it NOT_CHECKED. A height is read with "
               "the stilt left out (rule 5(c)); the plot is the net plot (rule 5(f)(ii)); a "
               "height above the last line of the plot's row is not permitted, and between 18 "
               "and 21 m no order read gives a line at all: G.O.Ms.No.95 of 2026 allows 18-21 m "
               "on 750-2,000 m² through TDR and says nothing of the setback, so that range is "
               "UNVERIFIED with no setback, never a pass. A plot of exactly 50 m² falls between "
               "rows 1 and 2 by the labels and is taken in row 2.",
    ),
    Entry(
        "Height", "The stilt floor is left out of the height Table III is read on.",
        "left out; not under 2.5 m high (4.5 m with a mechanical parking system and lift)",
        rules.TABLE_III_STILT_CLAUSE, Reading.AS_WRITTEN, (Where.LOOKUP, Where.RESOLVER),
        ("TABLE_III_STILT_CLAUSE",),
        choice="Rule 5(c), p.10, says so without a reading to choose. It is the opposite of the "
               "open reading for Table IV and the high-rise class (stilt_in_rule_height), where "
               "rule 5's own heading, 'Buildings below 18m in height inclusive of Stilt / Parking "
               "Floor', leans to counting the stilt for the class. A block is judged by both: "
               "the class on the reading, the Table III line without the stilt "
               "(HeightRules.band_for_block).",
    ),
    Entry(
        "Height", "A stilt floor is at least this high, a parking floor with a mechanical "
                  "system and lift more.",
        f"{rules.STILT_MIN_HEIGHT_M:g} m; {rules.MECHANICAL_PARKING_FLOOR_MIN_HEIGHT_M:g} m",
        rules.TABLE_III_STILT_CLAUSE, Reading.NOT_MODELLED,
        uses=("STILT_MIN_HEIGHT_M", "MECHANICAL_PARKING_FLOOR_MIN_HEIGHT_M"),
        choice="The stilt's height is the firm's standard (the brief); nothing holds it to 2.5 m "
               "yet. The 4.5 m is rule 5(c)'s, written for non-high-rise buildings.",
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
        f"{rules.GROUP_DEVELOPMENT_MIN_ROAD_M:g} m, existing", rules.GROUP_DEVELOPMENT_ROAD_CLAUSE,
        Reading.AS_WRITTEN, (Where.RESOLVER,),
        ("GROUP_DEVELOPMENT_MIN_ROAD_M", "GROUP_DEVELOPMENT_ROAD_CLAUSE"),
        choice="The resolver asks it of every band below 21 m on a group development scheme, "
               "so a block of that height on a road under 12 m is prohibited. Above 21 m the "
               "Table IV road check asks 12 m or more anyway, though of the master-plan width "
               "when one is given. The legacy checker does not check it on its own; 'black "
               "topped' is not a thing a survey shows.",
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
        f"blocks above {rules.PATHWAY_MAX_BLOCK_HEIGHT_M:g} m on a road; a pathway is "
        f"{rules.PATHWAY_WIDTH_M:g} m wide", rules.PATHWAY_CLAUSE,
        Reading.AS_WRITTEN, (Where.CHECKER, Where.RESOLVER),
        ("PATHWAY_MAX_BLOCK_HEIGHT_M", "PATHWAY_WIDTH_M", "PATHWAY_CLAUSE"),
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
    Entry(
        "Road", "Above 15 m and below 18 m a block needs a road at least this wide, on plots "
                "of 1,000 m² and more.",
        f"{rules.TABLE_III_TOP_TIER_MIN_ROAD_M:g} m", rules.TABLE_III_TOP_TIER_CLAUSE,
        Reading.AS_WRITTEN, (Where.LOOKUP, Where.RESOLVER),
        ("TABLE_III_TOP_TIER_MIN_ROAD_M", "TABLE_III_TOP_TIER_CLAUSE"),
        choice="Rule 5(e), p.10, for the '18**' lines of rows 9, 10 and 11.",
    ),
    Entry(
        "Road", "The road a block below high-rise needs by its use (Table II, category B).",
        f"{rules.TABLE_II_B1_ROAD_M:g} m for stilt or cellar and up to "
        f"{rules.TABLE_II_B1_MAX_FLOORS} floors; {rules.TABLE_II_B2_ROAD_M:g} m for six "
        f"floors, more than "
        f"{rules.TABLE_II_B2_UNITS_OVER} units, a group development scheme, or up to 18 m "
        "otherwise", rules.TABLE_II_CLAUSE, Reading.INTERPRETED, (Where.RESOLVER,),
        ("TABLE_II_B1_ROAD_M", "TABLE_II_B1_MAX_FLOORS", "TABLE_II_B2_ROAD_M",
         "TABLE_II_B2_UNITS_OVER", "TABLE_II_CLAUSE"),
        choice="Applied by the resolver to the bands below 21 m (not by the lookup, the layout "
               "or the checker). Table II counts floors and units, which ResolvedRules never "
               "holds (heights are metres), so a block up to 15 m is read as 'up to 5 floors' "
               "(9 m) and one above it as six floors (12 m), the line Table III's own 15 m "
               "draws and rule 5(e) confirms with its 12 m above 15 m. A scheme of more than "
               "100 units needs 12 m whatever its height, which the validator knows (the "
               "units), not the rules.",
        settles="A sanctioned non-high-rise group scheme on a 9 m road with six floors or more "
                "than 100 units, or one refused for them.",
    ),
    Entry(
        "Road", "A single plot sub-division's independent access.",
        f"{rules.SUBDIVISION_PATHWAY_M[0]:g} m for an individual residential building, "
        f"{rules.SUBDIVISION_PATHWAY_M[1]:g} m for non-high-rise group housing",
        rules.SUBDIVISION_PATHWAY_CLAUSE, Reading.NOT_MODELLED,
        uses=("SUBDIVISION_PATHWAY_M", "SUBDIVISION_PATHWAY_CLAUSE"),
        choice="Rule 4(f), p.8: a plot cut out of a larger holding by a sub-division the "
               "authority approved. The engine plans a whole site, so it never meets one.",
    ),
    Entry(
        "Road", "A site on more than one road keeps the front setback towards the bigger road.",
        "front on the bigger road, column 10 on the other sides",
        rules.TABLE_III_BIGGER_ROAD_CLAUSE, Reading.NOT_MODELLED,
        uses=("TABLE_III_BIGGER_ROAD_CLAUSE",),
        choice="The site model knows the access road, not which of the roads drawn beside the "
               "plot abut it. An individual residential building may choose its front; a "
               "group scheme does not.",
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
        Reading.INTERPRETED, (Where.RESOLVER,),
        ("ROAD_WIDENING_SHORTFALL_ALLOWANCE", "ROAD_WIDENING_SHORTFALL_CLAUSE"),
        choice=f"The text does not say {rules.ROAD_WIDENING_SHORTFALL_ALLOWANCE:.0%} of what; "
               f"the resolver takes it of the {rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m² minimum and "
               "never grants it. A site that surrenders land for road widening and falls short "
               f"of the minimum by no more than that (a net plot of {_NEAR_MISS_SQM:,.0f} m² or "
               "more) keeps its plot-size ground unmet but UNVERIFIED, citing the clause, so the "
               "plot alone never prohibits a high-rise there: the high-rise eligibility is "
               "UNVERIFIED unless the road prohibits it. Otherwise the ground is simply unmet. "
               "The independent validator's plot-size check reads it the same way "
               "(rules.high_rise_plot_met): UNVERIFIED for such a site, never a FAIL. The legacy "
               "checker, the height search and the floors calculator do not use the allowance: "
               "they hold the net plot to the minimum, so such a site still fails there.",
        settles="A sanctioned high-rise on a site left under the minimum by road widening: how "
                "far short it was, and of what the share was taken.",
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
        carried_in=(Where.RESOLVER,),
        choice="Carried as data and reported, never applied. The prototype's layout and checker "
               "do not model it. The resolved rules carry both distances "
               "(ResolvedRules.electrical), and the validator reports them UNVERIFIED wherever "
               "the survey marks a line: the site model holds a marked line without its "
               "geometry or height, so no distance is measured, passed or failed. Where a survey "
               "feature gives a corridor, the envelope keeps that corridor clear as drawn, "
               "citing rule 3(c), without these distances. Rule 3(c)(ii), the green belt and "
               "10 m roads under a tower line, is not modelled at all.",
    ),
    Entry(
        "Plot", "A plot of 750 m² and above earmarks a corner for public utilities such as a "
                "distribution transformer.",
        f"{rules.PUBLIC_UTILITY_AREA_M[0]:g} x {rules.PUBLIC_UTILITY_AREA_M[1]:g} m, plots from "
        f"{rules.PUBLIC_UTILITY_AREA_FROM_SQM:g} m²", rules.PUBLIC_UTILITY_AREA_CLAUSE,
        Reading.NOT_MODELLED,
        uses=("PUBLIC_UTILITY_AREA_M", "PUBLIC_UTILITY_AREA_FROM_SQM",
              "PUBLIC_UTILITY_AREA_CLAUSE"),
        choice="Rule 5(f)(viii), p.10, 'subject to mandated public safety requirements'. The "
               "corner is not placed or reserved.",
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
        choice="Read on 2026-10-01 from p.17, clause (b), 'The Front setback shall be as per "
               "Table-III of rule-5 & Table-IV of rule-7 for Non High Rise & High Rise buildings "
               "respectively'; corrected on 2026-10-03 (A2): that sentence is rule 12(b), "
               "written for 'U' type commercial buildings with a central courtyard, and the "
               "high-rise front is rule 7(a)(xi), p.14, the higher of this column and the "
               "Table III Building Line. The two differ only for exactly 21 m on a road above "
               "30 m (see the entry below); the legacy layout and checker keep column 4 there.",
    ),
    Entry(
        "Setbacks", "The front of a block below high-rise is the Building Line of its Table III "
                    "line, by the abutting road's width; the other sides keep column 10.",
        "front 3, 4, 5, 6 or 7.5 m for a road up to 12, 18, 24, 30 m or wider (plots from "
        "300 m²); other sides by plot size and height", rules.TABLE_III_CLAUSE,
        Reading.AS_WRITTEN, (Where.LOOKUP, Where.RESOLVER),
        ("TABLE_III", "TABLE_III_ROAD_UP_TO_M", "building_line_m"),
        choice="Where a site abuts more than one road the front goes towards the bigger road "
               "(rule 5(f)(iii)); the engine knows the access road, not which others abut, so "
               "it takes the front off the access road. With a master-plan width beside the "
               "road the larger front stands and the band is UNVERIFIED. The envelope insets a "
               "band's land by the larger of its front and its other sides, which is never more "
               "lenient than the law and costs a little room where the front is the smaller.",
    ),
    Entry(
        "Setbacks", "A road width given in feet is reckoned as the order's round metres.",
        "60 ft is 18 m, 40 ft 12 m, 80 ft 24 m, 100 ft 30 m", rules.ROAD_WIDTH_CONVERSION_CLAUSE,
        Reading.AS_WRITTEN, (Where.LOOKUP, Where.RESOLVER),
        ("ROAD_WIDTH_FEET", "ROAD_FEET_TOLERANCE_M", "ROAD_WIDTH_CONVERSION_CLAUSE",
         "reckoned_road_width_m", "building_line_m"),
        choice="Rule 5(f)(xvii), p.11, says the conversion 'shall be reckoned for the road widths "
               "only'. The engine keeps 60 ft as 18.288 m, which Table III's 'above 18 m' would "
               "put a column too far (a 5 m front for 4 m), so a width within 5 mm of a listed "
               "number of feet counts as the listed metres. A width typed in metres (18.3 m) is "
               "taken as it stands. Table IV's road test is 'at least', so it is not affected.",
    ),
    Entry(
        "Setbacks", "A high-rise's front is the higher of Table IV column 4 and the Building Line "
                    "of Table III.",
        "differs from column 4 only for exactly 21 m on a road above 30 m: 7.5 m, not 7 m",
        rules.BUILDING_LINE_HIGH_RISE_CLAUSE, Reading.AS_WRITTEN, (Where.RESOLVER,),
        ("BUILDING_LINE_HIGH_RISE_CLAUSE",),
        choice="Rule 7(a)(xi), p.14. Every Table IV figure above 21 m (8 m and up) is already "
               "above the largest Building Line, 7.5 m; the first row, 7 m, is not, so only the "
               "band of exactly 21 m carries a front, and only on a road above 30 m. The "
               "legacy layout and checker keep column 4 on the front.",
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
        "Setbacks", "A block below high-rise may move setback from one side to another, never "
                    "from the front.",
        f"{rules.SETBACK_TRANSFER_300_TO_750_M:g} m on a plot of 300-750 m², "
        f"{rules.SETBACK_TRANSFER_ABOVE_750_M:g} m above 750 m² (keeping "
        f"{rules.SETBACK_TRANSFER_MIN_OTHER_SIDE_M:g} m on the other side and a minimum building "
        "line), without exceeding the plinth area",
        rules.SETBACK_TRANSFER_CLAUSE, Reading.NOT_MODELLED,
        uses=("SETBACK_TRANSFER_300_TO_750_M", "SETBACK_TRANSFER_ABOVE_750_M",
              "SETBACK_TRANSFER_MIN_OTHER_SIDE_M", "SETBACK_TRANSFER_CLAUSE"),
        choice="Rule 5(f)(viiii) and (ixi), p.10: a design option, for the optimizer later. "
               "Every side keeps its full Table III figure here. The plinth area it may not "
               "exceed is not a quantity the engine holds.",
    ),
    Entry(
        "Setbacks", "A narrow plot (up to 400 m², four times as long as wide) may compensate its "
                    "side setbacks in the front and rear.",
        f"sides of {rules.NARROW_PLOT_MIN_SIDE_M[0][1]:g} m up to "
        f"{rules.NARROW_PLOT_MIN_SIDE_M[0][0]:g} m of height, "
        f"{rules.NARROW_PLOT_MIN_SIDE_M[1][1]:g} m up to {rules.NARROW_PLOT_MIN_SIDE_M[1][0]:g} m",
        rules.NARROW_PLOT_CLAUSE, Reading.NOT_MODELLED,
        uses=("NARROW_PLOT_MAX_SQM", "NARROW_PLOT_LENGTH_TO_WIDTH", "NARROW_PLOT_MIN_SIDE_M",
              "NARROW_PLOT_CLAUSE"),
        choice="Rule 5(f)(xi), pp.10-11, for narrow plots only (it does not apply to 'made-up "
               "plots'). The engine plans sites of thousands of square metres, so it never "
               "meets one.",
    ),
    Entry(
        "Setbacks", "An owner who surrenders land for road widening may take concessions in a "
                    "block below high-rise's setbacks, through the concession or through TDR.",
        "building line 6, 3 or 2 m for a road of 30 m or more, 18 m to under 30 m, under 18 m; "
        "side and rear 2, 2.5 or 3 m up to 12, 15 or 18 m of height",
        f"{rules.ROAD_WIDENING_NON_HIGH_RISE_CLAUSE}; {rules.TDR_NON_HIGH_RISE_SETBACK_CLAUSE}",
        Reading.NOT_MODELLED,
        uses=("ROAD_WIDENING_NON_HIGH_RISE_BUILDING_LINE_M",
              "ROAD_WIDENING_NON_HIGH_RISE_SIDE_REAR_M", "ROAD_WIDENING_NON_HIGH_RISE_CLAUSE",
              "TDR_NON_HIGH_RISE_SETBACK_CLAUSE"),
        carried_in=(Where.RESOLVER,),
        choice="G.O.Ms.No.7 of 2016, Amendment 16 (p.5), is the owner's choice of one reward "
               "among TDR, extra floors and these concessions; G.O.Ms.No.95 of 2026, rule "
               "17(d)(ix), lets a non-high-rise building relax its setbacks through TDR down to "
               "the same minimums. Never applied: a surrendering site's blocks keep Table III in "
               "full, stricter than the law. The resolved rules carry it as data, a concession "
               "citing both clauses with a note that the engine does not apply it "
               "(ResolvedRules.setbacks.concessions, written to `siteplan envelope`'s "
               "rules.json); nothing reads it.",
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
    Entry(
        "Spacing", "Two blocks below high-rise stand at least the side setback of the taller "
                   "apart, which is Table III column 10; the gap is not counted as tot-lot.",
        "the taller block's column 10", f"{rules.NON_HIGH_RISE_SPACING_CLAUSE}; "
        f"{rules.GROUP_SCHEME_SPACING_CLAUSE}", Reading.AS_WRITTEN,
        (Where.LOOKUP, Where.RESOLVER),
        ("NON_HIGH_RISE_SPACING_CLAUSE", "GROUP_SCHEME_SPACING_CLAUSE", "table_iii_line"),
        choice="Rule 5(f)(xiii) says 'the tallest block', so two blocks below 21 m need no open "
               "reading. What a block below 21 m and a high-rise keep between them is open: "
               "rule 8(j) says Column 10 of Table III or Column 4 of Table IV 'as the case may "
               "be' and never which; the same reading as two high-rise blocks of different "
               "heights (mixed_height_spacing).",
        settles="A sanctioned Group Development plan with a block below 21 m beside a high-rise.",
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
        choice="Not applied. G.O.168's rule 15(a)(i) named NBC 2005; G.O.Ms.No.50 of 2019, "
               "Amendment-1, substituted it with NBC 2016 'other than heights and setbacks' "
               "(read 2026-10-03, p.1), so the edition is no longer the question; whether HMDA "
               "enforces these particular figures is not shown by any document we hold.",
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
    Entry(
        "Open space", "A block below high-rise has a greenery strip along the frontage, and on a "
                      "plot above 300 m² a continuous planting strip on the other sides.",
        f"{rules.NON_HIGH_RISE_FRONTAGE_STRIP_M:g} m along the frontage; "
        f"{rules.NON_HIGH_RISE_PERIPHERY_STRIP_M:g} m on the remaining sides above "
        f"{rules.NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM:g} m²",
        rules.NON_HIGH_RISE_GREEN_STRIP_CLAUSE, Reading.AS_WRITTEN, (Where.RESOLVER,),
        ("NON_HIGH_RISE_FRONTAGE_STRIP_M", "NON_HIGH_RISE_PERIPHERY_STRIP_M",
         "NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM", "NON_HIGH_RISE_GREEN_STRIP_CLAUSE"),
        choice="Rule 5(f), p.10. Within the setback, never added to it. G.O.Ms.No.7 of 2016 "
               "does not touch these (its Amendment 8 is the high-rise 2 m strip of rule "
               "7(viii)), nor does any later order read. Carried on each band below 21 m "
               "(Band.green_strip_m) and drawn as a layer of the envelope; the legacy layout "
               "plans high-rise blocks only, so it never draws them.",
    ),
    Entry(
        "Open space", "A residential plot above 750 m² with no high-rise keeps a smaller share "
                      "as organised open space.",
        f"{rules.NON_HIGH_RISE_OPEN_SPACE_FRACTION:.0%} of the site; pockets at least "
        f"{rules.NON_HIGH_RISE_OPEN_SPACE_MIN_WIDTH_M:g} m wide and "
        f"{rules.NON_HIGH_RISE_OPEN_SPACE_MIN_POCKET_SQM:g} m², plots above "
        f"{rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM:g} m²",
        rules.NON_HIGH_RISE_OPEN_SPACE_CLAUSE, Reading.NOT_MODELLED,
        uses=("NON_HIGH_RISE_OPEN_SPACE_FRACTION", "NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM",
              "NON_HIGH_RISE_OPEN_SPACE_MIN_WIDTH_M", "NON_HIGH_RISE_OPEN_SPACE_MIN_POCKET_SQM",
              "NON_HIGH_RISE_OPEN_SPACE_CLAUSE"),
        choice="Rule 5(f)(vi), p.10, for the plots Table III governs. A group development scheme "
               "(rule 8(g)) and a high-rise site (rule 7(a)(vii)) keep 10%, the same 'over and "
               "above the setbacks', so the engine's schemes never meet the 5%. Which applies to "
               "a site that could take either depends on the design.",
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
    Entry(
        "Access", "A residential building above this height needs the prior clearance of the "
                "Fire Services Department.",
        f"{rules.FIRE_CLEARANCE_RESIDENTIAL_ABOVE_M:g} m", rules.FIRE_CLEARANCE_CLAUSE,
        Reading.NOT_MODELLED,
        uses=("FIRE_CLEARANCE_RESIDENTIAL_ABOVE_M", "FIRE_CLEARANCE_CLAUSE"),
        choice="Rule 5(f)(xvi), p.11, the only figure the order gives for fire below 21 m. A "
               "clearance is a document, not a drawing, so it is the architect's to confirm.",
    ),
    Entry(
        "Access", "A block below high-rise keeps the National Building Code's requirements other "
                "than heights and setbacks.",
        "no figure in the order", rules.NON_HIGH_RISE_NBC_CLAUSE, Reading.NOT_MODELLED,
        uses=("NON_HIGH_RISE_NBC_CLAUSE",),
        choice="Rule 15(a)(i) as G.O.Ms.No.50 of 2019 substituted it (NBC 2016; the 2012 text said "
               "2005). It gives no number, and carves out 'heights and setbacks': whether the "
               "NBC's fire-vehicle open space round a building of 15 m or more is a setback "
               "that the carve-out leaves out is not said, so no fire lane is asked of a "
               "block below 21 m and none is judged. High-rise fire access is rule 15(b)(iv), "
               "which cites NBC 2005 in the 2012 text and which no order read substitutes.",
        settles="The fire NOC of a sanctioned block of 15-21 m, or the Fire Services Department's "
                "reading.",
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
            if e.carried_in:
                where += "; carried in " + ", ".join(w.value for w in e.carried_in)
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
