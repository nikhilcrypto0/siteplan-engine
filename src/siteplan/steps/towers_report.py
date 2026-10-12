"""Step 5's report, pictures and facts, in plain words (steps/report.py's five questions)."""

from __future__ import annotations

from shapely.geometry import mapping

from siteplan import rules
from siteplan.steps import carried, gate
from siteplan.steps.drawing import Layer, Picture, frame
from siteplan.steps.report import Choice, RuleUsed, StepReport, Table
from siteplan.steps.towers import (
    DIFFERENT,
    FLAT_SQFT,
    MOST_A_COLUMN,
    MOST_CORES,
    MOST_LOWER,
    NARSINGI_FLATS_PER_ACRE,
    THREE,
    THREE_SHARE,
    TOWER_COUNTS,
    TWO,
    VARIANTS,
    Layout,
    Towers,
    checks,
    floors_of,
)

TITLE = "The towers"
DRAWN_AROUND_M = 30.0
COLOURS = {THREE: "#1f3f7a", TWO: "#7ea6dc", "core": "#555555"}


def report(t: Towers) -> StepReport:
    r = StepReport(5, TITLE, t.inputs.site, picture=None if t.stopped or not t.layouts
                   else "step5.svg")
    if t.stopped:
        r.did = ["Looked for the land left after the setbacks and the firm's flats, and "
                 "stopped: " + t.stopped + "."]
        r.stopped = "Step 5 cannot go on yet: " + t.stopped + "."
        r.happening = ["The towers stand on the land left after the setbacks (step 4) and are "
                       "built from the firm's flats, so this step needs both."]
        r.elements = ["The land left for buildings (step 4) and the firm's flat library."]
        r.choices = [Choice("The step stops instead of placing anything on a guess.",
                            "Where the towers go moves everything after them.")]
        r.output = ["Nothing placed yet: the step needs the answer below."]
        r.tables = [_carried_table(t)]
        r.questions = [t.ask] if t.ask else []
        return r
    k, s = t.kit, t.setbacks
    shortest = floors_of(k)[0].length_m if floors_of(k) else 0.0
    r.did = [
        f"Sized your two flats: 2BHK {FLAT_SQFT[TWO]:,.0f} sft and 3BHK {FLAT_SQFT[THREE]:,.0f} "
        f"sft saleable. Less the firm's {k.loading:.0%} common-area loading, at the firm's flat "
        f"depth of {k.depth_m:g} m, a 2BHK is {k.two.width_m:.2f} m wide along the corridor and "
        f"a 3BHK {k.three.width_m:.2f} m.",
        f"Built every tower floor from them: flats on both sides of a {k.corridor_m:g} m "
        f"corridor, the same flat opposite each, a {k.core_m:g} m lift and stair core for every "
        f"{k.per_core} flats a side (up to {MOST_CORES} cores). Every tower is "
        f"{k.tower_depth_m:.2f} m from east to west and longer than that from north to south "
        f"({shortest:.1f} m at the least), so each one runs north to south.",
        f"Kept, for every height from Stilt + {t.floors} (step 2) down to Stilt + "
        f"{min(t.lowest, t.floors)}, the land its setbacks leave, less the "
        f"{rules.INTERNAL_ROAD_M:g} m loop road inside the "
        f"{rules.PERIPHERAL_GREEN_STRIP_M:g} m green strip, the fire "
        "engine's turn at the gate and the water's buffer.",
        "Stood the towers in north-south columns across the plot, one or two to a column, the "
        "height's setback between any two; tried the columns packed from every place along the "
        "plot, spread evenly, and with open ground left between two.",
        f"For each layout, chose every tower's floor and height together so exactly "
        f"{THREE_SHARE:.0%} of the whole project's flats are 3BHK and the most flats stand.",
        f"Kept up to {VARIANTS} different layouts for each of {', '.join(map(str, TOWER_COUNTS))}"
        " towers, the most flats first.",
    ]
    r.happening = [
        f"Your mix is counted over the whole project, never inside one tower: some towers are "
        f"all 2BHK, some all 3BHK, some mixed, and the totals come to exactly {THREE_SHARE:.0%} "
        "3BHK.",
        "Because every floor of a tower is the same, the mix can only come out exact on some "
        "totals; that is why the flats come in round numbers, and why a tower sometimes stands a "
        "floor or two lower (it then keeps the full height's setbacks, more than it needs).",
        "Each tower's end lies on the loop road, with a 9 m driveway along it; a 6 m fire lane "
        "runs all round each tower.",
        "No tot-lot, club house or parking yet (your word): those come once you choose a layout.",
    ]
    r.elements = [
        f"The net plot (step 3): {s.widening.net.area:,.1f} m² ({t.acres:.2f} acres).",
        f"The height (step 2): at most Stilt + {t.floors}; the setbacks for each height "
        "(step 4's rules).",
        f"The main road (step 2), {s.height.road.name}: the gate is where it meets the plot.",
        f"The firm's flats: {k.source}.",
    ]
    if s.widening.water:
        r.elements.append("The water named in the project and its buffer (step 3).")
    r.elements.append("Everything step 1 found, carried on (the table at the end).")
    r.rules = _rules(t)
    r.choices = _choices(t)
    r.output, r.tables = _output(t)
    r.questions = _questions(t)
    r.files = [("step5.svg", "the first layout's picture"),
               ("step5.dxf", "the same, to open in CAD (metres)"),
               ("step5-N-towers-NN.svg", "each layout's picture, by tower count and number"),
               ("step5.json", "every number in this report, with every tower's outline")]
    return r


