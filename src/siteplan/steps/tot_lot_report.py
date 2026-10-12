"""Step 5's report, picture and facts, in plain words (steps/report.py's five questions)."""

from __future__ import annotations

from shapely.geometry import mapping

from siteplan import rules
from siteplan.steps import carried, gate
from siteplan.steps.drawing import Layer, Picture, frame
from siteplan.steps.report import Choice, RuleUsed, StepReport, Table
from siteplan.steps.survey_copy import SHORT_RUN_M
from siteplan.steps.tot_lot import (
    CORNER_TURN_DEG,
    CUT_TOLERANCE_M,
    SAME_SQM,
    SHALLOW,
    SHARP_DEG,
    STEEP,
    Placing,
    TotLot,
)

TITLE = "Where buildings fit, and the tot-lot"
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
        r.happening = ["The height map and the tot-lot start from the land left after the "
                       "setbacks and the firm's blocks, so this step needs both."]
        r.elements = ["The land left for buildings (step 4) and the firm's flat library."]
        r.choices = [Choice("The step stops instead of placing anything on a guess.",
                            "Where the tot-lot goes moves every building after it.")]
        r.output = ["Nothing placed yet: the step needs the answer below."]
        r.tables = [_carried_table(t)]
        r.questions = [t.ask] if t.ask else []
        return r
    if t.share is None:
        return _none_needed(r, t)
    s = t.setbacks
    low = min(t.lowest, s.floors)
    r.did = [
        f"Tried every height from Stilt + {s.floors} (step 2) down one floor at a time to "
        f"Stilt + {low}, each keeping its own setbacks, and marked where one of the firm's "
        "blocks fits: the kit and a slim block of one row of flats, turned either way.",
        "Kept the plot's edge's setback all round, and marked the land no building fits on.",
        "Marked the gate and kept clear the land in front of it: the way the approach road "
        "comes straight in, as wide as the gate, and a fire engine's turn there.",
        f"Laid out {len(t.options)} tot-lot options, each a different way of choosing the "
        "corners and shaping the pockets, every one keeping the same rules, for you to choose "
        "one; option 1 is set out below.",
    ]
    r.happening = [
        f"You choose (your word, 2026-10-12): {len(t.options)} options; step 6 builds round "
        "the one you choose.",
        f"Tallest first, one floor lower where it does not fit; below Stilt + {t.lowest} a "
        "block is not worth building (your word).",
        "The land no building fits on goes first; then pockets at the plot's major corners, "
        "the patch the corner's two sides make.",
        "No tot-lot in front of the gate (your rule). Beside it a corner's pocket is a "
        "right-angled triangle: its small side along the gate's side, the long slant away from "
        "the gate (your word).",
        "A pocket keeps out of every setback: the edge's, and each building's beside it.",
    ]
    r.elements = [
        f"The land left after the setbacks (step 4): {s.left.area:,.1f} m².",
        f"The whole plot's area (step 1): {t.plot_sqm:,.1f} m², {t.plot_from}.",
        f"The main road (step 2), {s.height.road.name}: the gate is where it meets the plot.",
        f"The firm's blocks: {len(t.blocks.footprints)}, from {t.blocks.source}.",
        f"The lowest block worth building: Stilt + {t.lowest}, your word (2026-10-12).",
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
               ("step5.json", "every number in this report, with each option's outlines")]
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
        RuleUsed("Setbacks by height", "Each height keeps its own open space all round (Table "
                 "IV).", rules.TABLE_IV_CLAUSE),
        RuleUsed("Setbacks below 21 m", "A height below high-rise keeps Table III's.",
                 rules.TABLE_III_2012_CLAUSE),
        RuleUsed("Gaps between blocks", "Never counted as tot-lot.",
                 rules.BLOCK_GAP_NOT_OPEN_SPACE_CLAUSE),
        RuleUsed("The approach road", "The main approach road is "
                 f"{rules.MAIN_APPROACH_ROAD_M[0]:g} to {rules.MAIN_APPROACH_ROAD_M[1]:g} m wide.",
                 rules.INTERNAL_ROAD_CLAUSE),
        RuleUsed("A fire engine's turn", f"A turning radius of at least "
                 f"{rules.FIRE_TURNING_RADIUS_M:g} m.", rules.FIRE_ACCESS_CLAUSE),
        RuleUsed("Amenities (the club house: not in this stage)", "Group housing of 100 flats "
                 f"or more: at least {rules.AMENITY_MIN_BUILT_UP_FRACTION:.0%} of the flats' "
                 "built-up area, in a block of its own.", rules.AMENITY_2012_CLAUSE),
    ]
    if t.setbacks.widening.water:
        out.append(RuleUsed("Water's buffer", "It may count as tot-lot (never as a setback).",
                            rules.WATER_BUFFER_2012_CLAUSE))
    return out


