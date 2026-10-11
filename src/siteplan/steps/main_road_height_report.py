"""Step 2's report, pictures and facts, in plain words (steps/report.py's five questions)."""

from __future__ import annotations

import math

from shapely.geometry import LineString, box

from siteplan import rules
from siteplan.steps import carried
from siteplan.steps.drawing import Layer, Picture, frame
from siteplan.steps.main_road_height import (
    DRAWN,
    SLAB_M,
    TABLE_III_WAY,
    TABLE_IV_WAY,
    Height,
)
from siteplan.steps.report import Choice, RuleUsed, StepReport, Table
from siteplan.steps.survey_copy import BIGGEST

TITLE = "The main road and the height it allows"
DRAWN_AROUND_M = 30.0
SECTION_WIDTH_M = 14.0  # the building's width in the side view: a picture, not a design
SECTION_LABEL_M = 9.0  # how far right of the building the side view's labels stand


def report(h: Height) -> StepReport:
    r = StepReport(2, TITLE, h.inputs.site, picture=None if h.stopped else "step2.svg")
    if h.stopped:
        r.did = ["Looked for the main road in step 1's list of roads, and stopped: there is "
                 "none, so no height can be read. Nothing else was worked out."]
        r.stopped = "No height can be read yet. The engine's words: " + h.stopped
        r.happening = ["The height a building may reach depends on the road in front of it. "
                       "Without the main road there is nothing to read it from."]
        r.elements = ["The roads step 1 found."]
        r.choices = [Choice("The step stops instead of picking a road itself.", "A main road "
                            "named but not found is a mismatch to settle, not to guess.")]
        r.output = ["Nothing yet: the step needs the answer below."]
        r.tables = [_carried_table(h)]
        r.questions = [h.ask] if h.ask else []
        return r
    road = h.road
    r.did = [
        f"Took the main road from step 1: {road.name}, on the {road.lies}.",
        f"Read its width ({_width_words(h)}) and wrote it the way the rules count it "
        f"({h.reckoned_m:g} m).",
        f"Looked up, in {h.way}, the tallest building a road that wide may serve.",
        "Counted how many floors fit in that height. The stilt is kept separate: it is not "
        "counted (your rule).",
        "Checked the two other things that change the height here: whether you have said the "
        "main road is a dead end, and the extra floors TDR may buy (shown, none taken).",
    ]
    r.happening = [
        "The wider the road in front of the plot, the taller you may build: fire engines and "
        "traffic need the room.",
        "The height is counted from the first floor up. The stilt (the parking floor at the "
        "bottom) is not counted: \"Stilt + 8\" means 8 floors plus a stilt (your rule).",
        f"One floor is {h.storeys.floor_m:g} m: the lowest room the rules allow "
        f"({rules.ROOM_HEIGHT_MIN_M:g} m) plus its slab ({SLAB_M:g} m).",
        "This step does not draw any building yet. It only says how tall one may be.",
    ]
    r.elements = [
        f"The main road from step 1 ({road.name}) and its width from {h.inputs.given_as}.",
        f"The plot's area as written ({h.plot_sqm:,.1f} m²), for the rules that go by plot "
        "size.",
        f"Whether {h.inputs.given_as} name the main road as a dead end.",
        "Everything step 1 found, carried on (the table at the end).",
    ]
    r.rules = _rules(h)
    r.choices = _choices(h)
    r.output = _output(h)
    r.tables = [_bands_table(h), _carried_table(h)]
    r.questions = _questions(h)
    r.files = [("step2.svg", "the picture: the plot and the main road"),
               ("step2.dxf", "the plan, to open in CAD (metres)"),
               ("step2.json", "every number in this report")]
    if h.allowed_floors is not None:
        r.files[1:1] = [("step2-section.svg", "the side view: the stilt and the floors, with "
                         "the limits"),
                        ("step2-section.dxf", "the side view, to open in CAD (metres)")]
    return r