def _rules(t: Towers) -> list[RuleUsed]:
    out = [
        RuleUsed("Setbacks by height", "Each height keeps Table IV's open space all round; the "
                 "front the higher of that and Table III's Building Line.", rules.TABLE_IV_CLAUSE),
        RuleUsed("The front", "The higher of Table IV and the Building Line for the road.",
                 rules.FRONT_SETBACK_CLAUSE),
        RuleUsed("Setbacks below 21 m", "A tower below high-rise keeps Table III's.",
                 rules.TABLE_III_2012_CLAUSE),
        RuleUsed("Between two towers", "The taller one's setback (Table IV column 4).",
                 rules.BLOCK_GAP_NOT_OPEN_SPACE_CLAUSE),
        RuleUsed("Between two blocks in a group scheme", "Table III column 10 or Table IV "
                 "column 4, as the case may be.", rules.GROUP_SCHEME_SPACING_CLAUSE),
        RuleUsed("The internal roads", f"Loop and other roads {rules.INTERNAL_ROAD_M:g} m; the "
                 f"main approach {rules.MAIN_APPROACH_ROAD_M[0]:g} to "
                 f"{rules.MAIN_APPROACH_ROAD_M[1]:g} m.", rules.INTERNAL_ROAD_CLAUSE),
        RuleUsed("A tower opens onto a road", f"Only blocks up to "
                 f"{rules.PATHWAY_MAX_BLOCK_HEIGHT_M:g} m may be reached by a "
                 f"{rules.PATHWAY_WIDTH_M:g} m pathway; a taller one opens onto an internal "
                 "road.", rules.PATHWAY_CLAUSE),
        RuleUsed("The green strip", f"A high-rise site keeps {rules.PERIPHERAL_GREEN_STRIP_M:g} "
                 "m of planting round its edge, within the setbacks; the loop runs inside it.",
                 rules.GREEN_STRIP_2012_CLAUSE),
        RuleUsed("Fire access", f"{rules.FIRE_TENDER_MIN_WIDTH_M:g} m of motorable open space "
                 f"on all sides of a tower and a {rules.FIRE_TURNING_RADIUS_M:g} m turn.",
                 rules.FIRE_ACCESS_CLAUSE),
        RuleUsed("Driveway", f"At least {rules.DRIVEWAY_MIN_WIDTH_M:g} m wide.",
                 rules.DRIVEWAY_CLAUSE),
    ]
    if t.setbacks.widening.water:
        out.append(RuleUsed("Water's buffer", "No building in it.",
                            rules.WATER_BUFFER_2012_CLAUSE))
    return out


