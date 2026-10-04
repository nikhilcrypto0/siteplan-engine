"""Shared by the prototype tests: the example kit, and a tower placed as the contract says.

Made-up flats only: the kit is composed from examples/flat_library.example.json.
"""

from pathlib import Path

from shapely.geometry import Polygon

from siteplan.contracts import TowerPrototype
from siteplan.contracts.candidate import PlacedTower
from siteplan.contracts.common import Shape
from siteplan.library import FlatLibrary
from siteplan.prototypes import compose_library

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples"
EXAMPLE_FLATS = EXAMPLES / "flat_library.example.json"
MIX = {"2BHK": 0.7, "3BHK": 0.3}


def example_library() -> FlatLibrary:
    return FlatLibrary.model_validate_json(EXAMPLE_FLATS.read_text())


def example_kit() -> list[TowerPrototype]:
    return compose_library(example_library(), MIX)


def place(prototype: TowerPrototype, x: float = 0.0, y: float = 0.0, rotation: float = 0.0,
          mirrored: bool = False) -> PlacedTower:
    """The prototype placed: mirrored (x -> -x) if asked, turned anticlockwise about its origin,
    then moved to (x, y); its footprint is whatever that makes of the prototype's own."""
    tower = PlacedTower(name="T1", prototype_id=prototype.id, x=x, y=y, rotation_deg=rotation,
                        mirrored=mirrored, floors_above_stilt=1, footprint=prototype.footprint)
    return tower.model_copy(update={
        "footprint": Shape.from_shapely(tower.world(prototype.footprint.to_shapely()))})


def parts(prototype: TowerPrototype) -> list[Polygon]:
    """Every flat, core and corridor piece of a prototype, in its own frame."""
    shapes = (*(m.shape for m in prototype.modules), *(z.shape for z in prototype.core_zones),
              *prototype.corridor)
    return [s.to_shapely() for s in shapes]