def _width_words(h: Height) -> str:
    if h.width_from == DRAWN and h.unpinned_m:
        return (f"{h.width_m:.2f} m as drawn; {h.inputs.given_as} give a legal width of "
                f"{h.unpinned_m:g} m without naming the road, so the drawn one stands in until "
                "you say it is this road's")
    if h.width_from == DRAWN:
        return (f"{h.width_m:.2f} m as drawn; no legal width is given, so the drawn one stands "
                "in until you give it")
    return f"legal width {h.width_m:.3f} m, {h.road.legal_source}"


def _rules(h: Height) -> list[RuleUsed]:
    out = [RuleUsed("Road widths in feet", "A width given in feet is counted in round metres: "
                    "40 ft is 12 m, 60 ft is 18 m, 80 ft is 24 m.",
                    rules.ROAD_WIDTH_CONVERSION_CLAUSE)]
    if h.way == TABLE_IV_WAY:
        out += [
            RuleUsed("Height by road (Table IV)", "Each height needs a road at least so wide: "
                     "up to 24 m a 12 m road, up to 30 m an 18 m road, up to 45 m a 24 m road, "
                     "and above that a 30 m road.", rules.TABLE_IV_CLAUSE),
            RuleUsed("High-rise", f"A building {rules.HIGH_RISE_THRESHOLD_M:g} m or taller is a "
                     "high-rise.", rules.HIGH_RISE_CLAUSE),
            RuleUsed("A plot big enough for a high-rise", f"At least "
                     f"{rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m² (step 3 checks the net plot).",
                     rules.MIN_HIGH_RISE_PLOT_CLAUSE),
        ]
    else:
        out += [
            RuleUsed("Height below high-rise (Table III)", "A building below high-rise may be "
                     "as tall as its plot size's row allows, the stilt left out.",
                     rules.TABLE_III_2012_CLAUSE),
            RuleUsed("The top line", "Above 15 m and below 18 m only on plots that abut a "
                     f"road of {rules.TABLE_III_TOP_TIER_MIN_ROAD_M:g} m or more.",
                     rules.TABLE_III_TOP_TIER_CLAUSE),
        ]
    out += [
        RuleUsed("Lowest room", f"A room is at least {rules.ROOM_HEIGHT_MIN_M:g} m high, floor "
                 "to the bottom of the slab.", rules.ROOM_HEIGHT_CLAUSE),
        RuleUsed("Lowest stilt", f"A stilt floor is at least {rules.STILT_MIN_HEIGHT_M:g} m high.",
                 rules.STILT_MIN_HEIGHT_2012_CLAUSE),
        RuleUsed("Stilt above the ground", f"Covered parking stands at least "
                 f"{rules.COVERED_PARKING_RAISE_M * 1000:g} mm above the ground.",
                 rules.COVERED_PARKING_RAISE_CLAUSE),
        RuleUsed("Dead-end road", "A residential building above "
                 f"{rules.DEAD_END_MAX_HEIGHT_M:g} m may not stand on a road that ends at the "
                 "plot. This height is the real one, from the ground, stilt included.",
                 rules.DEAD_END_CLAUSE),
    ]
    if h.tdr_floors:
        out.append(RuleUsed("Extra floors through TDR", "On plots above "
                            f"{rules.TDR_EXTRA_FLOORS_ABOVE_PLOT_SQM:,.0f} m²: up to 3 more "
                            "floors on a 40 ft road, 4 on a 60 ft road, 5 on an 80 ft road, "
                            "only by using TDR and subject to fire, airport and other norms.",
                            rules.TDR_EXTRA_FLOORS_CLAUSE))
    return out


