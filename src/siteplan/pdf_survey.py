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
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pdfplumber
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

from siteplan.geometry import angle_gap, straight_runs
from siteplan.survey import (
    Calibration,
    Label,
    ScaleEstimate,
    SpotLevel,
    Survey,
    calibrate,
    line_groups,
)
from siteplan.units import site_area

Colour = tuple[float, ...]
_NUMBER = re.compile(r"\d+\.\d+|\d+")
_METRES_PER_POINT_AT_1_TO_1 = 0.0254 / 72
STANDARD_SCALES = (100, 200, 250, 300, 400, 500, 750, 1000, 1250, 1500, 2000, 2500, 5000)
LEVEL_WINDOW_M = 15.0  # the spot levels of one site sit within a few metres of each other
MIN_LEVELS = 8  # that many decimals that close together are the sheet's levels
MIN_LEVELS_ON_PLOT = 3  # with no labels, the plot must hold at least this many levels
FRAME_SPAN = 0.8  # a shape this wide AND this tall on the page is the sheet's frame


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
    water_colour: Colour | None = None  # as the project states it: surveyors differ
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


def read_labels(page) -> list[tuple[str, float, float]]:
    """Whole text runs and where each sits on the page (the middle of its characters)."""
    labels = []
    for _, _, chars in _chars_by_direction(page).values():
        for line in _lines(chars):
            for part in _split(line, 1.2, on_space=False):
                text = "".join(c.text for c in part).strip()
                if text:
                    labels.append((text, sum(c.cx for c in part) / len(part),
                                   sum(c.cy for c in part) / len(part)))
    return labels


def colour_hex(colour: Colour) -> str:
    """'#RRGGBB' for an RGB stroke, grey for a one-channel one, CMYK turned to RGB."""
    if len(colour) == 1:
        colour = (colour[0],) * 3
    elif len(colour) == 4:
        c, m, y, k = colour
        colour = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return "#" + "".join(f"{round(v * 255):02X}" for v in colour[:3])


LABEL_REACH_M = 15.0  # colours drawn this close to a label are offered as what it names


def _nearby_finder(segments: dict[Colour, list], metres_per_unit: float
                   ) -> Callable[[float, float], tuple[tuple[str, float], ...]]:
    """For a label, the three closest colours within reach, nearest first. Offered, never
    chosen: on Suchitra's sheet the line nearest the word 'Nala' is grey, and a 'Road' label
    sits on the cyan line that may be the nala."""
    lines, colours = [], []
    for colour, segs in segments.items():
        if colour:
            lines += segs
            colours += [colour] * len(segs)
    tree = STRtree(lines) if lines else None
    reach = LABEL_REACH_M / metres_per_unit

    def nearby(x: float, y: float) -> tuple[tuple[str, float], ...]:
        if tree is None:
            return ()
        here, best = Point(x, y), {}
        for i in tree.query(here.buffer(reach)):
            metres = lines[i].distance(here) * metres_per_unit
            key = colour_hex(colours[i])
            if metres <= LABEL_REACH_M and metres < best.get(key, math.inf):
                best[key] = metres
        return tuple((key, round(m, 1)) for key, m in sorted(best.items(), key=lambda b: b[1]))[:3]

    return nearby


def _closest(segments: dict[Colour, list], colour: Colour | None) -> Colour | None:
    """The stroke colour on the sheet within rounding of the one asked for ('#00B82E' comes
    back as 0.722 where the sheet says 0.72)."""
    if not colour:
        return None
    same = [c for c in segments if len(c) == len(colour)
            and max(abs(a - b) for a, b in zip(c, colour, strict=True)) <= 0.01]
    return min(same, key=lambda c: sum(abs(a - b) for a, b in zip(c, colour, strict=True)),
               default=None)


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
) -> list[tuple[ScaleEstimate, Token]]:
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
            estimates.append((ScaleEstimate(value, nearest.length), token))
    return estimates


@dataclass(frozen=True)
class _Candidate:
    colour: Colour
    polygon: Polygon
    calibration: Calibration
    area_sqm: float
    dimension_tokens: frozenset[int]  # id() of tokens used as dimension labels


