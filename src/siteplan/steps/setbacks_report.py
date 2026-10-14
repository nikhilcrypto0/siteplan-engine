"""Step 4's report, picture and facts, in plain words (steps/report.py's five questions)."""

from __future__ import annotations

from shapely.geometry import mapping

from siteplan import rules
from siteplan.steps import carried, gate
from siteplan.steps.drawing import Layer, Picture, frame
from siteplan.steps.report import Choice, RuleUsed, StepReport, Table
from siteplan.steps.setbacks import FACES_ALONG_M, LANE_CROSSES_SQM, LONG_BLOCKS_M, Setbacks
from siteplan.steps.survey_copy import SHORT_RUN_M, side_label_at

TITLE = "Setbacks from every side"
DRAWN_AROUND_M = 30.0


def report(s: Setbacks) -> StepReport:
    r = StepReport(4, TITLE, s.inputs.site, picture=None if s.stopped else "step4.svg")
    if s.stopped:
        r.did = ["Looked for what the setbacks are measured from and how tall the building is, "
                 "and stopped: " + s.stopped + ". Nothing else was worked out."]
        r.stopped = "The setbacks cannot be drawn yet: " + s.stopped + "."
        r.happening = ["Setbacks are measured from the net plot and grow with the height, so "
                       "this step needs both before it can draw anything."]
        r.elements = ["The net plot (step 3) and the height (step 2)."]
        r.choices = [Choice("The step stops instead of drawing setbacks on a guessed plot or "
                            "height.", "A setback drawn on the wrong line moves every building "
                            "after it.")]
        r.output = ["Nothing yet: the step needs the answer below."]
        r.tables = [_carried_table(s)]
        r.questions = [s.ask] if s.ask else []
        return r
    h = s.height
    r.did = [
        f"Took the net plot from step 3 ({s.widening.net.area:,.1f} m²) and the height from "
        f"step 2: Stilt + {s.floors} ({s.counted_m:.1f} m counted, the stilt not counted).",
        f"Looked up the open space a building that tall keeps on every side: "
        f"{s.open_space_m:g} m ({'Table IV' if s.high_rise else 'Table III'}).",
        "Found which sides of the plot meet a road, and gave each of them the front setback "
        "the rules ask there.",
    ]
    if s.high_rise:
        r.did += [f"Marked the {rules.PERIPHERAL_GREEN_STRIP_M:g} m green strip inside the "
                  "setback along each side that keeps "
                  f"{rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M:g} m or more, drew where a "
                  f"{rules.FIRE_TENDER_MIN_WIDTH_M:g} m fire lane can run just inside it (dark "
                  "red), and checked it fits."]
    if s.left_by_water:
        r.did.append("Laid the water's buffer over the setbacks.")
    r.did.append("Measured the land left for buildings, and showed what lower heights, longer "
                 "blocks and other choices would change (none taken).")
    r.happening = [
        "A building has to stand back from the edge of its plot: for light and air, and so a "
        "fire engine can drive all the way round a tall one.",
        "The taller the building, the further back it stands.",
        "Setbacks are measured from the net plot, the line left after road widening (step 3).",
        "No building stands in the setback. The green strip and the fire lane go in it.",
    ]
    r.elements = [
        "The net plot (step 3), side by side.",
        f"The height (step 2): Stilt + {s.floors}, on {h.road.name}.",
        "Which roads meet which sides (step 1, and the land given up to widen them in step 3).",
    ]
    if s.widening.water:
        r.elements.append("The water named in the project and its buffer (step 3).")
    r.elements.append("Everything step 1 found, carried on (the table at the end).")
    r.rules = _rules(s)
    r.choices = _choices(s)
    r.output, r.tables = _output(s)
    r.questions = _questions(s)
    r.files = [("step4.svg", "the picture"), ("step4.dxf", "the same, to open in CAD (metres)"),
               ("step4.json", "every number in this report, with the outline of the land left "
                "for buildings")]
    return r