def _choices(t: TotLot) -> list[Choice]:
    blocks = t.blocks
    s = t.setbacks
    clear = s.front_m + rules.FIRE_TURNING_RADIUS_M
    return [
        Choice(f"The {t.share.fraction:.0%} is of the whole plot, {t.plot_sqm:,.1f} m² "
               f"({t.plot_from}).", "Your rule (2026-10-11): the rule says 'total site area' "
               "and does not say whole or net." + (
                   " The whole plot is the larger, so the plan holds on either reading."
                   if t.need_sqm >= t.net_need_sqm else
                   f" Here the net plot is the larger: {t.net_need_sqm:,.1f} m² of it.")),
        Choice("The firm's blocks are the kit its flat library composes and a slim block of one "
               "row of the same flats, as long as the kit's shortest; a block fits where the "
               f"land is as wide as its short side (the narrowest, {blocks.narrowest_m:.2f} m) "
               "and a piece holds its footprint.", "Your rule (2026-10-11): shape the building "
               f"to the land. The slim block is the engine's, from {blocks.source}."),
        Choice(f"In front of the gate is the gate's own width straight into the plot, across "
               f"it, and {clear:g} m round the gate (the front setback, {s.front_m:g} m, and a "
               f"fire engine's {rules.FIRE_TURNING_RADIUS_M:g} m turn); beside the gate along "
               "the edge is not in front of it.", "Your rule (2026-10-12): no tot-lot in front "
               "of the gate; beside it, at the corners. Step 6 places the road and may move "
               "the gate."),
        Choice(f"A major corner is where the land's edge facing one major edge of the plot "
               f"turns outward by at least {CORNER_TURN_DEG:g} degrees into the edge facing the "
               f"next; a major edge is a run of sides facing one way (a jog under "
               f"{SHORT_RUN_M:g} m does not part them) as long as the firm's shortest block "
               f"({blocks.shortest_m:.2f} m). A notch is not one.", "Your word: corners. Which "
               "count is the engine's reading."),
        Choice("A corner's pocket is the patch its two sides make, no further along either than "
               "halfway to the next corner; beside the gate (and wherever an option says) a "
               f"right-angled triangle, its long side {STEEP:g} times its small side (or "
               f"{SHALLOW:g} times in the 'wider' options), the small side toward the gate; a "
               f"corner sharper than {SHARP_DEG:g} degrees is cut straight across. Each picked "
               "corner holds an equal share; one that cannot passes the rest on.", "Your word "
               "(2026-10-12): beside the gate a triangle, small at the gate, slanting away; "
               "never a thin line."),
        Choice(f"The {len(t.options)} options: the engine's named ideas (option 1 the way of "
               "2026-10-11), then every two and every three of the site's corners, the first "
               f"{len(t.options)} that differ (two whose tot-lots differ by less than "
               f"{SAME_SQM:g} m² are one). 'Cost the fewest floors' counts each square metre "
               "by the height the map gives it.", "Your word (2026-10-12): give the architect "
               "options to choose from."),
        Choice(f"A pocket's {t.share.min_width_m:g} m is checked by rolling a circle that wide "
               f"(less {CUT_TOLERANCE_M * 100:g} cm) through it.", "The rule gives the width, "
               "not how to measure it on a bent piece."),
    ]


