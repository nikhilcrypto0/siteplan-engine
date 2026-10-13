"""Floor plates sized to the land (2026-10-13, the architect): from the flat library and the land
the envelope leaves, the single-row and double-loaded plates that physically fit, each with its
area schedule and what in it is assumed.

`compose_plate` (compose.py) builds one plate from a `PlateSpec`; this module adds the two things a
plate needs beyond its drawing:

- its area schedule (`account`): the gross floor, the flats' own area, the cores, the corridor or
  open gallery, the saleable area (each flat type's library figure, the same in every plate), and
  the effective loading, the saleable over the gross, against the loading the firm sells on. Where
  the geometry needs more common area than that loading pays for, the shortfall is said, never
  hidden and never made up by a larger saleable figure;
- what is assumed (`preliminary`): the flat dimensions a library derives rather than measures, the
  core and corridor sizes, and the standards the engine does not model (egress, lifts,
  accessibility, ventilation, how an open gallery counts).

`plates_for` reads the envelope's width profiles (legal/widths.py): for every region of land a
height band leaves, the plates whose depth its width takes and whose length its length takes, laid
along the region and tested whole against its shape. It invents no dimension: every length and
depth comes from the library's flats, cores and corridor. It imports nothing from the generator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import affinity
from shapely.geometry import Polygon, box

from siteplan.contracts import BuildableEnvelope, TowerPrototype
from siteplan.contracts.common import SourceKind
from siteplan.library import FlatLibrary
from siteplan.prototypes.compose import (
    Corridor,
    Loading,
    PlateSpec,
    checked_mix,
    compose_library,
    compose_plate,
    pick_flats,
)

SQFT_A_SQM = 10.7639
NET_PLOT = "net plot"  # legal/envelope.py's width profile of the plot before any setback
LOADING_TOL_SQM = 0.5  # a plate within this of what its loading pays for is not short
FIT_STEP_M = 1.0  # how finely a plate is slid along a region to find room
FIT_TOL_M = 1e-6  # a plate whose edge lies on the region's edge stands in it
DOUBLE_PER_SIDE = (2, 3, 4, 5, 6)  # flats a side tried for a double-loaded plate
SINGLE_ROW_LENGTHS = ((3, 1), (4, 1), (6, 2), (8, 2))  # flats a floor, cores
SHORTLIST = 8  # the most plates beside the families a search is given
MISSING_STANDARDS = (
    "egress: how many staircases a block of this height needs, their width and the travel "
    "distance to them (NBC Part 4; the validator reports egress NOT_CHECKED)",
    "lifts: how many lifts a block of this height and size needs (NBC Part 8)",
    "accessibility: lift car and corridor sizes for wheelchair access",
    "ventilation: light and air to habitable rooms off a single-loaded corridor",
)
PLATE_SOURCE = ("ENGINE-COMPOSED floor plate, PRELIMINARY: sized to this site's land from the "
                "flat library; not the firm's drawing and not shown to comply.")
GALLERY_UNKNOWN = ("open gallery: whether its area counts in the built-up area and how far it "
                   "counts as open for fire and ventilation")


@dataclass(frozen=True)
class PlateAccount:
    """A plate's area schedule, a typical floor."""

    gross_sqm: float  # the footprint, wall to wall
    flats_own_sqm: float
    cores_sqm: float
    corridor_sqm: float  # the enclosed corridor, or the open gallery
    gallery: bool  # the corridor is an open gallery
    saleable_sqft: float  # each flat type's library figure, summed
    loading: float  # the loading the firm sells on, e.g. 1.22
    effective_loading: float  # saleable over gross

    @property
    def paid_for_sqm(self) -> float:
        """The floor the loading pays for: the saleable area over the loading."""
        return self.saleable_sqft / SQFT_A_SQM / self.loading

    @property
    def shortfall_sqm(self) -> float:
        """Floor the geometry needs beyond what the loading pays for (0 when none)."""
        extra = self.gross_sqm - self.paid_for_sqm
        return extra if extra > LOADING_TOL_SQM else 0.0

    def note(self) -> str:
        if not self.shortfall_sqm:
            return (f"effective loading {self.effective_loading:.3f}: the {self.loading:.2f} "
                    "loading pays for the whole floor")
        return (f"effective loading {self.effective_loading:.3f}: the geometry needs "
                f"{self.shortfall_sqm:,.1f} m² ({self.shortfall_sqm / self.paid_for_sqm:.0%}) more "
                f"floor than the {self.loading:.2f} loading pays for; the saleable area is not "
                "raised to cover it")


@dataclass(frozen=True)
class Plate:
    spec: PlateSpec
    prototype: TowerPrototype
    account: PlateAccount
    preliminary: tuple[str, ...]  # what in it is assumed or not modelled
    fits: tuple[str, ...] = ()  # the regions it stands in whole, as 'band: region n'