def _choices(t: Towers) -> list[Choice]:
    k = t.kit
    return [
        Choice(f"Your {FLAT_SQFT[TWO]:,.0f} and {FLAT_SQFT[THREE]:,.0f} sft are taken as "
               f"saleable; a flat's own floor is that less the {k.loading:.0%} common-area "
               f"loading, and its width that floor over the firm's {k.depth_m:g} m flat depth.",
               "Flats are sold by saleable area in Hyderabad; the loading and the depth are the "
               "firm's (its workspace and library)."),
        Choice(f"A tower is the firm's double-loaded block: the same flat opposite each, a core "
               f"for every {k.per_core} flats a side, 3BHKs at the ends of a side first (the "
               "corner flats); every floor the same.", "The firm's own plan (its flat library) "
               "lays its blocks this way; which flats stand where inside a tower is the "
               "engine's."),
        Choice(f"A tower runs north to south when it is longer that way than its "
               f"{k.tower_depth_m:.2f} m depth; north is the survey sheet's north (up).",
               "Your word: 'from north to south or vice versa, not horizontal'."),
        Choice(f"Towers stand in columns, one or {MOST_A_COLUMN} end to end; the columns packed "
               "side by side from every place across the plot, spread evenly, or with open "
               "ground left between two.", "The engine's way of trying layouts; the rules give "
               "only the setbacks and the gaps."),
        Choice(f"The loop road is {rules.INTERNAL_ROAD_M:g} m wide just inside the "
               f"{rules.PERIPHERAL_GREEN_STRIP_M:g} m green strip, all round the plot, so no "
               "road stops with nowhere to go; each tower's end lies on it with a 9 m driveway "
               "along that end; nothing stands within the front setback and a fire engine's "
               f"{rules.FIRE_TURNING_RADIUS_M:g} m turn of the gate.", "Rule 8(m) gives the "
               "widths, not where the roads run; a loop round the plot is the simplest that "
               "reaches every tower."),
        Choice(f"Over the whole project exactly {THREE_SHARE:.0%} of the flats are 3BHK. A "
               f"tower may stand up to {MOST_LOWER} floors lower than the most step 2 allows "
               f"(never below Stilt + {t.lowest}) when that holds the mix with more flats; it "
               "keeps the full height's setbacks and gaps.", "Your word: the mix over the whole "
               "project, never inside a tower; Stilt + 7 is the lowest worth building (your "
               "word, 2026-10-12)."),
        Choice(f"Each tower count's layouts are different ideas: the best of each arrangement "
               f"(columns, which hold two towers, where they stand, which road the lone towers "
               f"face) first, none sharing more than {1 - DIFFERENT:.0%} of its towers' ground "
               "with one shown before it.", "Your word: ten outputs to choose from."),
        Choice(f"Each layout's flats an acre are set beside the approved Narsingi scheme's, "
               f"{NARSINGI_FLATS_PER_ACRE:.0f}.", "Your check (2026-10-12): a sense check, "
               "never a rule."),
        Choice("Not checked in this step: stairs and lifts inside a core (egress), parking, the "
               "tot-lot, the club house and the roads' turns.", "They come once you choose a "
               "layout."),
    ]


def _output(t: Towers) -> tuple[list[str], list[Table]]:
    if not t.layouts:
        return [f"NO TOWER FITS: no north-south tower of the firm's flats stands on the land "
                f"left, even at Stilt + {t.lowest}."], [_carried_table(t)]
    lines = []
    for count in TOWER_COUNTS:
        group = t.groups.get(count, ())
        if group:
            best = group[0]
            lines.append(f"{count} TOWERS: {len(group)} layout{'s' if len(group) > 1 else ''}, "
                         f"the best {best.flats} flats ({best.three_flats} 3BHK, "
                         f"{best.two_flats} 2BHK), {_density(t, best)}.")
        else:
            lines.append(f"{count} TOWERS DO NOT FIT north to south on this plot within the "
                         "rules" + (f": the most that fit is {t.most}." if t.most else "."))
    if t.most and t.most not in TOWER_COUNTS:
        lines.append(f"Shown instead: {t.most}-tower layouts, the most that fit.")
    for kind in t.waiting:
        lines.append(f"The {kind.replace('_', ' ')}'s buffer waits on one answer (step 3), so "
                     "it is not counted yet.")
    lines.append("Every layout holds the mix exactly and keeps every setback, gap, road and "
                 "fire lane (checked again on the drawing: the table's last column).")
    tables = [_table(t, count) for count in sorted(t.groups) if t.groups[count]]
    return lines, [*tables, _carried_table(t)]


def _density(t: Towers, layout: Layout) -> str:
    per_acre = layout.flats / t.acres if t.acres else 0.0
    return f"{per_acre:,.0f} flats an acre ({per_acre / NARSINGI_FLATS_PER_ACRE:.0%} of Narsingi's)"


