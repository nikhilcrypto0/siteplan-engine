"""Write a layout option as DXF (for ZWCAD) and as an SVG preview (for a browser)."""

from __future__ import annotations

from html import escape
from pathlib import Path

import ezdxf
from shapely.geometry import Polygon

from siteplan.layout import LayoutOption

# BuildNow plugin layer names where one fits; SOLVER-* layers are ours, not BuildNow's.
LAYERS = {
    "Plot": 6,
    "Building Plan": 7,
    "Dwelling Unit": 3,
    "Organized Open Space": 94,
    "Parking": 51,
    "SITE-AMENITIES": 140,
    "SOLVER-ROADS": 253,
    "SOLVER-FIRE-LANES": 30,
    "SOLVER-GREEN-STRIP": 82,
    "SOLVER-ENTRANCE": 1,
    "SOLVER-RAMPS": 5,
    "SOLVER-CELLAR": 8,
    "SOLVER-CORES": 8,
    "SOLVER-LABELS": 7,
}
ROAD_LABELS = {"loop": "LOOP ROAD", "main approach": "MAIN APPROACH ROAD",
               "internal": "INTERNAL ROAD", "cul-de-sac": "CUL-DE-SAC"}


def _ring(polygon: Polygon) -> list[tuple[float, float]]:
    return [(x, y) for x, y in list(polygon.exterior.coords)[:-1]]


def _parts(shape) -> list[Polygon]:
    """Roads and lanes come back as several pieces; nothing is one piece for free."""
    if shape is None or shape.is_empty:
        return []
    if isinstance(shape, Polygon):
        return [shape]
    return [p for p in getattr(shape, "geoms", []) if isinstance(p, Polygon)]


def write_layout_dxf(option: LayoutOption, plot: Polygon, path: str | Path) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    for name, colour in LAYERS.items():
        doc.layers.add(name, color=colour)
    msp = doc.modelspace()

    def add(polygon: Polygon, layer: str) -> None:
        msp.add_lwpolyline(_ring(polygon), close=True, dxfattribs={"layer": layer})
        for hole in polygon.interiors:
            msp.add_lwpolyline([(x, y) for x, y in list(hole.coords)[:-1]], close=True,
                               dxfattribs={"layer": layer})

    def label(text: str, at, height: float) -> None:
        msp.add_text(text, height=height, dxfattribs={"layer": "SOLVER-LABELS"}
                     ).set_placement((at.x, at.y))

    add(plot, "Plot")
    for part in _parts(option.green_strip):
        add(part, "SOLVER-GREEN-STRIP")
    for road in option.roads:
        for part in _parts(road.shape):
            add(part, "SOLVER-ROADS")
        biggest = max(_parts(road.shape), key=lambda p: p.area, default=None)
        if biggest is not None:
            label(f"{ROAD_LABELS.get(road.kind, road.kind.upper())} {road.width_m:g} M",
                  biggest.representative_point(), 2.0)
    for part in _parts(option.fire_lanes):
        add(part, "SOLVER-FIRE-LANES")
    if option.entrance is not None:
        for part in _parts(option.entrance.gate):
            add(part, "SOLVER-ENTRANCE")
        label("MAIN ENTRANCE", option.entrance.gate.centroid, 2.5)
    if option.parking is not None and option.parking.cellar_outline is not None:
        for part in _parts(option.parking.cellar_outline):
            add(part, "SOLVER-CELLAR")
    for ramp in option.ramps:
        add(ramp, "SOLVER-RAMPS")
        label("RAMP 1:8", ramp.centroid, 2.0)
    if option.club_house is not None:
        add(option.club_house, "Building Plan")
        label("CLUB HOUSE", option.club_house.centroid, 3.0)
    for bay in option.parking_bays:
        add(bay, "Parking")
    for amenity in option.amenities:
        add(amenity.shape, "SITE-AMENITIES")
        label(amenity.name, amenity.shape.centroid, 2.0)
    for pocket in option.open_space:
        add(pocket, "Organized Open Space")
    for tower in option.towers:
        add(tower.footprint, "Building Plan")
        for flat in tower.flat_outlines:
            add(flat, "Dwelling Unit")
        for core in tower.cores:
            add(core, "SOLVER-CORES")
        label(tower.name, tower.footprint.centroid, 3.0)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    return out


