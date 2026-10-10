"""Step 1's report, picture and facts, in plain words (steps/report.py's five questions)."""

from __future__ import annotations

from shapely.geometry import Point

from siteplan import rules
from siteplan.steps.drawing import Layer, Picture, colour_name, frame
from siteplan.steps.inputs import compass_word
from siteplan.steps.report import Choice, RuleUsed, StepReport, Table
from siteplan.steps.survey_copy import (
    AGREES_PCT,
    APART,
    CARRIED,
    ENDS_AT_DEG,
    ROAD_LEVEL_REACH_M,
    ROAD_TOUCH_M,
    SHORT_RUN_M,
    SIDE_MATCH_M,
    WIDTH_MATCH_M,
    SurveyCopy,
    outside_water,
    side_label_at,
)

TITLE = "Copy the survey"
DRAWN_AROUND_M = 45.0  # how far round the plot the picture shows roads and levels
LABEL_OFFSET_M = 6.0  # a side's label sits this far outside its middle


def report(copy: SurveyCopy) -> StepReport:
    inputs = copy.inputs
    r = StepReport(1, TITLE, inputs.site, picture="step1.svg")
    r.did = [
        f"Opened the survey drawing `{inputs.survey_path.name}` and read it in metres.",
        "Checked the drawing against the numbers written on it: "
        + ("the side lengths and " if copy.sides_read else "") + "the plot area.",
        "Found every road drawn within 40 m of the plot, measured how wide each one is drawn, "
        "and found where each one meets the plot.",
        "Read the ground levels (the small height numbers on the sheet).",
        "Listed what is drawn inside the plot (to be ignored) and what is drawn outside it, "
        f"within {rules.SITE_PLAN_NEIGHBOUR_BAND_M:g} m (to be reported).",
    ]
    r.happening = [
        "This step only copies the survey. Nothing is designed and no building rule is "
        "applied yet.",
        "Its job is to get the plot right, so every later step stands on the right land.",
        "Where the drawing and its written numbers disagree, or something cannot be read, it "
        "says so here instead of guessing.",
    ]
    r.elements = [
        "The plot's boundary line: its corners, sides, perimeter and area.",
        "The numbers written on the sheet: the side lengths and the plot's area.",
        "The roads: their drawn edge lines.",
        "The spot levels: the ground's heights written on the sheet.",
        "The words and lines drawn inside the plot and around it.",
        f"From {inputs.given_as}: which road is the access road and its legal width"
        + (", and the water bodies named" if inputs.project.site.water else "") + ".",
    ]
    r.rules = [
        RuleUsed("What a site plan shows",
                 f"Show the streets, buildings and premises within "
                 f"{rules.SITE_PLAN_NEIGHBOUR_BAND_M:g} m of the site; if no street is that "
                 "close, the nearest one.", rules.SITE_PLAN_NEIGHBOUR_BAND_CLAUSE),
        RuleUsed("What to ignore", "Things inside the plot (bores, rooms, trees, transformers) "
                 "are listed and ignored; roads, water and anything outside are respected.",
                 "Your instruction (the new approach, 2026-10-10); not a law"),
    ]
    r.choices = _choices(copy)
    r.output, r.tables = _output(copy)
    r.questions = _questions(copy)
    r.files = [("step1.svg", "the picture"), ("step1.dxf", "the same, to open in CAD (metres)"),
               ("step1.json", "every number in this report")]
    return r


def _choices(copy: SurveyCopy) -> list[Choice]:
    out = [
        Choice(f"The scale was {copy.scale}.", "The printed scale on a sheet is not trusted; the "
               "written lengths are."),
        Choice(f"The boundary is {copy.boundary_how}.", "A sheet can draw more than one "
               "outline."),
        Choice(f"A road runs into the plot (rather than along it) when its direction is more "
               f"than {ENDS_AT_DEG:g} degrees off the side it is nearest.",
               "The engine's reading, not a rule."),
        Choice(f"Straight stretches of the boundary shorter than {SHORT_RUN_M:g} m are counted "
               "as jogs, not listed as sides.", "To keep the list of sides readable."),
        Choice(f"A written length and a drawn figure agree when they are within {AGREES_PCT:g}%"
               + (f"; a written length belongs to the side whose drawn length is within "
                  f"{SIDE_MATCH_M * 100:g} cm of it" if copy.sides_read else "") + ".",
               "The engine's tolerance, not a rule."),
        Choice(f"A road meets the plot when its drawn edge comes within {ROAD_TOUCH_M:g} m of "
               "the boundary.", "The engine's tolerance, not a rule."),
        Choice(f"A road's level where it meets the plot is the middle of the levels drawn on it "
               f"within {ROAD_LEVEL_REACH_M:g} m of that point.", "Levels on the road itself, "
               "not on the plot."),
    ]
    for road in copy.roads:
        if road.meets == CARRIED:
            out.append(Choice(
                f"{road.name}'s straight edges stop {road.carried_m:.2f} m before the plot. One "
                "of its own drawn lines reaches the plot there, so the road was taken on in its "
                "own direction to the plot.",
                "Otherwise the road would look as if it does not reach the plot."))
    if copy.access is not None:
        site = copy.inputs.project.site
        matched = [f"lies on the {compass_word(site.access_side)}"] if site.access_side else []
        if site.measured_carriageway_m:
            matched.append(f"is drawn {site.measured_carriageway_m:g} m wide")
        said = " and ".join(matched) or "is the only road that meets the plot"
        out.append(Choice(f"{copy.access.name} is taken as the access road: of the roads that "
                          f"meet the plot, it is the one that {said}, as {copy.inputs.given_as} "
                          f"record (a width within {WIDTH_MATCH_M * 100:g} cm counts).",
                          "The access road is recorded by its side and its drawn width, not by "
                          "its number."))
    return out


