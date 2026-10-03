"""The land as the site model gives it: the net plot and the water that must be kept clear.

Everything is rebuilt from the site model and the rules, never taken from what the candidate or
an envelope says about them. A site whose net plot is not known has no geometry to judge on, and
the validator refuses to certify it (validate.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel, Water
from siteplan.validator.shapes import mended


@dataclass(frozen=True)
class WaterZone:
    """One water body and the land round it that no building may stand on (rule 3(a)(ii))."""

    id: str
    water_class: str
    buffer_m: float | None  # None when the rules give no buffer for its class
    keep_out: BaseGeometry  # the buffer round its lines and any channel they close
    drawn: bool  # False when the site model holds no line or channel for it


@dataclass(frozen=True)
class SiteGeometry:
    net: Polygon
    water: tuple[WaterZone, ...]

    @property
    def keep_out(self) -> BaseGeometry:
        """All water buffers together, unclipped."""
        return unary_union([z.keep_out for z in self.water if not z.keep_out.is_empty])

    @property
    def keep_out_on_site(self) -> BaseGeometry:
        return self.keep_out.intersection(self.net)

    @property
    def undrawn_water(self) -> tuple[WaterZone, ...]:
        return tuple(z for z in self.water if not z.drawn or z.buffer_m is None)


def net_plot_of(site: CanonicalSiteModel) -> Polygon | None:
    """The net plot outline as a shapely polygon; None while the site model has none, or has one
    that nothing can be measured on (it crosses itself, or encloses no ground)."""
    if site.net_plot is None:
        return None
    outline = site.net_plot.value.to_shapely()
    return outline if outline.is_valid and outline.area > 0 else None


def build(site: CanonicalSiteModel, rules: ResolvedRules) -> SiteGeometry | None:
    net = net_plot_of(site)
    if net is None:
        return None
    return SiteGeometry(net=net, water=tuple(_zone(w, rules) for w in site.water))


def _zone(water: Water, rules: ResolvedRules) -> WaterZone:
    widths = rules.water.buffer_m_by_class.value
    width = widths.get(water.water_class.value)
    lines = [LineString(line.points) for line in water.lines]
    channel = [mended(shape.to_shapely())[0] for shape in water.channel]
    if width is None or not (lines or channel):
        return WaterZone(water.id, water.water_class.value, width, Polygon(), False)
    drawn = unary_union(lines) if lines else None
    closed = list(polygonize(drawn)) if drawn is not None else []
    parts = [drawn.buffer(width)] if drawn is not None else []
    parts += [c.buffer(width) for c in channel] + closed
    return WaterZone(water.id, water.water_class.value, width, unary_union(parts), True)
