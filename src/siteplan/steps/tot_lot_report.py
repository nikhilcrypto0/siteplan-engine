"""Step 5's report, picture and facts, in plain words (steps/report.py's five questions)."""

from __future__ import annotations

from shapely.geometry import mapping

from siteplan import rules
from siteplan.steps import carried
from siteplan.steps.drawing import Layer, Picture, frame
from siteplan.steps.report import Choice, RuleUsed, StepReport, Table
from siteplan.steps.tot_lot import BLOCK, CUT_TOLERANCE_M, THIN, WATER, Placing, TotLot

TITLE = "The open space (tot-lot)"
DRAWN_AROUND_M = 30.0


def report(t: TotLot) -> StepReport:
    r = StepReport(5, TITLE, t.inputs.site, picture=None if t.stopped else "step5.svg")
    if t.stopped:
        r.did = ["Looked for the land left for buildings and what the tot-lot needs, and "
                 "stopped: " + t.stopped + "."]
        if t.share is not None:
            r.did.append(f"The rules ask {t.need_sqm:,.1f} m² ({t.share.fraction:.0%} of the "
                         f"whole plot's {t.plot_sqm:,.1f} m²); it is not placed yet.")
        r.stopped = "The tot-lot cannot be placed yet: " + t.stopped + "."
        r.happening = ["The tot-lot comes out of the land left after the setbacks, and goes "
                       "first where no block fits, so this step needs both."]
        r.elements = ["The land left for buildings (step 4) and the firm's blocks."]
        r.choices = [Choice("The step stops instead of placing the tot-lot on a guess.",
                            "Where it goes moves every building after it.")]
        r.output = ["Nothing placed yet: the step needs the answer below."]
        r.tables = [_carried_table(t)]
        r.questions = [t.ask] if t.ask else []
        return r
    if t.share is None:
        return _none_needed(r, t)
    p = t.placings[0]
    r.did = [
        f"Took the land left for buildings from step 4 ({t.setbacks.left.area:,.1f} m²).",
        f"Worked out the tot-lot the rules ask for {t.share.why}: {t.share.fraction:.0%} of the "
        f"whole plot's {t.plot_sqm:,.1f} m² ({t.plot_from}), {t.need_sqm:,.1f} m².",
        f"Found the land no block of the firm's fits on: narrower than its shallowest block "
        f"({t.blocks.depth_m:.2f} m deep), or a piece too small for its smallest "
        f"({t.blocks.smallest[0]:.2f} x {t.blocks.smallest[1]:.2f} m).",
        "Put the tot-lot there first" + (", and on the water's buffer outside the setbacks"
                                          if p.on(WATER) > 0 else "") + _then(p) + ".",
        f"Kept every pocket at least {t.share.min_width_m:g} m wide and "
        f"{t.share.min_pocket_sqm:g} m², and measured the land left after it.",
    ]
    r.happening = [
        "A big site keeps part of its land open to the sky for greenery and children's play: "
        "the tot-lot.",
        "It comes on top of the setbacks: setback land never counts.",
        "Your rule: it goes first where no building fits, so it costs the least building land.",
        "The gaps between blocks never count as tot-lot; they come with the blocks (step 6).",
    ]
    r.elements = [
        f"The land left for buildings (step 4): {t.setbacks.left.area:,.1f} m².",
        f"The whole plot's area (step 1): {t.plot_sqm:,.1f} m², {t.plot_from}.",
        f"The firm's blocks: {t.blocks.count}, from {t.blocks.source}.",
        f"The main road (step 2), {t.setbacks.height.road.name}: where a pocket is cut short, "
        "the tot-lot keeps the end away from it.",
    ]
    if t.setbacks.widening.water:
        r.elements.append("The water named in the project and its buffer (step 3).")
    r.elements.append("Everything step 1 found, carried on (the table at the end).")
    r.rules = _rules(t)
    r.choices = _choices(t)
    r.output, r.tables = _output(t)
    r.questions = _questions(t)
    r.files = [("step5.svg", "the picture"), ("step5.dxf", "the same, to open in CAD (metres)"),
               ("step5.json", "every number in this report, with the tot-lot's outline")]
    return r