def _rules(s: Setbacks) -> list[RuleUsed]:
    out = [RuleUsed("Measure from the net plot", "Setbacks are left after the land for road "
                    "widening comes off.", rules.SETBACK_ON_NET_PLOT_CLAUSE)]
    if s.high_rise:
        out += [
            RuleUsed("Open space all round (Table IV)", "A building up to 21 m keeps 7 m, up to "
                     "24 m 8 m, up to 27 m 9 m, up to 30 m 10 m, and so on.",
                     rules.TABLE_IV_CLAUSE),
            RuleUsed("The front", "Towards a road, the higher of Table IV and Table III's "
                     "Building Line for that road's width.", rules.FRONT_SETBACK_CLAUSE),
            RuleUsed("Building Line (Table III)", "By the road's width: 3 m up to 12 m, 4 m up "
                     "to 18 m, 5 m up to 24 m, 6 m up to 30 m, 7.5 m above (large plots).",
                     rules.TABLE_III_2012_CLAUSE),
            RuleUsed("Green strip", f"A {rules.PERIPHERAL_GREEN_STRIP_M:g} m green planting "
                     "strip inside the setbacks, along each side whose setback is "
                     f"{rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M:g} m or more (you confirmed "
                     "G.O.Ms.No.7 of 2016's wording on 2026-10-13; the 2012 text, without the "
                     f"{rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M:g} m, is no longer applied).",
                     rules.PERIPHERAL_GREEN_STRIP_CLAUSE),
            RuleUsed("Fire lane", f"A {rules.FIRE_TENDER_MIN_WIDTH_M:g} m open space a fire "
                     "engine can drive on, on all sides of a high-rise.",
                     rules.FIRE_ACCESS_CLAUSE),
            RuleUsed("Long buildings", f"A building longer than {rules.LONG_BLOCK_FROM_M:g} m "
                     f"keeps {rules.LONG_BLOCK_SHARE:.0%} of its length less "
                     f"{rules.LONG_BLOCK_LESS_M:g} m more, up to {rules.LONG_BLOCK_MAX_M:g} m.",
                     rules.LONG_BLOCK_CLAUSE),
            RuleUsed("A side without windows", f"May keep {rules.NO_OPENING_REDUCTION_M:g} m "
                     "less where its rooms take no light or air from it.",
                     rules.NO_OPENING_CLAUSE),
        ]
    else:
        out += [
            RuleUsed("Setbacks below high-rise (Table III)", "The front by the road's width, "
                     "the other sides by the plot's size and the building's height.",
                     rules.TABLE_III_2012_CLAUSE),
            RuleUsed("More than one road", "The front setback towards the bigger road; column "
                     "10 on the other sides.", rules.TABLE_III_BIGGER_ROAD_CLAUSE),
        ]
    if s.widening.water:
        outside, within = rules.RIVER_BUFFER_2012_M
        out.append(RuleUsed("Keep clear of water", "No building within a water body's buffer "
                            f"(a nala 9 or 2 m, a lake 30 or 9 m, a river {outside:g} or "
                            f"{within:g} m).", rules.WATER_BUFFER_2012_CLAUSE))
    if s.concession is not None:
        out.append(RuleUsed("Smaller setbacks for land given up", "A high-rise may keep "
                            f"{rules.ROAD_SURRENDER_HIGH_RISE_CLEAR_M:g} m clear on its sides "
                            "and rear, the front as it is; one of three rewards.",
                            rules.ROAD_SURRENDER_HIGH_RISE_CLAUSE))
    return out


