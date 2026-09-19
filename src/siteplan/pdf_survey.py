"""Read a surveyor's CAD-exported (vector) PDF into a Survey.

Two things are deliberately not trusted:
- the printed scale ("1:1000"), because sheets are often plotted "fit to paper";
- colours for the boundary, because every surveyor uses their own.

Instead, each closed shape on the sheet is tried as the boundary, calibrated from the
dimension labels written along its edges, and the one whose calibrated area matches the
area written on the sheet wins.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path

import pdfplumber
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, unary_union

from siteplan.geometry import angle_gap, largest_polygon, straight_runs
from siteplan.survey import Calibration, ScaleEstimate, SpotLevel, Survey, calibrate
from siteplan.units import parse_acre_gunta

Colour = tuple[float, ...]
_NUMBER = re.compile(r"\d+\.\d+|\d+")
_METRES_PER_POINT_AT_1_TO_1 = 0.0254 / 72
STANDARD_SCALES = (100, 200, 250, 300, 400, 500, 750, 1000, 1250, 1500, 2000, 2500, 5000)


def snap_to_standard_scale(cal: Calibration, tolerance_pct: float) -> Calibration:
    """Plotters print at standard scales; if the fit is within tolerance of one, use it exactly."""
    for n in STANDARD_SCALES:
        exact = n * _METRES_PER_POINT_AT_1_TO_1
        if abs(cal.fitted_metres_per_unit / exact - 1) * 100 <= tolerance_pct:
            return replace(cal, metres_per_unit=exact, snapped_scale=n)
    return cal


@dataclass(frozen=True)
class PdfProfile:
    """Surveyor-specific conventions. Defaults match the first survey sheet studied."""

    road_colour: Colour | None = (1.0, 0.0, 0.0)
    contour_colour: Colour | None = (1.0, 0.498, 0.0)
    level_range: tuple[float, float] = (400.0, 900.0)  # metres above MSL around Hyderabad
    label_angle_tolerance_deg: float = 8.0
    label_distance_em: float = 4.0  # how far a dimension label may sit from its edge
    scale_agreement_pct: float = 3.0
    snap_tolerance_pct: float = 0.5  # 0 disables snapping to a standard plot scale
    min_polygon_page_fraction: float = 0.002


@dataclass(frozen=True)
class Token:
    text: str
    x: float
    y: float
    angle_deg: float  # modulo 180
    size: float
    colour: Colour


@dataclass
class _Char:
    text: str
    s: float  # position along the baseline
    t: float  # position across the baseline
    advance: float
    size: float
    cx: float
    cy: float
    colour: Colour


def _colour(value: object) -> Colour:
    if value is None:
        return ()
    if isinstance(value, (int, float)):
        return (round(float(value), 3),)
    return tuple(round(float(v), 3) for v in value)  # type: ignore[union-attr]


def _chars_by_direction(page) -> dict[int, tuple[float, float, list[_Char]]]:
    groups: dict[int, tuple[float, float, list[_Char]]] = {}
    for ch in page.chars:
        a, b, _c, _d, e, f = ch["matrix"]
        norm = math.hypot(a, b) or 1.0
        ux, uy = a / norm, -b / norm  # baseline direction with y pointing down the page
        ox, oy = e, page.height - f
        key = round(math.degrees(math.atan2(uy, ux)) / 2)
        _, _, chars = groups.setdefault(key, (ux, uy, []))
        chars.append(
            _Char(
                text=ch["text"],
                s=ox * ux + oy * uy,
                t=-ox * uy + oy * ux,
                advance=ch["adv"] * norm,
                size=float(ch["size"]) or 1.0,
                cx=(ch["x0"] + ch["x1"]) / 2,
                cy=(ch["top"] + ch["bottom"]) / 2,
                colour=_colour(ch.get("non_stroking_color")),
            )
        )
    return groups


def _lines(chars: list[_Char]) -> list[list[_Char]]:
    chars = sorted(chars, key=lambda c: c.t)
    lines: list[list[_Char]] = [[chars[0]]]
    for ch in chars[1:]:
        if abs(ch.t - lines[-1][-1].t) <= 0.3 * ch.size:
            lines[-1].append(ch)
        else:
            lines.append([ch])
    return [sorted(line, key=lambda c: c.s) for line in lines]


def _split(line: list[_Char], gap_em: float, on_space: bool) -> list[list[_Char]]:
    parts: list[list[_Char]] = []
    current: list[_Char] = []
    for ch in line:
        gap = ch.s - (current[-1].s + current[-1].advance) if current else 0.0
        if (on_space and ch.text.isspace()) or (current and gap > gap_em * ch.size):
            if current:
                parts.append(current)
            current = [] if ch.text.isspace() else [ch]
        else:
            current.append(ch)
    if current:
        parts.append(current)
    return parts


def _token(chars: list[_Char], ux: float, uy: float) -> Token:
    return Token(
        text="".join(c.text for c in chars),
        x=sum(c.cx for c in chars) / len(chars),
        y=sum(c.cy for c in chars) / len(chars),
        angle_deg=math.degrees(math.atan2(uy, ux)) % 180,
        size=max(c.size for c in chars),
        colour=chars[0].colour,
    )


def read_text(page) -> tuple[list[Token], list[str]]:
    """Rebuild words (including rotated CAD text) and whole text runs from loose characters."""
    tokens: list[Token] = []
    runs: list[str] = []
    for ux, uy, chars in _chars_by_direction(page).values():
        for line in _lines(chars):
            tokens += [_token(p, ux, uy) for p in _split(line, 0.3, on_space=True)]
            runs += ["".join(c.text for c in p) for p in _split(line, 1.2, on_space=False)]
    return tokens, runs


def _segments_by_colour(page, include_rects: bool) -> dict[Colour, list[LineString]]:
    """Stroke segments grouped by colour. Rectangles are usually symbols (legend swatches,
    sheds), so they only count when looking for a boundary, never as roads or contours."""
    by_colour: dict[Colour, list[LineString]] = {}
    for obj in page.lines + page.curves + (page.rects if include_rects else []):
        pts = list(obj.get("pts") or [])
        if obj.get("object_type") == "rect":
            x0, x1, top, bottom = obj["x0"], obj["x1"], obj["top"], obj["bottom"]
            pts = [(x0, top), (x1, top), (x1, bottom), (x0, bottom), (x0, top)]
        segs = by_colour.setdefault(_colour(obj.get("stroking_color")), [])
        segs += [LineString([a, b]) for a, b in zip(pts, pts[1:], strict=False) if a != b]
    return by_colour


def _scale_estimates(
    polygon: Polygon, numbers: list[tuple[float, Token]], profile: PdfProfile
) -> list[ScaleEstimate]:
    runs = straight_runs(polygon)
    estimates = []
    for value, token in numbers:
        here = Point(token.x, token.y)
        parallel = [
            r
            for r in runs
            if angle_gap(r.angle_deg, token.angle_deg) <= profile.label_angle_tolerance_deg
            and r.line.distance(here) <= profile.label_distance_em * token.size
        ]
        if parallel:
            nearest = min(parallel, key=lambda r: r.line.distance(here))
            estimates.append(ScaleEstimate(written_m=value, drawn_units=nearest.length))
    return estimates


@dataclass(frozen=True)
class _Candidate:
    colour: Colour
    polygon: Polygon
    calibration: Calibration
    area_sqm: float


def read_pdf_survey(path: str | Path, profile: PdfProfile | None = None) -> Survey:
    profile = profile or PdfProfile()
    with pdfplumber.open(str(path)) as pdf:
        if not pdf.pages:
            raise ValueError(f"{path}: the PDF has no pages")
        page = pdf.pages[0]
        tokens, runs = read_text(page)
        shapes = _segments_by_colour(page, include_rects=True)
        segments = _segments_by_colour(page, include_rects=False)
        page_area = float(page.width * page.height)

    stated = next((a for a in (parse_acre_gunta(r) for r in runs) if a), None)
    numbers = [(float(t.text), t) for t in tokens if _NUMBER.fullmatch(t.text)]
    dims = [(v, t) for v, t in numbers if 0 < v < profile.level_range[0]]

    candidates = []
    for colour, segs in shapes.items():
        polygon = largest_polygon(segs)
        if polygon is None:
            continue
        fraction = polygon.area / page_area
        if not profile.min_polygon_page_fraction <= fraction <= 0.9:
            continue
        cal = calibrate(_scale_estimates(polygon, dims, profile), profile.scale_agreement_pct)
        if cal is not None:
            cal = snap_to_standard_scale(cal, profile.snap_tolerance_pct)
            area = polygon.area * cal.metres_per_unit**2
            candidates.append(_Candidate(colour, polygon, cal, area))
    if not candidates:
        raise ValueError(
            f"{path}: no closed boundary with at least two matching dimension labels was found"
        )

    if stated:
        best = min(candidates, key=lambda c: abs(c.area_sqm / stated - 1))
    else:
        best = max(candidates, key=lambda c: (len(c.calibration.agreeing), c.area_sqm))
    return _build_survey(str(path), best, stated, numbers, segments, profile)


def _build_survey(source, best, stated, numbers, segments, profile) -> Survey:
    k = best.calibration.metres_per_unit
    minx, _, _, maxy = best.polygon.bounds

    def to_m(x: float, y: float) -> tuple[float, float]:
        return ((x - minx) * k, (maxy - y) * k)

    boundary_page = best.polygon
    boundary = Polygon([to_m(x, y) for x, y in boundary_page.exterior.coords])
    lo, hi = profile.level_range
    levels = tuple(
        SpotLevel(*to_m(t.x, t.y), z=v, on_site=boundary_page.contains(Point(t.x, t.y)))
        for v, t in numbers
        if lo <= v <= hi and "." in t.text
    )

    def lines_of(colour: Colour | None) -> tuple[LineString, ...]:
        segs = segments.get(colour, []) if colour else []
        if not segs:
            return ()
        joined = unary_union(segs)
        merged = joined if joined.geom_type == "LineString" else linemerge(joined)
        parts = getattr(merged, "geoms", [merged])
        return tuple(LineString([to_m(x, y) for x, y in p.coords]) for p in parts)

    warnings = []
    if stated is None:
        warnings.append(
            "No area was written on the sheet; boundary chosen by label agreement only."
        )
    elif abs(boundary.area / stated - 1) > 0.02:
        warnings.append(
            f"Measured boundary differs from the written area by "
            f"{(boundary.area / stated - 1) * 100:+.1f}%. Check the boundary before using it."
        )
    if best.calibration.rejected:
        values = ", ".join(f"{e.written_m:g}" for e in best.calibration.rejected)
        warnings.append(f"Dimension labels that disagree with the others: {values}.")
    if best.colour == profile.road_colour:
        warnings.append("The boundary was drawn in the road colour; check the layer mapping.")

    return Survey(
        source=source,
        boundary=boundary,
        stated_area_sqm=stated,
        calibration=best.calibration,
        levels=levels,
        roads=lines_of(profile.road_colour),
        contours=lines_of(profile.contour_colour),
        warnings=tuple(warnings),
    )
