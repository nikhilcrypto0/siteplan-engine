"""Step 5's report, pictures and facts, in plain words (steps/report.py's five questions)."""

from __future__ import annotations

from shapely.geometry import mapping

from siteplan import rules
from siteplan.steps import buildings, carried, gate
from siteplan.steps.drawing import Layer, Picture, frame
from siteplan.steps.report import Choice, RuleUsed, StepReport, Table
from siteplan.steps.tot_lot import (
    CUT_TOLERANCE_M,
    EDGES_TRIED,
    MEDIUM_SQM,
    NARSINGI_FLATS_PER_ACRE,
    SAME_SQM,
    SECOND_LOOK,
    STEEP,
    Option,
    Placing,
    TotLot,
)

TITLE = "The buildings and the tot-lot"
DRAWN_AROUND_M = 30.0
SHADES = ("#1f3f7a", "#2f5a9e", "#4f7fc0", "#7ea6dc", "#b3cdee")  # tallest to lowest


def report(t: TotLot) -> StepReport:
    r = StepReport(5, TITLE, t.inputs.site, picture=None if t.stopped else "step5.svg")
    if t.stopped:
        r.did = ["Looked for the land left after the setbacks and the firm's blocks, and "
                 "stopped: " + t.stopped + "."]
        if t.share is not None:
            r.did.append(f"The rules ask {t.need_sqm:,.1f} m² of tot-lot "
                         f"({t.share.fraction:.0%} of the whole plot's {t.plot_sqm:,.1f} m²); it "
                         "is not placed yet.")
        r.stopped = "Step 5 cannot go on yet: " + t.stopped + "."
        r.happening = ["The buildings stand on the land left after the setbacks (step 4) and "
                       "are the firm's blocks, so this step needs both."]
        r.elements = ["The land left for buildings (step 4) and the firm's flat library."]
        r.choices = [Choice("The step stops instead of placing anything on a guess.",
                            "Where the buildings go moves everything after them.")]
        r.output = ["Nothing placed yet: the step needs the answer below."]
        r.tables = [_carried_table(t)]
        r.questions = [t.ask] if t.ask else []
        return r
    if t.share is None:
        return _none_needed(r, t)
    s = t.setbacks
    shown = t.options or t.failed
    arms = shown[0].placing.layout.arms if shown else ()
    r.did = [
        f"Tried every height from Stilt + {s.floors} (step 2) down one floor at a time to Stilt "
        f"+ {min(t.lowest, s.floors)}, each keeping its own setbacks.",
        f"Split the land into its {len(arms)} part{'' if len(arms) == 1 else 's'} (a bent "
        "plot's arms) and laid the firm's blocks in straight rows, each part along its own "
        "longest straight edge, the tallest first and lower ones into the narrow parts, round "
        "one road idea each: a loop round the blocks, or a spine from the gate.",
        "Laid the tot-lot in what each layout's blocks leave; where that held less than the "
        "share, shortened or dropped the block that frees the most tot-lot for the fewest flats, "
        "and counted the flats lost.",
        f"Kept {len(t.options)} whole option{'' if len(t.options) == 1 else 's'}, each its "
        "buildings and its tot-lot together, for you to choose one; option 1 is set out below.",
    ]
    r.happening = [
        "Buildings first, the tot-lot last, shown together (your word, 2026-10-12): you never "
        "choose buildings blind.",
        "Straight rows along the longest straight edge leave the slanted edges, tips and thin "
        "strips over: that is where the tot-lot goes, at no cost in flats.",
        f"Lower blocks, down to Stilt + {t.lowest}, go into narrow parts like an arm before any "
        "land is called unbuildable (your word).",
        "The tot-lot stays inside the land left for buildings, never in a setback, the gap "
        "between two blocks, a fire lane, a road or in front of the gate; several medium pieces "
        "rather than one big one; a right-angled triangle at the corners beside the gate.",
        "The club house comes in the next stage: on odd land next to the biggest tot-lot "
        "piece, never at the gate (your word).",
    ]
    r.elements = [
        f"The land left after the setbacks (step 4): {s.left.area:,.1f} m², and each height's "
        "own.",
        f"The whole plot's area (step 1): {t.plot_sqm:,.1f} m² ({t.acres:.2f} acres), "
        f"{t.plot_from}.",
        f"The main road (step 2), {s.height.road.name}: the gate is where it meets the plot.",
        f"The firm's blocks: {len(t.blocks.kinds)}, from {t.blocks.source}.",
    ]
    if s.widening.water:
        r.elements.append("The water named in the project and its buffer (step 3).")
    r.elements.append("Everything step 1 found, carried on (the table at the end).")
    r.rules = _rules(t)
    r.choices = _choices(t)
    r.output, r.tables = _output(t)
    r.questions = _questions(t)
    r.files = [("step5.svg", "option 1's picture"), ("step5.dxf", "the same, to open in CAD "
               "(metres)"), ("step5-option-NN.svg", "each option's picture"),
               ("step5.json", "every number in this report, with every block and tot-lot "
                "outline")]
    return r


