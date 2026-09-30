"""Read a surveyor's DXF (or a DWG saved as DXF in ZWCAD) into a Survey.

DXF carries real units, so no scale calibration is needed: the file's header says what one
unit is. Everything is read in world coordinates with every block opened out by its own
placement (dxf_entities.py), so a boundary, a level or a road drawn inside a block counts.
Layer names differ between surveyors, so the boundary is chosen by the area written on the
drawing when there is one, then by layer-name hints, then by size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import ezdxf
from shapely.geometry import LineString, Point, Polygon

from siteplan.dxf_entities import (
    TEXT_TYPES,
    Drawn,
    declared_metres_per_unit,
    has_arcs,
    is_closed,
    open_blocks,
    polyline_points,
    text_of,
    text_position,
)
from siteplan.survey import Label, SpotLevel, Survey, line_groups
from siteplan.units import site_area

_BOUNDARY_HINT = re.compile(r"BOUND|PLOT|SITE", re.IGNORECASE)
_LEVEL = re.compile(r"\d+\.\d+")


@dataclass(frozen=True)
class DxfProfile:
    level_range: tuple[float, float] = (400.0, 900.0)
    boundary_layer: str | None = None  # force a layer when the heuristics pick wrong
    road_layer_hint: str = "ROAD"
    contour_layer_hint: str = "CONTOUR"
    water_layer_hint: str | None = None  # as the project states it: surveyors differ
    metres_per_unit_if_unset: float | None = None


def _is_polyline(entity) -> bool:
    kind = entity.dxftype()
    return kind == "LWPOLYLINE" or (
        kind == "POLYLINE" and (entity.is_2d_polyline or entity.is_3d_polyline)
    )


def _closed_polylines(drawn: tuple[Drawn, ...]) -> list[tuple[str, Polygon, bool]]:
    found = []
    for d in drawn:
        if _is_polyline(d.entity) and is_closed(d.entity):
            points = polyline_points(d.entity)
            if len(points) >= 3:
                found.append((d.layer, Polygon(points), has_arcs(d.entity)))
    return [(layer, poly, arcs) for layer, poly, arcs in found if poly.is_valid and poly.area > 0]


def _texts(drawn: tuple[Drawn, ...]) -> list[tuple[str, tuple[float, float]]]:
    return [(text, where) for text, where, _ in _texts_with_layers(drawn)]


def _texts_with_layers(drawn: tuple[Drawn, ...]) -> list[tuple[str, tuple[float, float], str]]:
    texts = []
    for d in drawn:
        if d.entity.dxftype() in TEXT_TYPES:
            where = text_position(d.entity)
            if where is not None:
                texts.append((text_of(d.entity), where, d.layer))
    return texts


def _open_lines(drawn: tuple[Drawn, ...], hint: str,
                closed_too: bool = False) -> list[list[tuple[float, float]]]:
    """Lines on layers whose name holds the hint; closed shapes too if asked (a nala's channel)."""
    lines = []
    for d in drawn:
        if hint not in d.layer.upper():
            continue
        if d.entity.dxftype() == "LINE":
            start, end = d.entity.dxf.start, d.entity.dxf.end
            lines.append([(start.x, start.y), (end.x, end.y)])
        elif _is_polyline(d.entity) and not is_closed(d.entity):
            lines.append(polyline_points(d.entity))
        elif _is_polyline(d.entity) and closed_too:
            points = polyline_points(d.entity)
            lines.append([*points, points[0]])
    return [line for line in lines if len(line) >= 2]


def _lines_by_layer(drawn: tuple[Drawn, ...]) -> dict[str, list[list[tuple[float, float]]]]:
    """Every line and polyline, open or closed, grouped by its exact layer."""
    groups: dict[str, list[list[tuple[float, float]]]] = {}
    for d in drawn:
        points: list[tuple[float, float]] = []
        if d.entity.dxftype() == "LINE":
            start, end = d.entity.dxf.start, d.entity.dxf.end
            points = [(start.x, start.y), (end.x, end.y)]
        elif _is_polyline(d.entity):
            points = list(polyline_points(d.entity))
            if points and is_closed(d.entity):
                points.append(points[0])
        if len(set(points)) >= 2:
            groups.setdefault(d.layer, []).append(points)
    return groups


def read_dxf_survey(path: str | Path, profile: DxfProfile | None = None) -> Survey:
    profile = profile or DxfProfile()
    doc = ezdxf.readfile(str(path))
    opened = open_blocks(doc.modelspace())
    drawn = opened.drawn
    warnings = []
    if opened.missing_blocks:
        warnings.append("Blocks referenced but missing from the file, so not read: "
                        f"{', '.join(opened.missing_blocks)}.")
    if opened.skipped:
        warnings.append(f"{opened.skipped} pieces inside blocks could not be placed (text "
                        "scaled unevenly, for example) and were left out.")

    k = declared_metres_per_unit(doc)
    if k is None:
        if profile.metres_per_unit_if_unset is None:
            raise ValueError(
                f"{path}: drawing units are not set ($INSUNITS). "
                "Say what one drawing unit is (e.g. metres_per_unit_if_unset=0.3048 for feet)."
            )
        k = profile.metres_per_unit_if_unset
        warnings.append(f"Drawing units not set in the file; assumed 1 unit = {k:g} m.")

    texts = _texts(drawn)
    stated = site_area([text for text, _ in texts])
    candidates = _closed_polylines(drawn)
    if profile.boundary_layer:
        candidates = [c for c in candidates if c[0] == profile.boundary_layer]
    if not candidates:
        raise ValueError(f"{path}: no closed polyline that could be the site boundary")

    if stated:
        layer, boundary_units, arcs = min(
            candidates, key=lambda c: abs(c[1].area * k * k / stated - 1)
        )
    else:
        hinted = [c for c in candidates if _BOUNDARY_HINT.search(c[0])]
        layer, boundary_units, arcs = max(hinted or candidates, key=lambda c: c[1].area)
        warnings.append("No area was written on the drawing; boundary chosen by layer and size.")
    if arcs:
        warnings.append(f"Boundary on layer '{layer}' has arcs; they were read as straight edges.")

    minx, miny, _, _ = boundary_units.bounds

    def to_m(x: float, y: float) -> tuple[float, float]:
        return ((x - minx) * k, (y - miny) * k)

    boundary = Polygon([to_m(x, y) for x, y in boundary_units.exterior.coords])
    if stated and abs(boundary.area / stated - 1) > 0.02:
        warnings.append(
            f"Measured boundary differs from the written area by "
            f"{(boundary.area / stated - 1) * 100:+.1f}%. Check the boundary before using it."
        )

    # Surveyed points carry the true position; text labels sit beside them. Prefer points,
    # and fall back to labels only when the file has no levelled points.
    lo, hi = profile.level_range
    raw = [tuple(d.entity.dxf.location) for d in drawn if d.entity.dxftype() == "POINT"]
    raw = [(x, y, z) for x, y, z in raw if lo <= z <= hi]
    if not raw:
        raw = [
            (x, y, float(text))
            for text, (x, y) in texts
            if _LEVEL.fullmatch(text.strip()) and lo <= float(text) <= hi
        ]
    levels = [
        SpotLevel(*to_m(x, y), z=z, on_site=boundary_units.contains(Point(x, y)))
        for x, y, z in raw
    ]

    def lines(hint: str, closed_too: bool = False) -> tuple[LineString, ...]:
        return tuple(LineString([to_m(x, y) for x, y in ln])
                     for ln in _open_lines(drawn, hint, closed_too))

    water = profile.water_layer_hint
    by_layer = {name: [LineString([to_m(x, y) for x, y in pts]) for pts in groups]
                for name, groups in _lines_by_layer(drawn).items()}
    return Survey(
        source=str(path),
        boundary=boundary,
        stated_area_sqm=stated,
        calibration=None,
        levels=tuple(levels),
        roads=lines(profile.road_layer_hint),
        contours=lines(profile.contour_layer_hint),
        water=lines(water.upper(), closed_too=True) if water else (),
        labels=tuple(Label(text, *to_m(x, y), nearby=((layer_name, 0.0),))
                     for text, (x, y), layer_name in _texts_with_layers(drawn)),
        line_groups=line_groups(by_layer, boundary),
        boundary_key=layer,
        warnings=tuple(warnings),
    )
