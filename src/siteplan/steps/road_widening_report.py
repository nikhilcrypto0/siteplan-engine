"""Step 3's report, picture and facts, in plain words (steps/report.py's five questions)."""

from __future__ import annotations

from siteplan import rules
from siteplan.steps.drawing import Layer, Picture, frame
from siteplan.steps.report import Choice, RuleUsed, StepReport, Table
from siteplan.steps.road_widening import (
    CORNER_TURN_DEG,
    JUNCTION_REACH_M,
    MIN_PIECE_SQM,
    NONE,
    OUTLINE,
    SIDE_DEG,
    THIN_M,
    Widening,
)
from siteplan.steps.survey_copy import ROAD_TOUCH_M

TITLE = "Take off the land given up for road widening"
DRAWN_AROUND_M = 30.0


def report(w: Widening) -> StepReport:
    r = StepReport(3, TITLE, w.inputs.site, picture=None if w.stopped else "step3.svg")
    r.did = [
        "Read what the project says about land given up for a road: how much, and where it "
        "lies.",
        "Took that land off the surveyed plot. What is left is the net plot.",
        "Looked at every corner of the net plot where two roads meet, for the corner cut "
        "(splay) the rules ask there.",
        "Worked out what the land given up could earn the owner (shown, not taken).",
        "Checked the net plot is still big enough for a high-rise and for a group scheme.",
    ]
    r.happening = [
        "When a road is widened, the strip of the plot it needs is handed over to the "
        "authority. That strip is no longer the owner's to build on.",
        "Every later step (setbacks, open space, buildings) measures from the net plot, not "
        "from the surveyed plot.",
        "Where the strip lies has to come from you or a drawing. The engine never guesses it "
        "from the area alone; if nobody has said, this step stops and asks.",
    ]
    r.elements = [
        "The surveyed plot (step 1).",
        f"From {w.inputs.given_as}: the net area, and the side, width or outline of the land "
        "given up.",
        "The roads that meet the plot (step 1), to find corners where two roads meet.",
    ]
    if w.stopped:
        r.did = ["Read what the project says about land given up for a road: how much, and "
                 "where it lies.",
                 "Tried to take that land off the surveyed plot, and stopped: what is known "
                 "is not enough, or does not add up. Nothing else was worked out."]
        r.stopped = "The net plot cannot be drawn yet. The engine's words: " + w.stopped
        r.rules = [RuleUsed("Land given up for a road", "Land in a Master Plan road, or in a "
                            "road widened under a Road Development Plan, is handed over free.",
                            rules.ROAD_SURRENDER_CLAUSE)]
        r.choices = [Choice("The step stops instead of placing or reshaping the strip itself.",
                            "Placing it from the area alone has been wrong before: an even "
                            "strip along a whole side can take twice the land given up.")]
        r.output = ["Nothing yet: the step needs the answer below."]
        r.tables = [_declared_table(w)]
        r.questions = [w.ask] if w.ask else []
        return r
    r.rules = _rules(w)
    r.choices = _choices(w)
    r.output, r.tables = _output(w)
    r.questions = _questions(w)
    r.files = [("step3.svg", "the picture"), ("step3.dxf", "the same, to open in CAD (metres)"),
               ("step3.json", "every number in this report, with the net plot's outline")]
    return r