def _none_needed(r: StepReport, t: TotLot) -> StepReport:
    r.did = [f"Checked whether the rules ask a tot-lot of this plot ({t.plot_sqm:,.1f} m², "
             "below high-rise and below a Group Development Scheme)."]
    r.happening = ["Only a high-rise site, a Group Development Scheme or a plot above "
                   f"{rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM:,.0f} m² keeps a tot-lot."]
    r.elements = ["The plot's area (step 1) and the height (step 2)."]
    r.rules = [RuleUsed("Open space below high-rise", "Plots above "
                        f"{rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM:,.0f} m² keep "
                        f"{rules.NON_HIGH_RISE_OPEN_SPACE_FRACTION:.0%}.",
                        rules.NON_HIGH_RISE_OPEN_SPACE_CLAUSE)]
    r.output = ["No tot-lot is needed on this plot."]
    r.tables = [_carried_table(t)]
    r.picture = None
    return r


def _rules(t: TotLot) -> list[RuleUsed]:
    sh = t.share
    out = [RuleUsed(f"How much: {whom}", f"At least {sh.fraction:.0%} of the site, over and "
                    f"above the setbacks, open to the sky, in pockets at least "
                    f"{sh.min_width_m:g} m wide and {sh.min_pocket_sqm:g} m².", clause)
           for whom, clause in sh.clauses]
    out += [
        RuleUsed("Setbacks by height", "Each height keeps Table IV's open space all round.",
                 rules.TABLE_IV_CLAUSE),
        RuleUsed("Setbacks below 21 m", "A block below high-rise keeps Table III's.",
                 rules.TABLE_III_2012_CLAUSE),
        RuleUsed("Between two blocks", "The taller one's setback, never counted as tot-lot.",
                 rules.BLOCK_GAP_NOT_OPEN_SPACE_CLAUSE),
        RuleUsed("Between two blocks below 21 m", "The taller one's side setback.",
                 rules.NON_HIGH_RISE_SPACING_CLAUSE),
        RuleUsed("The internal roads", f"Loop and other roads {rules.INTERNAL_ROAD_M:g} m; the "
                 f"main approach {rules.MAIN_APPROACH_ROAD_M[0]:g} to "
                 f"{rules.MAIN_APPROACH_ROAD_M[1]:g} m.", rules.INTERNAL_ROAD_CLAUSE),
        RuleUsed("The green strip", f"A high-rise site keeps {rules.PERIPHERAL_GREEN_STRIP_M:g} "
                 "m of planting round its edge; the loop runs inside it.",
                 rules.GREEN_STRIP_2012_CLAUSE),
        RuleUsed("Fire access", f"A {rules.FIRE_TENDER_MIN_WIDTH_M:g} m motorable lane round a "
                 f"high-rise and a {rules.FIRE_TURNING_RADIUS_M:g} m turn.",
                 rules.FIRE_ACCESS_CLAUSE),
        RuleUsed("Amenities (the club house: the next stage)", "Group housing of 100 flats or "
                 f"more: at least {rules.AMENITY_MIN_BUILT_UP_FRACTION:.0%} of the flats' "
                 "built-up area, in a block of its own.", rules.AMENITY_2012_CLAUSE),
    ]
    if t.setbacks.widening.water:
        out.append(RuleUsed("Water's buffer", "No building in it; it may count as tot-lot.",
                            rules.WATER_BUFFER_2012_CLAUSE))
    return out