def _questions(t: TotLot) -> list[str]:
    short = [p for p in t.placings if p.short_sqm > 0]
    if not short:
        return []
    worst = max(short, key=lambda p: p.short_sqm)
    return [f"The land left after the setbacks cannot hold the tot-lot: it is short by "
            f"{worst.short_sqm:,.1f} m² (Stilt + {t.setbacks.floors}). Should the buildings be "
            "lower (smaller setbacks, step 4's table), or is the tot-lot to be found elsewhere?"]


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


def _then(p: Placing) -> str:
    if p.grew_from == "beside":
        return (", then took the rest from the building land on the side of the largest pocket, "
                "cut off by one straight line")
    if p.grew_from == "far end":
        return (", then, with no such land, took it at the end of the land furthest from the "
                "main road, cut off by one straight line")
    return ""


def _rules(t: TotLot) -> list[RuleUsed]:
    s = t.share
    out = [RuleUsed(f"How much: {whom}", f"At least {s.fraction:.0%} of the site, over and "
                    f"above the setbacks, open to the sky, in pockets at least "
                    f"{s.min_width_m:g} m wide and {s.min_pocket_sqm:g} m².", clause)
           for whom, clause in s.clauses]
    if t.setbacks.widening.water:
        out.append(RuleUsed("Water's buffer", "It may count as tot-lot (never as a setback).",
                            rules.WATER_BUFFER_2012_CLAUSE))
    out.append(RuleUsed("Gaps between blocks", "Never counted as tot-lot.",
                        rules.BLOCK_GAP_NOT_OPEN_SPACE_CLAUSE))
    return out


def _choices(t: TotLot) -> list[Choice]:
    b = t.blocks
    out = [
        Choice(f"The {t.share.fraction:.0%} is of the whole plot, {t.plot_sqm:,.1f} m² "
               f"({t.plot_from}).", "Your rule (2026-10-11): the rule says 'total site area' "
               "and does not say whole or net." + (
                   " The whole plot is the larger, so the plan holds on either reading."
                   if t.need_sqm >= t.net_need_sqm else
                   f" Here the net plot is the larger: {t.net_need_sqm:,.1f} m² of it.")),
        Choice(f"Land no block fits on: narrower than the firm's shallowest block "
               f"({b.depth_m:.2f} m), or a piece with less area than its smallest "
               f"({b.smallest[0]:.2f} x {b.smallest[1]:.2f} m).", "Your rule (2026-10-11): the "
               "tot-lot goes where blocks cannot fit. The blocks are the kit composed from "
               + b.source + ", the flats in equal shares (no mix is given at this step)."),
        Choice("Free land is taken largest pocket first; the last one is cut square to its "
               "length, at its end away from the main road.", "Fewest and biggest pockets; free "
               "land costs no building land wherever it is taken."),
        Choice("What free land does not hold comes from the building land on the side of the "
               "largest pocket, or, with no free land, from the end of the land furthest from "
               "the main road, cut off by one straight line.", "Keeps the tot-lot in few pieces, "
               "with straight edges the blocks can line up on, and away from the entrance's "
               "traffic. The engine's choice: say if the architects do it otherwise."),
        Choice("'Away from the main road' runs from the middle of its frontage through the "
               "middle of the land, so a road at a corner gives a cut on the diagonal.",
               "The rule names no direction; this one keeps the tot-lot off the entrance side."),
        Choice(f"A pocket's {t.share.min_width_m:g} m is checked by rolling a circle that wide "
               f"(less {CUT_TOLERANCE_M * 100:g} cm) through it; square corners keep their shape; "
               f"pieces within {CUT_TOLERANCE_M * 100:g} cm of each other are one pocket.",
               "The rule gives the width, not how to measure it on a bent piece; the "
               "centimetre is the drawing's tolerance."),
    ]
    if t.placings[0].reading:
        out.append(Choice("Only the water's buffer outside the setbacks counts as tot-lot.",
                          "The tot-lot is over and above the setbacks, and with the buffer and "
                          "the setbacks overlapping (your rule) land in both is setback."))
    return out