def _choices(h: Height) -> list[Choice]:
    s = h.storeys
    out = [
        Choice("The stilt is not counted in the height that picks the Table IV row: the height "
               "starts at the first floor.", "Your rule (2026-10-11). For your information: "
               "rule 2(e) of G.O.168 lists what is left out of a height (parapet, staircase "
               "head room, lift room, water tank) and does not name the stilt, so an authority "
               "could count it."),
        Choice(f"A floor is {s.floor_m:g} m: the {rules.ROOM_HEIGHT_MIN_M:g} m room plus a "
               f"{SLAB_M:g} m slab.", "No file gives a slab's thickness. No file gives a "
               "highest room either, so there is no range to take the middle of (your rule): "
               "the lowest is used."),
        Choice(f"The stilt is {s.stilt_m:g} m floor to floor: the {rules.STILT_MIN_HEIGHT_M:g} m "
               f"rule plus the same {SLAB_M:g} m slab.", "The rule says the stilt's height, not "
               "whether it is clear of the slab; the engine reads it as the room rule reads a "
               "room (clear), so the real height is never under-counted."),
        Choice("The dead-end check uses the real height: from the ground to the terrace "
               f"({s.raise_m:g} m raise + stilt + floors).", "NBC measures its own height that "
               "way; your rule about the stilt is for the Table IV height."),
        Choice(f"The plot-size rules read the plot's written area ({h.plot_sqm:,.1f} m²).",
               "Step 2 comes before road widening; step 3 checks the net plot for a "
               "high-rise."),
    ]
    if not h.dead_end:
        out.append(Choice(f"{h.road.name} is taken as a through road, not a dead end.", "Your "
                          "rule (2026-10-11): a road is a dead end only when you say which one; "
                          "until then every road is not."))
    if h.road is not None and h.copy.access_how == BIGGEST:
        out.append(Choice(f"{h.road.name} is the main road because it is the biggest road that "
                          "meets the plot.", "Your rule: when the main road is not named, the "
                          "biggest road is the main road."))
    if h.width_from == DRAWN:
        why = (f"{h.inputs.given_as.capitalize()} give a legal width without naming the road, "
               "and step 1 does not pin it on the biggest road (asked)." if h.unpinned_m else
               "No legal width is given (asked).")
        out.append(Choice(f"The height is read from {h.road.name}'s drawn width.", why + " A "
                          "drawing often shows only the carriageway, narrower than the legal "
                          "road."))
    if h.way == TABLE_III_WAY:
        out.append(Choice("Below high-rise the height comes from Table III, the stilt left out.",
                          "The road is narrower than Table IV's 12 m, or the plot is under "
                          f"{rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m², so no high-rise is allowed. "
                          "Between 18 and 21 m no file read gives a setback: not offered."))
    return out