def _output(copy: SurveyCopy) -> tuple[list[str], list[Table]]:
    lines = [f"Plot: {len(copy.plot.exterior.coords) - 1} corners, {len(copy.sides)} sides"
             + (f" and {copy.jogs[0]} short jogs" if copy.jogs[0] else "")
             + f", perimeter {copy.plot.length:,.2f} m."]
    if copy.written_sqm:
        diff = (copy.drawn_sqm / copy.written_sqm - 1) * 100
        verdict = ("no check: the scale came from this area" if not copy.scale_is_a_check else
                   "they agree" if abs(diff) <= AGREES_PCT else "THEY DISAGREE")
        lines.append(f"Area: drawn {copy.drawn_sqm:,.1f} m², written "
                     f"{copy.written_sqm:,.2f} m² ({diff:+.2f}%): {verdict}.")
    else:
        lines.append(f"Area: drawn {copy.drawn_sqm:,.1f} m²; no area is written on the sheet.")
    written = [s for s in copy.sides if s.written_m is not None]
    if written:
        bad = [s for s in written if not s.agrees]
        lines.append(f"Sides: {len(written)} have a length written on the sheet. The drawing's "
                     "scale is worked out from those same lengths, so this checks they agree "
                     "with each other: "
                     + ("they all do." if not bad else
                        f"{len(bad)} DO NOT: side(s) "
                        + ", ".join(str(s.number) for s in bad) + "."))
    elif copy.inputs.survey.calibration is None:
        lines.append("Sides: written side lengths are read from a PDF sheet only; this is a CAD "
                     "drawing, so none were checked.")
    else:
        lines.append("Sides: no length is written on the sheet, so none can be checked.")
    meeting = [r for r in copy.roads if r.meets != APART]
    lines.append(f"Roads: {len(copy.roads)} within 40 m; {len(meeting)} meet the plot ("
                 + ", ".join(r.name for r in meeting) + ").")
    if copy.access is not None:
        a = copy.access
        lines.append(f"Access road: {a.name} on the {a.lies}, drawn {a.drawn_width_m:.2f} m "
                     f"wide; legal width {a.legal_width_m:.2f} m ({a.legal_source}).")
    else:
        lines.append("Access road: not told apart from the others yet (step 2 picks the main "
                     "road).")
    t = copy.terrain
    if t:
        lines.append(f"Ground: {t.lowest:.2f} to {t.highest:.2f} m, falling to the "
                     f"{compass_word(t.falls_towards)}, {t.slope_pct:.2f}% on average "
                     f"({copy.levels[0]} levels on the plot, {copy.levels[1]} off it).")
    else:
        lines.append("Ground: too few levels on the plot to read its slope.")
    lines.append("Inside the plot (ignored): "
                 + (", ".join(_counted(t, n) for t, n in copy.inside) or "nothing written")
                 + (f"; and lines in {len(copy.inside_lines)} colour(s) or layer(s) cross the "
                    "plot that the engine cannot name" if copy.inside_lines else "") + ".")
    near = [f"{w.replace('_', ' ')} {d:.1f} m away" for w, d in copy.water
            if d <= rules.SITE_PLAN_NEIGHBOUR_BAND_M]
    near += [f'"{m.text}" written {m.distance_m:.1f} m away' for m in copy.marks]
    for missing in copy.inputs.water_missing:
        lines.append(f"Water named in {copy.inputs.given_as} but NOT drawn on the survey: "
                     f"{missing}.")
    lines.append(f"Outside, within {rules.SITE_PLAN_NEIGHBOUR_BAND_M:g} m (reported): "
                 + ", ".join([*(f"{r.name} ({r.distance_m:.1f} m)" for r in copy.roads
                                if r.distance_m <= rules.SITE_PLAN_NEIGHBOUR_BAND_M),
                              *near, *(_counted(t, n) for t, n in copy.outside)]) + ".")
    if not any(r.distance_m <= rules.SITE_PLAN_NEIGHBOUR_BAND_M for r in copy.roads):
        nearest = min(copy.roads, key=lambda r: r.distance_m, default=None)
        lines.append("No street within 12 m; the nearest is "
                     + (f"{nearest.name}, {nearest.distance_m:.1f} m away." if nearest
                        else "not drawn on the sheet."))
    sides = Table("The sides", ("Side", "Faces", "Drawn (m)", "Written on the sheet (m)",
                                "Agree?"),
                  tuple((str(s.number), s.faces, f"{s.drawn_m:.2f}",
                         f"{s.written_m:.2f}" if s.written_m is not None else "not written",
                         {None: "-", True: "yes", False: "NO"}[s.agrees]) for s in copy.sides))
    roads = Table("The roads", ("Road", "Lies to the", "Drawn width", "Meets the plot?",
                                "Length it meets", "Road level there", "Legal width"),
                  tuple((r.name, r.lies, f"{r.drawn_width_m:.2f} m",
                         r.meets + ("" if r.meets != APART else f" ({r.distance_m:.2f} m off)"),
                         f"{r.frontage_m:.2f} m" if r.frontage_m else "-",
                         f"{r.level[1]:.2f} m ({r.level[3]} level(s))" if r.level else "none drawn",
                         f"{r.legal_width_m:.2f} m" if r.legal_width_m else "not given")
                        for r in copy.roads))
    unnamed = Table("Lines the engine cannot name", ("Colour or layer", "Length near the plot",
                                                     "Crosses the plot?"),
                    tuple((colour_name(g.key), f"{g.length_m:,.1f} m",
                           "yes" if g.crosses_plot else "no")
                          for g in (*copy.inside_lines, *copy.near_lines)))
    tables = [sides, roads] + ([unnamed] if unnamed.rows else [])
    return lines + [f"Warning from the survey reader: {w}" for w in copy.warnings], tables


