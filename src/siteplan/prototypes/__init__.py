"""Tower prototypes: reusable buildings the optimizer places, instead of arbitrary rectangles.

A prototype (contracts/prototype.py) is one typical floor of a building in its own frame. This
package makes them and keeps them:

- `compose`: a kit of four families (about 4, 6, 8 and 12 flats a floor) composed from a flat
  library, its flats chosen for the unit mix. A kit from the engine's example flats is
  ENGINE_DEFAULT; one from the firm's own library at run time is FIRM_STANDARD.
- `library`: the kit as a JSON file (a list of prototypes), and the checks a file must pass.
- `draw`: each prototype as a DXF block, placed the way a `PlacedTower` places it.
- `legacy`: a tower the prototype generator laid, as a LEGACY_RECTANGLE prototype, so the
  characterization baseline runs through the same interface.

Make the example library from the example flats (a test fails if the committed file drifts):

    uv run python -m siteplan.prototypes examples/flat_library.example.json \\
        --mix 2BHK=0.7,3BHK=0.3 --out examples/prototypes.example.json

Compose the firm's own library the same way, with `--source-kind FIRM_STANDARD`; `--dxf` also
writes the blocks to open in ZWCAD. The package imports nothing from the generator: the
generator imports it.
"""

from siteplan.prototypes.compose import (
    FAMILY_PLANS,
    compose_library,
    compose_prototype,
    servable_families,
)
from siteplan.prototypes.draw import (
    add_block,
    add_blocks,
    block_name,
    insert_tower,
    new_drawing,
    write_library_dxf,
)
from siteplan.prototypes.legacy import legacy_tower
from siteplan.prototypes.library import (
    dumps,
    effective_heights,
    load_library,
    problems,
    save_library,
)

__all__ = ["FAMILY_PLANS", "add_block", "add_blocks", "block_name", "compose_library",
           "compose_prototype", "dumps", "effective_heights", "insert_tower", "legacy_tower",
           "load_library", "new_drawing", "problems", "save_library", "servable_families",
           "write_library_dxf"]