def _output(h: Height) -> list[str]:
    s, road = h.storeys, h.road
    if h.width_from == DRAWN:
        width = f"{h.width_m:.2f} m as drawn" + (
            f" (a legal width of {h.unpinned_m:g} m is given without naming the road)"
            if h.unpinned_m else " (no legal width given)")
    elif h.reckoned_m != h.width_m:
        width = f"{h.width_m:.3f} m ({_feet(h.width_m)} ft), counted as {h.reckoned_m:g} m"
    else:
        width = f"{h.width_m:.2f} m"
    lines = [f"Main road: {road.name} on the {road.lies}, {width}. It meets the plot along "
             f"{road.frontage_m:.2f} m."]
    if math.isinf(h.limit_m):
        lines.append(f"{h.way}: a road this wide sets no height limit (every row is allowed). "
                     "Other limits (fire, airport) are for the later steps.")
    else:
        word = "below" if h.below else "up to"
        lines.append(f"{h.way}: on a road {h.reckoned_m:g} m wide, a building may go {word} "
                     f"{h.limit_m:g} m (counted from the first floor; the stilt is not "
                     "counted).")
        if h.allowed_floors != h.floors:
            lines.append(f"The road alone would allow Stilt + {h.floors}.")
        nxt = next((b for b in h.bands if not b.served), None)
        if nxt is not None and nxt.road_m:
            lines.append(f"One floor more would need a wider road: {nxt.heights} needs "
                         f"{nxt.road_m:g} m.")
    allowed = h.allowed_floors
    if allowed is not None:
        why = (f", because {road.name} is a dead end" if allowed != h.floors else "")
        lines.append(f"THE MOST: Stilt + {allowed} floors{why}. Counted height "
                     f"{s.counted_m(allowed):.1f} m; real height from the ground to the terrace "
                     f"{s.physical_m(allowed):.2f} m ({s.raise_m:g} raise + {s.stilt_m:g} "
                     f"stilt + {allowed} x {s.floor_m:g}).")
    floors = h.floors
    over = floors is None or s.physical_m(floors) > rules.DEAD_END_MAX_HEIGHT_M
    if over:
        cap = (f"Stilt + {h.dead_end_floors} at most ({s.physical_m(h.dead_end_floors):.2f} m "
               "from the ground)")
        if h.dead_end:
            lines.append(f"{road.name} IS A DEAD END ({h.inputs.given_as}), so nothing above "
                         f"{rules.DEAD_END_MAX_HEIGHT_M:g} m real height: {cap}.")
        else:
            lines.append(f"{road.name} is not a dead end (nobody has said it is), so the "
                         f"{rules.DEAD_END_MAX_HEIGHT_M:g} m dead-end limit does not apply. If "
                         f"you ever name it a dead end: {cap}.")
    else:
        lines.append(f"The real height stays within {rules.DEAD_END_MAX_HEIGHT_M:g} m, so it "
                     "does not matter whether the road ends at the plot.")
    if allowed is not None:
        kind = "a HIGH-RISE" if h.high_rise else "not a high-rise"
        lines.append(f"Stilt + {allowed} is {kind} (high-rise is "
                     f"{rules.HIGH_RISE_THRESHOLD_M:g} m and more, counted).")
    if h.tdr_shown and allowed is not None:
        most = allowed + h.tdr_shown
        lines.append(f"With TDR (shown, NOT taken): up to {h.tdr_shown} more floors, so "
                     f"Stilt + {most} ({s.physical_m(most):.2f} m real height), only by buying "
                     "TDR and subject to fire, airport and other norms"
                     + (", and never on a dead-end road." if s.physical_m(most)
                        > rules.DEAD_END_MAX_HEIGHT_M else "."))
    elif h.tdr_floors:
        lines.append(f"TDR: no extra floor here: the {h.tdr_floors} it may buy on this road would "
                     f"go above {rules.DEAD_END_MAX_HEIGHT_M:g} m on a dead-end road.")
    if h.unpinned_m:
        other = ("no height limit" if h.unpinned_floors is None
                 else f"Stilt + {h.unpinned_floors}")
        lines.append(f"If {h.unpinned_m:g} m is {road.name}'s legal width: {other} (asked).")
    return lines


def _width_checked(h: Height) -> bool:
    """The legal width is checked against a document or confirmed by the architect."""
    site = h.inputs.project.site
    status = h.inputs.status.get("abutting_road", "")
    return (site.abutting_road_status == "CERTIFIED_ROW"
            or status in ("VERIFIED", "USER_CONFIRMED"))


def _feet(width_m: float) -> str:
    return f"{width_m / 0.3048:.0f}"


def _bands_table(h: Height) -> Table:
    rows = []
    for band in h.bands:
        floors = (f"{band.floors[0]}" if len(band.floors) == 1 else
                  f"{band.floors[0]} to {band.floors[-1]}" if band.floors else "-")
        rows.append((band.heights, "-" if band.road_m is None else f"{band.road_m:g} m",
                     "-" if band.open_space_m is None else f"{band.open_space_m:g} m",
                     floors, "yes" if band.served else "NO: the road is too narrow"))
    title = (f"{h.way}, row by row (floors at {h.storeys.floor_m:g} m each, the stilt "
             "separate)")
    return Table(title, ("Height (counted)", "Road it needs", "Open space round it (step 4)",
                         "Floors", f"Allowed on {h.road.name}"), tuple(rows))


def _used_here(h: Height) -> dict[str, str]:
    used = {}
    for item in carried.found_in(h.copy):
        if h.stopped:
            used[item.key] = "carried unchanged (this step stopped)"
        elif item.kind == carried.ROAD and h.road is not None and item.key == h.road.name:
            used[item.key] = (
                f"the main road: its width sets the height (Stilt + {h.allowed_floors})"
                if h.allowed_floors is not None else
                "the main road: its width sets the height (no limit)")
        elif item.kind == carried.ROAD:
            used[item.key] = "not used for the height: only the main road's width counts"
        else:
            used[item.key] = "carried unchanged"
    return used