def _choices(s: Setbacks) -> list[Choice]:
    out = [
        Choice("The setbacks are drawn for the tallest building step 2 allows "
               f"(Stilt + {s.floors}).", "No building is designed yet; lower ones may stand "
               "closer (the table of heights)."),
        Choice(f"A side meets a road when at least {FACES_ALONG_M:g} m of it lies along the "
               "road's frontage, or along land given up to widen that road.", "The rules speak "
               "of the side abutting the road and do not say how much is enough."),
        Choice("Every point of the land left is at least its side's setback from that side; at a "
               "corner the two setbacks meet in a curve.", "The rules give a distance from each "
               "side; the engine keeps each one exactly."),
        Choice("A side that meets a road keeps its front setback along its whole length, even "
               "where the road meets only part of it.", "The rules speak of the side abutting "
               "the road and do not cut a side where the road stops."),
        Choice("The stilt is not counted in the height that picks the row.", "Your rule "
               "(2026-10-11), carried from step 2."),
    ]
    if not s.high_rise:
        out.append(Choice(f"The front is towards {s.front_road}, the widest road that meets the "
                          "net plot (its legal width where one is given, else as drawn).",
                          "Rule 5(f)(iii): the front setback towards the bigger road; the main "
                          "road wins a tie."))
    if s.concession is not None:
        out.append(Choice("Under the concession every side that meets a road keeps its front "
                          "setback; only the others come down to 7 m.", "Rule 16(e) keeps 'the "
                          "front' as it is and does not say which side that is on a plot with "
                          "more than one road: the stricter reading."))
    if s.left_by_water:
        out.append(Choice("The water's buffer is laid over the setbacks: land in both is kept "
                          "free once, and the setback is still measured from the plot's edge.",
                          "Your rule (2026-10-11): the buffer and the setbacks overlap; neither is "
                          "added to the other. Rule 3(a)(iii)(3) reckons the buffer as tot-lot or "
                          "open space 'and not for setback requirements'; you read the two as "
                          "overlapping."))
    if s.options:
        out.append(Choice("The table of lower heights reads Table IV's first row as G.O.50 "
                          "prints it (up to 21 m: 7 m).", "Below "
                          f"{rules.HIGH_RISE_THRESHOLD_M:g} m a building is not a high-rise, "
                          "and Table III may ask less of it; that is for the buildings "
                          "(step 6)."))
    if s.high_rise:
        green, lane = rules.PERIPHERAL_GREEN_STRIP_M, rules.FIRE_TENDER_MIN_WIDTH_M
        out.append(Choice(f"The fire lane is drawn just inside the green strip, {green:g} m to "
                          f"{green + lane:g} m in from the edge, and from the edge where a side "
                          "keeps no strip.", "NBC asks a "
                          f"{lane:g} m lane on all sides and does not say where in the setback. "
                          "Where the buildings and roads finally put it, and its turns at the "
                          "corners, are step 6's."))
    if s.lane_in_water:
        out.append(Choice("The fire lane may run in a water body's buffer.", "Your rule "
                          "(2026-10-11), with the buffer overlapping the setbacks."))
    return out