def _output(t: TotLot) -> tuple[list[str], list[Table]]:
    p = t.placings[0]
    s = t.setbacks
    lines = [f"{len(t.options)} OPTIONS for you to choose from: the first table below. Option 1 "
             "is drawn in step5.svg and set out here; each option is drawn in "
             "step5-option-NN.svg.", _map_line(p)]
    lines.append(f"Land no building fits on (inside the edge's setback): {p.free.area:,.1f} m².")
    if not p.gate.is_empty:
        lines.append(f"GATE: where {s.height.road.name} meets the plot; kept clear in front of "
                     f"it: {p.gate_zone.area:,.1f} m².")
    else:
        lines.append(f"GATE: not known ({s.height.road.name} does not reach the plot).")
    lines.append(f"TOT-LOT NEEDED: {t.need_sqm:,.1f} m² ({t.share.fraction:.0%} of the whole "
                 f"plot's {t.plot_sqm:,.1f} m²). OPTION 1 PLACES {p.tot_lot.area:,.1f} m²: "
                 f"{p.free_taken.area:,.1f} m² on the land no building fits on, the rest at "
                 f"{len(p.corners)} corner{'' if len(p.corners) == 1 else 's'}.")
    lines.append(f"Land a building fits on: {p.buildable.area:,.1f} m² before, "
                 f"{p.building_land_after.area:,.1f} m² after (measured again).")
    if p.short_sqm > 0:
        lines.append(f"THE LAND CANNOT HOLD THE TOT-LOT: it is short by {p.short_sqm:,.1f} m².")
    if f"{t.net_need_sqm:,.1f}" != f"{t.need_sqm:,.1f}":
        lines.append(f"Of the net plot instead it would be {t.net_need_sqm:,.1f} m² (shown, not "
                     "taken).")
    for other in t.placings[1:]:
        if other.tot_lot.equals(p.tot_lot):
            lines.append(f"The same with {other.reading} (asked in step 3).")
            continue
        lines.append(f"With {other.reading} (asked in step 3): tot-lot {other.tot_lot.area:,.1f}"
                     f" m²; land a building fits on after it {other.building_land_after.area:,.1f}"
                     " m²." + (f" SHORT BY {other.short_sqm:,.1f} m²." if other.short_sqm > 0
                               else ""))
    for kind in t.waiting:
        lines.append(f"The {kind.replace('_', ' ')}'s buffer waits on one answer (step 3), so "
                     "it is not counted yet.")
    lines.append("The club house is not in this stage (your word).")
    tiers = Table("The height map: the tallest building that fits, part by part",
                  ("Height", "Setback", "Land where it is the tallest that fits"),
                  tuple((f"Stilt + {tier.floors}", f"{tier.setback_m:g} m",
                         f"{tier.tallest.area:,.1f} m²") for tier in p.tiers))
    pieces = Table("Option 1's pieces", ("Piece", "Lies", "Area", "Stands on"),
                   tuple((str(i), pocket.lies, f"{pocket.area_sqm:,.1f} m²",
                          "; ".join(f"{kind}: {area:,.1f} m²" for kind, area in pocket.on_sqm
                                    if f"{area:,.1f}" != "0.0"))
                         for i, pocket in enumerate(p.pockets, 1)))
    return lines, [_options_table(t), tiers, pieces, _carried_table(t)]


def _map_line(p: Placing) -> str:
    parts = [f"Stilt + {tier.floors} on {tier.tallest.area:,.1f} m²" for tier in p.tiers
             if f"{tier.tallest.area:,.1f}" != "0.0"]
    return "HEIGHT MAP, the tallest that fits: " + (", ".join(parts) or "nothing fits") + "."


def _options_table(t: TotLot) -> Table:
    rows = []
    for o in t.options:
        p = o.placing
        lost = p.buildable.area - p.building_land_after.area
        smallest = min((q.area_sqm for q in p.pockets), default=0.0)
        idea = o.idea.words[0].upper() + o.idea.words[1:] + (
            f" (also: {'; '.join(o.same)})" if o.same else "")
        triangles = sum(1 for c in p.corners if c.triangle and not c.tot_lot.is_empty)
        short = max(q.short_sqm for q in o.placings)
        rows.append((str(o.number), idea, f"{p.tot_lot.area:,.1f} m²", str(len(p.pockets)),
                     str(triangles), f"{smallest:,.1f} m²",
                     f"{p.building_land_after.area:,.1f} m²", f"{lost:,.1f} m²",
                     f"SHORT BY {short:,.1f} m²" if short > 0 else "holds it"))
    return Table("The options: choose one", ("Option", "The idea", "Tot-lot", "Pieces",
                                             "Triangles", "Smallest piece",
                                             "Land a building fits on after",
                                             "Building land it takes",
                                             "Every reading of the water"), tuple(rows))


def _questions(t: TotLot) -> list[str]:
    out = [f"Which tot-lot option do you choose (1 to {len(t.options)})? Each is drawn in "
           "step5-option-NN.svg; step 6 lays the buildings round the one you choose."]
    short = [p for p in (*t.placings, *(q for o in t.options for q in o.placings))
             if p.short_sqm > 0]
    if short:
        worst = max(short, key=lambda p: p.short_sqm)
        out.append(f"The plot cannot hold the tot-lot: it is short by {worst.short_sqm:,.1f} m² "
                   f"(Stilt + {t.setbacks.floors}). Should the buildings be lower (smaller "
                   "setbacks), or is the tot-lot to be found elsewhere?")
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
    """Every option drawn on its own, to choose from."""
    return [(f"step5-option-{o.number:02d}", picture(t, o.number)) for o in t.options]


