"""The drawing sheet: one chosen option drawn up as a document, not a diagram.

The layout DXF holds the geometry on BuildNow layer names and nothing else, so it can be
dropped into the firm's own template. This adds everything that makes it a sheet an
architect can read and check: dimensions, labels, a north arrow, a scale bar, the area
statement and a title block. All of it goes on SHEET-* layers, so their draughtsman can
switch ours off and use their own.

Everything is drawn in model space at true size, and the border is drawn at the sheet
scale around it, which is how these sheets are usually set out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import ezdxf
from shapely.geometry import Polygon

from siteplan.area_statement import render
from siteplan.layout import LayoutOption, LayoutRequest, area_statement
from siteplan.layout_export import LAYERS, ROAD_LABELS, _parts, _ring

STANDARD_SCALES = (100, 150, 200, 250, 300, 400, 500, 750, 1000, 1250, 1500, 2000)
SHEET_MM = (841.0, 594.0)  # A1 landscape
MARGIN_MM = 15.0
TITLE_BLOCK_MM = (190.0, 78.0)
STATEMENT_WIDTH_MM = 62.0
TEXT_MM = 2.6  # printed text height; everything else is sized from it
TITLE_CHARS = 42  # what fits on the title block's heading line
ROW_CHARS = 30  # and in a title block row's value column
SHEET_LAYERS = {
    "SHEET-BORDER": 7,
    "SHEET-DIMENSIONS": 4,
    "SHEET-TEXT": 7,
    "SHEET-NORTH": 7,
}


@dataclass(frozen=True)
class SheetInfo:
    """What the title block says. Ours until the firm gives us theirs."""

    project: str
    client: str = ""
    architect: str = ""
    drawing: str = "SITE PLAN"
    number: str = ""
    revision: str = ""
    drawn_by: str = ""
    sheet_date: date | None = None

    def rows(self, scale: int) -> list[tuple[str, str]]:
        return [
            ("PROJECT", self.project),
            ("CLIENT", self.client),
            ("ARCHITECT", self.architect),
            ("DRAWING", self.drawing),
            ("SCALE", f"1:{scale} (A1)"),
            ("DATE", (self.sheet_date or date.today()).strftime("%d-%m-%Y")),
            ("DRG. NO.", self.number),
            ("REV.", self.revision),
            ("DRAWN", self.drawn_by),
        ]


def _fit(text: str, chars: int) -> str:
    """A title block has fixed-width boxes; text that does not fit is cut, not run off."""
    return text if len(text) <= chars else text[: chars - 1].rstrip(" ,;(") + "…"


def pick_scale(plot: Polygon) -> int:
    """The tightest standard scale that still leaves room for the title block."""
    minx, miny, maxx, maxy = plot.bounds
    usable_mm = (
        SHEET_MM[0] - 2 * MARGIN_MM - STATEMENT_WIDTH_MM - 6,
        SHEET_MM[1] - 2 * MARGIN_MM - 14,  # strip for the labels above the drawing
    )
    for scale in STANDARD_SCALES:
        if ((maxx - minx) * 1000 / scale <= usable_mm[0]
                and (maxy - miny) * 1000 / scale <= usable_mm[1]):
            return scale
    return STANDARD_SCALES[-1]


def write_sheet_dxf(option: LayoutOption, plot: Polygon, request: LayoutRequest,
                    info: SheetInfo, path: str | Path) -> Path:
    """The option drawn up as an A1 sheet, dimensioned and titled."""
    scale = pick_scale(plot)
    m = scale / 1000  # one printed millimetre in metres on the ground
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    for name, colour in (LAYERS | SHEET_LAYERS).items():
        doc.layers.add(name, color=colour)
    msp = doc.modelspace()
    text_h = TEXT_MM * m

    def poly(shape: Polygon, layer: str) -> None:
        msp.add_lwpolyline(_ring(shape), close=True, dxfattribs={"layer": layer})

    def label(text: str, at, height: float = text_h, layer: str = "SHEET-TEXT",
              align: str = "MIDDLE_CENTER") -> None:
        entity = msp.add_text(text, height=height, dxfattribs={"layer": layer})
        entity.set_placement(at, align=ezdxf.enums.TextEntityAlignment[align])

    # --- the drawing itself ------------------------------------------------------
    poly(plot, "Plot")
    for part in _parts(option.green_strip):
        poly(part, "SOLVER-GREEN-STRIP")
    for road in option.roads:
        for part in _parts(road.shape):
            poly(part, "SOLVER-ROADS")
        biggest = max(_parts(road.shape), key=lambda p: p.area, default=None)
        if biggest is not None:
            at = biggest.representative_point()
            label(f"{ROAD_LABELS.get(road.kind, road.kind.upper())} {road.width_m:g} M",
                  (at.x, at.y), text_h * 0.8)
    for part in _parts(option.fire_lanes):
        poly(part, "SOLVER-FIRE-LANES")
    if option.entrance is not None:
        for part in _parts(option.entrance.gate):
            poly(part, "SOLVER-ENTRANCE")
        centre = option.entrance.gate.centroid
        label("MAIN ENTRANCE", (centre.x, centre.y), text_h * 0.9)
    if option.parking is not None and option.parking.cellar_outline is not None:
        for part in _parts(option.parking.cellar_outline):
            poly(part, "SOLVER-CELLAR")
    for ramp in option.ramps:
        poly(ramp, "SOLVER-RAMPS")
        label("RAMP 1:8", (ramp.centroid.x, ramp.centroid.y), text_h * 0.7)
    for bay in option.parking_bays:
        poly(bay, "Parking")
    for amenity in option.amenities:
        poly(amenity.shape, "SITE-AMENITIES")
        label(amenity.name, (amenity.shape.centroid.x, amenity.shape.centroid.y), text_h * 0.75)
    for pocket in option.open_space:
        poly(pocket, "Organized Open Space")
        label("TOT-LOT", (pocket.centroid.x, pocket.centroid.y), text_h * 0.8)
    if option.club_house is not None:
        poly(option.club_house, "Building Plan")
        centre = option.club_house.centroid
        label("CLUB HOUSE", (centre.x, centre.y + text_h), text_h * 0.9)
        label(f"{option.club_house_floors} FLOORS", (centre.x, centre.y - text_h), text_h * 0.8)
    for tower in option.towers:
        poly(tower.footprint, "Building Plan")
        for flat in tower.flat_outlines:
            poly(flat, "Dwelling Unit")
        for core in tower.cores:
            poly(core, "SOLVER-CORES")
        centre = tower.footprint.centroid
        flats = sum(tower.flats_per_floor().values())
        label(f"{tower.name} · {flats} FLATS/FLOOR", (centre.x, centre.y), text_h * 0.9)

    _dimension(msp, plot, option, m)
    _north_arrow(msp, plot, m)
    _scale_bar(msp, plot, scale, m)
    _border(msp, plot, option, request, info, scale, m)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    return out


def _dimension(msp, plot: Polygon, option: LayoutOption, m: float) -> None:
    """Overall site extents and every tower, so the setbacks can be read off the sheet."""
    minx, miny, maxx, maxy = plot.bounds
    style = {
        "dimstyle": "EZDXF",
        "dxfattribs": {"layer": "SHEET-DIMENSIONS"},
        # dimlfac 1: ezdxf's EZDXF style multiplies by 100 (centimetres); the sheet reads metres
        "override": {"dimtxt": 2.2 * m, "dimasz": 2.0 * m, "dimexe": 1.0 * m,
                     "dimexo": 1.0 * m, "dimdec": 2, "dimlfac": 1.0},
    }
    msp.add_linear_dim(base=(minx, miny - 9 * m), p1=(minx, miny), p2=(maxx, miny),
                       **style).render()
    msp.add_linear_dim(base=(minx - 9 * m, miny), p1=(minx, miny), p2=(minx, maxy),
                       angle=90, **style).render()
    for tower in option.towers:
        x0, y0, x1, y1 = tower.footprint.bounds
        msp.add_linear_dim(base=(x0, y1 + 3 * m), p1=(x0, y1), p2=(x1, y1), **style).render()


def _north_arrow(msp, plot: Polygon, m: float) -> None:
    minx, miny, maxx, maxy = plot.bounds
    x, y = maxx + 6 * m, maxy - 4 * m
    size = 8 * m
    msp.add_lwpolyline(
        [(x, y), (x - size / 3, y - size), (x, y - size * 0.7), (x + size / 3, y - size)],
        close=True, dxfattribs={"layer": "SHEET-NORTH"},
    )
    msp.add_text("N", height=3.5 * m, dxfattribs={"layer": "SHEET-NORTH"}).set_placement(
        (x, y + 1.5 * m), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
    )


def _scale_bar(msp, plot: Polygon, scale: int, m: float) -> None:
    minx, miny, _, _ = plot.bounds
    step = 10 ** len(str(int(scale / 10)).rstrip("0").replace("", ""))  # 10, 20, 50 m steps
    step = max(5, round(scale / 20 / 5) * 5)
    y = miny - 14 * m
    for i in range(4):
        x0 = minx + i * step
        msp.add_lwpolyline(
            [(x0, y), (x0 + step, y), (x0 + step, y + 1.2 * m), (x0, y + 1.2 * m)],
            close=True, dxfattribs={"layer": "SHEET-BORDER"},
        )
        msp.add_text(f"{i * step:g}", height=2.2 * m,
                     dxfattribs={"layer": "SHEET-TEXT"}).set_placement(
            (x0, y - 3 * m), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    msp.add_text(f"{4 * step:g} m", height=2.2 * m,
                 dxfattribs={"layer": "SHEET-TEXT"}).set_placement(
        (minx + 4 * step, y - 3 * m), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)


def _border(msp, plot: Polygon, option: LayoutOption, request: LayoutRequest,
            info: SheetInfo, scale: int, m: float) -> None:
    """The A1 border, the area statement and the title block, all at sheet scale."""
    width, height = SHEET_MM[0] * m, SHEET_MM[1] * m
    minx, miny, maxx, maxy = plot.bounds
    # Centre the drawing in the space left of the area statement column.
    left = (minx + maxx) / 2 - (width - STATEMENT_WIDTH_MM * m) / 2
    bottom = (miny + maxy) / 2 - height / 2
    frame = [(left, bottom), (left + width, bottom), (left + width, bottom + height),
             (left, bottom + height)]
    msp.add_lwpolyline(frame, close=True, dxfattribs={"layer": "SHEET-BORDER"})
    inner = MARGIN_MM * m
    msp.add_lwpolyline(
        [(left + inner, bottom + inner), (left + width - inner, bottom + inner),
         (left + width - inner, bottom + height - inner), (left + inner, bottom + height - inner)],
        close=True, dxfattribs={"layer": "SHEET-BORDER"},
    )

    right = left + width - inner
    statement = render(area_statement(option, request))
    msp.add_mtext(statement.replace("\n", "\\P"), dxfattribs={"layer": "SHEET-TEXT"}).set_location(
        (right - STATEMENT_WIDTH_MM * m, bottom + height - inner - 4 * m)
    ).dxf.char_height = 2.2 * m

    block_w, block_h = TITLE_BLOCK_MM[0] * m, TITLE_BLOCK_MM[1] * m
    x0, y0 = right - block_w, bottom + inner
    msp.add_lwpolyline([(x0, y0), (x0 + block_w, y0), (x0 + block_w, y0 + block_h),
                        (x0, y0 + block_h)], close=True, dxfattribs={"layer": "SHEET-BORDER"})
    rows = info.rows(scale)
    line_h = block_h / (len(rows) + 1)
    for i, (key, value) in enumerate(rows):
        y = y0 + block_h - (i + 1) * line_h
        msp.add_line((x0, y), (x0 + block_w, y), dxfattribs={"layer": "SHEET-BORDER"})
        msp.add_text(key, height=2.2 * m, dxfattribs={"layer": "SHEET-TEXT"}).set_placement(
            (x0 + 2 * m, y + line_h * 0.3), align=ezdxf.enums.TextEntityAlignment.LEFT)
        msp.add_text(_fit(value or "-", ROW_CHARS), height=2.6 * m,
                     dxfattribs={"layer": "SHEET-TEXT"}).set_placement(
            (x0 + 34 * m, y + line_h * 0.3), align=ezdxf.enums.TextEntityAlignment.LEFT)
    msp.add_text(_fit(info.project, TITLE_CHARS), height=3.6 * m,
                 dxfattribs={"layer": "SHEET-TEXT"}).set_placement(
        (x0 + 2 * m, y0 + block_h - line_h * 0.55), align=ezdxf.enums.TextEntityAlignment.LEFT)
