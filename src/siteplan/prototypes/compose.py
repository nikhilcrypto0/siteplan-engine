"""Compose tower prototypes from a flat library: the kit of buildings the optimizer chooses from.

A prototype is one typical floor of a slab laid out as today's towers are (towers.py): flats
facing each other across a corridor, the same flat opposite itself, and a lift/stair core that
spans the full depth after the first half of each group of flats, so a core cuts the corridor
and every flat is a short walk from one. The four families differ in how many cores a block has
and how many flats each core serves on a side:

    SINGLE_CORE_SMALL   1 core  x 2 flats a side    4 flats a floor
    SINGLE_CORE         1 core  x 3 flats a side    6
    TWO_CORE_MEDIUM     2 cores x 2 flats a side    8
    TWO_CORE_LARGE      2 cores x 3 flats a side   12

These counts are design choices, not law: no order limits a block's cores or flats a floor. The
library's own `flats_per_core_per_side` caps what one core may serve, and a family it cannot
serve is not composed. Which flat stands where follows the requested unit mix (`MixTracker`, the
rule today's towers use), so every block of the kit sits near the mix, whichever the optimizer
picks.

Everything is metres in the prototype's own frame: the footprint centred on the origin, its long
axis along x. A prototype holds no legal value and no floor count: how tall it stands is the
optimizer's choice within what the law allows, and its heights stay unset because the brief's
firm standards apply. Coordinates are rounded to a micrometre so the saved library reads cleanly
and its figures are the same on every machine.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from siteplan.contracts.common import Shape, SourceKind
from siteplan.contracts.prototype import PrototypeFamily, TowerPrototype
from siteplan.library import FlatLibrary, FlatType

COORD_DIGITS = 6
# Placeholders until egress is modelled (the validator reports it NOT_CHECKED): a design
# convention for what a core holds, not a rule.
LIFTS_PER_CORE = 2
STAIRS_PER_CORE = 1
MIX_SUM_TOLERANCE = 0.01  # the brief's own tolerance on a unit mix adding up to 1
COMPOSED_SOURCES = (SourceKind.ENGINE_DEFAULT, SourceKind.FIRM_STANDARD)


class MixTracker:
    """Which flat a block needs next to keep what is built near the requested unit mix. It moved
    here from towers.py unchanged: the prototype generator imports it from here now."""

    def __init__(self, target: dict[str, float]):
        self.target = target
        self.counts = {k: 0 for k in target}

    def next_choices(self, library: FlatLibrary, pending: dict[str, int]) -> list[FlatType]:
        """Flats in the order to try: most under-represented category first, then the flat
        that sells the most area per metre of corridor."""
        counts = {k: self.counts.get(k, 0) + pending.get(k, 0) for k in self.target}
        total = sum(counts.values()) + 2
        wanted = [f for f in library.flats if self.target.get(f.bhk, 0) > 0]
        return sorted(
            wanted,
            key=lambda f: (
                -(self.target[f.bhk] - counts[f.bhk] / total),
                -f.saleable_sqft / f.width_m,
            ),
        )


@dataclass(frozen=True)
class BlockPlan:
    """How a family is built: the cores a block has and the flats each serves on a side."""

    cores: int
    flats_per_core_per_side: int

    @property
    def flats_per_side(self) -> int:
        return self.cores * self.flats_per_core_per_side

    @property
    def flats_per_floor(self) -> int:
        return 2 * self.flats_per_side


FAMILY_PLANS: dict[PrototypeFamily, BlockPlan] = {
    PrototypeFamily.SINGLE_CORE_SMALL: BlockPlan(cores=1, flats_per_core_per_side=2),
    PrototypeFamily.SINGLE_CORE: BlockPlan(cores=1, flats_per_core_per_side=3),
    PrototypeFamily.TWO_CORE_MEDIUM: BlockPlan(cores=2, flats_per_core_per_side=2),
    PrototypeFamily.TWO_CORE_LARGE: BlockPlan(cores=2, flats_per_core_per_side=3),
}


def servable_families(library: FlatLibrary) -> list[PrototypeFamily]:
    """The families the library's cores can serve: a core may not serve more flats on a side
    than the library says it does."""
    return [family for family, plan in FAMILY_PLANS.items()
            if plan.flats_per_core_per_side <= library.flats_per_core_per_side]


def checked_mix(library: FlatLibrary, unit_mix: dict[str, float] | None) -> dict[str, float]:
    """The unit mix to compose for: the one asked, or an even share of every category the
    library has when none is."""
    if unit_mix is None:
        categories = sorted(library.categories)
        return {category: 1 / len(categories) for category in categories}
    unknown = set(unit_mix) - library.categories
    if unknown:
        raise ValueError(f"unit_mix asks for {sorted(unknown)}, not in the flat library")
    total = sum(unit_mix.values())
    if any(share < 0 for share in unit_mix.values()) or abs(total - 1) > MIX_SUM_TOLERANCE:
        raise ValueError(f"unit_mix shares must not be negative and must add up to 1 "
                         f"(got {total:.3f})")
    return dict(unit_mix)


def pick_flats(library: FlatLibrary, unit_mix: dict[str, float], count: int) -> list[FlatType]:
    """The flats along one side of a block, in order: the category furthest below its share
    first. The same flat stands opposite each, so every choice counts twice."""
    mix = MixTracker(unit_mix)
    chosen: list[FlatType] = []
    pending: dict[str, int] = {}
    for _ in range(count):
        flat = mix.next_choices(library, pending)[0]
        chosen.append(flat)
        pending[flat.bhk] = pending.get(flat.bhk, 0) + 2
    return chosen


def split_evenly(flats: list[FlatType], groups: int) -> list[list[FlatType]]:
    """The flats in as many consecutive groups, one per core, of as even a size as they allow."""
    size, extra = divmod(len(flats), groups)
    sizes = [size + (1 if i < extra else 0) for i in range(groups)]
    starts = [sum(sizes[:i]) for i in range(groups)]
    return [flats[start: start + n] for start, n in zip(starts, sizes, strict=True)]


def compose_prototype(library: FlatLibrary, family: PrototypeFamily,
                      unit_mix: dict[str, float] | None = None, *,
                      source_kind: SourceKind = SourceKind.ENGINE_DEFAULT,
                      source: str | None = None) -> TowerPrototype:
    """One prototype of a family, its flats chosen for the unit mix.

    source_kind says whose library it is: ENGINE_DEFAULT for the engine's example flats,
    FIRM_STANDARD for the firm's own library at run time."""
    plan = FAMILY_PLANS.get(family)
    if plan is None:
        raise ValueError(f"{family.value} is not composed from a library: a legacy rectangle is "
                         "made from a tower the prototype generator laid (prototypes.legacy)")
    if plan.flats_per_core_per_side > library.flats_per_core_per_side:
        raise ValueError(f"{family.value} has each core serve {plan.flats_per_core_per_side} flats "
                         f"a side; this library's cores serve {library.flats_per_core_per_side}")
    if source_kind not in COMPOSED_SOURCES:
        raise ValueError(f"a composed prototype comes from the engine's default or the firm's "
                         f"standard library, not {source_kind.value}")
    flats = pick_flats(library, checked_mix(library, unit_mix), plan.flats_per_side)
    return _lay_out(f"{family.value.lower().replace('_', '-')}-{plan.flats_per_floor}", family,
                    split_evenly(flats, plan.cores), library, source_kind,
                    source or _source_of(library))


