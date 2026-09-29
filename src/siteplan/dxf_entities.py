"""What a DXF drawing shows, in world coordinates, and the unit it declares.

A DWG keeps everything in one world coordinate system at real size, and says in its header what
one unit is ($INSUNITS). Repeated items (a flat, a tree, a tower, sometimes the plot outline) are
blocks, each placed by its own position, scale and rotation, so what is drawn inside a block only
lands in the world once that placement is applied: a reader that takes model space as it is
sees none of it. Positions must be read in world terms too, because a mirrored block turns its
contents' own coordinate system over, and a text read from its raw insertion point then lands on
the wrong side of the drawing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import ezdxf
from ezdxf.document import Drawing
from ezdxf.entities import DXFEntity
from ezdxf.math import Vec3

# $INSUNITS code -> metres per drawing unit (0 means "unitless").
METRES_PER_UNIT = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
TEXT_TYPES = frozenset({"TEXT", "MTEXT", "ATTRIB"})


def declared_metres_per_unit(doc: Drawing) -> float | None:
    """What one drawing unit is, from the file's own header; None when it does not say."""
    return METRES_PER_UNIT.get(doc.header.get("$INSUNITS", 0))


@dataclass(frozen=True)
class Drawn:
    entity: DXFEntity
    layer: str  # the layer CAD shows it on: a block's layer-0 contents take the block's layer


@dataclass(frozen=True)
class Opened:
    drawn: tuple[Drawn, ...]
    missing_blocks: tuple[str, ...]  # referenced but not defined in the file
    skipped: int  # pieces the block's placement could not carry (e.g. text scaled unevenly)


def open_blocks(entities: Iterable[DXFEntity]) -> Opened:
    """Every entity, with each block reference opened out (nested ones too) and its contents
    moved into world coordinates by the block's placement."""
    drawn: list[Drawn] = []
    missing: list[str] = []
    skipped = [0]

    def count(_entity, _reason) -> None:
        skipped[0] += 1

    def walk(items: Iterable[DXFEntity], parent_layer: str | None) -> None:
        for entity in items:
            layer = entity.dxf.get("layer", "0")
            if parent_layer is not None and layer == "0":
                layer = parent_layer
            if entity.dxftype() != "INSERT":
                drawn.append(Drawn(entity, layer))
                continue
            for attrib in entity.attribs:
                own = attrib.dxf.get("layer", "0")
                drawn.append(Drawn(attrib, layer if own == "0" else own))
            try:
                contents = list(entity.virtual_entities(skipped_entity_callback=count))
            except ezdxf.DXFStructureError:
                missing.append(entity.dxf.name)
                continue
            walk(contents, layer)

    walk(entities, None)
    return Opened(tuple(drawn), tuple(sorted(set(missing))), skipped[0])


def text_of(entity: DXFEntity) -> str:
    raw = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
    return " ".join(str(raw).split())


def text_position(entity: DXFEntity) -> tuple[float, float] | None:
    """Where a text sits in world coordinates. MTEXT stores that directly; TEXT and ATTRIB
    store it in their own coordinate system, which a mirrored block turns over."""
    point = entity.dxf.get("insert", None)
    if point is None:
        return None
    if entity.dxftype() == "MTEXT":
        return float(point[0]), float(point[1])
    world = entity.ocs().to_wcs(Vec3(point))
    return world.x, world.y


def polyline_points(entity: DXFEntity) -> list[tuple[float, float]]:
    """A polyline's vertices in world coordinates, whatever way it has been mirrored."""
    if entity.dxftype() == "LWPOLYLINE":
        return [(v.x, v.y) for v in entity.vertices_in_wcs()]
    return [(v.x, v.y) for v in entity.points_in_wcs()]


def has_arcs(entity: DXFEntity) -> bool:
    if entity.dxftype() == "LWPOLYLINE":
        return any(bulge for *_, bulge in entity.get_points("xyb"))
    return any(v.dxf.bulge for v in entity.vertices)


def is_closed(entity: DXFEntity) -> bool:
    return bool(entity.closed if entity.dxftype() == "LWPOLYLINE" else entity.is_closed)