def _rules(w: Widening) -> list[RuleUsed]:
    out = [
        RuleUsed("Land given up for a road", "Land in a Master Plan road, or in a road widened "
                 "under a Road Development Plan, is handed over free.",
                 rules.ROAD_SURRENDER_CLAUSE),
        RuleUsed("Measure from the net plot", "Setbacks are left after the land for road "
                 "widening comes off.", rules.SETBACK_ON_NET_PLOT_CLAUSE),
        RuleUsed("Big enough for a high-rise", f"A high-rise needs a plot of "
                 f"{rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m²; a site short of it because of road "
                 f"widening may be up to {rules.ROAD_WIDENING_SHORTFALL_ALLOWANCE:.0%} short.",
                 f"{rules.MIN_HIGH_RISE_PLOT_CLAUSE}; {rules.ROAD_WIDENING_SHORTFALL_CLAUSE}"),
        RuleUsed("A group scheme", "Housing on a site of "
                 f"{rules.GROUP_DEVELOPMENT_MIN_SITE_SQM:,.0f} m² or more is a group "
                 "development scheme (internal roads, open space).",
                 rules.GROUP_DEVELOPMENT_CLAUSE),
        RuleUsed("Corner cut where roads meet (splay)", "Where two roads meet at a corner, "
                 "the corner is cut off and becomes part of the road: "
                 f"{rules.JUNCTION_SPLAY_LEGS_M[0]:g} x {rules.JUNCTION_SPLAY_LEGS_M[0]:g} m on "
                 f"roads under {rules.JUNCTION_SPLAY_ROAD_M[0]:g} m, "
                 f"{rules.JUNCTION_SPLAY_LEGS_M[1]:g} x {rules.JUNCTION_SPLAY_LEGS_M[1]:g} m "
                 f"above {rules.JUNCTION_SPLAY_ROAD_M[0]:g} up to "
                 f"{rules.JUNCTION_SPLAY_ROAD_M[1]:g} m, {rules.JUNCTION_SPLAY_LEGS_M[2]:g} x "
                 f"{rules.JUNCTION_SPLAY_LEGS_M[2]:g} m above that. This table is for buildings "
                 "below high-rise; for a high-rise the authority decides.",
                 f"{rules.JUNCTION_SPLAY_CLAUSE}; {rules.JUNCTION_SPLAY_HIGH_RISE_CLAUSE}"),
    ]
    if w.given_sqm:
        out += [
            RuleUsed("What the land given up earns", "One of three, not all: a TDR "
                     "certificate, OR one extra floor, OR smaller setbacks.",
                     rules.ROAD_SURRENDER_REWARDS_CLAUSE),
            RuleUsed("How big the TDR is", f"{rules.TDR_ROAD_SURRENDER_SHARE:.0%} of the land "
                     "given up, as built-up area.", rules.TDR_ROAD_SURRENDER_CLAUSE),
            RuleUsed("Smaller setbacks, at most", "A building below high-rise keeps a building "
                     f"line of {_listed(rules.ROAD_WIDENING_NON_HIGH_RISE_BUILDING_LINE_M)} m "
                     "by road width and sides and rear of "
                     f"{_listed(rules.ROAD_WIDENING_NON_HIGH_RISE_SIDE_REAR_M)} m by height; "
                     f"a high-rise keeps {rules.ROAD_SURRENDER_HIGH_RISE_CLEAR_M:g} m "
                     "clear on its sides and rear for fire engines, the front as it is.",
                     f"{rules.ROAD_SURRENDER_REWARDS_CLAUSE}; "
                     f"{rules.ROAD_SURRENDER_HIGH_RISE_CLAUSE}"),
            RuleUsed("A cap", "After a concession the built-up area may not be more than the "
                     "whole site allowed without the widening plus the land given up.",
                     rules.ROAD_SURRENDER_CAP_CLAUSE),
            RuleUsed("Who decides", "The sanctioning authority.",
                     rules.ROAD_SURRENDER_AUTHORITY_CLAUSE),
            RuleUsed("A later order, NOT one of your 7 files", "G.O.Ms.No.7 of 2016 rewrote "
                     "rule 16 (a high-rise down to 7 m on all sides). The engine's other steps "
                     "still follow it; your decision on which order wins is pending.",
                     rules.ROAD_WIDENING_CLAUSE),
        ]
    return out


def _listed(rows: tuple[tuple[float, float], ...]) -> str:
    """'6, 3 or 2' from a rule's (bound, metres) rows."""
    figures = [f"{metres:g}" for _, metres in rows]
    return ", ".join(figures[:-1]) + " or " + figures[-1]