def _choices(t: TotLot) -> list[Choice]:
    blocks = t.blocks
    s = t.setbacks
    return [
        Choice(f"The {t.share.fraction:.0%} is of the whole plot, {t.plot_sqm:,.1f} m² "
               f"({t.plot_from}).", "Your rule (2026-10-11): the rule says 'total site area' "
               "and does not say whole or net."),
        Choice("The firm's blocks are the kit its flat library composes and a slim block of one "
               "row of the same flats beside the corridor, as long as the kit's shortest, with "
               "half its flats.", "The firm draws no slim block; this one is the engine's, from "
               f"{blocks.source}."),
        Choice(f"A bent plot is cut into arms at its narrowest neck: a cut from an inward "
               f"corner no longer than {buildings.NECK_SHARE:.0%} of the smaller piece's length; "
               f"each arm's rows run along its own longest straight edge (the main part's along "
               f"each of its {EDGES_TRIED} longest, one option each). Rows are swept from either "
               "side and the better sweep kept, so options are different ideas, not copies.",
               "Your word (2026-10-12): straight rows lined up with the longest straight edge; "
               "each arm its own. The cut and the edges are the engine's reading."),
        Choice("The deepest blocks first, the longest that fit each stretch of a row; the "
               "slim blocks then on what the deep rows leave; a block's height is the tallest "
               "the land under it allows; two blocks keep the taller one's setback between "
               "them, and every block its own from the plot's edge.", "The rules give the "
               "setbacks and the gaps; the packing is the engine's."),
        Choice(f"The loop is {rules.INTERNAL_ROAD_M:g} m inside the "
               f"{rules.PERIPHERAL_GREEN_STRIP_M:g} m green strip, round the main part (a narrow "
               "arm keeps none); the spine is the gate's own width straight in across the plot, "
               f"and nothing stands within {s.front_m + rules.FIRE_TURNING_RADIUS_M:g} m of the "
               "gate.", "Rule 8(m) gives the widths, not where the roads run; the reference "
               "plans run a loop round the blocks (Kondapur) or a spine with rows facing it "
               "(Praneeth, Silpa). Step 6 draws the roads."),
        Choice(f"The tot-lot takes each leftover piece first up to {MEDIUM_SQM:,.0f} m², the "
               "part farthest from the blocks, the largest pieces first, and only then more; "
               f"at a corner beside the gate only a right-angled triangle, its long side "
               f"{STEEP:g} times its small side, the small side toward the gate.", "Your word "
               "(2026-10-12): several medium pieces; triangles beside the gate. The reference "
               "plans' pieces run about 100 to 900 m²."),
        Choice("When the leftovers hold less than the share, each block is tried dropped and "
               "shortened to each shorter block of the firm's at either end; the change that "
               "frees the most tot-lot for each flat lost is made, until the share is held. A "
               "layout that cannot be made to hold it is not offered.", "Your word "
               "(2026-10-12): the block that frees the most tot-lot for the fewest flats."),
        Choice(f"Each option's flats an acre are set beside the approved Narsingi scheme's, "
               f"{NARSINGI_FLATS_PER_ACRE:.0f} (367 flats on 3.95 acres); one under "
               f"{SECOND_LOOK:.0%} of it or over {1 / SECOND_LOOK:.0%} is marked for a second "
               "look. Table IV's 14 m for a 45 to 50 m building is what the approved Kondapur "
               "plan's 49.98 m tower keeps all round.", "Your checks (2026-10-12): approved "
               "plans as a sense check, never as a rule."),
        Choice(f"Two layouts whose blocks differ by less than {SAME_SQM:g} m² are one option; "
               f"a pocket's {t.share.min_width_m:g} m is checked by rolling a circle that wide "
               f"(less {CUT_TOLERANCE_M * 100:g} cm) through it.", "Drawing tolerances."),
    ]


def _density(t: TotLot, p: Placing) -> str:
    per_acre = p.flats / t.acres if t.acres else 0.0
    share = per_acre / NARSINGI_FLATS_PER_ACRE
    look = " (a second look)" if share < SECOND_LOOK or share > 1 / SECOND_LOOK else ""
    return f"{per_acre:,.0f} an acre, {share:.0%} of Narsingi's{look}"


