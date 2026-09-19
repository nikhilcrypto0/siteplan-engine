"""Read a surveyor's DXF (or a DWG saved as DXF in ZWCAD) into a Survey.

DXF carries real units, so no scale calibration is needed. Layer names differ between
surveyors, so the boundary is chosen by the area written on the drawing when there is
one, then by layer-name hints, then by size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import ezdxf
from shapely.geometry import LineString, Point, Polygon

from siteplan.survey import SpotLevel, Survey
from siteplan.units import parse_acre_gunta

# $INSUNITS code -> metres per drawing unit (0 means "unitless").
_METRES_PER_UNIT = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
_BOUNDARY_HINT = re.compile(r"BOUND|PLOT|SITE", re.IGNORECASE)
_LEVEL = re.compile(r"\d+\.\d+")


@dataclass(frozen=True)
class DxfProfile:
    level_range: tuple[float, float] = (400.0, 900.0)
    boundary_layer: str | None = None  # force a layer when the heuristics pick wrong
    road_layer_hint: str = "ROAD"
    contour_layer_hint: str = "CONTOUR"
    metres_per_unit_if_unset: float | None = None


def _closed_polylines(msp) -> list[tuple[str, Polygon, bool]]:
    found = []
    for e in msp.query("LWPOLYLINE"):
        if e.closed and len(e) >= 3:
            points = e.get_points("xyb")
            has_arcs = any(bulge for *_, bulge in points)
            found.append((e.dxf.layer, Polygon([(x, y) for x, y, _ in points]), has_arcs))
    for e in msp.query("POLYLINE"):
        if e.is_closed and len(e) >= 3:
            ring = [tuple(v.dxf.location)[:2] for v in e.vertices]
            has_arcs = any(v.dxf.bulge for v in e.vertices)
            found.append((e.dxf.layer, Polygon(ring), has_arcs))
    return [(layer, poly, arcs) for layer, poly, arcs in found if poly.is_valid and poly.area > 0]


def _texts(msp) -> list[tuple[str, tuple[float, float]]]:
    texts = [(e.dxf.text, tuple(e.dxf.insert)[:2]) for e in msp.query("TEXT")]
    texts += [(e.plain_text(), tuple(e.dxf.insert)[:2]) for e in msp.query("MTEXT")]
    return texts


def _open_lines(msp, hint: str) -> list[list[tuple[float, float]]]:
    lines = []
    for e in msp.query("LINE"):
        if hint in e.dxf.layer.upper():
            lines.append([tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2]])
    for e in msp.query("LWPOLYLINE"):
        if hint in e.dxf.layer.upper() and not e.closed:
            lines.append([(x, y) for x, y in e.get_points("xy")])
    return [line for line in lines if len(line) >= 2]


def read_dxf_survey(path: str | Path, profile: DxfProfile | None = None) -> Survey:
    profile = profile or DxfProfile()
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    warnings = []

    k = _METRES_PER_UNIT.get(doc.header.get("$INSUNITS", 0))
    if k is None:
        if profile.metres_per_unit_if_unset is None:
            raise ValueError(
                f"{path}: drawing units are not set ($INSUNITS). "
                "Say what one drawing unit is (e.g. metres_per_unit_if_unset=0.3048 for feet)."
            )
        k = profile.metres_per_unit_if_unset
        warnings.append(f"Drawing units not set in the file; assumed 1 unit = {k:g} m.")

    texts = _texts(msp)
    stated = next((a for a in (parse_acre_gunta(t) for t, _ in texts) if a), None)
    candidates = _closed_polylines(msp)
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
    raw = [tuple(e.dxf.location) for e in msp.query("POINT")]
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

    def lines(hint: str) -> tuple[LineString, ...]:
        return tuple(LineString([to_m(x, y) for x, y in ln]) for ln in _open_lines(msp, hint))

    return Survey(
        source=str(path),
        boundary=boundary,
        stated_area_sqm=stated,
        calibration=None,
        levels=tuple(levels),
        roads=lines(profile.road_layer_hint),
        contours=lines(profile.contour_layer_hint),
        warnings=tuple(warnings),
    )
