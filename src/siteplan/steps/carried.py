"""What step 1 found that a rule may need later, carried by every step after it.

The list is built from step 1's own findings (every road, every water body the project names,
every note written near the plot, every line the engine cannot name), so a later step cannot drop
one by forgetting it: each later step's report gives every item a row (how the step used it, or
carried unchanged), its facts file carries every item and its shape, and its picture draws every
item that has one (`draw`). tests/test_steps.py holds all three. Added after step 3 first left
Suchitra's nala out of its picture and its report (2026-10-10)."""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.steps.drawing import Layer, Picture, colour_name
from siteplan.steps.survey_copy import SurveyCopy, outside_water

ROAD, WATER, MARK, UNNAMED = "road", "water", "note on the sheet", "lines not named"
MARK_LATER = {  # what a note on the sheet bears on, by the kind intake.MARKS finds
    "road widening": "the land given up for road widening (step 3)",
    "water": "the water's class and its buffer (rule 3(a)(ii)), from step 3 on",
    "HT line": "the safe distance from a power line (rule 3(c)), from step 4 on",
}
CONTEXT_LAYERS = (
    Layer("ROADS", "#d62828", 1, "Roads as drawn", fill=0.10, width=1.0),
    Layer("WATER", "#00a6c8", 4, "Water the project names", width=2.5),
)


@dataclass(frozen=True)
class Carried:
    key: str  # 'R6', 'nala_over_10m', 'note: ROAD WIDENING', 'lines: #808080'
    kind: str  # ROAD, WATER, MARK or UNNAMED
    what: str  # in plain words
    later: str  # what the later steps need it for
    shape: BaseGeometry | None = None  # drawn in every later step's picture


def found_in(copy: SurveyCopy) -> list[Carried]:
    out = []
    for road in copy.roads:
        if road is copy.access:
            later = ("the main road: the height it allows and the entry (step 2), the front "
                     "setback on its side (step 4)")
        elif road.reaches:
            later = ("a road that meets the plot: a corner cut where it meets another (step 3), "
                     "the setback on its side (step 4)")
        else:
            later = "reported on the site plan; no later rule uses a road that does not reach it"
        out.append(Carried(road.name, ROAD, f"{road.name}: a road on the {road.lies}, drawn "
                           f"{road.drawn_width_m:.2f} m wide; it {road.meets}", later, road.area))
    drawn: dict[str, list] = {}
    for kind, line in outside_water(copy.inputs):
        drawn.setdefault(kind, []).append(line)
    for kind, lines in drawn.items():
        water = unary_union(lines)
        out.append(Carried(kind, WATER, f"the {kind.replace('_', ' ')}, drawn "
                           f"{water.distance(copy.plot):.1f} m from the plot", "its buffer "
                           "(rule 3(a)(ii)) kept free of building from step 4 on; it may count "
                           "as open space (step 5)", water))
    for missing in copy.inputs.water_missing:
        out.append(Carried(f"not drawn: {missing}", WATER, f"the {missing}: named, but not drawn "
                           "on the survey", "its buffer, once its lines are known (asked in "
                           "step 1)"))
    for mark in copy.marks:
        out.append(Carried(f"note: {mark.text}", MARK, f'"{mark.text}" written '
                           f"{mark.distance_m:.1f} m from the plot", MARK_LATER.get(
                               mark.kind, "whatever it names (asked)")))
    for group in (*copy.inside_lines, *copy.near_lines):
        where = "cross the plot" if group.crosses_plot else "lie near the plot"
        out.append(Carried(f"lines: {group.key}", UNNAMED, f"lines in {colour_name(group.key)} "
                           f"{where}; the engine cannot name them", "if they are a road, water "
                           "or a power line, the later steps need them"
                           + (" (asked in step 1)" if group.crosses_plot else "")))
    return out


def draw(picture: Picture, items: list[Carried], view: BaseGeometry) -> None:
    """Every carried item that has a shape, in a later step's picture, under the step's own."""
    have = {layer.name for layer in picture.layers}
    picture.layers[:0] = [layer for layer in CONTEXT_LAYERS if layer.name not in have]
    for item in items:
        if item.shape is None:
            continue
        shown = item.shape.intersection(view)
        if shown.is_empty:
            continue
        picture.add("ROADS" if item.kind == ROAD else "WATER", shown)
        if item.kind == ROAD:
            spot = shown.representative_point()
            picture.label("ROADS", (spot.x, spot.y), item.key)


def facts(items: list[Carried], used: dict[str, str]) -> list[dict]:
    """Every carried item, how a step used it, and its shape for the steps after."""
    return [{"key": i.key, "kind": i.kind, "what": i.what, "in_this_step": used[i.key],
             "needed_later_for": i.later,
             "shape": None if i.shape is None else mapping(i.shape)} for i in items]
