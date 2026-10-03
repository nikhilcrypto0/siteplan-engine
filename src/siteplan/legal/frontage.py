"""Where the net plot faces the access road: the stretches of its boundary that face the side the
road runs along, and the access zones where a gate may open.

The survey gives the road's side and width but not the edge it runs beside, so the frontage is
the straight runs of the net plot's boundary that face that side within 45 degrees, the same
reading the entrance uses. An access zone is that frontage less any statutory exclusion (a gate
cannot open into a water buffer). Nothing here draws a road or a gate.
"""

from __future__ import annotations

from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import linemerge

from siteplan.contracts.common import Line
from siteplan.contracts.envelope import AccessZone
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.geometry import COMPASS_DEG, Run, facing_deg, straight_runs

FACING_TOLERANCE_DEG = 45.0  # a run faces a compass side within this
MIN_ZONE_M = 0.5  # a shorter stretch is drawing noise, not frontage


def _faces(net: Polygon, run: Run, side: str) -> bool:
    gap = (facing_deg(net, run) - COMPASS_DEG[side] + 180) % 360 - 180
    return abs(gap) < FACING_TOLERANCE_DEG


def front_runs(net: Polygon, side: str | None) -> list[LineString]:
    """The straight stretches of the net plot's boundary facing the access side; none when the
    side is not known."""
    if side is None:
        return []
    return [run.line for run in straight_runs(net) if _faces(net, run, side)]


def access_zones(site: CanonicalSiteModel, net: Polygon, excluded) -> list[AccessZone]:
    """One zone per unbroken stretch of frontage, less the exclusions."""
    side = site.access.side.value
    runs = front_runs(net, side)
    if not runs:
        return []
    frontage = linemerge(MultiLineString(runs)) if len(runs) > 1 else runs[0]
    if excluded is not None:
        frontage = frontage.difference(excluded)
    pieces = [g for g in getattr(frontage, "geoms", [frontage])
              if g.geom_type == "LineString" and g.length >= MIN_ZONE_M]
    road_id = site.access.road_id.value
    return [AccessZone(id=f"access-{i}", road_id=road_id, side=side,
                       frontage=Line(points=list(line.coords)), length_m=line.length,
                       note=f"the net plot's frontage facing {side}, where the access road "
                            "runs, less any statutory exclusion")
            for i, line in enumerate(pieces, 1)]
