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
    "Driveway": 253,
    "Parking": 51,
    "SITE-AMENITIES": 140,
    "SOLVER-GATES": 1,
    "SOLVER-CORES": 8,
    "SOLVER-LABELS": 7,
}


def _ring(polygon: Polygon) -> list[tuple[float, float]]:
    return [(x, y) for x, y in list(polygon.exterior.coords)[:-1]]


def _parts(shape) -> list[Polygon]:
    """The driveway ring can come back as several pieces; nothing is one piece for free."""
    if shape is None or shape.is_empty:
        return []
    return [shape] if isinstance(shape, Polygon) else [p for p in shape.geoms]


def write_layout_dxf(option: LayoutOption, plot: Polygon, path: str | Path) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    for name, colour in LAYERS.items():
        doc.layers.add(name, color=colour)
    msp = doc.modelspace()

    def add(polygon: Polygon, layer: str) -> None:
        msp.add_lwpolyline(_ring(polygon), close=True, dxfattribs={"layer": layer})

    add(plot, "Plot")
    for part in _parts(option.driveway):
        add(part, "Driveway")
    if option.club_house is not None:
        add(option.club_house, "Building Plan")
        c = option.club_house.centroid
        msp.add_text(
            "CLUB HOUSE", height=3.0, dxfattribs={"layer": "SOLVER-LABELS"}
        ).set_placement((c.x, c.y))
    for bay in option.parking_bays:
        add(bay, "Parking")
    for name, gate in option.gates:
        add(gate, "SOLVER-GATES")
        c = gate.centroid
        msp.add_text(name, height=2.5, dxfattribs={"layer": "SOLVER-LABELS"}).set_placement(
            (c.x, c.y)
        )
    for amenity in option.amenities:
        add(amenity.shape, "SITE-AMENITIES")
        c = amenity.shape.centroid
        msp.add_text(amenity.name, height=2.0, dxfattribs={"layer": "SOLVER-LABELS"}
                     ).set_placement((c.x, c.y))
    for pocket in option.open_space:
        add(pocket, "Organized Open Space")
    for tower in option.towers:
        add(tower.footprint, "Building Plan")
        for flat in tower.flat_outlines:
            add(flat, "Dwelling Unit")
        for core in tower.cores:
            add(core, "SOLVER-CORES")
        c = tower.footprint.centroid
        msp.add_text(tower.name, height=3.0, dxfattribs={"layer": "SOLVER-LABELS"}).set_placement(
            (c.x, c.y)
        )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    return out


def write_layout_svg(option: LayoutOption, plot: Polygon, path: str | Path, title: str) -> Path:
    """A plain drawing for a browser: plot, open space, towers, flats, cores, labels."""
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

    s = option.summary()
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="Helvetica, Arial, sans-serif">',
        '<rect width="100%" height="100%" fill="#fbfbf8"/>',
        f'<text x="14" y="26" font-size="17" font-weight="700">{escape(title)}</text>',
        f'<text x="14" y="50" font-size="13" fill="#444">{s["towers"]} tower'
        f'{"" if s["towers"] == 1 else "s"} · '
        f'{s["total_flats"]} flats · {s["saleable_sqft"]:,} sft saleable · open space '
        f'{s["open_space_share_pct"]}% · mix {escape(str(s["unit_mix_achieved"]))}</text>',
        f'<polygon points="{pts(plot)}" fill="none" stroke="#ad2677" stroke-width="2"/>',
    ]
    for part in _parts(option.driveway):
        lines.append(f'<polygon points="{pts(part)}" fill="#ded9cc" stroke="#b0a894"/>')
    if option.club_house is not None:
        c = option.club_house.centroid
        lines.append(
            f'<polygon points="{pts(option.club_house)}" fill="#cfd8e8" stroke="#3a5a8c"/>'
        )
        lines.append(
            f'<text x="{(c.x - minx + pad) * scale:.1f}" y="{(maxy - c.y + pad) * scale + 70:.1f}" '
            f'font-size="11" font-weight="700" text-anchor="middle" fill="#3a5a8c">CLUB</text>'
        )
    for bay in option.parking_bays:
        lines.append(
            f'<polygon points="{pts(bay)}" fill="#f0ece0" stroke="#9a9384" stroke-width="0.5"/>'
        )
    for name, gate in option.gates:
        c = gate.centroid
        lines.append(f'<polygon points="{pts(gate)}" fill="#f6d6cc" stroke="#bd3b27"/>')
        lines.append(
            f'<text x="{(c.x - minx + pad) * scale:.1f}" y="{(maxy - c.y + pad) * scale + 70:.1f}" '
            f'font-size="10" font-weight="700" text-anchor="middle" fill="#bd3b27">{name}</text>'
        )
    for amenity in option.amenities:
        c = amenity.shape.centroid
        lines.append(f'<polygon points="{pts(amenity.shape)}" fill="#cde7ef" stroke="#3b7f96"/>')
        lines.append(
            f'<text x="{(c.x - minx + pad) * scale:.1f}" y="{(maxy - c.y + pad) * scale + 70:.1f}" '
            f'font-size="9" text-anchor="middle" fill="#2b5d6e">{escape(amenity.name)}</text>'
        )
    for pocket in option.open_space:
        lines.append(f'<polygon points="{pts(pocket)}" fill="#bfdcaa" stroke="#47762c"/>')
    for tower in option.towers:
        lines.append(f'<polygon points="{pts(tower.footprint)}" fill="#e8e4d6" stroke="#333"/>')
        for flat in tower.flat_outlines:
            lines.append(
                f'<polygon points="{pts(flat)}" fill="none" stroke="#777" stroke-width="0.6"/>'
            )
        for core in tower.cores:
            lines.append(f'<polygon points="{pts(core)}" fill="#8a8a8a"/>')
        c = tower.footprint.centroid
        lines.append(
            f'<text x="{(c.x - minx + pad) * scale:.1f}" y="{(maxy - c.y + pad) * scale + 70:.1f}" '
            f'font-size="14" font-weight="700" text-anchor="middle" fill="#bd3b27">'
            f"{escape(tower.name)}</text>"
        )
    lines.append("</svg>")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    return out
