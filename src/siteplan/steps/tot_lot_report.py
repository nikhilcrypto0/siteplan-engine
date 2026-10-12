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
    Placing,
    TotLot,
)

TITLE = "Where buildings fit, and the tot-lot"
DRAWN_AROUND_M = 30.0


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
        r.happening = ["The tot-lot starts from the land left after the setbacks (step 4) and "
                       "the firm's blocks, so this step needs both."]
        r.elements = ["The land left for buildings (step 4) and the firm's flat library."]
        r.choices = [Choice("The step stops instead of placing anything on a guess.",
                            "Where the tot-lot goes moves every building after it.")]
        r.output = ["Nothing placed yet: the step needs the answer below."]
        r.tables = [_carried_table(t)]
        r.questions = [t.ask] if t.ask else []
        return r
    if t.share is None:
        return _none_needed(r, t)
    p = t.placings[0]
    s = t.setbacks
    r.did = [
        f"Took step 4's land left after the setbacks ({s.left.area:,.1f} m², Stilt + "
        f"{s.floors}) and marked where one of the firm's blocks fits on it: the kit and a slim "
        "block of one row of flats, turned either way.",
        "Where none fits, no building stands.",
        "Marked the gate, where the approach road comes in from the main road, and kept the "
        "land in front of it clear.",
        f"Laid the tot-lot, {t.share.fraction:.0%} of the whole plot, inside the land left: "
        "first where no building stands"
        + (f"; then what was still needed split equally over {len(p.corners)} major corners."
           if p.corners else "."),
        f"Laid out {len(t.options)} options for the tot-lot, each a different idea, every one "
        "keeping the same rules, for you to choose one; the one above is option 1.",
    ]
    r.happening = [
        f"You choose (your word, 2026-10-12): {len(t.options)} options, each a different idea "
        "of where the tot-lot goes, all inside the same rules; step 6 builds round the one you "
        "choose.",
        "The tot-lot stays inside the land left for buildings (your word): it never takes a "
        "setback, the green strip or the fire lane.",
        "Land left where no building stands goes first, the part farthest from the buildings "
        "first: it costs no building land.",
        "What it cannot hold is divided by the number of major corners and each corner takes "
        "its part (your word), a strip along both sides of the corner, long and shallow.",
        "A corner that cannot hold its part passes the rest to the other corners equally.",
        "Nothing covers the gate: the land in front of it is kept clear (your word).",
        "The club house comes once the tot-lot is right (your word).",
    ]
    r.elements = [
        f"Step 4's land left after the setbacks: {s.left.area:,.1f} m², and the setback band, "
        "the green strip and the fire lane it keeps.",
        f"The whole plot's area (step 1): {t.plot_sqm:,.1f} m², {t.plot_from}.",
        f"The main road (step 2), {s.height.road.name}: the gate is where it meets the plot.",
        f"The firm's blocks: {len(t.blocks.footprints)}, from {t.blocks.source}.",
        f"A corner strip's depth: {t.depth_m:g} m, {t.depth_from}.",
    ]
    if s.widening.water:
        r.elements.append("The water named in the project and its buffer (step 3).")
    r.elements.append("Everything step 1 found, carried on (the table at the end).")
    r.rules = _rules(t)
    r.choices = _choices(t)
    r.output, r.tables = _output(t)
    r.questions = _questions(t)
    r.files = [("step5.svg", "the picture"), ("step5.dxf", "the same, to open in CAD (metres)"),
               ("step5.json", "every number in this report, with the tot-lot's outline and "
                "the gate")]
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
        RuleUsed("Setbacks by height", "A building keeps Table IV's open space all round.",
                 rules.TABLE_IV_CLAUSE),
        RuleUsed("Gaps between blocks", "Never counted as tot-lot.",
                 rules.BLOCK_GAP_NOT_OPEN_SPACE_CLAUSE),
        RuleUsed("The approach road", "The main approach road is "
                 f"{rules.MAIN_APPROACH_ROAD_M[0]:g} to {rules.MAIN_APPROACH_ROAD_M[1]:g} m wide.",
                 rules.INTERNAL_ROAD_CLAUSE),
        RuleUsed("A fire engine's turn", f"A turning radius of at least "
                 f"{rules.FIRE_TURNING_RADIUS_M:g} m.", rules.FIRE_ACCESS_CLAUSE),
        RuleUsed("Amenities (the club house, a later step)", "Group housing of 100 flats or "
                 f"more: at least {rules.AMENITY_MIN_BUILT_UP_FRACTION:.0%} of the flats' "
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
        Choice(f"A block fits where step 4's land left is as wide as the block's short side (the "
               f"narrowest, {blocks.narrowest_m:.2f} m) and a piece holds its footprint; the "
               "blocks are the kit the firm's flat library composes and a slim block of one row "
               "of the same flats, as long as the kit's shortest.", "The firm draws no slim "
               f"block; this one is the engine's, from {blocks.source}."),
        Choice("No building stands on the land left where no block fits; it goes to the "
               "tot-lot first, the part farthest from the buildings first.", "Your word "
               "(2026-10-11): where no building stands first, and never outside the land left "
               "for buildings."),
        Choice(f"A major corner is where the land left's edge facing one major edge of the plot "
               f"turns outward, by at least {CORNER_TURN_DEG:g} degrees, into the edge facing the "
               f"next; a major edge is a run of sides facing the same way (a jog under "
               f"{SHORT_RUN_M:g} m between them does not part them) at least as long as the "
               f"firm's shortest block ({blocks.shortest_m:.2f} m). A notch is not one; a corner "
               "next to the land already taken is served by it.", "Your word (2026-10-11): "
               "divide by the number of major corners. Which corners count is the engine's "
               "reading."),
        Choice(f"Each corner's part is a strip {t.depth_m:g} m deep along both sides of the "
               "corner, on the edge of the land left (inside every setback), no further than "
               "halfway to the next corner; the corners with the least room take theirs first. "
               "Deeper only when the corners together cannot hold the rest.", "Your word: long "
               f"along the side, not much into the usable space. The {t.depth_m:g} m is "
               f"{t.depth_from}."),
        Choice(f"The gate is where {s.height.road.name} meets the plot, as wide as the main "
               f"approach road may be ({rules.MAIN_APPROACH_ROAD_M[0]:g} to "
               f"{rules.MAIN_APPROACH_ROAD_M[1]:g} m): where the road meets less, the edge either "
               "side of the meeting is taken; where it meets more, the middle. Nothing stands "
               f"within {clear:g} m of it: the front setback ({s.front_m:g} m) and a fire "
               f"engine's {rules.FIRE_TURNING_RADIUS_M:g} m turn.", "Your word: no tot-lot in "
               "front of the gate. Step 6 places the road and may move the gate."),
        Choice(f"The {len(t.options)} options are the first {len(t.options)} different ones "
               "of the engine's list of ideas, in its order: option 1 is the rule agreed on "
               "2026-10-11, the rest change one thing each (the strip's depth, one side only, "
               "which corners, the edges' middles instead of the corners, nothing taken first); "
               f"two ideas whose tot-lots differ by less than {SAME_SQM:g} m² are one option.",
               "Your word (2026-10-12): give the architect options to choose from. Which ideas "
               "are offered is the engine's choice; say which to add or drop."),
        Choice(f"A pocket's {t.share.min_width_m:g} m is checked by rolling a circle that wide "
               f"(less {CUT_TOLERANCE_M * 100:g} cm) through it; pieces within "
               f"{CUT_TOLERANCE_M * 100:g} cm of each other are one pocket.", "The rule gives "
               "the width, not how to measure it on a bent piece."),
    ]