def _output(t: TotLot) -> tuple[list[str], list[Table]]:
    p = t.placings[0]
    lines = [f"TOT-LOT NEEDED: {t.need_sqm:,.1f} m² ({t.share.fraction:.0%} of the whole "
             f"plot's {t.plot_sqm:,.1f} m²). PLACED: {p.tot_lot.area:,.1f} m² in "
             f"{len(p.pockets)} pocket{'' if len(p.pockets) == 1 else 's'}."]
    lines += _placing_lines(p)
    if p.short_sqm > 0:
        lines.append(f"THE LAND LEFT CANNOT HOLD THE TOT-LOT: it is short by {p.short_sqm:,.1f} "
                     "m². Lower buildings keep smaller setbacks (step 4's table).")
    if f"{t.net_need_sqm:,.1f}" != f"{t.need_sqm:,.1f}":
        lines.append(f"Of the net plot instead it would be {t.net_need_sqm:,.1f} m² (shown, not "
                     "taken).")
    for other in t.placings[1:]:
        if other.tot_lot.equals(p.tot_lot) and other.after.equals(p.after):
            lines.append(f"The same with {other.reading} (asked in step 3).")
            continue
        lines.append(f"With {other.reading} (asked in step 3): tot-lot {other.tot_lot.area:,.1f}"
                     f" m², {other.on(WATER):,.1f} m² of it on the buffer, {other.on(BLOCK):,.1f}"
                     f" m² of building land; land left after it {other.after.area:,.1f} m²."
                     + (f" SHORT BY {other.short_sqm:,.1f} m²." if other.short_sqm > 0 else ""))
    for placing in t.placings:
        if f"{placing.water_lost_sqm:,.1f}" != "0.0":
            lines.append(f"With {placing.reading}, {placing.water_lost_sqm:,.1f} m² of the "
                         "water's buffer lies outside the setbacks but is too thin or too small "
                         f"to count (pockets at least {t.share.min_width_m:g} m wide and "
                         f"{t.share.min_pocket_sqm:g} m²).")
    for kind in t.waiting:
        lines.append(f"The {kind.replace('_', ' ')}'s buffer waits on one answer (step 3), so "
                     "it is not counted yet.")
    lines.append("The gaps between blocks never count as tot-lot; they come with the blocks "
                 "(step 6).")
    rows = tuple((str(i), pocket.lies, f"{pocket.area_sqm:,.1f} m²",
                  "; ".join(f"{kind}: {area:,.1f} m²" for kind, area in pocket.on_sqm
                            if f"{area:,.1f}" != "0.0"))
                 for i, pocket in enumerate(p.pockets, 1))
    return lines, [Table("The tot-lot's pockets", ("Pocket", "Lies", "Area", "Stands on"), rows),
                   _carried_table(t)]


def _placing_lines(p: Placing) -> list[str]:
    after = p.after.area
    water = f"{p.on(WATER):,.1f} m² of the water's buffer, " if p.reading else ""
    return [
        f"It stands on: {water}{p.on(THIN):,.1f} m² of land no block fits on, and "
        f"{p.on(BLOCK):,.1f} m² of land a block fits on (the building land it costs).",
        f"LAND LEFT FOR BUILDINGS, ROADS AND PARKING: {after:,.1f} m² ({p.land.area:,.1f} m² "
        f"left after the setbacks{' and the water' + chr(39) + 's buffer' if p.reading else ''}, "
        "less the tot-lot on it).",
        f"Land a block fits on: {p.block_land.area:,.1f} m² before, "
        f"{p.block_land_after.area:,.1f} m² after (measured again: a strip the tot-lot leaves "
        "too thin for a block no longer counts).",
    ]


def _used_here(t: TotLot) -> dict[str, str]:
    used = {}
    main = t.setbacks.height.road.name if not t.setbacks.stopped else None
    for item in carried.found_in(t.copy):
        if t.stopped:
            used[item.key] = "carried unchanged (this step stopped)"
        elif item.kind == carried.ROAD and item.key == main and t.placings:
            used[item.key] = ("the main road: where a pocket is cut short, the tot-lot keeps the "
                              "end away from it")
        elif item.kind == carried.WATER and t.placings and t.placings[0].reading:
            used[item.key] = "its buffer outside the setbacks counts as tot-lot"
        else:
            used[item.key] = "carried unchanged"
    return used