def _choices(w: Widening) -> list[Choice]:
    out = [Choice(f"How the net plot was found: {w.basis}.",
                  "From what the project says (section 5 lists where each value came from).")]
    if w.route == OUTLINE:
        out.append(Choice(f"Where the two outlines run less than {THIN_M:g} m apart, the land "
                          "between them is a drawing difference, not land given up. A wider "
                          "piece is land given up when its side faces within "
                          f"{SIDE_DEG:g} degrees of the side the answers name, or a road runs "
                          "along that same side.", "Two outlines traced from different drawings "
                          "never match exactly; confirm each piece."))
    elif w.route != NONE:
        out.append(Choice("All the land the strip takes is counted as given up.", "You placed "
                          "it (by its side and width, or its outline)."))
    out.append(Choice("A piece of land that runs round a corner of the plot is cut there, on "
                      "the line halving the corner, so each side's land is judged on its own.",
                      "A strip on one side and a strip on the next can have different reasons."))
    out.append(Choice(f"Slivers under {MIN_PIECE_SQM:g} m² are dropped.", "Rounding between "
                      "two outlines."))
    out.append(Choice(f"A corner where two roads meet: two different roads come within "
                      f"{ROAD_TOUCH_M:g} m of the two sides there (within "
                      f"{JUNCTION_REACH_M:g} m of the corner); or one road wraps round the "
                      "corner and another runs into it within its own width of the corner. "
                      f"Only corners turning at least {CORNER_TURN_DEG:g} degrees count.",
                      "The engine's reading of where a junction is; the rule does not say."))
    out.append(Choice("The splay is sized by the wider of the two roads whose width is known; "
                      "land given up for a road says nothing of that road's width.", "The rule "
                      "gives one road width per row and does not say which road."))
    out.append(Choice("A strip and the road it widens (a road running along the strip's side) "
                      "are one road, never a junction.", "Otherwise every widened road would "
                      "show a corner cut against itself."))
    out.append(Choice("The TDR is read as built-up area equal to twice the land given up.",
                      "The rule's words: '200% of built up area of such area surrendered'."))
    out.append(Choice("The group-scheme size is checked on the plot's written area (the area "
                      "as per documents), or the drawn area when none is written.", "Rule 2(c) "
                      "speaks of the site; the engine takes the documents' figure."))
    return out


def _output(w: Widening) -> tuple[list[str], list[Table]]:
    documents = w.copy.written_sqm or w.copy.drawn_sqm
    lines = []
    if w.given_sqm:
        lines.append(f"Land given up: {w.given_sqm:,.1f} m², in "
                     + "; ".join(f"{p.area_sqm:,.1f} m² on the {p.lies} side (up to "
                                 f"{p.widest_m:.1f} m wide, {p.why})"
                                 for p in w.pieces if p.counted)
                     + ".")
    else:
        lines.append("Land given up: none.")
    lines.append(f"Net plot: {w.net.area:,.1f} m², perimeter {w.net.length:,.2f} m, "
                 f"{len(w.net.exterior.coords) - 1} corners (the plot was {documents:,.2f} m² "
                 "as written). Every later step measures from this line.")
    stated = w.inputs.project.site.net_sqm()
    if stated:
        gap = w.net.area - stated
        lines.append(f"The net area according to {w.inputs.given_as}: {stated:,.1f} m²; the "
                     f"net plot drawn here: {w.net.area:,.1f} m² ({gap:+,.1f} m²).")
    if not w.adds_up:
        lines.append(f"THIS DOES NOT ADD UP: according to {w.inputs.given_as}, "
                     f"{w.stated_given_sqm:,.1f} m² is given up; the land counted here is "
                     f"{w.given_sqm:,.1f} m².")
    if w.difference_sqm:
        lines.append(f"Left out of the net plot but NOT counted as land given up (drawing "
                     f"differences): {w.difference_sqm:,.1f} m².")
    if w.beyond_sqm >= MIN_PIECE_SQM:
        lines.append(f"The net outline runs outside the surveyed line by {w.beyond_sqm:,.1f} m² "
                     "in places: a drawing difference to confirm.")
    hr = {True: "yes", False: "NO", None: "only through the 10% allowance (to confirm)"}
    lines.append(f"Big enough for a high-rise ({rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m²): "
                 f"{hr[w.high_rise_plot]}. A group scheme "
                 f"({rules.GROUP_DEVELOPMENT_MIN_SITE_SQM:,.0f} m² and more): "
                 f"{'yes' if w.group_scheme else 'no'}.")
    if w.splays:
        for s in w.splays:
            size = (" or ".join(f"{leg:g} x {leg:g} m ({a:,.1f} m²)"
                                for leg, a in zip(s.legs_m, s.areas_sqm, strict=False))
                    if s.legs_m else "size unknown")
            lines.append(f"Corner cut (splay) at the {s.lies} corner, where {s.roads[0]} and "
                         f"{s.roads[1]} meet: {size}, sized by {s.width_from}. Shown, not "
                         "taken off.")
    else:
        lines.append("Corner cuts (splays): no corner of the net plot is where two roads "
                     "meet.")
    if w.given_sqm:
        lines.append("What the land given up could earn (ONE of these; none is taken): a TDR "
                     f"of {rules.TDR_ROAD_SURRENDER_SHARE * w.given_sqm:,.1f} m² of built-up "
                     f"area, OR one extra floor of {w.given_sqm:,.1f} m², OR smaller setbacks "
                     "(step 4 shows what they would add). This applies only if the road is a "
                     "Master Plan road or a Road Development Plan road.")
    tables = [_declared_table(w)]
    if w.pieces:
        tables.append(Table("The land that comes off", ("Piece", "Lies on the", "Area",
                                                        "Widest", "Counted as"),
                            tuple((str(i), p.lies, f"{p.area_sqm:,.1f} m²",
                                   f"{p.widest_m:.2f} m",
                                   f"land given up ({p.why})" if p.counted else
                                   "a drawing difference (nothing says it is land given up)")
                                  for i, p in enumerate(w.pieces, 1))))
    return lines, tables