def account(prototype: TowerPrototype, spec: PlateSpec, loading_pct: float) -> PlateAccount:
    """The plate's area schedule from its own drawing."""
    floor = prototype.per_floor
    cores = sum(z.shape.to_shapely().area for z in prototype.core_zones)
    corridor = sum(s.to_shapely().area for s in prototype.corridor)
    gross = floor.gross_floor_sqm
    return PlateAccount(
        gross_sqm=gross, flats_own_sqm=floor.flats_own_sqm, cores_sqm=cores,
        corridor_sqm=corridor, gallery=spec.corridor is Corridor.OPEN_GALLERY,
        saleable_sqft=floor.saleable_sqft, loading=1 + loading_pct / 100,
        effective_loading=floor.saleable_sqft / SQFT_A_SQM / gross if gross else 0.0)


def preliminary(library: FlatLibrary, spec: PlateSpec) -> tuple[str, ...]:
    """What in a plate is assumed: never empty, since no library yet carries measured flats."""
    found = [
        "flat frontages: derived from each flat's area at the library's one depth "
        f"({library.flats[0].depth_m:g} m), not measured from the firm's flat plans",
        f"core: {library.core_width_m:g} m along the corridor, "
        + (f"across the flats' whole depth ({library.flats[0].depth_m:g} m)"
           if spec.loading is Loading.SINGLE_ROW or not library.core_depth_m
           else f"{library.core_depth_m:g} m across it")
        + "; its lifts and stairs are placeholders",
        f"corridor: {library.corridor_width_m:g} m wide, the library's figure",
        *MISSING_STANDARDS,
    ]
    if spec.corridor is Corridor.OPEN_GALLERY:
        found.append(GALLERY_UNKNOWN)
    if spec.loading is Loading.SINGLE_ROW:
        found.append("single-row: each flat as large as its type in the library's double-loaded "
                     "block, so a flat is the same flat in every plate")
    return tuple(found)


def plate(library: FlatLibrary, spec: PlateSpec, *, reference_own: dict[str, float] | None,
          loading_pct: float, source_kind: SourceKind = SourceKind.ENGINE_DEFAULT) -> Plate:
    """One plate, composed, with its schedule and what in it is assumed; its prototype's source
    says so (PLATE_SOURCE, the schedule's note, every item assumed), so every layout that uses it
    carries the label."""
    composed = compose_plate(library, spec, reference_own=reference_own,
                             source_kind=source_kind)
    schedule = account(composed, spec, loading_pct)
    assumed = preliminary(library, spec)
    prototype = composed.model_copy(update={"source": " ".join(
        [PLATE_SOURCE, f"Its schedule: {schedule.note()}.", "Assumed or not modelled: "
         + "; ".join(assumed) + "."])})
    return Plate(spec, prototype, schedule, assumed)


def plates_for(envelope: BuildableEnvelope, library: FlatLibrary,
               unit_mix: dict[str, float] | None, *, loading_pct: float,
               reference_own: dict[str, float],
               source_kind: SourceKind = SourceKind.ENGINE_DEFAULT) -> list[Plate]:
    """The plates the land takes: for each region of each band's land (the envelope's width
    profiles), the single-row and double-loaded plates whose depth its width takes and whose
    length its length takes, tested whole against the region's shape. Each plate once, with every
    region it fits; a plate that fits nowhere is left out."""
    mix = checked_mix(library, unit_mix)
    specs = _specs(library, mix)
    built: dict[str, Plate] = {}
    for profile in envelope.width_profiles:
        if profile.applies_to == NET_PLOT:
            continue  # the plot before any setback: no block may stand on it all
        for n, region in enumerate(profile.regions, 1):
            shape = region.shape.to_shapely()
            for spec in specs:
                found = built.get(spec.key)
                if found is None:
                    try:
                        found = plate(library, spec, reference_own=reference_own,
                                      loading_pct=loading_pct, source_kind=source_kind)
                    except ValueError:
                        continue  # cores that take the block, a core no flat can sit beside
                    built[spec.key] = found
                p = found.prototype
                if min(p.length_m, p.depth_m) > region.max_inscribed_width_m + FIT_TOL_M:
                    continue
                if max(p.length_m, p.depth_m) > region.length_m + FIT_TOL_M:
                    continue
                if fits(shape, p.length_m, p.depth_m):
                    where = f"{profile.applies_to}: region {n}"
                    built[spec.key] = Plate(found.spec, p, found.account, found.preliminary,
                                            (*built[spec.key].fits, where))
    return [p for p in built.values() if p.fits]


