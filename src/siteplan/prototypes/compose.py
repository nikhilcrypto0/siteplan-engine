"""Compose tower prototypes from a flat library: the kit of buildings the optimizer chooses from.

A prototype is one typical floor of a slab laid out as today's towers are (towers.py): flats
facing each other across a corridor, the same flat opposite itself, and a lift/stair core after
the first half of each group of flats, so a core cuts the corridor and every flat is a short walk
from one. Since 2026-10-12 the floor is the flats' shares of it (each library flat's width x
depth, AreaBasis.PLATE_SHARE), the cores and corridor laid out of it rather than added, and a
core is compact across the corridor (`core_depth_m`), the flats either side of it taking the
ground behind it; the old drawing (FLAT_ONLY, a core across the whole depth) is still composed
when a library asks for it. The four families differ in how many cores a block has
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
axis along x (a block shorter than it is deep is turned a quarter, its corridor along y). A
prototype holds no legal value and no floor count: how tall it stands is the
optimizer's choice within what the law allows, and its heights stay unset because the brief's
firm standards apply. Coordinates are rounded to a micrometre so the saved library reads cleanly
and its figures are the same on every machine.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from shapely.geometry import box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from siteplan.contracts.common import Shape, SourceKind
from siteplan.contracts.prototype import PrototypeFamily, TowerPrototype
from siteplan.library import AreaBasis, FlatLibrary, FlatType

COORD_DIGITS = 6
# Placeholders until egress is modelled (the validator reports it NOT_CHECKED): a design
# convention for what a core holds, not a rule.
LIFTS_PER_CORE = 2
STAIRS_PER_CORE = 1
MIX_SUM_TOLERANCE = 0.01  # the brief's own tolerance on a unit mix adding up to 1
COMPOSED_SOURCES = (SourceKind.ENGINE_DEFAULT, SourceKind.FIRM_STANDARD)
EDGE_M = 1e-6  # how near a flat's end must be to a core's to stand beside it


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
    origin with the block's long axis along x. Where the library's flats are each one's share of
    the floor (AreaBasis.PLATE_SHARE), the floor is their sum and the cores and corridor are laid
    out of it; a compact core (`core_depth_m`) stands across the corridor, and the ground behind
    it on each side goes to the flats either side of it. Every flat's own area is its share of
    what the cores and corridor leave (`_fitted`), whether or not it wraps a core."""
    depth = library.flats[0].depth_m
    half_corridor = library.corridor_width_m / 2
    span = half_corridor + depth  # from the corridor's centre line to the outer wall
    core_half = span if library.core_depth_m is None else min(span, library.core_depth_m / 2)
    groups = _fitted(groups, library, span, core_half)
    row = _row(groups, library.core_width_m)
    shift = row.length / 2

    def along(a: float, b: float, y0: float, y1: float) -> Shape:
        return _rect(a - shift, y0, b - shift, y1)

    sides = ((half_corridor, span), (-span, -half_corridor))
    behind = _behind_cores(row, (core_half, span)) if core_half < span else {}
    modules = []
    for i, (flat, x0, x1) in enumerate(row.flats):
        for side, (y0, y1) in enumerate(sides):
            pieces = [box(x0 - shift, y0, x1 - shift, y1)]
            pieces += [box(a - shift, b0 if side == 0 else -b1, b - shift,
                           b1 if side == 0 else -b0)
                       for a, b, (b0, b1) in behind.get(i, [])]
            modules.append({"id": f"m{2 * i + side + 1}", "type_id": flat.name,
                            "category": flat.bhk, "shape": _shape(unary_union(pieces)),
                            "saleable_sqft": flat.saleable_sqft, "carpet_sqft": flat.carpet_sqft,
                            "built_up_sqft": flat.built_up_sqft})
    gross = row.length * 2 * span
    own = sum(m["shape"].area_sqm for m in modules)
    # A block shorter than it is deep is drawn a quarter turned, its long side along x as every
    # prototype's frame is; the corridor then runs along y.
    turned = row.length < 2 * span
    turn = _quarter_turn if turned else (lambda shape: shape)
    for module in modules:
        module["shape"] = turn(module["shape"])
    long_m, short_m = (2 * span, row.length) if turned else (row.length, 2 * span)
    return TowerPrototype(
        id=prototype_id, family=family, source_kind=source_kind, source=source,
        footprint=turn(along(0.0, row.length, -span, span)), length_m=_clean(long_m),
        depth_m=_clean(short_m), cores=len(row.cores), modules=modules,
        core_zones=[{"shape": turn(along(start, end, -core_half, core_half)),
                     "lifts": LIFTS_PER_CORE, "stairs": STAIRS_PER_CORE}
                    for start, end in row.cores],
        corridor=[turn(along(start, end, -half_corridor, half_corridor))
                  for start, end in _corridor_runs(row)],
        per_floor={"flats": len(modules),
                   "flats_by_type": dict(Counter(m["category"] for m in modules)),
                   "gross_floor_sqm": _clean(gross), "flats_own_sqm": _clean(own),
                   "common_core_sqm": _clean(gross - own),
                   "saleable_sqft": _clean(2 * sum(f.saleable_sqft for f, _, _ in row.flats))})