def _output(s: Setbacks) -> tuple[list[str], list[Table]]:
    net = s.widening.net
    lines = [_keeps(s) + "."]
    lines.append(f"Setback land: {s.band.area:,.1f} m². LAND LEFT FOR BUILDINGS: "
                 f"{s.left.area:,.1f} m² of the net plot's {net.area:,.1f} m² "
                 f"({s.left.area / net.area:.0%}).")
    if s.left.is_empty:
        lines.append("NO LAND IS LEFT for buildings at this height: no building fits.")
    if s.green is not None:
        lines.append(f"Green strip ({rules.PERIPHERAL_GREEN_STRIP_M:g} m, inside the setback): "
                     f"{s.green.area:,.1f} m².")
        room = s.fire_room_m
        fits = "it fits" if room >= rules.FIRE_TENDER_MIN_WIDTH_M - 1e-6 else "IT DOES NOT FIT"
        lines.append(f"Fire lane: beside the green strip the narrowest setback leaves {room:g} m "
                     f"for a {rules.FIRE_TENDER_MIN_WIDTH_M:g} m lane: {fits}. Drawn in dark "
                     f"red: {s.fire_lane.area:,.1f} m².")
        into = s.fire_lane.intersection(s.left).area
        if into >= LANE_CROSSES_SQM:
            lines.append(f"The lane reaches {into:,.1f} m² into the land left for buildings, "
                         "where the setback is too narrow for it.")
        for kind, on_line, on_edge in s.lane_in_water:
            lines.append(f"{on_line:,.1f} m² of the fire lane lies in the "
                         f"{kind.replace('_', ' ')}'s buffer from the line drawn "
                         f"({on_edge:,.1f} m² from the plot's edge): allowed (your rule, "
                         "2026-10-11).")
    for kind, from_line, from_edge in s.left_by_water:
        lines.append(f"With the {kind.replace('_', ' ')}'s buffer laid over the setbacks: "
                     f"{from_line.area:,.1f} m² left if the buffer starts at the line drawn, "
                     f"{from_edge.area:,.1f} m² if it starts at the plot's edge (asked in "
                     "step 3).")
    if any(w.buffer_m is None for w in s.widening.water):
        lines.append("The river's buffer waits on one answer (step 3), so it is not laid over "
                     "the setbacks yet.")
    if s.concession is not None:
        c = s.concession
        lines.append(f"With the road-widening concession (shown, NOT taken): sides and rear "
                     f"{c.open_space_m:g} m, every side on a road {c.front_m:g} m, land left "
                     f"{c.left_sqm:,.1f} m² ({c.left_sqm - s.left.area:+,.1f} m²). It is one of "
                     "three rewards (step 3) and only for a Master Plan or Road Development Plan "
                     "road.")
    if s.high_rise:
        less = s.open_space_m - rules.NO_OPENING_REDUCTION_M
        low, high = rules.NO_OPENING_LIMITS_M
        figure = (f"{less:g} m" if low <= less <= high
                  else f"{less:g} m, or {high:g} m by the note's maximum: asked")
        lines.append(f"A side whose rooms take no light or air from it may keep "
                     f"{rules.NO_OPENING_REDUCTION_M:g} m less ({figure}). Not drawn: it "
                     "depends on the building's design (step 6).")
    tables = [_sides_table(s)]
    if s.options:
        tables.append(Table("Lower buildings stand closer (shown, not taken)",
                            ("Height (counted)", "Floors", "Open space all round",
                             f"Towards {s.front_road}", "Land left for buildings"),
                            tuple((o.heights, _floors(o.floors), f"{o.open_space_m:g} m",
                                   f"{o.front_m:g} m", f"{o.left_sqm:,.1f} m²")
                                  for o in s.options)))
    if s.long_blocks:
        tables.append(Table("Longer buildings keep more (applied when a block is drawn, "
                            "step 6)", ("Block length", "Open space round it"),
                            tuple((f"{length:g} m", f"{metres:g} m")
                                  for length, metres in s.long_blocks)))
    return lines, [*tables, _carried_table(s)]


def _keeps(s: Setbacks) -> str:
    """'Every side keeps 10 m', or the sides and the front apart when they differ."""
    if s.front_m == s.open_space_m:
        return f"Every side keeps {s.open_space_m:g} m"
    return (f"The sides keep {s.open_space_m:g} m; the front, towards {s.front_road}, keeps "
            f"{s.front_m:g} m")


def _floors(floors: tuple[int, ...]) -> str:
    return f"{floors[0]}" if len(floors) == 1 else f"{floors[0]} to {floors[-1]}"