def _questions(copy: SurveyCopy) -> list[str]:
    out = [f"What is the legal width of {r.name} (drawn {r.drawn_width_m:.2f} m, on the "
           f"{r.lies})? It meets the plot." for r in copy.roads
           if r.meets != APART and r.legal_width_m is None]
    site = copy.inputs.project.site
    if copy.access is None and (site.abutting_road_m or site.abutting_road_ft):
        out.append(f"According to {copy.inputs.given_as} there is an access road, but no road "
                   "that meets the plot matches it (by its side and drawn width). Which road is "
                   "it?")
    elif copy.access is None:
        out.append("Which road is the main (access) road? Step 2 starts from it.")
    for missing in copy.inputs.water_missing:
        out.append(f"The {missing} is named but the survey does not draw it in that colour or "
                   "layer. Where is it drawn?")
    if not copy.scale_is_a_check:
        out.append("Can you confirm one side's length? No length is written on the sheet, so "
                   "the drawing's size rests on its written area alone.")
    if any(g.crosses_plot for g in copy.inside_lines):
        out.append("Lines in " + ", ".join(colour_name(g.key) for g in copy.inside_lines)
                   + " cross the plot "
                   "and the engine cannot name them. If any of them is a road, a drain, a "
                   "power line or water, say which.")
    return out