def _fitted(groups: list[list[FlatType]], library: FlatLibrary, span: float,
            core_half: float) -> list[list[FlatType]]:
    """The flats with the frontage that gives each its own area: the floor is the flats' shares'
    sum (PLATE_SHARE) or the flats and cores laid end to end (FLAT_ONLY); what its cores and
    corridor leave is shared among the flats by their library areas, and a flat beside a compact
    core, which also takes ground behind the core, stands that much narrower."""
    flats = [flat for group in groups for flat in group]
    depth, core_m = flats[0].depth_m, library.core_width_m
    shares = sum(flat.width_m for flat in flats)
    if library.area_basis is AreaBasis.PLATE_SHARE:
        length = 2 * depth * shares / (2 * span)
    else:
        length = shares + len(groups) * core_m
    corridor_m = length - len(groups) * core_m
    if corridor_m <= 0:
        raise ValueError(f"the cores ({len(groups)} x {core_m:g} m) take the whole "
                         f"{length:.2f} m the flats' shares of the floor give")
    own_a_side = depth * corridor_m + len(groups) * core_m * (span - core_half)
    behind = _behind_cores(_row(groups, core_m), (core_half, span)) if core_half < span else {}
    fitted, index = [], 0
    for group in groups:
        fitted.append([])
        for flat in group:
            strip = sum((b - a) * (y1 - y0) for a, b, (y0, y1) in behind.get(index, []))
            width = (own_a_side * flat.width_m / shares - strip) / depth
            if width <= 0:
                raise ValueError(f"a {flat.name} beside a core keeps no frontage: the ground "
                                 f"behind the core is more than its share")
            fitted[-1].append(flat.model_copy(update={"width_m": round(width, COORD_DIGITS)}))
            index += 1
    return _even_length(fitted, len(groups) * core_m)


def _even_length(groups: list[list[FlatType]], cores_m: float) -> list[list[FlatType]]:
    """The flats' frontages on the micrometre grid with the block an even number of micrometres
    long, so its footprint, centred on the origin, measures exactly its stated length: a block a
    micrometre longer than stated stood half a micrometre inside the gap the search kept to its
    neighbour, and the validator failed it (2026-10-12)."""
    unit = 10 ** -COORD_DIGITS
    length = round(sum(f.width_m for g in groups for f in g) + cores_m, COORD_DIGITS)
    if round(length / unit) % 2 == 0:
        return groups
    last = groups[-1][-1]
    return [*groups[:-1], [*groups[-1][:-1], last.model_copy(
        update={"width_m": round(last.width_m + unit, COORD_DIGITS)})]]


def _behind_cores(row: _Row, band: tuple[float, float]
                  ) -> dict[int, list[tuple[float, float, tuple[float, float]]]]:
    """The ground behind each compact core, out to the outer wall on one side (`band`), shared
    by the flats either side of it: half each, or the whole to the one flat it has."""
    pieces: dict[int, list[tuple[float, float, tuple[float, float]]]] = {}
    for start, end in row.cores:
        before = [i for i, (_, _, x1) in enumerate(row.flats) if abs(x1 - start) < EDGE_M]
        after = [i for i, (_, x0, _) in enumerate(row.flats) if abs(x0 - end) < EDGE_M]
        middle = (start + end) / 2
        if before and after:
            pieces.setdefault(before[-1], []).append((start, middle, band))
            pieces.setdefault(after[0], []).append((middle, end, band))
        elif before or after:
            pieces.setdefault((before or after)[0], []).append((start, end, band))
    return pieces


def _quarter_turn(shape: Shape) -> Shape:
    """The shape turned a quarter anticlockwise about the origin: (x, y) to (-y, x)."""
    return Shape(outer=[(_clean(-y), _clean(x)) for x, y in shape.outer],
                 holes=[[(_clean(-y), _clean(x)) for x, y in hole] for hole in shape.holes])


def _shape(polygon) -> Shape:
    """A flat's outline, rounded as the rest of the prototype is."""
    corners = orient(polygon.simplify(0)).exterior.coords[:-1]  # no corner on a straight edge
    return Shape(outer=[(_clean(x), _clean(y)) for x, y in corners])


