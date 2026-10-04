"""The land as the search sees it: where the blocks, the roads and the open space may stand.

Three kinds of ground are told apart, each from the rules and nothing else:

- the setback zone, as deep as the deepest block a configuration allows (Table IV: the deepest
  setback decides it for the whole plot, because the validator measures the zone from the deepest
  block);
- the planted strip along the boundary, where that setback reaches the width the rule names;
- the roadable ground, which is the plot without the statutory exclusions (a water buffer), the
  strip and, when roads may not use the setback, the setback zone.

The cluster land is where blocks and their streets may stand: the roadable ground less the width of
the ring road that has to run round them. It is worked out for the configuration, never fixed for
the plot, because the ring follows the blocks that are placed.

Everything is in the survey's frame. A mitre join is used throughout: it is the validator's
convention for the setback and the strip, and it is the stricter at a reflex corner.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts import BuildableEnvelope, CanonicalSiteModel
from siteplan.geometry import opening

EMPTY = Polygon()


def erode(geometry: BaseGeometry, distance_m: float) -> BaseGeometry:
    """The geometry shrunk by a distance, corners kept square."""
    return geometry.buffer(-distance_m, join_style="mitre") if distance_m > 0 else geometry


def grow(geometry: BaseGeometry, distance_m: float) -> BaseGeometry:
    return geometry.buffer(distance_m, join_style="mitre") if distance_m > 0 else geometry


def polygons(geometry: BaseGeometry | None, min_sqm: float = 0.0) -> list[Polygon]:
    """The polygons of a geometry (a polygon, a multipolygon, a collection), none smaller than
    `min_sqm`."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry] if geometry.area > min_sqm else []
    return [p for part in getattr(geometry, "geoms", ()) for p in polygons(part, min_sqm)]


@dataclass(frozen=True)
class Plot:
    """The net plot and what the envelope fixes on it: the exclusions no block, road or building
    may stand on, and the stretches of boundary a gate may open in."""

    net: Polygon
    excluded: BaseGeometry
    gate_runs: tuple[LineString, ...]
    access_side: str | None

    @property
    def minimum_inset_m(self) -> float:
        return 0.0


def plot_of(site: CanonicalSiteModel, envelope: BuildableEnvelope) -> Plot:
    net = site.net_plot.value.to_shapely()
    excluded = unary_union([shape.to_shapely() for item in envelope.exclusions
                            for shape in item.shapes]) if envelope.exclusions else EMPTY
    runs = tuple(zone.frontage.to_shapely() for zone in envelope.circulation.access_zones)
    return Plot(net, excluded.intersection(net) if not excluded.is_empty else EMPTY, runs,
                site.access.side.value)


@dataclass(frozen=True)
class Land:
    zone: BaseGeometry  # the setback zone: nothing but the planted strip and the gate in it
    strip: BaseGeometry  # the planted strip the rules ask for, or empty
    roadable: BaseGeometry  # where a road or a fire lane may run
    cluster_land: BaseGeometry  # where blocks and their streets may stand, the ring road fitting
    # round them
    interior: BaseGeometry  # the plot beyond the setback zone: where open space and buildings stand


def make_land(plot: Plot, *, zone_depth_m: float, strip_width_m: float, ring_width_m: float,
              roads_may_use_setback: bool, kept_clear: BaseGeometry | None = None) -> Land:
    """The ground of one configuration. `kept_clear` is ground a configuration keeps for something
    else (the open space reserved at one end of the plot): no road runs on it, so the blocks stand
    a ring road's width away from it."""
    net = plot.net
    interior = erode(net, zone_depth_m)
    zone = net.difference(interior)
    strip = net.difference(erode(net, strip_width_m)) if strip_width_m > 0 else EMPTY
    taken = [plot.excluded, strip, kept_clear if kept_clear is not None else EMPTY]
    if not roads_may_use_setback:
        taken.append(zone)
    roadable = net.difference(unary_union([g for g in taken if not g.is_empty])) \
        if any(not g.is_empty for g in taken) else net
    return Land(zone, strip, roadable, erode(roadable, ring_width_m), interior)


def reserve_end(interior_turned: BaseGeometry, side: str, target_sqm: float, min_width_m: float
                ) -> BaseGeometry | None:
    """The ground to keep at one end of the plot for the open space, the club house and the ramp, in
    the turned frame: the half-plane beyond a cut across (`N`, `S`: across the columns' length;
    `E`, `W`: across the columns), as small as holds `target_sqm` of ground at least `min_width_m`
    wide beyond the setback zone. None when even the whole plot does not."""
    minx, miny, maxx, maxy = interior_turned.bounds
    pad = 10.0
    axis_low, axis_high = (miny, maxy) if side in "NS" else (minx, maxx)

    def region(cut: float) -> Polygon:
        if side == "N":
            return Polygon([(minx - pad, cut), (maxx + pad, cut), (maxx + pad, maxy + pad),
                            (minx - pad, maxy + pad)])
        if side == "S":
            return Polygon([(minx - pad, miny - pad), (maxx + pad, miny - pad), (maxx + pad, cut),
                            (minx - pad, cut)])
        if side == "E":
            return Polygon([(cut, miny - pad), (maxx + pad, miny - pad), (maxx + pad, maxy + pad),
                            (cut, maxy + pad)])
        return Polygon([(minx - pad, miny - pad), (cut, miny - pad), (cut, maxy + pad),
                        (minx - pad, maxy + pad)])

    def usable(cut: float) -> float:
        return opening(interior_turned.intersection(region(cut)), min_width_m).area

    grows_with_cut = side in "SW"  # the region grows as the cut moves up
    far, near = (axis_high, axis_low) if grows_with_cut else (axis_low, axis_high)
    if usable(far) < target_sqm:
        return None
    low, high = near, far  # `near` holds nothing, `far` holds the most
    for _ in range(40):
        middle = (low + high) / 2
        low, high = (middle, high) if usable(middle) < target_sqm else (low, middle)
        if abs(high - low) < 0.05:
            break
    return region(high)
