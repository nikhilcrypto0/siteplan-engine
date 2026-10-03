"""Prototypes as DXF blocks, to open in ZWCAD and to place the way the optimizer places them.

Each prototype is one block in metres (ezdxf R2018), drawn in its own frame: the footprint, every
flat, every core and the corridor, each kind on its own PROTO-* layer so the firm can switch one
off, and the flat types written on PROTO-LABELS. A block reference carries the placement of a
`PlacedTower`: a negative x scale mirrors (x -> -x) before the rotation, which turns the block
anticlockwise about its origin, and the insertion point moves it, which is exactly
`PlacedTower.world`. So a placed block and the candidate's own footprint are the same ground.

The layer names are ours. Whether the BuildNow plugin reads blocks, or wants its own layer names
inside them, is untested (it needs Windows, ZWCAD 2025 and the plugin).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.entities import Insert
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts import BaseLayout, BlockLayout

from siteplan.contracts.candidate import PlacedTower
from siteplan.contracts.common import Shape
from siteplan.contracts.prototype import TowerPrototype

BLOCK_PREFIX = "PROTO-"
FOOTPRINT, FLATS, CORES = "PROTO-FOOTPRINT", "PROTO-FLATS", "PROTO-CORES"
CORRIDOR, LABELS, TOWERS = "PROTO-CORRIDOR", "PROTO-LABELS", "PROTO-TOWERS"  # TOWERS: references
LAYERS = {FOOTPRINT: 7, FLATS: 3, CORES: 8, CORRIDOR: 9, LABELS: 7, TOWERS: 7}  # AutoCAD colours
LABEL_HEIGHT_M = 0.8
LIBRARY_GAP_M = 10.0  # between blocks in a library drawing
NOT_A_NAME = re.compile(r"[^A-Za-z0-9_.-]")


def block_name(prototype_id: str) -> str:
    """The DXF block a prototype is drawn as."""
    return BLOCK_PREFIX + NOT_A_NAME.sub("_", prototype_id)


def new_drawing() -> Drawing:
    """An empty drawing in metres with the prototype layers."""
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    for name, colour in LAYERS.items():
        doc.layers.add(name, color=colour)
    return doc


def add_block(doc: Drawing, prototype: TowerPrototype) -> str:
    """Draw one prototype as a block of the drawing; returns the block's name."""
    name = block_name(prototype.id)
    if name in doc.blocks:
        raise ValueError(f"the drawing already has a block {name}")
    block = doc.blocks.new(name)
    _outline(block, prototype.footprint, FOOTPRINT)
    for module in prototype.modules:
        _outline(block, module.shape, FLATS)
        _label(block, module.type_id, module.shape)
    for zone in prototype.core_zones:
        _outline(block, zone.shape, CORES)
        _label(block, "CORE", zone.shape)
    for piece in prototype.corridor:
        _outline(block, piece, CORRIDOR)
    return name


def add_blocks(doc: Drawing, prototypes: Iterable[TowerPrototype]) -> dict[str, str]:
    """A block for each prototype; returns each prototype id's block name. Two prototypes may
    not share an id: the second would be drawn as the first."""
    return {prototype.id: add_block(doc, prototype) for prototype in prototypes}


def insert_tower(layout: BaseLayout, tower: PlacedTower) -> Insert:
    """A placed tower as a reference to its prototype's block, placed as the tower is."""
    name = block_name(tower.prototype_id)
    if name not in layout.doc.blocks:
        raise ValueError(f"tower {tower.name}: the drawing has no block {name}; add_block first")
    return layout.add_blockref(name, (tower.x, tower.y), dxfattribs={
        "rotation": tower.rotation_deg, "xscale": -1.0 if tower.mirrored else 1.0,
        "layer": TOWERS})


def write_library_dxf(prototypes: list[TowerPrototype], path: str | Path) -> Path:
    """A drawing of the library: every prototype as a block, one of each side by side."""
    doc = new_drawing()
    names = add_blocks(doc, prototypes)
    msp = doc.modelspace()
    cursor = 0.0
    for prototype in prototypes:
        centre = cursor + prototype.length_m / 2
        msp.add_blockref(names[prototype.id], (centre, 0.0), dxfattribs={"layer": TOWERS})
        words = (f"{prototype.id}: {prototype.family.value}, {prototype.per_floor.flats} flats "
                 f"a floor, {prototype.cores} cores, {prototype.length_m:g} x "
                 f"{prototype.depth_m:g} m")
        msp.add_text(words, height=2 * LABEL_HEIGHT_M, dxfattribs={"layer": LABELS}).set_placement(
            (cursor, prototype.depth_m / 2 + 2.0))
        cursor += prototype.length_m + LIBRARY_GAP_M
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    return out


def _outline(block: BlockLayout, shape: Shape, layer: str) -> None:
    for ring in (shape.outer, *shape.holes):
        block.add_lwpolyline(ring, close=True, dxfattribs={"layer": layer})


def _label(block: BlockLayout, text: str, shape: Shape) -> None:
    centre = shape.to_shapely().representative_point()
    block.add_text(text, height=LABEL_HEIGHT_M, dxfattribs={"layer": LABELS}).set_placement(
        (centre.x, centre.y), align=TextEntityAlignment.MIDDLE_CENTER)