def _output(t: TotLot) -> tuple[list[str], list[Table]]:
    if not t.options and not t.failed:
        return ["No layout could be drawn: no block of the firm's fits the land."], [
            _carried_table(t)]
    lines = [f"{len(t.options)} WHOLE OPTIONS for you to choose from: the first table below. "
             "Option 1 is drawn in step5.svg and set out here; each option in "
             "step5-option-NN.svg."]
    if not t.options:
        lines.append("NO LAYOUT HOLDS THE TOT-LOT: every one's leftovers stay short of the "
                     "share, even with blocks given up; the best is drawn.")
    p = t.placings[0]
    lines.append(f"TOT-LOT NEEDED: {t.need_sqm:,.1f} m² ({t.share.fraction:.0%} of the whole "
                 f"plot's {t.plot_sqm:,.1f} m²).")
    heights: dict[int, list] = {}
    for b in p.layout.blocks:
        heights.setdefault(b.floors, []).append(b)
    lines.append("OPTION 1's BLOCKS: " + ", ".join(
        f"{len(bs)} at Stilt + {floors} ({sum(b.flats for b in bs)} flats)"
        for floors, bs in sorted(heights.items(), reverse=True)) + f": {p.flats} flats, "
        f"{_density(t, p)}.")
    lines.append(f"OPTION 1's TOT-LOT: {p.tot_lot.area:,.1f} m² in {len(p.pockets)} "
                 f"piece{'' if len(p.pockets) == 1 else 's'}, from {p.leftover.area:,.1f} m² "
                 f"of leftovers; it cost {p.flats_lost} flat{'' if p.flats_lost == 1 else 's'}.")
    for change in p.changes:
        lines.append(f"For the tot-lot: {change}.")
    used = {b.floors for b in p.layout.blocks}
    for tier in p.tiers:
        if tier.floors in used and tier.permission != "ALLOWED":
            said = "CONDITIONAL" if tier.permission == "UNVERIFIED" else tier.permission
            lines.append(f"STILT + {tier.floors} IS {said}: {tier.why}. Its setback is drawn at "
                         f"Table IV's first row, {tier.setback_m:g} m, as a stand-in; the engine "
                         "reports such a block the same way.")
    if p.short_sqm > 0:
        lines.append(f"THE LAND CANNOT HOLD THE TOT-LOT: it is short by {p.short_sqm:,.1f} m².")
    for other in t.placings[1:]:
        lines.append(f"With {other.reading} (asked in step 3): {other.flats} flats, tot-lot "
                     f"{other.tot_lot.area:,.1f} m², {other.flats_lost} flats lost."
                     + (f" SHORT BY {other.short_sqm:,.1f} m²." if other.short_sqm > 0 else ""))
    for kind in t.waiting:
        lines.append(f"The {kind.replace('_', ' ')}'s buffer waits on one answer (step 3), so "
                     "it is not counted yet.")
    for o in t.failed if t.options else ():
        lines.append(f"Not offered: {o.plan.words[0].lower() + o.plan.words[1:]} (its leftovers "
                     f"stay {o.placing.short_sqm:,.1f} m² short).")
    lines.append("The club house comes in the next stage.")
    pieces = Table("Option 1's tot-lot pieces", ("Piece", "Lies", "Area", "Stands on"),
                   tuple((str(i), pocket.lies, f"{pocket.area_sqm:,.1f} m²",
                          "; ".join(f"{kind}: {area:,.1f} m²" for kind, area in pocket.on_sqm
                                    if f"{area:,.1f}" != "0.0"))
                         for i, pocket in enumerate(p.pockets, 1)))
    return lines, [_options_table(t), pieces, _carried_table(t)]


def _options_table(t: TotLot) -> Table:
    rows = []
    for o in t.options or t.failed:
        p = o.placing
        heights = sorted({b.floors for b in p.layout.blocks}, reverse=True)
        short = max(q.short_sqm for q in o.placings)
        rows.append((str(o.number), o.plan.words,
                     f"{len(p.layout.blocks)} (Stilt + {', '.join(map(str, heights))})",
                     str(p.flats), f"{p.tot_lot.area:,.1f} m² in {len(p.pockets)}",
                     str(p.flats_lost), _density(t, p),
                     "holds it" if o.holds else f"SHORT BY {short:,.1f} m²"))
    return Table("The options: choose one", ("Option", "The idea", "Blocks", "Flats",
                                             "Tot-lot", "Flats the tot-lot cost",
                                             "Flats an acre", "Every reading of the water"),
                 tuple(rows))


