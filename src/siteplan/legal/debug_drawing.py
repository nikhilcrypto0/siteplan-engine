"""A debug drawing of the legal envelope, as DXF (for ZWCAD) and SVG (for a browser).

It exists so a person can see what the stage decided before any tower is drawn: the original and
the net site, the statutory exclusions, each band's setback envelope and buildable land, the width
regions, the access zones, the rule layers, and a text block with the open-space requirement under
each reading and the height limits. It is a debug aid on its own layers, not a deliverable for the
firm. Both files are metres in the survey's frame ($INSUNITS 6). The drawing is built once, as
plain items on named layers, and each format only writes them.

Layers: ORIGINAL-SITE, NET-SITE, EXCLUSIONS, SETBACK-<band>, BUILDABLE-<band>, WIDTH-REGIONS (the
net plot's; a band's are WIDTH-REGIONS-<band>), ACCESS-ZONES, RULE-LAYERS and NOTES.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

import ezdxf

from siteplan.contracts.common import Point, Shape
from siteplan.contracts.envelope import BuildableEnvelope
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.legal.bands import band_key
from siteplan.legal.envelope import NET_PLOT

SETBACK_ACI = (150, 160, 170, 180, 190, 200)
BUILDABLE_ACI = (70, 80, 90, 100, 110, 120)
SETBACK_HEX = ("#5b9bd5", "#4a86c8", "#3a72b8", "#2b5ea3", "#1d4a8c", "#123874")
BUILDABLE_HEX = ("#a8d5a2", "#8ccb85", "#70b868", "#55a34d", "#3d8f36", "#2a7a24")
NOTE_WIDTH = 78  # characters to a line of the text block
SVG_PX = 900  # the longer side of the SVG's drawing, in pixels
SVG_PAD_M = 12.0
LABEL_SHARE = 0.012  # text height as a share of the plot's longer side
LABEL_SCALE = 0.6  # a label on the plan is this share of the notes' text height


@dataclass(frozen=True)
class Style:
    aci: int  # DXF colour index
    colour: str  # SVG stroke
    fill: bool = False
    dash: str = ""


BASE_STYLES = {
    "ORIGINAL-SITE": Style(8, "#8a8a8a", dash="6 4"),
    "NET-SITE": Style(6, "#ad2677"),
    "EXCLUSIONS": Style(1, "#c0392b", fill=True),
    "WIDTH-REGIONS": Style(30, "#e08a1e", dash="3 3"),
    "ACCESS-ZONES": Style(5, "#1f6fb2"),
    "RULE-LAYERS": Style(210, "#9b59b6", dash="2 3"),
    "NOTES": Style(7, "#222222"),
}


@dataclass
class Drawing:
    layers: dict[str, Style] = field(default_factory=dict)
    polygons: list[tuple[str, Shape]] = field(default_factory=list)
    paths: list[tuple[str, list[Point]]] = field(default_factory=list)
    labels: list[tuple[str, Point, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)

    @property
    def text_height(self) -> float:
        minx, miny, maxx, maxy = self.bounds
        return max(1.2, LABEL_SHARE * max(maxx - minx, maxy - miny))


def build_drawing(site: CanonicalSiteModel, rules: ResolvedRules,
                  env: BuildableEnvelope) -> Drawing:
    """Everything the drawing shows, on its layers; the envelope must have come from this
    site (a site with no net plot has no envelope)."""
    net = site.net_plot.value
    d = Drawing(layers={name: style for name, style in BASE_STYLES.items()})
    if site.boundary is not None:
        d.polygons.append(("ORIGINAL-SITE", site.boundary))
    d.polygons.append(("NET-SITE", net))
    for item in env.exclusions:
        d.polygons += [("EXCLUSIONS", shape) for shape in item.shapes]
    for number, band in enumerate(b for b in env.bands
                                  if b.modelled and b.setback_m is not None):
        key = _layer_key(band.above_m, band.up_to_m)
        d.layers[f"SETBACK-{key}"] = Style(SETBACK_ACI[number % len(SETBACK_ACI)],
                                           SETBACK_HEX[number % len(SETBACK_HEX)], dash="8 3")
        d.layers[f"BUILDABLE-{key}"] = Style(BUILDABLE_ACI[number % len(BUILDABLE_ACI)],
                                             BUILDABLE_HEX[number % len(BUILDABLE_HEX)],
                                             fill=True)
        d.polygons += [(f"SETBACK-{key}", shape) for shape in band.setback_envelope]
        d.polygons += [(f"BUILDABLE-{key}", shape) for shape in band.buildable]
    _width_regions(d, env)
    for zone in env.circulation.access_zones:
        d.paths.append(("ACCESS-ZONES", list(zone.frontage.points)))
        d.labels.append(("ACCESS-ZONES", zone.frontage.points[len(zone.frontage.points) // 2],
                         f"{zone.id}: {zone.length_m:.0f} m facing {zone.side}"))
    for layer in env.rule_layers.layers:
        for shape in layer.shapes:
            d.polygons.append(("RULE-LAYERS", shape))
            d.labels.append(("RULE-LAYERS", _inside(shape), layer.id))
    d.bounds = (site.boundary or net).to_shapely().union(net.to_shapely()).bounds
    d.labels = _declutter(d.labels, d.text_height * LABEL_SCALE)
    d.notes = notes(site, rules, env)
    return d


def _declutter(labels: list[tuple[str, Point, str]], height: float):
    """Labels that would sit on top of one another (the same region in several bands) are stacked
    downward, one line apart."""
    seen: dict[tuple[int, int], int] = {}
    out = []
    for layer, (x, y), text in labels:
        cell = (round(x / (12 * height)), round(y / (2 * height)))
        stacked = seen.get(cell, 0)
        seen[cell] = stacked + 1
        out.append((layer, (x, y - stacked * 1.2 * height), text))
    return out


def _layer_key(above_m: float, up_to_m: float) -> str:
    """'21-24', or '21' for the band of one height, as the width regions name it."""
    return band_key(above_m, up_to_m).removesuffix(" m")


def _inside(shape: Shape) -> Point:
    point = shape.to_shapely().representative_point()
    return (point.x, point.y)


def _width_regions(d: Drawing, env: BuildableEnvelope) -> None:
    for profile in env.width_profiles:
        name = "WIDTH-REGIONS" if profile.applies_to == NET_PLOT else (
            f"WIDTH-REGIONS-{profile.applies_to.removesuffix(' m')}")
        d.layers.setdefault(name, BASE_STYLES["WIDTH-REGIONS"])
        for region in profile.regions:
            d.polygons.append((name, region.shape))
            d.labels.append((name, _inside(region.shape),
                             f"{region.max_inscribed_width_m:.1f} m wide, "
                             f"{region.area_sqm:,.0f} m2, {region.length_m:.0f} m long"))


def notes(site: CanonicalSiteModel, rules: ResolvedRules, env: BuildableEnvelope) -> list[str]:
    """The text block: the net plot and where it came from, the open-space requirement under
    each reading, the height limits, each band, and the readings still open."""
    plot = site.net_plot
    lines = [f"LEGAL ENVELOPE (debug): {site.name}",
             f"net plot {plot.value.area_sqm:,.0f} m2 [{plot.status}, {plot.source_kind}]"]
    if plot.source_kind == "FIRM_FINISHED_PLAN":
        lines.append("DEBUG ONLY: the net outline comes from the firm's finished plan")
    share = rules.open_space.share.value
    lines += ["", f"OPEN SPACE REQUIRED ({share:.0%} of the site area, over and above the "
              "setbacks), by reading of the area it is taken of:"]
    lines += [f"  {reading}: {area:,.0f} m2"
              for reading, area in rules.open_space.requirement_sqm_by_reading.items()]
    lines += ["", "HEIGHT LIMITS (metres):"]
    lines += textwrap.wrap(f"high-rise: {rules.height.high_rise.eligibility.value}", NOTE_WIDTH,
                           initial_indent="  ", subsequent_indent="      ")
    for limit in rules.height.limits:
        figure = (f"{limit.max_m:g} m" if limit.max_m is not None
                  else limit.bound.value.lower().replace("_", " "))
        when = (f", only if {limit.condition.text} ({limit.applicability.value.lower()})"
                if limit.condition else "")
        lines += textwrap.wrap(f"{limit.measure.value.lower()}: {figure}{when} [{limit.status}]: "
                               f"{limit.reason}", NOTE_WIDTH, initial_indent="  ",
                               subsequent_indent="      ")
    lines += ["", "BANDS (setback, buildable land):"]
    for band in env.bands:
        key = band_key(band.above_m, band.up_to_m)
        if not band.modelled:
            lines.append(f"  {key}: not modelled")
        elif band.setback_m is None:
            lines.append(f"  {key}: {band.permission.value.lower()}")
        else:
            front = ("" if band.front_setback_m is None
                     else f", front {band.front_setback_m:g} m")
            lines.append(f"  {key}: {band.setback_m:g} m{front}, {band.area_sqm:,.0f} m2, "
                         f"{band.permission.value.lower()}")
    open_readings = [f"{i.id} = {i.selected}" for i in rules.interpretations
                     if i.selected == "ALL"]
    if open_readings:
        lines += ["", "OPEN READINGS EVALUATED EVERY WAY: " + ", ".join(open_readings)]
    return lines


# --- DXF -------------------------------------------------------------------------------------


def _rings(shape: Shape) -> list[list[Point]]:
    return [shape.outer, *shape.holes]


def write_debug_dxf(site: CanonicalSiteModel, rules: ResolvedRules, env: BuildableEnvelope,
                    path: str | Path) -> Path:
    d = build_drawing(site, rules, env)
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    for name, style in d.layers.items():
        doc.layers.add(name, color=style.aci)
    msp = doc.modelspace()
    for layer, shape in d.polygons:
        for ring in _rings(shape):
            msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": layer})
    for layer, points in d.paths:
        msp.add_lwpolyline(points, dxfattribs={"layer": layer, "const_width": 0.4})
    height = d.text_height
    for layer, (x, y), text in d.labels:
        msp.add_text(text, height=height * LABEL_SCALE, dxfattribs={"layer": layer}
                     ).set_placement((x, y))
    minx, miny, maxx, maxy = d.bounds
    x, y = maxx + 2 * height, maxy
    for line in d.notes:
        msp.add_text(line or " ", height=height, dxfattribs={"layer": "NOTES"}
                     ).set_placement((x, y))
        y -= 1.7 * height
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    return out


# --- SVG -------------------------------------------------------------------------------------


def write_debug_svg(site: CanonicalSiteModel, rules: ResolvedRules, env: BuildableEnvelope,
                    path: str | Path) -> Path:
    d = build_drawing(site, rules, env)
    minx, miny, maxx, maxy = d.bounds
    scale = SVG_PX / max(maxx - minx + 2 * SVG_PAD_M, maxy - miny + 2 * SVG_PAD_M)
    notes_top = (maxy - miny + 2 * SVG_PAD_M) * scale + 10
    width = (maxx - minx + 2 * SVG_PAD_M) * scale
    height = notes_top + 16 * (len(d.notes) + 1)

    def xy(point: Point) -> tuple[float, float]:
        x, y = point
        return (x - minx + SVG_PAD_M) * scale, (maxy - y + SVG_PAD_M) * scale

    def px(point: Point) -> str:
        return "{:.1f},{:.1f}".format(*xy(point))

    def outline(shape: Shape, style: Style) -> str:
        data = " ".join("M " + " L ".join(px(p) for p in ring) + " Z" for ring in _rings(shape))
        fill = f'fill="{style.colour}" fill-opacity="0.22"' if style.fill else 'fill="none"'
        dash = f' stroke-dasharray="{style.dash}"' if style.dash else ""
        return (f'<path d="{data}" fill-rule="evenodd" {fill} stroke="{style.colour}" '
                f'stroke-width="1.2"{dash}/>')

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
             f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="Helvetica, Arial, sans-serif">',
             '<rect width="100%" height="100%" fill="#fbfbf8"/>']
    for name, style in d.layers.items():
        if name == "NOTES":
            continue
        parts.append(f'<g id="{name}">')
        parts += [outline(shape, style) for layer, shape in d.polygons if layer == name]
        parts += [f'<polyline points="{" ".join(px(p) for p in points)}" fill="none" '
                  f'stroke="{style.colour}" stroke-width="3"/>'
                  for layer, points in d.paths if layer == name]
        parts += [f'<text x="{xy(at)[0]:.1f}" y="{xy(at)[1]:.1f}" font-size="9" '
                  f'text-anchor="middle" fill="{style.colour}">{escape(text)}</text>'
                  for layer, at, text in d.labels if layer == name]
        parts.append("</g>")
    parts.append('<g id="NOTES">')
    for i, line in enumerate(d.notes):
        parts.append(f'<text x="14" y="{notes_top + 16 * (i + 1):.0f}" font-size="12" '
                     f'xml:space="preserve">{escape(line)}</text>')
    parts += ["</g>", "</svg>"]
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts))
    return out