def picture(t: TotLot, number: int = 0) -> Picture:
    """Option 1 as the step's picture, or option `number` titled with its idea."""
    option = t.options[number - 1] if number else None
    p = option.placing if option else t.placings[0]
    s = t.setbacks
    title = (f"Step 5: tot-lot option {number} of {len(t.options)}" if option
             else f"Step 5: {TITLE}")
    debug = " (DEBUG RUN: not evidence)" if "DEBUG RUN" in t.inputs.site else ""
    subtitle = (option.idea.words[0].upper() + option.idea.words[1:] + debug if option
                else t.inputs.site)
    heights = [Layer(f"STILT-{tier.floors}", SHADES[min(i, len(SHADES) - 1)], 5,
                     f"Stilt + {tier.floors} is the tallest that fits", fill=0.45, width=0.3)
               for i, tier in enumerate(p.tiers)]
    pic = Picture(title, subtitle, layers=[
        *heights,
        Layer("SETBACK", "#f08c00", 30, "Setback: no building here", fill=0.25, width=0.5),
        Layer("FIRE-LANE", "#8b0000", 14, f"Where the {rules.FIRE_TENDER_MIN_WIDTH_M:g} m fire "
              "lane can run (beside a high-rise)", fill=0.85, width=0.5),
        Layer("WATER-BUFFER", "#5cc4dd", 4, "Water's buffer from the line drawn", fill=0.45,
              width=0.5),
        Layer("FREE", "#8c8c8c", 8, "No building fits here", fill=0.30, width=0.8, dash="4 3"),
        Layer("GATE-ZONE", "#d62828", 1, "In front of the gate: kept clear", fill=0.08,
              width=1.0, dash="6 4"),
        Layer("TOT-LOT", "#9acd32", 3, "The tot-lot", fill=0.9, width=1.5),
        Layer("NET-PLOT", "#2e8b3d", 3, "The net plot (step 3)", width=3.0),
        gate.LAYER,
        Layer("NOTES", "#222222", 7, ""),
    ])
    view = frame(t.copy.plot, DRAWN_AROUND_M)
    carried.draw(pic, carried.found_in(t.copy), view)
    for tier in p.tiers:
        pic.add(f"STILT-{tier.floors}", tier.tallest)
    kept = s.widening.net.difference(p.room).union(p.kept_setbacks)
    pic.add("SETBACK", kept)
    if s.fire_lane is not None:
        pic.add("FIRE-LANE", s.fire_lane.intersection(kept))
    for water in s.widening.water:
        pic.add("WATER-BUFFER", water.kept_free)
    pic.add("FREE", p.free)
    pic.add("GATE-ZONE", p.gate_zone)
    pic.add("TOT-LOT", p.tot_lot)
    pic.add("NET-PLOT", s.widening.net)
    gate.draw(pic, p.gate)
    for pocket in p.pockets:
        spot = pocket.polygon.representative_point()
        pic.label("NOTES", (spot.x, spot.y), f"TOT-LOT {pocket.area_sqm:,.1f} m²")
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
            "need_sqm": round(t.need_sqm, 2), "net_plot_need_sqm": round(t.net_need_sqm, 2),
            "min_width_m": t.share.min_width_m, "min_pocket_sqm": t.share.min_pocket_sqm,
            "blocks": [{"what": what, "length_m": round(length, 2), "depth_m": round(depth, 2)}
                       for what, length, depth in t.blocks.footprints],
            "blocks_from": t.blocks.source, "lowest_floors": t.lowest,
            "options": [{"option": o.number, "idea": o.idea.words, "same_as": list(o.same),
                         "readings": [_placing_facts(q) for q in o.placings]}
                        for o in t.options],
            "readings": [_placing_facts(p) for p in t.placings],
            "waiting": list(t.waiting)}


def _placing_facts(p: Placing) -> dict:
    return {"water_reading": p.reading or None,
            "height_map": [{"floors": tier.floors, "setback_m": tier.setback_m,
                            "tallest_sqm": round(tier.tallest.area, 2)} for tier in p.tiers],
            "free_sqm": round(p.free.area, 2),
            "gate": mapping(p.gate) if not p.gate.is_empty else None,
            "gate_clear_sqm": round(p.gate_zone.area, 2),
            "tot_lot_sqm": round(p.tot_lot.area, 2),
            "free_taken_sqm": round(p.free_taken.area, 2),
            "corners": [{"corner": c.number, "lies": c.lies, "triangle": c.triangle,
                         "share_sqm": round(c.share_sqm, 2),
                         "placed_sqm": round(c.tot_lot.area, 2)} for c in p.corners],
            "short_sqm": round(p.short_sqm, 2),
            "floors_lost_sqm": round(p.floors_lost_sqm(), 2),
            "building_land_sqm": round(p.buildable.area, 2),
            "building_land_after_sqm": round(p.building_land_after.area, 2),
            "pieces": [{"lies": pocket.lies, "area_sqm": round(pocket.area_sqm, 2),
                        "on": {k: round(a, 2) for k, a in pocket.on_sqm},
                        "outline": mapping(pocket.polygon)} for pocket in p.pockets]}