def _carried_table(h: Height) -> Table:
    used = _used_here(h)
    return Table("Carried on from step 1 (everything a later rule may need)",
                 ("What", "In this step", "Needed later for"),
                 tuple((item.what, used[item.key], item.later)
                       for item in carried.found_in(h.copy)))


def _questions(h: Height) -> list[str]:
    out = []
    road = h.road
    allowed = ("no limit" if h.allowed_floors is None else f"Stilt + {h.allowed_floors}")
    if h.width_from == DRAWN and h.unpinned_m:
        out.append(f"Is {h.unpinned_m:g} m {road.name}'s legal width ({h.inputs.given_as} give it "
                   "without naming the road; step 1 asks too)? Until you say, the height is read "
                   f"from its drawn width, {h.width_m:.2f} m ({allowed}).")
    elif h.width_from == DRAWN:
        out.append(f"What is {road.name}'s legal width? The height here is read from its drawn "
                   f"width, {h.width_m:.2f} m, which may be only the carriageway.")
    elif not _width_checked(h):
        out.append(f"Is {h.width_m:g} m really {road.name}'s legal width? It sets the height "
                   f"({allowed}), and nothing records it as checked: {road.legal_source}.")
    return out


def picture(h: Height) -> Picture:
    p = Picture(f"Step 2: {TITLE}", h.inputs.site, layers=[
        Layer("PLOT", "#b0177e", 6, "The plot (step 1)", fill=0.05, width=2.5),
        Layer("MAIN-ROAD", "#d62828", 1, "The main road: its width sets the height", fill=0.45,
              width=2.0),
        Layer("MAIN-ROAD-MEETS", "#1f6fb2", 5, "Where the main road meets the plot", width=6.0),
        Layer("NOTES", "#222222", 7, ""),
    ])
    view = frame(h.copy.plot, DRAWN_AROUND_M)
    carried.draw(p, carried.found_in(h.copy), view)
    road = h.road
    ground = road.ground if road.ground is not None and not road.ground.is_empty else road.area
    p.add("MAIN-ROAD", ground.difference(h.copy.plot).intersection(view)
          if ground is not None else None)
    p.add("MAIN-ROAD-MEETS", road.frontage)
    p.add("PLOT", h.copy.plot)
    centre = h.copy.plot.representative_point()
    p.label("NOTES", (centre.x, centre.y), _headline(h))
    return p


def _headline(h: Height) -> str:
    road = h.road
    if h.width_from == DRAWN:
        width = f"{h.width_m:.2f} m drawn"
    elif h.reckoned_m != h.width_m:
        width = f"{_feet(h.width_m)} ft = {h.reckoned_m:g} m"
    else:
        width = f"{h.width_m:g} m"
    limit = ("no height limit from the road" if math.isinf(h.limit_m)
             else f"up to {h.limit_m:g} m counted")
    if h.allowed_floors is None:
        return f"MAIN ROAD {road.name}: {width}\n{limit}"
    dead = " (dead end)" if h.allowed_floors != h.floors else ""
    return f"MAIN ROAD {road.name}: {width}\n{limit}\nSTILT + {h.allowed_floors} FLOORS{dead}"