def _declared_table(w: Widening) -> Table:
    rows = tuple(w.declared) or (("Land given up", "nothing recorded", w.inputs.given_as),)
    return Table("What the project says", ("What", "Value", "Where it came from"), rows)


def _questions(w: Widening) -> list[str]:
    out = []
    if not w.declared:
        out.append("Is any of the plot given up for a road? Nothing is recorded, so the whole "
                   "plot is taken as the net plot.")
    if not w.adds_up:
        out.append(f"According to {w.inputs.given_as}, {w.stated_given_sqm:,.1f} m² is given "
                   f"up, but the land counted here is {w.given_sqm:,.1f} m². Which is right?")
    if w.given_sqm:
        out.append("Is the road a Master Plan road or a Road Development Plan road? Only then "
                   "does rule 16 apply to the land given up.")
        if w.splays and any("land given up" in name for s in w.splays for name in s.roads):
            out.append("How wide is the road the land is given up for? It sizes the corner cut "
                       "next to it.")
    for s in w.splays:
        if not s.legs_m or "drawn" in s.width_from:
            out.append(f"The corner cut at the {s.lies} corner is sized from a drawn width, not "
                       "a legal one. Give both roads' legal widths to size it properly.")
    counted = [p for p in w.pieces if p.counted]
    for i, piece in enumerate(w.pieces, 1):
        if piece.counted and len(counted) > 1 and piece is not counted[0]:
            out.append(f"Piece {i} ({piece.area_sqm:,.1f} m², up to {piece.widest_m:.1f} m wide, "
                       f"on the {piece.lies} side) is taken as land given up because it lies "
                       f"{piece.why.split(',')[0]}. Is it road land, or a difference between "
                       "the drawings?")
    if w.difference_sqm >= MIN_PIECE_SQM or w.beyond_sqm >= MIN_PIECE_SQM:
        out.append("Are the drawing differences really just that? They are left out of the "
                   "net plot but not counted as land given up.")
    return out