def write_layout_svg(option: LayoutOption, plot: Polygon, path: str | Path, title: str) -> Path:
    """A plain drawing for a browser: plot, roads, lanes, open space, towers, flats, labels."""
    minx, miny, maxx, maxy = plot.bounds
    pad = 12.0
    scale = 900 / max(maxx - minx + 2 * pad, maxy - miny + 2 * pad)
    width = (maxx - minx + 2 * pad) * scale
    height = (maxy - miny + 2 * pad) * scale + 70

    def pts(polygon: Polygon) -> str:
        return " ".join(
            f"{(x - minx + pad) * scale:.1f},{(maxy - y + pad) * scale + 70:.1f}"
            for x, y in polygon.exterior.coords
        )

    def text(at, words: str, size: int, colour: str, bold: bool = False) -> str:
        weight = ' font-weight="700"' if bold else ""
        return (f'<text x="{(at.x - minx + pad) * scale:.1f}" '
                f'y="{(maxy - at.y + pad) * scale + 70:.1f}" font-size="{size}"{weight} '
                f'text-anchor="middle" fill="{colour}">{escape(words)}</text>')

    s = option.summary()
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="Helvetica, Arial, sans-serif">',
        '<rect width="100%" height="100%" fill="#fbfbf8"/>',
        f'<text x="14" y="26" font-size="17" font-weight="700">{escape(title)}</text>',
        f'<text x="14" y="50" font-size="13" fill="#444">{s["towers"]} tower'
        f'{"" if s["towers"] == 1 else "s"} · stilt + {option.floors} · '
        f'{s["total_flats"]} flats · {s["saleable_sqft"]:,} sft saleable (flats) · tot-lot '
        f'{s["open_space_share_pct"]}% · mix {escape(str(s["unit_mix_achieved"]))}</text>',
        f'<polygon points="{pts(plot)}" fill="none" stroke="#ad2677" stroke-width="2"/>',
    ]
    for part in _parts(option.green_strip):
        lines.append(f'<polygon points="{pts(part)}" fill="#d9ead0" stroke="none"/>')
    for road in option.roads:
        for part in _parts(road.shape):
            lines.append(f'<polygon points="{pts(part)}" fill="#d6d2c6" stroke="#9c9587"/>')
    for part in _parts(option.fire_lanes):
        lines.append(f'<polygon points="{pts(part)}" fill="#f3e3c7" stroke="#d0a24c" '
                     'stroke-dasharray="4 3"/>')
    if option.entrance is not None:
        for part in _parts(option.entrance.gate):
            lines.append(f'<polygon points="{pts(part)}" fill="#f6d6cc" stroke="#bd3b27"/>')
        lines.append(text(option.entrance.gate.centroid, "ENTRANCE", 10, "#bd3b27", True))
    for ramp in option.ramps:
        lines.append(f'<polygon points="{pts(ramp)}" fill="#6d7f99" stroke="#34445c"/>')
        lines.append(text(ramp.centroid, "RAMP", 9, "#ffffff", True))
    if option.club_house is not None:
        lines.append(f'<polygon points="{pts(option.club_house)}" fill="#cfd8e8" '
                     'stroke="#3a5a8c"/>')
        lines.append(text(option.club_house.centroid, "CLUB", 11, "#3a5a8c", True))
    for bay in option.parking_bays:
        lines.append(f'<polygon points="{pts(bay)}" fill="#f0ece0" stroke="#9a9384" '
                     'stroke-width="0.5"/>')
    for amenity in option.amenities:
        lines.append(f'<polygon points="{pts(amenity.shape)}" fill="#cde7ef" stroke="#3b7f96"/>')
        lines.append(text(amenity.shape.centroid, amenity.name, 9, "#2b5d6e"))
    for pocket in option.open_space:
        lines.append(f'<polygon points="{pts(pocket)}" fill="#bfdcaa" stroke="#47762c"/>')
    for tower in option.towers:
        lines.append(f'<polygon points="{pts(tower.footprint)}" fill="#e8e4d6" stroke="#333"/>')
        for flat in tower.flat_outlines:
            # Filled, not just outlined: on a 300px card an unfilled hairline disappears and
            # the towers read as empty blocks. The flats are the point of the drawing.
            lines.append(
                f'<polygon points="{pts(flat)}" fill="#f7f4ea" stroke="#5b5b5b" '
                f'stroke-width="1.1"/>'
            )
        for core in tower.cores:
            lines.append(f'<polygon points="{pts(core)}" fill="#8a8a8a"/>')
        lines.append(text(tower.footprint.centroid, tower.name, 14, "#bd3b27", True))
    lines.append("</svg>")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    return out