def _output(t: TotLot) -> tuple[list[str], list[Table]]:
    p = t.placings[0]
    s = t.setbacks
    lines = [f"{len(t.options)} OPTIONS for you to choose from: the first table below. Option 1 "
             "is drawn in step5.svg and set out here; each option is drawn in "
             "step5-option-NN.svg.",
             f"Land left (step 4): {s.left.area:,.1f} m². A block fits on {p.fits.area:,.1f} m² "
             f"of it."]
    lines.append(f"WHERE NO BUILDING STANDS (inside the land left): {p.idle.area:,.1f} m² the "
                 "tot-lot can use.")
    if not p.gate.is_empty:
        lines.append(f"GATE: where {s.height.road.name} meets the plot, kept clear for "
                     f"{s.front_m + rules.FIRE_TURNING_RADIUS_M:g} m in front "
                     f"({p.gate_zone.area:,.1f} m²).")
    else:
        lines.append(f"GATE: not known ({s.height.road.name} does not reach the plot).")
    lines.append(f"TOT-LOT NEEDED: {t.need_sqm:,.1f} m² ({t.share.fraction:.0%} of the whole "
                 f"plot's {t.plot_sqm:,.1f} m²). PLACED: {p.tot_lot.area:,.1f} m².")
    lines.append(f"FIRST, where no building stands: {p.idle_taken.area:,.1f} m².")
    if p.corners:
        each = (t.need_sqm - p.idle_taken.area) / len(p.corners)
        lines.append(f"THEN AT THE MAJOR CORNERS: {len(p.corners)}, so {each:,.1f} m² each, "
                     f"strips {p.depth_m:g} m deep.")
        for corner in p.corners:
            if corner.share_sqm < each - 0.05:
                lines.append(f"Corner {corner.number} ({corner.lies}) holds only "
                             f"{corner.share_sqm:,.1f} m²; the rest went to the other corners.")
        if p.depth_m > t.depth_m + CUT_TOLERANCE_M:
            lines.append(f"The corners together at {t.depth_m:g} m could not hold it, so the "
                         f"strips are {p.depth_m:.2f} m deep.")
    else:
        lines.append("No corner is needed: the land where no building stands holds it all.")
    lines.append(f"Land a block fits on: {p.fits.area:,.1f} m² before, {p.fits_after.area:,.1f} "
                 "m² after (measured again: land the tot-lot leaves too thin for a block no "
                 "longer counts).")
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
                     f" m², {other.idle_taken.area:,.1f} m² of it where no building stands; land "
                     f"a block fits on after it {other.fits_after.area:,.1f} m²."
                     + (f" SHORT BY {other.short_sqm:,.1f} m²." if other.short_sqm > 0 else ""))
    for kind in t.waiting:
        lines.append(f"The {kind.replace('_', ' ')}'s buffer waits on one answer (step 3), so "
                     "it is not counted yet.")
    lines.append("The club house comes once the tot-lot is right.")
    tables = [_options_table(t)]
    if p.corners:
        tables.append(Table("The major corners and the tot-lot at each",
                            ("Corner", "Lies", "Its part", "Placed"),
                            tuple((str(c.number), c.lies, f"{c.share_sqm:,.1f} m²",
                                   f"{c.tot_lot.area:,.1f} m²") for c in p.corners)))
    tables.append(Table("The tot-lot's pieces", ("Piece", "Lies", "Area", "Stands on"),
                        tuple((str(i), pocket.lies, f"{pocket.area_sqm:,.1f} m²",
                               "; ".join(f"{kind}: {area:,.1f} m²" for kind, area in pocket.on_sqm
                                         if f"{area:,.1f}" != "0.0"))
                              for i, pocket in enumerate(p.pockets, 1))))
    tables.append(_carried_table(t))
    return lines, tables