def _table(t: Towers, count: int) -> Table:
    rows = []
    for o in t.groups[count]:
        towers = "; ".join(f"T{tw.number} S+{tw.floors} {tw.floor.flats}/floor "
                           f"({tw.floor.three_flats} 3BHK) {tw.floor.length_m:.1f} m"
                           for tw in o.towers)
        held = checks(t, o)
        rows.append((str(o.number), o.idea, towers, str(o.flats),
                     f"{o.three_flats} ({o.three_flats / o.flats:.0%})", str(o.two_flats),
                     f"{o.saleable_sqft:,.0f}", _density(t, o),
                     "all held" if all(held.values()) else
                     "FAILS: " + ", ".join(name for name, ok in held.items() if not ok)))
    return Table(f"{count} towers: choose one", ("Layout", "The idea", "Towers (north to "
                                                 "south)", "Flats", "3BHK", "2BHK",
                                                 "Saleable sft", "Flats an acre", "Rules"),
                 tuple(rows))


def _questions(t: Towers) -> list[str]:
    out = []
    if t.layouts:
        shown = ", ".join(f"{c} towers" for c in sorted(t.groups) if t.groups[c])
        out.append(f"Which layout do you choose ({shown})? Each is drawn in "
                   "step5-N-towers-NN.svg; the next step lays the tot-lot, the parking and the "
                   "club house round it.")
    missing = [c for c in TOWER_COUNTS if not t.groups.get(c)]
    if missing:
        out.append(f"{', '.join(map(str, missing))} towers do not fit north to south: a tower "
                   f"has to be longer north to south than its {t.kit.tower_depth_m:.1f} m depth, "
                   "and every tower has to open onto a 9 m road. More would fit with towers of "
                   "two flats a side (about 22 by 26 m, a little wider than long). Should those "
                   "count as north-south towers?")
    return out


def _used_here(t: Towers) -> dict[str, str]:
    used = {}
    main = t.setbacks.height.road.name if not t.setbacks.stopped else None
    for item in carried.found_in(t.copy):
        if t.stopped:
            used[item.key] = "carried unchanged (this step stopped)"
        elif item.kind == carried.ROAD and item.key == main:
            used[item.key] = ("the main road: the gate is where it meets the plot; no tower in "
                              "a fire engine's turn there")
        elif item.kind == carried.WATER and t.setbacks.widening.water:
            used[item.key] = "no tower in its buffer"
        else:
            used[item.key] = "carried unchanged"
    return used


def _carried_table(t: Towers) -> Table:
    used = _used_here(t)
    return Table("Carried on from step 1 (everything a later rule may need)",
                 ("What", "In this step", "Needed later for"),
                 tuple((item.what, used[item.key], item.later)
                       for item in carried.found_in(t.copy)))


def option_pictures(t: Towers) -> list[tuple[str, Picture]]:
    """Every layout drawn on its own, to choose from."""
    return [(f"step5-{o.count}-towers-{o.number:02d}", picture(t, o)) for o in t.layouts]