def picture(copy: SurveyCopy) -> Picture:
    plot = copy.plot
    view = frame(plot, DRAWN_AROUND_M)
    p = Picture(f"Step 1: {TITLE}", copy.inputs.site, layers=[
        Layer("BAND-12M", "#f2b84b", 30, f"{rules.SITE_PLAN_NEIGHBOUR_BAND_M:g} m round the "
              "plot: what lies here is reported", fill=0.18, width=0.5),
        Layer("ROADS", "#d62828", 1, "Roads as drawn (the ground between their edges)",
              fill=0.12, width=1.0),
        Layer("ROAD-EDGES", "#d62828", 1, "", width=1.5),
        Layer("WATER", "#00a6c8", 4, "Water the project names", width=2.5),
        Layer("PLOT", "#b0177e", 6, "The plot's boundary, as surveyed", fill=0.05, width=2.5),
        Layer("ROAD-MEETS", "#1f6fb2", 5, "Where a road meets the plot", width=6.0),
        Layer("LEVELS", "#8a8a8a", 8, "Spot levels", width=1.0),
        Layer("INSIDE", "#6d6d6d", 8, "Inside the plot: listed, then ignored", width=2.0),
        Layer("SIDES", "#5a2a82", 6, ""),
        Layer("NOTES", "#222222", 7, ""),
    ])
    p.add("BAND-12M", copy.band)
    for road in copy.roads:
        p.add("ROADS", road.area.intersection(view) if road.area else None)
        p.add("ROAD-MEETS", road.frontage)
        if road.area:
            p.label("ROADS", _label_at(road, view), f"{road.name}: {road.drawn_width_m:.2f} m"
                    + (f" (legal {road.legal_width_m:.2f} m)" if road.legal_width_m else ""))
    for line in copy.inputs.survey.roads:
        p.add("ROAD-EDGES", line.intersection(view))
    for _, line in outside_water(copy.inputs):
        p.add("WATER", line.intersection(view))
    p.add("PLOT", plot)
    for level in copy.inputs.survey.levels:
        if view.contains(Point(level.x, level.y)):
            p.add("LEVELS", Point(level.x, level.y))
    for label in copy.inputs.survey.labels:
        if plot.contains(Point(label.x, label.y)) and any(
                label.text.strip().upper() == text for text, _ in copy.inside):
            p.add("INSIDE", Point(label.x, label.y))
            p.label("INSIDE", (label.x, label.y + 2.0), f"{label.text.strip()} (ignored)")
    for side in copy.sides:
        p.label("SIDES", side_label_at(side, plot, LABEL_OFFSET_M),
                f"{side.drawn_m:.2f} m" + (f" (written {side.written_m:.2f})"
                                          if side.written_m is not None else ""))
    centre = plot.representative_point()
    p.label("NOTES", (centre.x, centre.y),
            f"PLOT {copy.drawn_sqm:,.1f} m² drawn"
            + (f"\n{copy.written_sqm:,.2f} m² written" if copy.written_sqm else "")
            + f"\nperimeter {plot.length:,.2f} m"
            + (f"\nground {copy.terrain.lowest:.2f}-{copy.terrain.highest:.2f} m, falls "
               f"{compass_word(copy.terrain.falls_towards)}" if copy.terrain else ""))
    return p


def facts(copy: SurveyCopy) -> dict:
    t = copy.terrain
    return {
        "step": 1, "title": TITLE, "site": copy.inputs.site,
        "plot": {"corners": len(copy.plot.exterior.coords) - 1,
                 "perimeter_m": round(copy.plot.length, 2),
                 "drawn_sqm": round(copy.drawn_sqm, 2),
                 "written_sqm": round(copy.written_sqm, 2) if copy.written_sqm else None,
                 "outline_m": [[round(x, 3), round(y, 3)]
                               for x, y in list(copy.plot.exterior.coords)[:-1]]},
        "scale": copy.scale, "scale_is_a_check": copy.scale_is_a_check,
        "sides": [{"side": s.number, "faces": s.faces, "drawn_m": round(s.drawn_m, 2),
                   "written_m": s.written_m, "agrees": s.agrees} for s in copy.sides],
        "jogs": {"count": copy.jogs[0], "length_m": round(copy.jogs[1], 2)},
        "roads": [{"road": r.name, "lies": r.lies, "drawn_width_m": round(r.drawn_width_m, 2),
                   "divided": r.divided, "distance_m": round(r.distance_m, 2), "meets": r.meets,
                   "taken_on_m": round(r.carried_m, 2), "meets_over_m": round(r.frontage_m, 2),
                   "level_m": None if r.level is None else {
                       "lowest": r.level[0], "middle": r.level[1], "highest": r.level[2],
                       "count": r.level[3]},
                   "legal_width_m": r.legal_width_m, "legal_width_from": r.legal_source or None}
                  for r in copy.roads],
        "access_road": copy.access.name if copy.access else None,
        "ground": None if t is None else {"lowest_m": t.lowest, "highest_m": t.highest,
                                          "falls_towards": compass_word(t.falls_towards),
                                          "slope_pct": round(t.slope_pct, 2)},
        "levels": {"on_plot": copy.levels[0], "off_plot": copy.levels[1]},
        "inside_ignored": [{"text": t, "count": n} for t, n in copy.inside],
        "outside_within_band": [{"text": t, "count": n} for t, n in copy.outside],
        "water": [{"class": w, "distance_m": round(d, 2)} for w, d in copy.water],
        "lines_not_named": [{"key": g.key, "length_m": g.length_m, "crosses_plot": g.crosses_plot}
                            for g in (*copy.inside_lines, *copy.near_lines)],
        "warnings": copy.warnings,
    }


def _counted(text: str, n: int) -> str:
    """A word as the sheet writes it, and how many times."""
    return f'"{text}"' + (f" x{n}" if n > 1 else "")


def _label_at(road, view) -> tuple[float, float]:
    """A road's label: the middle of the part of it the picture shows."""
    shown = road.area.intersection(view)
    spot = (shown if not shown.is_empty else road.area).representative_point()
    return spot.x, spot.y