def _sides_table(s: Setbacks) -> Table:
    long = [side for side in s.sides if side.length_m >= SHORT_RUN_M]
    rows = [(str(side.number), side.faces, f"{side.length_m:.2f} m",
             ", ".join(side.roads) or "-", f"{side.metres:g} m", side.why) for side in long]
    short = [side for side in s.sides if side.length_m < SHORT_RUN_M]
    if short:
        metres = sorted({side.metres for side in short})
        jogs = f"{len(short)} jog{'' if len(short) == 1 else 's'}"
        rows.append((jogs, "-", f"{sum(x.length_m for x in short):.2f} m in all",
                     ", ".join(sorted({r for x in short for r in x.roads})) or "-",
                     " or ".join(f"{m:g} m" for m in metres),
                     f"short stretches under {SHORT_RUN_M:g} m, each with its own setback"))
    return Table("Every side of the net plot", ("Side", "Faces", "Length", "Meets road",
                                                "Setback", "Why"), tuple(rows))


def _used_here(s: Setbacks) -> dict[str, str]:
    used = {}
    met = {name for side in s.sides for name in side.roads}
    water = {w.kind: w for w in s.widening.water}
    for item in carried.found_in(s.copy):
        if s.stopped:
            used[item.key] = "carried unchanged (this step stopped)"
        elif item.kind == carried.ROAD and item.key in met:
            used[item.key] = (f"meets the net plot: the side it meets keeps "
                              f"{max(x.metres for x in s.sides if item.key in x.roads):g} m")
        elif item.kind == carried.ROAD:
            used[item.key] = "meets no side of the net plot: no setback is set by it"
        elif item.kind == carried.WATER and item.key in water and water[item.key].buffer_m:
            used[item.key] = (f"its {water[item.key].buffer_m:g} m buffer is laid over the "
                              "setbacks (both readings, from step 3)")
        elif item.kind == carried.WATER and item.key in water:
            used[item.key] = "its buffer waits on one answer (step 3)"
        elif item.kind == carried.MARK and "power line" in item.later:
            used[item.key] = "asked: where the line runs and its voltage set the safe distance"
        else:
            used[item.key] = "carried unchanged"
    return used


def _carried_table(s: Setbacks) -> Table:
    used = _used_here(s)
    return Table("Carried on from step 1 (everything a later rule may need)",
                 ("What", "In this step", "Needed later for"),
                 tuple((item.what, used[item.key], item.later)
                       for item in carried.found_in(s.copy)))


def _questions(s: Setbacks) -> list[str]:
    out = []
    low, high = rules.NO_OPENING_LIMITS_M
    less = s.open_space_m - rules.NO_OPENING_REDUCTION_M
    if s.high_rise and not low <= less <= high:
        out.append("G.O.50's note lets a side without windows keep "
                   f"{rules.NO_OPENING_REDUCTION_M:g} m less, 'subject to a minimum of "
                   f"{low:g} m and a maximum of {high:g} m'. "
                   f"For a {s.open_space_m:g} m open space, is that {less:g} m, or at most "
                   f"{high:g} m?")
    for item in carried.found_in(s.copy):
        if item.kind == carried.MARK and "power line" in item.later:
            out.append(f"{item.what}: where does the power line run, and what is its voltage? "
                       "The safe distance from it goes by both.")
    return out