def _carried_table(t: TotLot) -> Table:
    used = _used_here(t)
    return Table("Carried on from step 1 (everything a later rule may need)",
                 ("What", "In this step", "Needed later for"),
                 tuple((item.what, used[item.key], item.later)
                       for item in carried.found_in(t.copy)))


def picture(t: TotLot) -> Picture:
    p = Picture(f"Step 5: {TITLE}", t.inputs.site, layers=[
        Layer("SETBACK", "#f08c00", 30, "Setback (step 4)", fill=0.20, width=0.5),
        Layer("FIRE-LANE", "#8b0000", 14, f"Where the {rules.FIRE_TENDER_MIN_WIDTH_M:g} m fire "
              "lane can run (step 4)", fill=0.85, width=0.5),
        Layer("WATER-BUFFER", "#5cc4dd", 4, "Water's buffer from the line drawn", fill=0.45,
              width=0.5),
        Layer("BLOCK-LAND", "#4f86c6", 5, "Land a block of the firm's fits on", fill=0.18,
              width=1.0),
        Layer("NO-BLOCK", "#8c8c8c", 8, "Land no block fits on", fill=0.35, width=0.8,
              dash="4 3"),
        Layer("TOT-LOT", "#9acd32", 3, "The tot-lot", fill=0.80, width=1.5),
        Layer("NET-PLOT", "#2e8b3d", 3, "The net plot (step 3)", width=3.0),
        Layer("NOTES", "#222222", 7, ""),
    ])
    s, placing = t.setbacks, t.placings[0]
    net = s.widening.net
    view = frame(t.copy.plot, DRAWN_AROUND_M)
    carried.draw(p, carried.found_in(t.copy), view)
    p.add("SETBACK", s.band)
    p.add("FIRE-LANE", s.fire_lane)
    for water in s.widening.water:
        p.add("WATER-BUFFER", water.kept_free)
    p.add("BLOCK-LAND", placing.block_land)
    p.add("NO-BLOCK", placing.land.difference(placing.block_land))
    p.add("TOT-LOT", placing.tot_lot)
    p.add("NET-PLOT", net)
    for pocket in placing.pockets:
        spot = pocket.polygon.representative_point()
        p.label("NOTES", (spot.x, spot.y), f"TOT-LOT {pocket.area_sqm:,.1f} m²")
    after = placing.after
    if not after.is_empty:
        spot = max(getattr(after, "geoms", [after]), key=lambda g: g.area).representative_point()
        p.label("NOTES", (spot.x, spot.y), f"LAND LEFT {after.area:,.1f} m²")
    return p


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
            "blocks": {"shallowest_m": round(t.blocks.depth_m, 2),
                       "smallest_m": [round(v, 2) for v in t.blocks.smallest],
                       "source": t.blocks.source},
            "readings": [_placing_facts(p) for p in t.placings],
            "waiting": list(t.waiting)}


def _placing_facts(p: Placing) -> dict:
    return {"water_reading": p.reading or None,
            "land_left_sqm": round(p.land.area, 2),
            "water_counted_sqm": round(p.water.area, 2),
            "water_too_thin_sqm": round(p.water_lost_sqm, 2),
            "no_block_sqm": round(p.thin.area, 2),
            "block_land_sqm": round(p.block_land.area, 2),
            "tot_lot_sqm": round(p.tot_lot.area, 2),
            "on": {kind: round(p.on(kind), 2) for kind in (WATER, THIN, BLOCK)},
            "short_sqm": round(p.short_sqm, 2),
            "land_left_after_sqm": round(p.after.area, 2),
            "block_land_after_sqm": round(p.block_land_after.area, 2),
            "rest_from": p.grew_from or None,
            "pockets": [{"lies": pocket.lies, "area_sqm": round(pocket.area_sqm, 2),
                         "on": {k: round(a, 2) for k, a in pocket.on_sqm},
                         "outline": mapping(pocket.polygon)} for pocket in p.pockets]}