def _level_band(numbers: list[tuple[float, Token]]) -> tuple[float, float] | None:
    """Where this sheet's spot levels sit: the densest run of decimals within a few metres.

    Some surveys level from sea level (583 m at Dhulapally), others from a local benchmark
    (100.000 at Suchitra), so no fixed range finds both. A fixed range read none of Suchitra's
    36 levels, and let two of them pass for dimension labels."""
    values = sorted(v for v, t in numbers if "." in t.text)
    best, span, start = 0, None, 0
    for end, value in enumerate(values):
        while value - values[start] > LEVEL_WINDOW_M:
            start += 1
        if end - start + 1 > best:
            best, span = end - start + 1, (values[start], value)
    return span if best >= MIN_LEVELS else None


def _level_tests(
    numbers: list[tuple[float, Token]], profile: PdfProfile
) -> tuple[Callable[[float], bool], Callable[[float], bool]]:
    """(is_level, is_ambiguous): a level lies in the profile's range or this sheet's own band;
    an ambiguous number could be a level or a dimension, so it may only confirm a scale."""
    lo, hi = profile.level_range
    band = _level_band(numbers)

    def in_band(value: float) -> bool:
        return band is not None and band[0] <= value <= band[1]

    return (lambda v: lo <= v <= hi or in_band(v)), (lambda v: v >= lo or in_band(v))


def _plot_shapes(
    shapes: dict[Colour, list[LineString]], width: float, height: float, profile: PdfProfile
) -> list[tuple[Colour, Polygon]]:
    """Every closed shape that could be the plot: each face the sheet's lines close, in every
    colour, filled in, less the sheet's own frame. Keeping only the largest shape of each
    colour once took Suchitra's black sheet frame for its black plot boundary."""
    found = []
    for colour, segs in shapes.items():
        if len(segs) < 3:
            continue
        for face in polygonize(unary_union(segs)):
            filled = Polygon(face.exterior)
            fraction = filled.area / (width * height)
            x0, y0, x1, y1 = filled.bounds
            frame = x1 - x0 >= FRAME_SPAN * width and y1 - y0 >= FRAME_SPAN * height
            if profile.min_polygon_page_fraction <= fraction <= 0.9 and not frame:
                found.append((colour, filled))
    return found


def _calibrate_candidate(
    polygon: Polygon,
    numbers: list[tuple[float, Token]],
    ambiguous: Callable[[float], bool],
    profile: PdfProfile,
) -> tuple[Calibration, frozenset[int]] | None:
    """Calibrate from dimension labels. Unambiguous numbers can only be dimensions, so they set
    the scale. A number that could be a level counts as a dimension only if it sits along an
    edge AND agrees with that scale, so a 450 m edge label is used, and never mistaken for a
    level."""
    small = [(v, t) for v, t in numbers if v > 0 and not ambiguous(v)]
    small = _scale_estimates(polygon, small, profile)
    cal = calibrate([e for e, _ in small], profile.scale_agreement_pct)
    if cal is None:
        return None
    large = _scale_estimates(polygon, [(v, t) for v, t in numbers if ambiguous(v)], profile)
    tolerance = profile.scale_agreement_pct / 100
    large = [
        (e, t)
        for e, t in large
        if abs(e.metres_per_unit / cal.fitted_metres_per_unit - 1) <= tolerance
    ]
    if large:
        cal = calibrate([e for e, _ in small + large], profile.scale_agreement_pct) or cal
    agreeing = set(cal.agreeing)
    tokens = frozenset(id(t) for e, t in small + large if e in agreeing)
    return snap_to_standard_scale(cal, profile.snap_tolerance_pct), tokens