def _specs(library: FlatLibrary, mix: dict[str, float]) -> list[PlateSpec]:
    """The plates worth trying, bounded, each of the brief's mix as the library's families are
    (a plate of one flat type alone sells more a floor and would win a column on that while
    missing the mix): a single row of 3 or 4 flats on one core, or 6 or 8 on two
    (`SINGLE_ROW_LENGTHS`), each with an enclosed corridor and with an open gallery; a
    double-loaded plate at every number of flats a side in `DOUBLE_PER_SIDE`, one core up to
    three a side, two above. Every length and depth comes from the library's flats, cores and
    corridor: no depth is invented."""
    specs: dict[tuple, PlateSpec] = {}
    for count, cores in SINGLE_ROW_LENGTHS:
        flats = tuple(f.name for f in pick_flats(library, mix, count))
        for corridor in Corridor:
            spec = PlateSpec(Loading.SINGLE_ROW, flats, cores, corridor)
            specs.setdefault(spec.key, spec)
    for per_side in DOUBLE_PER_SIDE:
        flats = tuple(f.name for f in pick_flats(library, mix, per_side))
        spec = PlateSpec(Loading.DOUBLE_LOADED, flats, 1 if per_side <= 3 else 2)
        specs.setdefault(spec.key, spec)
    return list(specs.values())


def shortlist(plates: list[Plate], limit: int = SHORTLIST) -> list[Plate]:
    """A diverse, bounded few of the plates that fit: one for each idea (how the flats stand,
    flats a floor, cores, corridor, unit mix), the one that sells the most of each; then the ideas
    taken in turn across the kinds, so a long list of near copies never crowds out a different
    idea. An open gallery and an enclosed corridor are different ideas, each with its own schedule
    and its own list of what is assumed, although their footprints are the same."""
    best: dict[tuple, Plate] = {}
    for p in plates:
        floor = p.prototype.per_floor
        idea = (p.spec.loading.value, floor.flats, p.spec.cores, p.spec.corridor.value,
                tuple(sorted(floor.flats_by_type.items())))
        if idea not in best or floor.saleable_sqft > best[idea].prototype.per_floor.saleable_sqft:
            best[idea] = p
    by_kind: dict[tuple, list[Plate]] = {}
    for idea, p in sorted(best.items(),
                          key=lambda item: -item[1].prototype.per_floor.saleable_sqft):
        by_kind.setdefault((idea[0], idea[3]), []).append(p)
    chosen: list[Plate] = []
    while len(chosen) < limit and any(by_kind.values()):
        for kind in sorted(by_kind):
            if by_kind[kind] and len(chosen) < limit:
                chosen.append(by_kind[kind].pop(0))
    return chosen


def kit_for(library: FlatLibrary, unit_mix: dict[str, float] | None,
            envelope: BuildableEnvelope | None, *, loading_pct: float,
            source_kind: SourceKind = SourceKind.ENGINE_DEFAULT,
            limit: int = SHORTLIST) -> tuple[list[TowerPrototype], list[Plate]]:
    """The prototypes the search is given: the library's families, as ever, and beside them a
    shortlist of plates the site's own land takes (`plates_for`, `shortlist`), wherever they
    stand, so a new plate may win where a family also fits. Without an envelope, the families
    alone. Also the plates, each with its schedule and what is assumed."""
    families = compose_library(library, unit_mix, source_kind=source_kind)
    if envelope is None:
        return families, []
    same = {_block(p) for p in families}  # a plate that is a family's own block adds nothing
    found = shortlist([p for p in plates_for(envelope, library, unit_mix,
                                             loading_pct=loading_pct,
                                             reference_own=own_areas(families[-1]),
                                             source_kind=source_kind)
                       if _block(p.prototype) not in same], limit)
    return [*families, *(p.prototype for p in found)], found


def _block(prototype: TowerPrototype) -> tuple:
    """What makes two prototypes the same block: their size, cores and flats a floor."""
    return (round(prototype.length_m, 2), round(prototype.depth_m, 2), prototype.cores,
            tuple(sorted(prototype.per_floor.flats_by_type.items())))


def fits(region: Polygon, length_m: float, depth_m: float) -> bool:
    """Whether a length x depth rectangle stands wholly in the region: laid along each edge
    direction of the region's hull (and across it), slid along the region a metre at a time."""
    hull = list(region.convex_hull.exterior.coords)
    angles = {round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180, 6)
              for a, b in zip(hull, hull[1:], strict=False) if math.dist(a, b) > FIT_STEP_M}
    room = region.buffer(FIT_TOL_M)
    for angle in sorted(angles):
        for turn in (angle, angle + 90):
            turned = affinity.rotate(room, -turn, origin=region.centroid)
            minx, miny, maxx, maxy = turned.bounds
            x = minx
            while x + length_m <= maxx + FIT_TOL_M:
                y = miny
                while y + depth_m <= maxy + FIT_TOL_M:
                    if turned.contains(box(x, y, x + length_m, y + depth_m)):
                        return True
                    y += FIT_STEP_M
                x += FIT_STEP_M
    return False


def own_areas(reference: TowerPrototype) -> dict[str, float]:
    """Each flat type's own area in a double-loaded block: a flat is the same flat in every plate
    (the architect, 2026-10-13: a flat type's saleable stays fixed)."""
    own: dict[str, float] = {}
    for module in reference.modules:
        own.setdefault(module.type_id, module.shape.area_sqm)
    return own


__all__ = ["PLATE_SOURCE", "Plate", "PlateAccount", "account", "fits", "kit_for", "own_areas",
           "plate", "plates_for", "preliminary", "shortlist"]