def picture(s: Setbacks) -> Picture:
    p = Picture(f"Step 4: {TITLE}", s.inputs.site, layers=[
        Layer("LEFT", "#4f86c6", 5, "Land left for buildings", fill=0.18, width=1.5),
        Layer("SETBACK", "#f08c00", 30, "Setback: no building here", fill=0.30, width=0.5),
        Layer("GREEN-STRIP", "#2e8b3d", 3, f"{rules.PERIPHERAL_GREEN_STRIP_M:g} m green strip "
              "(inside the setback)", fill=0.55, width=0.5),
        Layer("FIRE-LANE", "#8b0000", 14, f"Where the {rules.FIRE_TENDER_MIN_WIDTH_M:g} m fire "
              "lane can run (inside the setback)", fill=0.85, width=0.5),
        Layer("WATER-BUFFER-EDGE", "#b9e6f2", 4, "Water's buffer if the water reaches the "
              "plot's edge", fill=0.35, width=0.8, dash="4 3"),
        Layer("WATER-BUFFER", "#5cc4dd", 4, "Water's buffer from the line drawn", fill=0.45,
              width=0.5),
        Layer("NET-PLOT", "#2e8b3d", 3, "The net plot (step 3): setbacks are measured from it",
              width=3.0),
        gate.LAYER,
        Layer("NOTES", "#222222", 7, ""),
    ])
    net = s.widening.net
    view = frame(s.copy.plot, DRAWN_AROUND_M)
    carried.draw(p, carried.found_in(s.copy), view)
    p.add("SETBACK", s.band)
    p.add("GREEN-STRIP", s.green)
    for water in s.widening.water:
        p.add("WATER-BUFFER-EDGE", water.edge_kept_free)
        p.add("WATER-BUFFER", water.kept_free)
    p.add("FIRE-LANE", s.fire_lane)
    p.add("LEFT", s.left)
    p.add("NET-PLOT", net)
    gate.draw(p, gate.on_net(net, s.height.road, s.widening.pieces))
    for side in s.sides:
        if side.length_m >= SHORT_RUN_M:
            p.label("NOTES", side_label_at(side, net, -side.metres / 2), f"{side.metres:g} m")
    spot = s.left.representative_point() if not s.left.is_empty else net.representative_point()
    keeps = (f"{s.open_space_m:g} m all round" if s.front_m == s.open_space_m
             else f"sides {s.open_space_m:g} m, front {s.front_m:g} m")
    p.label("NOTES", (spot.x, spot.y), f"LAND LEFT {s.left.area:,.1f} m²\nStilt + {s.floors}: "
            f"{keeps}")
    return p


def facts(s: Setbacks) -> dict:
    out = {"step": 4, "title": TITLE, "site": s.inputs.site, "stopped": s.stopped,
           "question": s.ask, "carried": carried.facts(carried.found_in(s.copy), _used_here(s))}
    if s.stopped:
        return out
    return {**out,
            "floors": s.floors, "counted_height_m": round(s.counted_m, 2),
            "high_rise": s.high_rise, "open_space_m": s.open_space_m, "front_m": s.front_m,
            "front_road": s.front_road,
            "sides": [{"side": x.number, "faces": x.faces, "length_m": round(x.length_m, 2),
                       "meets_roads": list(x.roads), "setback_m": x.metres, "why": x.why}
                      for x in s.sides],
            "setback_sqm": round(s.band.area, 2),
            "green_strip_sqm": None if s.green is None else round(s.green.area, 2),
            "fire_lane_room_m": round(s.fire_room_m, 2) if s.high_rise else None,
            "fire_lane_sqm": None if s.fire_lane is None else round(s.fire_lane.area, 2),
            "fire_lane_in_water_buffer_sqm": [{"water": kind, "from_line_drawn": round(a, 2),
                                               "from_plot_edge": round(b, 2)}
                                              for kind, a, b in s.lane_in_water],
            "left_sqm": round(s.left.area, 2),
            "left_with_water_sqm": [{"water": kind, "buffer_from_line_drawn": round(a.area, 2),
                                     "buffer_from_plot_edge": round(b.area, 2)}
                                    for kind, a, b in s.left_by_water],
            "lower_heights": [{"heights": o.heights, "floors": list(o.floors),
                               "open_space_m": o.open_space_m, "front_m": o.front_m,
                               "left_sqm": round(o.left_sqm, 2)} for o in s.options],
            "long_blocks": [{"length_m": length, "open_space_m": metres}
                            for length, metres in s.long_blocks],
            "long_block_lengths_shown_m": list(LONG_BLOCKS_M) if s.long_blocks else [],
            "concession_shown_not_taken": None if s.concession is None else {
                "sides_and_rear_m": s.concession.open_space_m, "front_m": s.concession.front_m,
                "left_sqm": round(s.concession.left_sqm, 2)},
            "left_outline": mapping(s.left)}