def _questions(t: TotLot) -> list[str]:
    out = []
    if t.options:
        out.append(f"Which option do you choose (1 to {len(t.options)})? Each is drawn whole, "
                   "buildings and tot-lot, in step5-option-NN.svg; step 6 lays the roads, the "
                   "parking and the club house round it.")
    short = [p for p in t.placings if p.short_sqm > 0]
    if short or not t.options:
        worst = max((p.short_sqm for p in short), default=0.0)
        out.append(f"The plot cannot hold the tot-lot: it is short by {worst:,.1f} m². Should the "
                   "buildings be lower, or fewer?")
    return out


def _used_here(t: TotLot) -> dict[str, str]:
    used = {}
    main = t.setbacks.height.road.name if not t.setbacks.stopped else None
    for item in carried.found_in(t.copy):
        if t.stopped:
            used[item.key] = "carried unchanged (this step stopped)"
        elif item.kind == carried.ROAD and item.key == main and t.placings:
            used[item.key] = ("the main road: the gate is where it meets the plot; no tot-lot "
                              "in front of it")
        elif item.kind == carried.WATER and t.placings and t.placings[0].reading:
            used[item.key] = "no building in its buffer; the buffer may count as tot-lot"
        else:
            used[item.key] = "carried unchanged"
    return used


def _carried_table(t: TotLot) -> Table:
    used = _used_here(t)
    return Table("Carried on from step 1 (everything a later rule may need)",
                 ("What", "In this step", "Needed later for"),
                 tuple((item.what, used[item.key], item.later)
                       for item in carried.found_in(t.copy)))


def option_pictures(t: TotLot) -> list[tuple[str, Picture]]:
    """Every option drawn whole on its own, to choose from."""
    return [(f"step5-option-{o.number:02d}", picture(t, o.number)) for o in t.options]


def picture(t: TotLot, number: int = 0) -> Picture:
    """Option 1 as the step's picture, or option `number` titled with its idea."""
    shown = t.options or t.failed
    option: Option | None = shown[number - 1] if number else None
    p = option.placing if option else t.placings[0]
    s = t.setbacks
    title = (f"Step 5: option {number} of {len(t.options)}: {p.flats} flats" if option
             else f"Step 5: {TITLE}")
    debug = " (DEBUG RUN: not evidence)" if "DEBUG RUN" in t.inputs.site else ""
    subtitle = (option.plan.words + debug) if option else t.inputs.site
    floors = sorted({b.floors for b in p.layout.blocks} | {tier.floors for tier in p.tiers},
                    reverse=True)
    shades = {f: SHADES[min(i, len(SHADES) - 1)] for i, f in enumerate(floors)}
    pic = Picture(title, subtitle, layers=[
        Layer("SETBACK", "#f08c00", 30, "Setback: no building here", fill=0.25, width=0.5),
        Layer("FIRE-LANE", "#8b0000", 14, f"Where the {rules.FIRE_TENDER_MIN_WIDTH_M:g} m fire "
              "lane can run (beside a high-rise)", fill=0.6, width=0.5),
        Layer("WATER-BUFFER", "#5cc4dd", 4, "Water's buffer from the line drawn", fill=0.45,
              width=0.5),
        Layer("ROAD", "#8c8c8c", 8, "The road idea: a loop round the blocks, or a spine",
              fill=0.35, width=0.8, dash="4 3"),
        Layer("GATE-ZONE", "#d62828", 1, "In front of the gate: no tot-lot", fill=0.06,
              width=1.0, dash="6 4"),
        *(Layer(f"STILT-{f}", shades[f], 5, f"A Stilt + {f} block", fill=0.8, width=0.5)
          for f in floors if any(b.floors == f for b in p.layout.blocks)),
        Layer("TOT-LOT", "#9acd32", 3, "The tot-lot", fill=0.9, width=1.5),
        Layer("NET-PLOT", "#2e8b3d", 3, "The net plot (step 3)", width=3.0),
        gate.LAYER,
        Layer("NOTES", "#222222", 7, ""),
    ])
    view = frame(t.copy.plot, DRAWN_AROUND_M)
    carried.draw(pic, carried.found_in(t.copy), view)
    edge = s.widening.net.difference(p.room)
    pic.add("SETBACK", edge)
    if s.fire_lane is not None:
        pic.add("FIRE-LANE", s.fire_lane.intersection(edge))
    for water in s.widening.water:
        pic.add("WATER-BUFFER", water.kept_free)
    pic.add("ROAD", p.layout.roads)
    pic.add("GATE-ZONE", p.gate_zone)
    for b in p.layout.blocks:
        pic.add(f"STILT-{b.floors}", b.polygon)
        c = b.polygon.centroid
        pic.label("NOTES", (c.x, c.y), f"S+{b.floors} · {b.flats}")
    pic.add("TOT-LOT", p.tot_lot)
    pic.add("NET-PLOT", s.widening.net)
    gate.draw(pic, p.gate)
    for pocket in p.pockets:
        spot = pocket.polygon.representative_point()
        pic.label("NOTES", (spot.x, spot.y), f"TOT-LOT {pocket.area_sqm:,.0f} m²")
    return pic