def compose_library(library: FlatLibrary, unit_mix: dict[str, float] | None = None, *,
                    families: list[PrototypeFamily] | None = None,
                    source_kind: SourceKind = SourceKind.ENGINE_DEFAULT,
                    source: str | None = None) -> list[TowerPrototype]:
    """The kit: a prototype of every family the library's cores can serve (or of the families
    asked for, refusing one it cannot), smallest first."""
    wanted = servable_families(library) if families is None else families
    if not wanted:
        raise ValueError(f"no family can be composed: this library's cores serve "
                         f"{library.flats_per_core_per_side} flat(s) a side and the smallest "
                         f"family has each core serve {_smallest_core_load()}")
    return [compose_prototype(library, family, unit_mix, source_kind=source_kind,
                              source=source)
            for family in wanted]


def _smallest_core_load() -> int:
    return min(plan.flats_per_core_per_side for plan in FAMILY_PLANS.values())


def _source_of(library: FlatLibrary) -> str:
    return f"composed from the flat library. {library.note}".strip()


def _clean(value: float) -> float:
    """Rounded to a micrometre, and never a negative zero."""
    return round(value, COORD_DIGITS) + 0.0


def _rect(x0: float, y0: float, x1: float, y1: float) -> Shape:
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return Shape(outer=[(_clean(x), _clean(y)) for x, y in corners])