def section(h: Height) -> Picture | None:
    """The side view: the stilt and the floors standing on the ground, with each limit as a
    line at its height."""
    floors = h.allowed_floors
    if floors is None:
        return None
    s = h.storeys
    p = Picture("Step 2: the side view", h.inputs.site, plan=False, layers=[
        Layer("GROUND", "#5b3a1a", 8, "The ground", width=3.0),
        Layer("STILT", "#9e9e9e", 8, "The stilt (parking): not counted in the height",
              fill=0.5, width=1.0),
        Layer("FLOORS", "#2e8b3d", 3, "The floors: counted in the height", fill=0.25,
              width=1.0),
        Layer("TDR", "#2e8b3d", 3, "Floors TDR may add (shown, not taken)", width=1.0,
              dash="5 4"),
        Layer("LIMIT", "#d62828", 1, "The height the road allows (counted from the first "
              "floor)", width=2.0, dash="8 4"),
        Layer("DEAD-END", "#f08c00", 30, f"{rules.DEAD_END_MAX_HEIGHT_M:g} m real height: the "
              "most on a dead-end road", width=2.0, dash="3 3"),
        Layer("NOTES", "#222222", 7, ""),
    ])
    w, right = SECTION_WIDTH_M, SECTION_WIDTH_M + SECTION_LABEL_M
    first = s.raise_m + s.stilt_m  # the first floor's level
    p.add("GROUND", LineString([(-4.0, 0.0), (right + 8.0, 0.0)]))
    p.add("STILT", box(0.0, s.raise_m, w, first))
    p.label("NOTES", (w / 2, s.raise_m + s.stilt_m / 2 - 0.4), f"STILT {s.stilt_m:g} m")
    for n in range(floors):
        p.add("FLOORS", box(0.0, first + n * s.floor_m, w, first + (n + 1) * s.floor_m))
    for n in range(floors, floors + h.tdr_shown):
        p.add("TDR", box(0.0, first + n * s.floor_m, w, first + (n + 1) * s.floor_m))
    p.label("NOTES", (w / 2, first + floors * s.floor_m / 2),
            f"{floors} FLOORS x {s.floor_m:g} m\n= {s.counted_m(floors):.1f} m counted")
    top = first + s.counted_m(floors)
    p.label("NOTES", (right, top - 0.5), f"terrace {s.physical_m(floors):.2f} m\nfrom the ground")
    if not math.isinf(h.limit_m):
        limit = first + h.limit_m
        p.add("LIMIT", LineString([(-2.0, limit), (right + 6.0, limit)]))
        p.label("LIMIT", (right, limit + 0.6), f"road allows {h.limit_m:g} m counted")
    if h.dead_end:
        p.add("DEAD-END", LineString([(-2.0, rules.DEAD_END_MAX_HEIGHT_M),
                                      (right + 6.0, rules.DEAD_END_MAX_HEIGHT_M)]))
        p.label("DEAD-END", (right, rules.DEAD_END_MAX_HEIGHT_M - 1.4),
                f"{rules.DEAD_END_MAX_HEIGHT_M:g} m: dead-end limit")
    p.label("NOTES", (w / 2, -1.6), f"ground (stilt floor {s.raise_m:g} m above it)")
    return p


def facts(h: Height) -> dict:
    out = {"step": 2, "title": TITLE, "site": h.inputs.site, "stopped": h.stopped,
           "question": h.ask, "carried": carried.facts(carried.found_in(h.copy), _used_here(h))}
    if h.stopped:
        return out
    s = h.storeys
    allowed = h.allowed_floors
    return {**out,
            "main_road": {"name": h.road.name, "lies": h.road.lies,
                          "how_found": h.copy.access_how, "width_m": round(h.width_m, 3),
                          "width_from": h.width_from, "counted_as_m": h.reckoned_m},
            "plot_written_sqm": round(h.plot_sqm, 2),
            "table": h.way,
            "height_limit_m": None if math.isinf(h.limit_m) else h.limit_m,
            "limit_not_reached": h.below,
            "storey_m": {"floor": s.floor_m, "stilt": s.stilt_m, "raise": s.raise_m,
                         "slab": SLAB_M, "room": rules.ROOM_HEIGHT_MIN_M},
            "stilt_counted": False,
            "most_floors": h.floors,
            "counted_height_m": None if h.floors is None else round(s.counted_m(h.floors), 2),
            "real_height_m": None if h.floors is None else round(s.physical_m(h.floors), 2),
            "dead_end": h.dead_end,
            "dead_end_from": ("named by " + h.inputs.given_as if h.dead_end else
                              "not named a dead end, so a through road (the architect's rule)"),
            "most_floors_on_a_dead_end": h.dead_end_floors,
            "allowed_floors": allowed,
            "high_rise": h.high_rise,
            "tdr_extra_floors_shown_not_taken": h.tdr_shown,
            "legal_width_given_unnamed_m": h.unpinned_m,
            "floors_with_that_width": h.unpinned_floors,
            "rows": [{"heights": b.heights, "road_m": b.road_m, "open_space_m": b.open_space_m,
                      "floors": list(b.floors), "allowed": b.served} for b in h.bands]}