def _options_table(t: TotLot) -> Table:
    rows = []
    for o in t.options:
        p = o.placing
        lost = p.fits.area - p.fits_after.area
        smallest = min((q.area_sqm for q in p.pockets), default=0.0)
        idea = o.idea.words[0].upper() + o.idea.words[1:] + (
            f" (the same as: {'; '.join(o.same)})" if o.same else "")
        short = max(q.short_sqm for q in o.placings)
        rows.append((str(o.number), idea, f"{p.tot_lot.area:,.1f} m²", str(len(p.pockets)),
                     f"{smallest:,.1f} m²", f"{p.depth_m:.2f} m",
                     f"{p.fits_after.area:,.1f} m²", f"{lost:,.1f} m²",
                     f"SHORT BY {short:,.1f} m²" if short > 0 else "holds it"))
    return Table("The options: choose one", ("Option", "The idea", "Tot-lot", "Pieces",
                                             "Smallest piece", "Strip depth",
                                             "Land a block fits on after", "Building land it "
                                             "takes", "Every reading of the water"),
                 tuple(rows))


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
    subtitle = f"{t.inputs.site}; {option.idea.words}" if option else t.inputs.site
    pic = Picture(title, subtitle, layers=[
        Layer("LEFT", "#4f86c6", 5, "Land left for buildings (step 4)", fill=0.18, width=1.5),
        Layer("SETBACK", "#f08c00", 30, "Setback: no building here", fill=0.30, width=0.5),
        Layer("GREEN-STRIP", "#2e8b3d", 3, f"{rules.PERIPHERAL_GREEN_STRIP_M:g} m green strip "
              "(inside the setback)", fill=0.55, width=0.5),
        Layer("FIRE-LANE", "#8b0000", 14, f"Where the {rules.FIRE_TENDER_MIN_WIDTH_M:g} m fire "
              "lane can run (inside the setback)", fill=0.85, width=0.5),
        Layer("WATER-BUFFER", "#5cc4dd", 4, "Water's buffer from the line drawn", fill=0.45,
              width=0.5),
        Layer("NO-BUILDING", "#8c8c8c", 8, "No building stands here (no block of the firm's "
              "fits)", fill=0.30, width=0.8, dash="4 3"),
        Layer("GATE-ZONE", "#d62828", 1, "Kept clear in front of the gate", fill=0.06,
              width=1.0, dash="6 4"),
        Layer("TOT-LOT", "#9acd32", 3, "The tot-lot", fill=0.9, width=1.5),
        Layer("NET-PLOT", "#2e8b3d", 3, "The net plot (step 3)", width=3.0),
        gate.LAYER,
        Layer("NOTES", "#222222", 7, ""),
    ])
    view = frame(t.copy.plot, DRAWN_AROUND_M)
    carried.draw(pic, carried.found_in(t.copy), view)
    pic.add("SETBACK", s.band)
    pic.add("GREEN-STRIP", s.green)
    pic.add("FIRE-LANE", s.fire_lane)
    for water in s.widening.water:
        pic.add("WATER-BUFFER", water.kept_free)
    pic.add("LEFT", s.left)
    pic.add("NO-BUILDING", p.idle)
    pic.add("GATE-ZONE", p.gate_zone)
    pic.add("TOT-LOT", p.tot_lot)
    pic.add("NET-PLOT", s.widening.net)
    gate.draw(pic, p.gate)
    for corner in p.corners:
        pic.label("NOTES", (corner.point.x, corner.point.y), f"{corner.what} {corner.number}")
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
            "blocks_from": t.blocks.source,
            "strip_depth_m": t.depth_m, "strip_depth_from": t.depth_from,
            "options": [{"option": o.number, "idea": o.idea.words, "same_as": list(o.same),
                         "readings": [_placing_facts(q) for q in o.placings]}
                        for o in t.options],
            "readings": [_placing_facts(p) for p in t.placings],
            "waiting": list(t.waiting)}


def _placing_facts(p: Placing) -> dict:
    return {"water_reading": p.reading or None,
            "block_fits_sqm": round(p.fits.area, 2),
            "where_no_building_stands_sqm": round(p.idle.area, 2),
            "gate": mapping(p.gate) if not p.gate.is_empty else None,
            "gate_clear_sqm": round(p.gate_zone.area, 2),
            "tot_lot_sqm": round(p.tot_lot.area, 2),
            "where_no_building_stands_taken_sqm": round(p.idle_taken.area, 2),
            "strip_depth_m": round(p.depth_m, 2),
            "major_corners": [{"corner": c.number, "lies": c.lies,
                               "at": [round(c.point.x, 2), round(c.point.y, 2)],
                               "share_sqm": round(c.share_sqm, 2),
                               "placed_sqm": round(c.tot_lot.area, 2)} for c in p.corners],
            "short_sqm": round(p.short_sqm, 2),
            "block_fits_after_sqm": round(p.fits_after.area, 2),
            "pieces": [{"lies": pocket.lies, "area_sqm": round(pocket.area_sqm, 2),
                        "on": {k: round(a, 2) for k, a in pocket.on_sqm},
                        "outline": mapping(pocket.polygon)} for pocket in p.pockets]}
