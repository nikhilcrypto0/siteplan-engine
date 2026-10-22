"""Where the net plot meets the access road, and the access zones where a gate may open.

Where the survey draws the road, the site model carries the stretches of the surveyed boundary
it reaches (`site.access.frontage`, step 1's reading), and the frontage is the net plot's edge
there (`geometry.road_meets`, which the validator measures the same way): an entrance opens onto
the road, never onto an edge that only faces the road's side (2026-10-21: Suchitra's R2 meets
the plot at one notch, and the gate went 80 m away to an edge no road touches). Where nothing
draws it, the project's side is all there is, and the frontage is the straight runs of the net
plot's boundary facing that side as `geometry.faces` reads it (within 45 degrees, a diagonal
label half a compass step more). An access zone is that frontage less any statutory exclusion (a
gate cannot open into a water buffer). Nothing here draws a road or a gate.
"""

from __future__ import annotations

from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import linemerge

from siteplan.contracts.common import Line
from siteplan.contracts.envelope import AccessZone
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.geometry import faces, facing_deg, road_meets, straight_runs

MIN_ZONE_M = 0.5  # a shorter stretch is drawing noise, not frontage
ROAD_MEETS_M = 1.0  # the net edge this near where the road's drawn ground reaches the plot meets it


def front_runs(net: Polygon, side: str | None) -> list[LineString]:
    """The straight stretches of the net plot's boundary facing the access side; none when the
    side is not known."""
    if side is None:
        return []
    return [run.line for run in straight_runs(net) if faces(facing_deg(net, run), side)]


def access_zones(site: CanonicalSiteModel, net: Polygon, excluded) -> list[AccessZone]:
    """One zone per unbroken stretch of frontage, less the exclusions; when the project pins the
    entrance (`site.access.gate`), that stretch alone, so no layout moves it."""
    side = site.access.side.value
    gate = site.access.gate
    if gate is not None:
        line = LineString(gate.value.points)
        return [AccessZone(id="access-gate", road_id=site.access.road_id.value, side=side,
                           frontage=gate.value, length_m=line.length,
                           note=f"the entrance the project pins ({gate.source}, "
                                f"{gate.status.value}): the main approach comes in here only")]
    met = site.access.frontage
    if met is not None:
        gross = site.boundary.to_shapely() if site.boundary is not None else None
        runs = road_meets(net, gross, [LineString(line.points) for line in met.value],
                          ROAD_MEETS_M)
    else:
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
                       note=(f"where the access road meets the net plot ({met.source}), less "
                             "any statutory exclusion") if met is not None else
                            f"the net plot's frontage facing {side}, where the access road "
                            "runs, less any statutory exclusion")
            for i, line in enumerate(pieces, 1)]
