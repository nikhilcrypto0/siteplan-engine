"""A tower the prototype generator laid, as a LEGACY_RECTANGLE prototype and its placement.

Today's generator draws every tower on the site, already turned and moved. To run it through the
prototype interface, each becomes its own prototype in its own frame (centred on the origin, long
side along x) with the placement that puts it back where it stood, so a placed legacy prototype
is the generator's footprint, flat for flat and core for core. The tower is read by its
attributes, not imported: the generator depends on the prototypes, never the other way round.
"""

from __future__ import annotations

import math
from typing import Protocol

import shapely
from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts.candidate import PlacedTower
from siteplan.contracts.common import Shape, SourceKind, shapes_from
from siteplan.contracts.prototype import PrototypeFamily, TowerPrototype
from siteplan.library import FlatType
from siteplan.prototypes.library import SLIVER_SQM

# A tower was turned to the site's angle in floating point, so its flats and cores share edges
# only to about 1e-13 m. Overlaying them as they are leaves zero-width spikes in the corridor, a
# ring that is valid on the site and not once it is turned back. In the prototype's own frame
# the tower runs along the axes, so snapping to a micrometre makes shared edges one edge.
SNAP_M = 1e-6


class LegacyTower(Protocol):
    """What of a towers.Tower this module reads."""

    name: str
    footprint: Polygon
    flats_per_side: tuple[FlatType, ...]  # one side; the other mirrors it
    flat_outlines: tuple[Polygon, ...]  # two a flat, one each side of the corridor
    cores: tuple[Polygon, ...]
    length_m: float
    width_m: float

    def saleable_sqft_per_floor(self) -> float: ...


def legacy_tower(tower: LegacyTower, floors: int, prototype_id: str,
                 library_note: str = "") -> tuple[TowerPrototype, PlacedTower]:
    """A legacy tower as its own prototype, and the placement that puts it where it stood."""
    cx, cy, angle = _frame(tower.footprint)

    def moved(geometry: BaseGeometry) -> BaseGeometry:
        """From the site into the prototype's frame."""
        return affinity.rotate(affinity.translate(geometry, -cx, -cy), -angle, origin=(0, 0))

    outlines = tower.flat_outlines
    if len(outlines) != 2 * len(tower.flats_per_side):
        raise ValueError(f"{tower.name}: {len(outlines)} flat outlines for "
                         f"{len(tower.flats_per_side)} flats a side")
    modules = [{"id": f"{tower.name}-{i + 1}", "type_id": flat.name, "category": flat.bhk,
                "shape": Shape.from_shapely(moved(outlines[i])),
                "saleable_sqft": flat.saleable_sqft, "carpet_sqft": flat.carpet_sqft,
                "built_up_sqft": flat.built_up_sqft}
               for i, flat in ((i, tower.flats_per_side[i // 2]) for i in range(len(outlines)))]
    own = sum(o.area for o in outlines)
    by_type: dict[str, int] = {}
    for module in modules:
        by_type[module["category"]] = by_type.get(module["category"], 0) + 1
    prototype = TowerPrototype(
        id=prototype_id, family=PrototypeFamily.LEGACY_RECTANGLE,
        source_kind=SourceKind.ENGINE_DEFAULT,
        source=f"prototype generator; flats from the library ({library_note})".strip(),
        footprint=Shape.from_shapely(moved(tower.footprint)), length_m=tower.length_m,
        depth_m=tower.width_m, cores=len(tower.cores), modules=modules,
        core_zones=[{"shape": Shape.from_shapely(moved(c))} for c in tower.cores],
        corridor=_corridor(moved(tower.footprint),
                           [moved(p) for p in (*outlines, *tower.cores)]),
        per_floor={"flats": len(modules), "flats_by_type": by_type,
                   "gross_floor_sqm": tower.footprint.area, "flats_own_sqm": own,
                   "common_core_sqm": tower.footprint.area - own,
                   "saleable_sqft": tower.saleable_sqft_per_floor()})
    placed = PlacedTower(name=tower.name, prototype_id=prototype_id, x=cx, y=cy,
                         rotation_deg=angle, floors_above_stilt=floors,
                         footprint=Shape.from_shapely(tower.footprint))
    return prototype, placed


def _corridor(footprint: BaseGeometry, occupied: list[BaseGeometry]) -> list[Shape]:
    """What the flats and cores leave of the floor, as clean pieces; all in the prototype's
    frame."""
    snapped = [shapely.set_precision(g, SNAP_M) for g in occupied]
    left = shapely.set_precision(footprint, SNAP_M).difference(unary_union(snapped))
    return [s for s in shapes_from(left) if s.area_sqm > SLIVER_SQM]


def _frame(footprint: Polygon) -> tuple[float, float, float]:
    """The centre of a rectangular footprint and the direction of its long side, degrees."""
    corners = [c[:2] for c in footprint.exterior.coords]
    (x0, y0), (x1, y1), (x2, y2) = corners[0], corners[1], corners[2]
    if math.dist((x0, y0), (x1, y1)) >= math.dist((x1, y1), (x2, y2)):
        angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
    else:
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
    return footprint.centroid.x, footprint.centroid.y, angle
