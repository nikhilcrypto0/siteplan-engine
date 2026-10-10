"""A step's picture: one drawing in the survey's own metres, as SVG to look at and DXF to open in
CAD, with a title, a legend that says what each colour is, a north arrow and a scale bar."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path

import ezdxf
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

DRAWING_PX = 1000.0  # the drawing's longer side
MARGIN_PX = 30.0
TITLE_PX = 64.0
LEGEND_ROW_PX = 22.0
LABEL_PX = 12.0
TEXT_SHARE = 0.008  # DXF text height, as a share of the drawing's longer side
NICE_LENGTHS_M = (5, 10, 20, 25, 50, 100, 200, 250, 500)  # a scale bar is one of these


@dataclass(frozen=True)
class Layer:
    name: str  # also the DXF layer's name
    colour: str  # '#rrggbb'
    aci: int  # the DXF colour index
    legend: str  # what it shows, in plain words; empty leaves it out of the legend
    fill: float = 0.0  # fill opacity; 0 draws the outline only
    width: float = 1.5  # line width, in pixels
    dash: str = ""


@dataclass
class Picture:
    title: str
    subtitle: str
    layers: list[Layer] = field(default_factory=list)
    shapes: list[tuple[str, BaseGeometry]] = field(default_factory=list)
    labels: list[tuple[str, tuple[float, float], str]] = field(default_factory=list)

    def add(self, layer: str, geometry: BaseGeometry | None) -> None:
        if geometry is not None and not geometry.is_empty:
            self.shapes.append((layer, geometry))

    def label(self, layer: str, at: tuple[float, float], text: str) -> None:
        self.labels.append((layer, (float(at[0]), float(at[1])), text))

    def bounds(self) -> tuple[float, float, float, float]:
        xs, ys = [], []
        for _, geometry in self.shapes:
            x0, y0, x1, y1 = geometry.bounds
            xs += [x0, x1]
            ys += [y0, y1]
        xs += [at[0] for _, at, _ in self.labels]
        ys += [at[1] for _, at, _ in self.labels]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 1.0, 1.0)

    def write(self, folder: Path, stem: str) -> tuple[Path, Path]:
        folder.mkdir(parents=True, exist_ok=True)
        svg, dxf = folder / f"{stem}.svg", folder / f"{stem}.dxf"
        svg.write_text(self.svg())
        self.dxf().saveas(dxf)
        return svg, dxf

    def svg(self) -> str:
        x0, y0, x1, y1 = self.bounds()
        scale = DRAWING_PX / max(x1 - x0, y1 - y0, 1.0)
        width = (x1 - x0) * scale + 2 * MARGIN_PX
        legend = [layer for layer in self.layers if layer.legend]
        top = TITLE_PX
        height = top + (y1 - y0) * scale + 2 * MARGIN_PX + LEGEND_ROW_PX * (len(legend) + 1)

        def xy(x: float, y: float) -> tuple[float, float]:
            return MARGIN_PX + (x - x0) * scale, top + MARGIN_PX + (y1 - y) * scale

        styles = {layer.name: layer for layer in self.layers}
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
                 f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
                 'font-family="Helvetica, Arial, sans-serif">',
                 '<rect width="100%" height="100%" fill="#ffffff"/>',
                 f'<text x="{MARGIN_PX}" y="28" font-size="20" font-weight="700">'
                 f'{escape(self.title)}</text>',
                 f'<text x="{MARGIN_PX}" y="50" font-size="13" fill="#444">'
                 f'{escape(self.subtitle)}</text>']
        for layer in self.layers:  # in the layers' order, so a fill goes under the lines
            for name, geometry in self.shapes:
                if name == layer.name:
                    parts += _svg_shape(geometry, layer, xy)
        for name, (x, y), text in self.labels:
            colour = styles[name].colour if name in styles else "#222222"
            px, py = xy(x, y)
            for k, line in enumerate(text.split("\n")):
                parts.append(f'<text x="{px:.1f}" y="{py + k * (LABEL_PX + 2):.1f}" '
                             f'font-size="{LABEL_PX:g}" fill="{colour}" stroke="#ffffff" '
                             'stroke-width="3" paint-order="stroke" text-anchor="middle">'
                             f'{escape(line)}</text>')
        parts += _north_arrow(width - MARGIN_PX - 20, top + MARGIN_PX + 30)
        parts += _scale_bar(scale, MARGIN_PX, top + MARGIN_PX + (y1 - y0) * scale + 18)
        base = top + (y1 - y0) * scale + 2 * MARGIN_PX + 10
        for i, layer in enumerate(legend):
            y = base + i * LEGEND_ROW_PX
            fill = layer.colour if layer.fill else "none"
            parts.append(f'<rect x="{MARGIN_PX}" y="{y:.0f}" width="26" height="12" '
                         f'fill="{fill}" fill-opacity="{max(layer.fill, 0.0):.2f}" '
                         f'stroke="{layer.colour}" stroke-width="2"/>')
            parts.append(f'<text x="{MARGIN_PX + 36}" y="{y + 11:.0f}" font-size="13">'
                         f'{escape(layer.legend)}</text>')
        parts.append("</svg>")
        return "\n".join(parts)

    def dxf(self):
        doc = ezdxf.new(setup=True)
        doc.header["$INSUNITS"] = 6  # metres
        msp = doc.modelspace()
        for layer in self.layers:
            doc.layers.add(layer.name, color=layer.aci)
        x0, y0, x1, y1 = self.bounds()
        height = max(0.5, TEXT_SHARE * max(x1 - x0, y1 - y0))
        for name, geometry in self.shapes:
            for coords, closed in _rings(geometry):
                if len(coords) == 1:
                    msp.add_circle(coords[0], height / 2, dxfattribs={"layer": name})
                else:
                    msp.add_lwpolyline(coords, close=closed, dxfattribs={"layer": name})
        for name, at, text in self.labels:
            msp.add_mtext(text, dxfattribs={"layer": name, "char_height": height,
                                            "insert": at})
        return doc


def _rings(geometry: BaseGeometry) -> list[tuple[list[tuple[float, float]], bool]]:
    kind = geometry.geom_type
    if kind == "Polygon":
        return [(list(ring.coords)[:-1], True) for ring in (geometry.exterior, *geometry.interiors)]
    if kind in ("LineString", "LinearRing"):
        return [(list(geometry.coords), kind == "LinearRing")]
    if kind == "Point":
        return [([(geometry.x, geometry.y)], False)]
    return [ring for part in getattr(geometry, "geoms", []) for ring in _rings(part)]


def _svg_shape(geometry: BaseGeometry, layer: Layer, xy) -> list[str]:
    dash = f' stroke-dasharray="{layer.dash}"' if layer.dash else ""
    out = []
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        data = " ".join("M " + " L ".join("{:.1f},{:.1f}".format(*xy(*p)) for p in coords) + " Z"
                        for coords, closed in _rings(geometry) if closed)
        fill = (f'fill="{layer.colour}" fill-opacity="{layer.fill:.2f}"' if layer.fill
                else 'fill="none"')
        out.append(f'<path d="{data}" fill-rule="evenodd" {fill} stroke="{layer.colour}" '
                   f'stroke-width="{layer.width:g}"{dash}/>')
        return out
    for coords, _ in _rings(geometry):
        if len(coords) == 1:
            px, py = xy(*coords[0])
            out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{max(layer.width, 2):g}" '
                       f'fill="{layer.colour}"/>')
        else:
            points = " ".join("{:.1f},{:.1f}".format(*xy(*p)) for p in coords)
            out.append(f'<polyline points="{points}" fill="none" stroke="{layer.colour}" '
                       f'stroke-width="{layer.width:g}"{dash}/>')
    return out


def _north_arrow(x: float, y: float) -> list[str]:
    return [f'<polygon points="{x:.0f},{y - 24:.0f} {x - 9:.0f},{y + 6:.0f} {x + 9:.0f},'
            f'{y + 6:.0f}" fill="#222"/>',
            f'<text x="{x:.0f}" y="{y + 24:.0f}" font-size="14" text-anchor="middle" '
            'font-weight="700">N</text>']


def _scale_bar(scale: float, x: float, y: float) -> list[str]:
    length = next((n for n in NICE_LENGTHS_M if n * scale >= 80), NICE_LENGTHS_M[-1])
    px = length * scale
    return [f'<rect x="{x:.0f}" y="{y:.0f}" width="{px:.0f}" height="5" fill="#222"/>',
            f'<text x="{x + px + 6:.0f}" y="{y + 6:.0f}" font-size="12">{length} m</text>']


BASIC_COLOURS = {"black": (0, 0, 0), "white": (255, 255, 255), "grey": (128, 128, 128),
                 "red": (255, 0, 0), "green": (0, 170, 0), "blue": (0, 0, 255),
                 "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
                 "orange": (255, 140, 0), "brown": (140, 70, 20)}


def colour_name(key: str) -> str:
    """'#808080' -> 'grey (#808080)'; a DXF layer's name -> 'layer NAME'."""
    if not (key.startswith("#") and len(key) == 7):
        return f"layer {key}"
    rgb = tuple(int(key[i:i + 2], 16) for i in (1, 3, 5))
    name = min(BASIC_COLOURS, key=lambda n: sum(
        (a - b) ** 2 for a, b in zip(rgb, BASIC_COLOURS[n], strict=True)))
    return f"{name} ({key})"


def frame(geometry: BaseGeometry, margin_m: float):
    """A box round a shape, for clipping what is drawn around it."""
    x0, y0, x1, y1 = geometry.bounds
    return box(x0 - margin_m, y0 - margin_m, x1 + margin_m, y1 + margin_m)
