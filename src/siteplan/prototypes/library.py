"""A prototype library: a JSON list of TowerPrototype, and what a file must pass to enter it.

The contract (contracts/prototype.py) already refuses a prototype whose per-floor numbers do not
agree with its modules. What it cannot see is the drawing: a file written by hand, the firm's own
building types, can have a flat standing outside the footprint, two flats on one another, a block
off its frame, or a corridor that is not what the flats and cores leave of the floor. `problems`
finds those, and the loader refuses a file that has any, naming each, rather than give the
optimizer a building that does not close.
"""

from __future__ import annotations

import json
import re
from itertools import combinations
from pathlib import Path

from pydantic import ValidationError
from shapely.geometry import Polygon

from siteplan.contracts.prototype import TowerPrototype

PROTOTYPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # also a DXF block's name (draw.py)
BALANCE_TOLERANCE = 0.02  # share of the footprint the flats, cores and corridor may miss by
SLIVER_SQM = 0.01  # an overhang or an overlap this small is drawing noise
FRAME_TOLERANCE_M = 0.01  # how far a centre may sit from the origin, or a size from what is stated
PAIR = re.compile(r"\[\s+(-?[0-9][0-9.eE+-]*),\s+(-?[0-9][0-9.eE+-]*)\s+\]")


def problems(prototype: TowerPrototype) -> list[str]:
    """Everything wrong with how a prototype is drawn; empty when it closes."""
    found = []
    if not PROTOTYPE_ID.fullmatch(prototype.id):
        found.append(f"id {prototype.id!r} may use letters, digits, '.', '_' and '-' only")
    footprint = prototype.footprint.to_shapely()
    parts = [(f"module {m.id}", m.shape.to_shapely()) for m in prototype.modules]
    parts += [(f"core {i}", z.shape.to_shapely()) for i, z in enumerate(prototype.core_zones, 1)]
    parts += [(f"corridor piece {i}", s.to_shapely()) for i, s in enumerate(prototype.corridor, 1)]
    unclosed = [name for name, shape in [("footprint", footprint), *parts] if not shape.is_valid]
    if unclosed or footprint.area <= 0:
        return [*found, f"not a valid polygon: {', '.join(unclosed) or 'footprint'}"]
    found += _frame_problems(prototype, footprint)
    found += _balance_problems(footprint, parts)
    found += [f"{name} stands outside the footprint" for name, shape in parts
              if shape.difference(footprint).area > SLIVER_SQM]
    found += [f"{a} and {b} overlap" for (a, one), (b, two) in combinations(parts, 2)
              if one.intersection(two).area > SLIVER_SQM]
    stretch = prototype.stretch
    if stretch is not None and stretch.min_modules > stretch.max_modules:
        found.append(f"stretch runs from {stretch.min_modules} modules down to "
                     f"{stretch.max_modules}")
    return found


def _frame_problems(prototype: TowerPrototype, footprint: Polygon) -> list[str]:
    """The prototype's own frame: centred on the origin, long axis along x, size as stated."""
    minx, miny, maxx, maxy = footprint.bounds
    length, depth = maxx - minx, maxy - miny
    found = []
    centre = ((minx + maxx) / 2, (miny + maxy) / 2)
    if max(abs(centre[0]), abs(centre[1])) > FRAME_TOLERANCE_M:
        found.append(f"the footprint is not centred on the origin (its centre is at "
                     f"({centre[0]:.3f}, {centre[1]:.3f}))")
    if depth > length + FRAME_TOLERANCE_M:
        found.append(f"the long axis is not along x ({length:.2f} m along x, {depth:.2f} m "
                     "along y)")
    if (abs(length - prototype.length_m) > FRAME_TOLERANCE_M
            or abs(depth - prototype.depth_m) > FRAME_TOLERANCE_M):
        found.append(f"length_m x depth_m say {prototype.length_m:g} x {prototype.depth_m:g} m; "
                     f"the footprint measures {length:.3f} x {depth:.3f} m")
    return found


def _balance_problems(footprint: Polygon, parts: list[tuple[str, Polygon]]) -> list[str]:
    drawn = sum(shape.area for _, shape in parts)
    if abs(footprint.area - drawn) > BALANCE_TOLERANCE * footprint.area:
        return [f"the footprint is {footprint.area:.2f} m² but its flats, cores and corridor "
                f"add up to {drawn:.2f} m² (more than {BALANCE_TOLERANCE:.0%} apart)"]
    return []


def effective_heights(prototype: TowerPrototype, *, stilt_height_m: float,
                      floor_to_floor_m: float) -> tuple[float, float]:
    """The stilt and floor-to-floor heights a placed tower is built to: the prototype's own
    where its design sets them, else the brief's firm standards."""
    own = prototype.heights
    return (stilt_height_m if own.stilt_height_m is None else own.stilt_height_m,
            floor_to_floor_m if own.floor_to_floor_m is None else own.floor_to_floor_m)


def dumps(prototypes: list[TowerPrototype]) -> str:
    """A library as the text of its file: JSON, a coordinate on one line, so a block of a dozen
    flats stays readable."""
    text = json.dumps([p.model_dump(mode="json") for p in prototypes], indent=1)
    return PAIR.sub(r"[\1, \2]", text) + "\n"


def save_library(prototypes: list[TowerPrototype], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(prototypes))
    return out


def load_library(path: str | Path) -> list[TowerPrototype]:
    """The prototypes in a library file: a JSON list, each one valid and drawn consistently,
    no two sharing an id. Everything wrong with the file is named in one error."""
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc})") from None
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path}: a prototype library is a JSON list of at least one prototype")
    prototypes, found = [], []
    for number, item in enumerate(data, 1):
        label = f"prototype {number} ({item.get('id', '?') if isinstance(item, dict) else '?'})"
        try:
            prototype = TowerPrototype.model_validate(item)
        except ValidationError as exc:
            found.append(f"{label}: {exc}")
            continue
        found += [f"{label}: {problem}" for problem in problems(prototype)]
        prototypes.append(prototype)
    ids = [p.id for p in prototypes]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    found += [f"id {i!r} is used more than once" for i in repeated]
    if found:
        raise ValueError(f"{path}: " + "; ".join(found))
    return prototypes