def picture(w: Widening) -> Picture:
    p = Picture(f"Step 3: {TITLE}", w.inputs.site, layers=[
        Layer("ROADS", "#d62828", 1, "Roads as drawn", fill=0.10, width=1.0),
        Layer("NET-PLOT", "#2e8b3d", 3, "The net plot: every later step measures from it",
              fill=0.12, width=3.0),
        Layer("GIVEN-UP", "#f08c00", 30, "Land given up for road widening", fill=0.45,
              width=1.0),
        Layer("SLIVERS", "#7a7a7a", 8, "Drawing differences (not counted)", fill=0.6),
        Layer("SURVEYED", "#b0177e", 6, "The surveyed plot (step 1)", width=1.5, dash="6 4"),
        Layer("SPLAYS", "#111111", 7, "Corner cut where two roads meet (shown, not taken)",
              fill=0.8),
        Layer("NOTES", "#222222", 7, ""),
    ])
    view = frame(w.copy.plot, DRAWN_AROUND_M)
    for road in w.copy.roads:
        shown = road.area.intersection(view) if road.area else None
        p.add("ROADS", shown)
        if shown is not None and not shown.is_empty:
            spot = shown.representative_point()
            p.label("ROADS", (spot.x, spot.y), road.name)
    p.add("NET-PLOT", w.net)
    p.add("SLIVERS", w.slivers)
    for i, piece in enumerate(w.pieces, 1):
        p.add("GIVEN-UP" if piece.counted else "SLIVERS", piece.polygon)
        spot = piece.polygon.representative_point()
        p.label("NOTES", (spot.x, spot.y), f"piece {i}: {piece.area_sqm:,.1f} m²")
    p.add("SURVEYED", w.copy.plot)
    for s in w.splays:
        p.add("SPLAYS", s.triangle)
        p.label("SPLAYS", (s.corner[0], s.corner[1] + 4.0),
                "splay " + " or ".join(f"{leg:g} x {leg:g} m" for leg in s.legs_m))
    centre = w.net.representative_point()
    p.label("NOTES", (centre.x, centre.y), f"NET PLOT {w.net.area:,.1f} m²\nperimeter "
            f"{w.net.length:,.2f} m")
    return p


def facts(w: Widening) -> dict:
    out = {"step": 3, "title": TITLE, "site": w.inputs.site, "stopped": w.stopped,
           "question": w.ask, "known_from": w.route,
           "declared": [{"what": a, "value": b, "from": c} for a, b, c in w.declared]}
    if w.stopped:
        return out
    return {**out,
            "how_found": w.basis,
            "given_up_sqm": round(w.given_sqm, 2),
            "stated_given_up_sqm": (None if w.stated_given_sqm is None
                                    else round(w.stated_given_sqm, 2)),
            "adds_up": w.adds_up,
            "pieces": [{"lies": p.lies, "area_sqm": round(p.area_sqm, 2),
                        "widest_m": round(p.widest_m, 2), "road_land": p.counted,
                        "why": p.why, "widens": list(p.widens)}
                       for p in w.pieces],
            "drawing_differences_sqm": round(w.difference_sqm, 2),
            "net_outline_beyond_survey_sqm": round(w.beyond_sqm, 2),
            "net_plot": {"drawn_sqm": round(w.net.area, 2), "perimeter_m": round(w.net.length, 2),
                         "outline_m": [[round(x, 3), round(y, 3)]
                                       for x, y in list(w.net.exterior.coords)[:-1]]},
            "high_rise_plot": w.high_rise_plot, "group_scheme": w.group_scheme,
            "splays": [{"corner": [round(c, 2) for c in s.corner], "lies": s.lies,
                        "roads": list(s.roads), "sized_by": s.width_from,
                        "width_m": None if s.width_m is None else round(s.width_m, 2),
                        "legs_m": list(s.legs_m),
                        "areas_sqm": [round(a, 2) for a in s.areas_sqm]} for s in w.splays],
            "rewards_shown_not_taken": None if not w.given_sqm else {
                "tdr_built_up_sqm": round(rules.TDR_ROAD_SURRENDER_SHARE * w.given_sqm, 2),
                "extra_floor_sqm": round(w.given_sqm, 2),
                "high_rise_sides_and_rear_m": rules.ROAD_SURRENDER_HIGH_RISE_CLEAR_M,
                "building_line_m": [list(row) for row in
                                    rules.ROAD_WIDENING_NON_HIGH_RISE_BUILDING_LINE_M],
                "side_and_rear_m": [list(row) for row in
                                    rules.ROAD_WIDENING_NON_HIGH_RISE_SIDE_REAR_M]}}