SINGLE_ROW_FLATS = (3, 4)  # flats a floor of the single-row blocks composed for narrow land
SINGLE_ROW_SOURCE = ("ENGINE-COMPOSED single-row block, PRELIMINARY: one row of the library's "
                     "flats beside its corridor, one core in line taking the library's core "
                     "width across the flats' depth (the firm's Suchitra in-line core of two "
                     "lifts, a stair and a lobby measures 8.24 x 10.77 m, the same 88.7 m2); "
                     "each flat as large as its type in the double-loaded blocks. Not the "
                     "firm's design: the stairs its height needs, an open or closed corridor "
                     "and windows on the corridor side are not checked.")


def compose_single_rows(library: FlatLibrary, unit_mix: dict[str, float] | None,
                        reference: TowerPrototype, *,
                        source_kind: SourceKind = SourceKind.ENGINE_DEFAULT
                        ) -> list[TowerPrototype]:
    """Single-row blocks of 3 and 4 flats a floor for land too narrow for a double-loaded one
    (2026-10-12, the architect): one row of flats beside a corridor, one core in line after the
    first half of them. Each flat keeps its type's own area in `reference` (a double-loaded
    block of the same library), so a flat is the same flat whichever block it stands in and the
    single-row block, with fewer flats to share its core and corridor, honestly carries more
    floor a flat. Labelled engine-composed and preliminary in its source."""
    if source_kind not in COMPOSED_SOURCES:
        raise ValueError(f"a composed prototype comes from the engine's default or the firm's "
                         f"standard library, not {source_kind.value}")
    own: dict[str, float] = {}
    for module in reference.modules:
        own.setdefault(module.type_id, module.shape.area_sqm)
    depth = library.flats[0].depth_m
    mix = checked_mix(library, unit_mix)
    out = []
    for count in SINGLE_ROW_FLATS:
        picked = pick_flats(library, mix, count)
        missing = sorted({f.name for f in picked} - set(own))
        if missing:
            raise ValueError(f"the reference block has no {missing} to size a single row from")
        flats = [f.model_copy(update={"width_m": round(own[f.name] / depth, COORD_DIGITS)})
                 for f in picked]
        [flats] = _even_length([flats], library.core_width_m)
        out.append(_single_row(f"single-row-{count}", flats, library, source_kind))
    return out


def _single_row(prototype_id: str, flats: list[FlatType], library: FlatLibrary,
                source_kind: SourceKind) -> TowerPrototype:
    """The flats in a row, a core in line after the first half, the corridor along one side:
    centred on the origin, its long side along x (turned a quarter if shorter than deep)."""
    row = _row([flats], library.core_width_m)
    depth = flats[0].depth_m
    corridor = library.corridor_width_m
    half = (depth + corridor) / 2
    flat_band = (corridor - half, half)  # the flats on the +y side of the corridor
    shift = row.length / 2

    def along(a: float, b: float, y0: float, y1: float) -> Shape:
        return _rect(a - shift, y0, b - shift, y1)

    turned = row.length < 2 * half
    turn = _quarter_turn if turned else (lambda shape: shape)
    modules = [{"id": f"m{i}", "type_id": flat.name, "category": flat.bhk,
                "shape": turn(along(x0, x1, *flat_band)), "saleable_sqft": flat.saleable_sqft,
                "carpet_sqft": flat.carpet_sqft, "built_up_sqft": flat.built_up_sqft}
               for i, (flat, x0, x1) in enumerate(row.flats, 1)]
    gross = row.length * 2 * half
    own = sum(m["shape"].area_sqm for m in modules)
    long_m, short_m = (2 * half, row.length) if turned else (row.length, 2 * half)
    return TowerPrototype(
        id=prototype_id, family=PrototypeFamily.SINGLE_ROW, source_kind=source_kind,
        source=SINGLE_ROW_SOURCE, footprint=turn(along(0.0, row.length, -half, half)),
        length_m=_clean(long_m), depth_m=_clean(short_m), cores=len(row.cores), modules=modules,
        core_zones=[{"shape": turn(along(start, end, *flat_band)), "lifts": LIFTS_PER_CORE,
                     "stairs": STAIRS_PER_CORE} for start, end in row.cores],
        corridor=[turn(along(0.0, row.length, -half, corridor - half))],
        per_floor={"flats": len(modules),
                   "flats_by_type": dict(Counter(m["category"] for m in modules)),
                   "gross_floor_sqm": _clean(gross), "flats_own_sqm": _clean(own),
                   "common_core_sqm": _clean(gross - own),
                   "saleable_sqft": _clean(sum(f.saleable_sqft for f in flats))})