@dataclass(frozen=True)
class _Row:
    """A block laid out along the corridor from x = 0, before it is centred: where each flat
    stands (one side of the corridor; the same flat stands opposite) and each core."""

    flats: tuple[tuple[FlatType, float, float], ...]
    cores: tuple[tuple[float, float], ...]
    length: float


def _row(groups: list[list[FlatType]], core_width_m: float) -> _Row:
    """Each group of flats with its core after the first half of it, as towers.build_tower
    lays them. Plain arithmetic on the library's own numbers, so the parts tile the block."""
    flats: list[tuple[FlatType, float, float]] = []
    cores: list[tuple[float, float]] = []
    x = 0.0
    for group in groups:
        before_core = math.ceil(len(group) / 2)
        for position, flat in enumerate(group):
            if position == before_core:
                cores.append((x, x + core_width_m))
                x += core_width_m
            flats.append((flat, x, x + flat.width_m))
            x += flat.width_m
        if before_core >= len(group):
            cores.append((x, x + core_width_m))
            x += core_width_m
    return _Row(tuple(flats), tuple(cores), x)


def _corridor_runs(row: _Row) -> list[tuple[float, float]]:
    """The stretches of corridor a core does not stand across."""
    runs, cursor = [], 0.0
    for start, end in row.cores:
        if start > cursor:
            runs.append((cursor, start))
        cursor = end
    if row.length > cursor:
        runs.append((cursor, row.length))
    return runs


def _lay_out(prototype_id: str, family: PrototypeFamily, groups: list[list[FlatType]],
             library: FlatLibrary, source_kind: SourceKind, source: str) -> TowerPrototype:
    """The groups of flats as a prototype: a flat each side of the corridor, centred on the
    origin with the block's long axis along x."""
    row = _row(groups, library.core_width_m)
    depth = library.flats[0].depth_m
    half_corridor = library.corridor_width_m / 2
    span = half_corridor + depth  # from the corridor's centre line to the outer wall
    shift = row.length / 2

    def along(a: float, b: float, y0: float, y1: float) -> Shape:
        return _rect(a - shift, y0, b - shift, y1)

    sides = ((half_corridor, span), (-span, -half_corridor))
    modules = [{"id": f"m{2 * i + side + 1}", "type_id": flat.name, "category": flat.bhk,
                "shape": along(x0, x1, y0, y1), "saleable_sqft": flat.saleable_sqft,
                "carpet_sqft": flat.carpet_sqft, "built_up_sqft": flat.built_up_sqft}
               for i, (flat, x0, x1) in enumerate(row.flats)
               for side, (y0, y1) in enumerate(sides)]
    gross = row.length * 2 * span
    own = 2 * depth * sum(x1 - x0 for _, x0, x1 in row.flats)
    return TowerPrototype(
        id=prototype_id, family=family, source_kind=source_kind, source=source,
        footprint=along(0.0, row.length, -span, span), length_m=_clean(row.length),
        depth_m=_clean(2 * span), cores=len(row.cores), modules=modules,
        core_zones=[{"shape": along(start, end, -span, span), "lifts": LIFTS_PER_CORE,
                     "stairs": STAIRS_PER_CORE} for start, end in row.cores],
        corridor=[along(start, end, -half_corridor, half_corridor)
                  for start, end in _corridor_runs(row)],
        per_floor={"flats": len(modules),
                   "flats_by_type": dict(Counter(m["category"] for m in modules)),
                   "gross_floor_sqm": _clean(gross), "flats_own_sqm": _clean(own),
                   "common_core_sqm": _clean(gross - own),
                   "saleable_sqft": _clean(2 * sum(f.saleable_sqft for f, _, _ in row.flats))})