def read_pdf_survey(path: str | Path, profile: PdfProfile | None = None) -> Survey:
    profile = profile or PdfProfile()
    with pdfplumber.open(str(path)) as pdf:
        if not pdf.pages:
            raise ValueError(f"{path}: the PDF has no pages")
        page = pdf.pages[0]
        tokens, runs = read_text(page)
        labels = read_labels(page)
        shapes = _segments_by_colour(page, include_rects=True)
        segments = _segments_by_colour(page, include_rects=False)
        plots = _plot_shapes(shapes, float(page.width), float(page.height), profile)

    stated = site_area(runs)
    numbers = [(float(t.text), t) for t in tokens if _NUMBER.fullmatch(t.text)]
    is_level, ambiguous = _level_tests(numbers, profile)

    candidates = []
    for colour, polygon in plots:
        found = _calibrate_candidate(polygon, numbers, ambiguous, profile)
        if found is not None:
            cal, dimension_tokens = found
            area = polygon.area * cal.metres_per_unit**2
            candidates.append(_Candidate(colour, polygon, cal, area, dimension_tokens))

    if candidates and stated:
        best = min(candidates, key=lambda c: abs(c.area_sqm / stated - 1))
    elif candidates:
        best = max(candidates, key=lambda c: (len(c.calibration.agreeing), c.area_sqm))
    elif stated:
        best = _scaled_by_written_area(plots, numbers, is_level, stated)
        if best is None:
            raise ValueError(
                f"{path}: the sheet has no dimension labels, and no closed shape holds its spot "
                "levels, so the plot cannot be told from the rest of the drawing"
            )
    else:
        raise ValueError(
            f"{path}: no closed boundary with at least two matching dimension labels was found, "
            "and no area is written to scale one from"
        )
    return _build_survey(str(path), best, stated, numbers, segments, is_level, profile, labels)


def _scaled_by_written_area(
    plots: list[tuple[Colour, Polygon]],
    numbers: list[tuple[float, Token]],
    is_level: Callable[[float], bool],
    stated: float,
) -> _Candidate | None:
    """With no dimension labels, the plot is the tightest shape round the spot levels, and the
    written area is the only scale there is. A surveyor levels the land being surveyed."""
    points = [Point(t.x, t.y) for v, t in numbers if "." in t.text and is_level(v)]
    held = [(sum(polygon.contains(p) for p in points), -polygon.area, colour, polygon)
            for colour, polygon in plots]
    if not held:
        return None
    count, _, colour, polygon = max(held, key=lambda h: (h[0], h[1]))
    if count < MIN_LEVELS_ON_PLOT:
        return None
    k = math.sqrt(stated / polygon.area)
    return _Candidate(colour, polygon, Calibration(k, (), (), k), stated, frozenset())


def _build_survey(source, best, stated, numbers, segments, is_level, profile,
                  labels=()) -> Survey:
    k = best.calibration.metres_per_unit
    minx, _, _, maxy = best.polygon.bounds

    def to_m(x: float, y: float) -> tuple[float, float]:
        return ((x - minx) * k, (maxy - y) * k)

    boundary_page = best.polygon
    boundary = Polygon([to_m(x, y) for x, y in boundary_page.exterior.coords])
    near = _nearby_finder(segments, k)
    levels = tuple(
        SpotLevel(*to_m(t.x, t.y), z=v, on_site=boundary_page.contains(Point(t.x, t.y)))
        for v, t in numbers
        if is_level(v) and "." in t.text and id(t) not in best.dimension_tokens
    )

    def lines_of(colour: Colour | None) -> tuple[LineString, ...]:
        key = _closest(segments, colour)
        segs = segments.get(key, []) if key else []
        if not segs:
            return ()
        joined = unary_union(segs)
        merged = joined if joined.geom_type == "LineString" else linemerge(joined)
        parts = getattr(merged, "geoms", [merged])
        return tuple(LineString([to_m(x, y) for x, y in p.coords]) for p in parts)

    warnings = []
    if not best.calibration.agreeing:
        plotted_at = k / _METRES_PER_POINT_AT_1_TO_1
        warnings.append(
            "The sheet has no dimension labels, so the scale comes from the written area "
            f"(about 1:{plotted_at:,.0f}) and the area cannot be checked against the drawing. "
            "The plot is taken as the tightest shape round the spot levels. Confirm one "
            "boundary length before relying on the dimensions."
        )
    elif stated is None:
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
        water=lines_of(profile.water_colour),
        labels=tuple(Label(text, *to_m(x, y), nearby=near(x, y)) for text, x, y in labels),
        line_groups=line_groups(
            {colour_hex(c): [LineString([to_m(*p) for p in s.coords]) for s in segs]
             for c, segs in segments.items() if c},
            boundary),
        boundary_key=colour_hex(best.colour) if best.colour else None,
        warnings=tuple(warnings),
    )