def picture(t: Towers, layout: Layout | None = None) -> Picture:
    """A layout drawn whole: its setbacks, roads, driveways, fire lanes and towers with their
    flats. Without one, the first layout, titled as the step."""
    o = layout or t.layouts[0]
    s = t.setbacks
    debug = " (DEBUG RUN: not evidence)" if "DEBUG RUN" in t.inputs.site else ""
    title = (f"Step 5: {o.count} towers, layout {o.number}: {o.flats} flats "
             f"({o.three_flats} 3BHK, {o.two_flats} 2BHK)")
    pic = Picture(title, o.idea + debug, layers=[
        Layer("SETBACK", "#f08c00", 30, f"Setback for Stilt + {o.top}: no tower here",
              fill=0.22, width=0.5),
        Layer("GREEN-STRIP", "#2e8b3d", 3, f"{rules.PERIPHERAL_GREEN_STRIP_M:g} m green strip",
              fill=0.45, width=0.5),
        Layer("WATER-BUFFER", "#5cc4dd", 4, "Water's buffer: no tower", fill=0.45, width=0.5),
        Layer("ROAD", "#8c8c8c", 8, f"{rules.INTERNAL_ROAD_M:g} m loop road and the way in from "
              "the gate", fill=0.55, width=0.8),
        Layer("DRIVEWAY", "#5a5a5a", 8, "9 m driveway along each tower's end", fill=0.55,
              width=0.8),
        Layer("FIRE-LANE", "#8b0000", 14, f"{rules.FIRE_TENDER_MIN_WIDTH_M:g} m fire lane round "
              "each tower", fill=0.22, width=0.4),
        Layer("GATE-TURN", "#d62828", 1, "A fire engine's turn at the gate: no tower",
              fill=0.06, width=1.0, dash="6 4"),
        Layer("FLAT-3BHK", COLOURS[THREE], 5, f"3BHK ({FLAT_SQFT[THREE]:,.0f} sft)", fill=0.85,
              width=0.3),
        Layer("FLAT-2BHK", COLOURS[TWO], 4, f"2BHK ({FLAT_SQFT[TWO]:,.0f} sft)", fill=0.85,
              width=0.3),
        Layer("CORE", COLOURS["core"], 8, "Lift and stair core", fill=0.85, width=0.3),
        Layer("TOWER", "#111111", 7, "", width=1.6),
        Layer("NET-PLOT", "#2e8b3d", 3, "The net plot (step 3)", width=3.0),
        gate.LAYER,
        Layer("NOTES", "#222222", 7, ""),
    ])
    view = frame(t.copy.plot, DRAWN_AROUND_M)
    carried.draw(pic, carried.found_in(t.copy), view)
    net = s.widening.net
    pic.add("SETBACK", net.difference(t.lands[o.top]))
    pic.add("GREEN-STRIP", t.green)
    pic.add("WATER-BUFFER", t.water)
    pic.add("ROAD", t.loop.union(t.approach))
    pic.add("DRIVEWAY", o.driveways)
    pic.add("FIRE-LANE", o.lanes)
    pic.add("GATE-TURN", t.turn)
    for tower in o.towers:
        for kind, part in tower.parts(t.kit):
            pic.add({"core": "CORE", THREE: "FLAT-3BHK", TWO: "FLAT-2BHK"}[kind], part)
        pic.add("TOWER", tower.polygon)
        c = tower.polygon.centroid
        pic.label("NOTES", (c.x, c.y), f"T{tower.number} S+{tower.floors}\n"
                  f"{tower.flats} flats\n{tower.three_flats} 3BHK")
    pic.add("NET-PLOT", net)
    gate.draw(pic, t.gate)
    return pic


def facts(t: Towers) -> dict:
    out = {"step": 5, "title": TITLE, "site": t.inputs.site, "stopped": t.stopped,
           "question": t.ask, "carried": carried.facts(carried.found_in(t.copy), _used_here(t))}
    if t.stopped:
        return out
    k = t.kit
    return {**out,
            "brief": {"flat_sqft": FLAT_SQFT, "three_share": THREE_SHARE,
                      "tower_counts": list(TOWER_COUNTS), "variants": VARIANTS},
            "flats": {bhk: {"sqft": f.sqft, "width_m": round(f.width_m, 3)}
                      for bhk, f in ((TWO, k.two), (THREE, k.three))},
            "flat_depth_m": k.depth_m, "corridor_m": k.corridor_m, "core_m": k.core_m,
            "tower_depth_m": round(k.tower_depth_m, 3), "loading": k.loading,
            "flats_from": k.source, "most_floors": t.floors, "lowest_floors": t.lowest,
            "gap_m_by_floors": {str(f): g for f, g in t.gaps.items()},
            "acres": round(t.acres, 3), "most_towers": t.most,
            "layouts_holding_the_mix": {str(c): n for c, n in t.tried.items()},
            "groups": {str(count): [_layout_facts(t, o) for o in group]
                       for count, group in sorted(t.groups.items())},
            "waiting": list(t.waiting)}


def _layout_facts(t: Towers, o: Layout) -> dict:
    return {"layout": o.number, "idea": o.idea, "tallest_floors": o.top, "gap_m": o.gap_m,
            "flats": o.flats, "three_bhk": o.three_flats, "two_bhk": o.two_flats,
            "three_share": round(o.three_flats / o.flats, 4) if o.flats else None,
            "saleable_sqft": round(o.saleable_sqft, 1),
            "flats_per_acre": round(o.flats / t.acres, 1) if t.acres else None,
            "checks": checks(t, o),
            "towers": [{"tower": tw.number, "floors": tw.floors, "column": tw.column,
                        "road_end": tw.end, "cores": tw.floor.cores,
                        "flats_per_floor": tw.floor.flats,
                        "three_bhk_per_floor": tw.floor.three_flats,
                        "length_m": round(tw.floor.length_m, 2),
                        "depth_m": round(tw.depth_m, 2), "flats": tw.flats,
                        "outline": mapping(tw.polygon)} for tw in o.towers]}