def facts(t: TotLot) -> dict:
    out = {"step": 5, "title": TITLE, "site": t.inputs.site, "stopped": t.stopped,
           "question": t.ask, "carried": carried.facts(carried.found_in(t.copy), _used_here(t))}
    if t.stopped or t.share is None:
        if t.share is None:  # stopped before the share was known, or none is needed
            return {**out, "needed": None if t.stopped else False, "need_sqm": None if t.stopped
                    else 0.0}
        return {**out, "needed": True, "need_sqm": round(t.need_sqm, 2)}
    return {**out,
            "needed": True, "share": t.share.fraction, "because": t.share.why,
            "plot_sqm": round(t.plot_sqm, 2), "plot_from": t.plot_from,
            "acres": round(t.acres, 3), "need_sqm": round(t.need_sqm, 2),
            "net_plot_need_sqm": round(t.net_need_sqm, 2),
            "min_width_m": t.share.min_width_m, "min_pocket_sqm": t.share.min_pocket_sqm,
            "blocks": [{"what": k.what, "length_m": round(k.length_m, 2),
                        "depth_m": round(k.depth_m, 2), "flats_per_floor": k.flats_per_floor}
                       for k in t.blocks.kinds],
            "blocks_from": t.blocks.source, "lowest_floors": t.lowest,
            "narsingi_flats_per_acre": round(NARSINGI_FLATS_PER_ACRE, 1),
            "options": [_option_facts(t, o) for o in t.options],
            "not_offered": [_option_facts(t, o) for o in t.failed],
            "waiting": list(t.waiting)}


def _option_facts(t: TotLot, o: Option) -> dict:
    return {"option": o.number, "idea": o.plan.words, "road": o.plan.road,
            "row_directions_deg": [round(a, 1) for a in o.plan.angles], "holds": o.holds,
            "readings": [_placing_facts(t, p) for p in o.placings]}


def _placing_facts(t: TotLot, p: Placing) -> dict:
    return {"water_reading": p.reading or None,
            "flats": p.flats, "flats_before_the_tot_lot": p.flats_first,
            "flats_the_tot_lot_cost": p.flats_lost,
            "flats_per_acre": round(p.flats / t.acres, 1) if t.acres else None,
            "changes": list(p.changes),
            "blocks": [{"floors": b.floors, "what": b.kind.what, "flats": b.flats,
                        "row_direction_deg": round(b.angle_deg, 1), "arm": b.arm,
                        "outline": mapping(b.polygon)} for b in p.layout.blocks],
            "gate": mapping(p.gate) if not p.gate.is_empty else None,
            "tot_lot_sqm": round(p.tot_lot.area, 2),
            "leftover_sqm": round(p.leftover.area, 2),
            "short_sqm": round(p.short_sqm, 2),
            "pieces": [{"lies": pocket.lies, "area_sqm": round(pocket.area_sqm, 2),
                        "on": {k: round(a, 2) for k, a in pocket.on_sqm},
                        "outline": mapping(pocket.polygon)} for pocket in p.pockets]}
