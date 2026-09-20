"""Stage 2a layout solver: place slab towers built from a flat library inside the rules envelope.

A deterministic "test-fit" search. No language model is involved and no geometry is guessed:
1. envelope = plot shrunk by the Table IV open space for the requested height;
2. for orientations aligned with the plot's longest edges, and for column offsets swept
   across one pitch, lay parallel slab columns spaced by the Table IV block gap;
3. fill every free stretch of each column with towers made of flats and cores, choosing
   each next flat by how far its category is below the requested unit mix;
4. reserve organized open space: drop the smallest towers until the leftover pockets
   (at least 3 m wide, 50 m² each) reach 10% of the plot;
5. rank by saleable area discounted by unit-mix error, keep distinct options, and
   re-check every option with the Stage 1 rule checker.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from siteplan import rules
from siteplan.amenities import club_house, driveway_ring
from siteplan.area_statement import AreaStatement, FloorLine, TowerGroup
from siteplan.checks import Building, Finding, Site, check_site
from siteplan.geometry import angle_gap, opening, straight_runs
from siteplan.library import FlatLibrary, FlatType
from siteplan.units import sqm_to_sqft, sqm_to_sqyd

EPS_M = 0.01  # added to every minimum so floating-point noise can never break a rule
SWEEP_STEP_M = 1.0


class LayoutRequest(BaseModel):
    """What the architect (or, in Stage 2b, the LLM from a brief) asks the solver for."""

    floors: PositiveInt = Field(description="Floors above the stilt")
    stilt_height_m: PositiveFloat = 3.0
    floor_height_m: PositiveFloat = 3.0
    unit_mix: dict[str, float] = Field(
        description="Share of flats per category, e.g. {'2BHK': 0.7, '3BHK': 0.3}"
    )
    common_area_pct: float = Field(22.0, ge=0, le=100)
    club_house_sqm: float | None = Field(
        None, gt=0, description="Club house / amenity block reserved before the towers"
    )
    driveway_width_m: float = Field(
        rules.DRIVEWAY_MIN_WIDTH_M, ge=rules.DRIVEWAY_MIN_WIDTH_M,
        description="Drive around the buildings, inside the setback",
    )
    max_tower_length_m: PositiveFloat = 80.0
    min_flats_per_side: PositiveInt = 2
    options: int = Field(3, ge=1, le=10)

    @model_validator(mode="after")
    def _mix_adds_up(self) -> LayoutRequest:
        if not self.unit_mix or any(v < 0 for v in self.unit_mix.values()):
            raise ValueError("unit_mix needs at least one category and no negative shares")
        total = sum(self.unit_mix.values())
        if abs(total - 1) > 0.01:
            raise ValueError(f"unit_mix shares must add up to 1 (got {total:.3f})")
        return self

    @property
    def height_m(self) -> float:
        return self.stilt_height_m + self.floors * self.floor_height_m


@dataclass(frozen=True)
class Tower:
    name: str
    footprint: Polygon
    flats_per_side: tuple[FlatType, ...]  # along one side; the other side mirrors it
    flat_outlines: tuple[Polygon, ...]
    cores: tuple[Polygon, ...]

    def flats_per_floor(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for flat in self.flats_per_side:
            counts[flat.bhk] = counts.get(flat.bhk, 0) + 2
        return counts

    def saleable_sqft_per_floor(self) -> float:
        return 2 * sum(f.saleable_sqft for f in self.flats_per_side)


@dataclass(frozen=True)
class LayoutOption:
    orientation_deg: float
    towers: tuple[Tower, ...]
    open_space: tuple[Polygon, ...]
    floors: int
    unit_mix_target: dict[str, float]
    plot_area_sqm: float
    findings: tuple[Finding, ...] = ()
    club_house: Polygon | None = None
    driveway: Polygon | None = None

    @property
    def flats_per_floor(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tower in self.towers:
            for bhk, n in tower.flats_per_floor().items():
                counts[bhk] = counts.get(bhk, 0) + n
        return counts

    @property
    def total_flats(self) -> int:
        return sum(self.flats_per_floor.values()) * self.floors

    @property
    def saleable_sqft(self) -> float:
        return sum(t.saleable_sqft_per_floor() for t in self.towers) * self.floors

    @property
    def built_up_sqft_per_floor(self) -> float:
        return sum(sqm_to_sqft(t.footprint.area) for t in self.towers)

    @property
    def open_space_sqm(self) -> float:
        return sum(p.area for p in self.open_space)

    @property
    def open_space_share(self) -> float:
        return self.open_space_sqm / self.plot_area_sqm

    @property
    def mix_error(self) -> float:
        """Half the summed gap between achieved and requested shares (0 = exact, 1 = disjoint)."""
        counts = self.flats_per_floor
        total = sum(counts.values()) or 1
        keys = set(counts) | set(self.unit_mix_target)
        return 0.5 * sum(
            abs(counts.get(k, 0) / total - self.unit_mix_target.get(k, 0)) for k in keys
        )

    @property
    def score(self) -> float:
        return self.saleable_sqft * (1 - self.mix_error)

    def summary(self) -> dict:
        counts = self.flats_per_floor
        total = sum(counts.values()) or 1
        return {
            "orientation_deg": round(self.orientation_deg, 1),
            "towers": len(self.towers),
            "flats_per_floor": counts,
            "unit_mix_achieved": {k: round(v / total, 3) for k, v in sorted(counts.items())},
            "total_flats": self.total_flats,
            "saleable_sqft": round(self.saleable_sqft),
            "built_up_sqft_per_floor": round(self.built_up_sqft_per_floor),
            "open_space_sqm": round(self.open_space_sqm, 1),
            "open_space_share_pct": round(self.open_space_share * 100, 2),
            "mix_error": round(self.mix_error, 3),
            "club_house_sqm": round(self.club_house.area, 1) if self.club_house else 0,
            "driveway_sqm": round(self.driveway.area, 1) if self.driveway else 0,
            "rule_findings": {f.rule: f.status.value for f in self.findings},
        }


def orientations(plot: Polygon) -> list[float]:
    """Tower directions worth trying: along and across the plot's three longest edges."""
    angles: list[float] = []
    for run in sorted(straight_runs(plot), key=lambda r: -r.length)[:3]:
        for angle in (run.angle_deg, (run.angle_deg + 90) % 180):
            if all(angle_gap(angle, other) > 5 for other in angles):
                angles.append(angle)
    return angles


def _parts(geometry) -> list[Polygon]:
    parts = getattr(geometry, "geoms", [geometry])
    return [p for p in parts if isinstance(p, Polygon) and not p.is_empty]


def free_stretches(envelope, x0: float, width: float) -> list[tuple[float, float]]:
    """Y-ranges where a full-width strip [x0, x0 + width] lies inside the envelope.

    Exact for axis-aligned rectangles: anything of the strip outside the envelope blocks
    its whole y-range, because a tower spans the strip's full width."""
    _, miny, _, maxy = envelope.bounds
    strip = box(x0, miny - 1, x0 + width, maxy + 1)
    blocked = sorted((p.bounds[1], p.bounds[3]) for p in _parts(strip.difference(envelope)))
    stretches, y = [], miny - 1
    for lo, hi in blocked:
        if lo > y:
            stretches.append((y, lo))
        y = max(y, hi)
    if y < maxy + 1:
        stretches.append((y, maxy + 1))
    return [(a, b) for a, b in stretches if b - a > 0]


class _MixTracker:
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


def _length(flats: list[FlatType], library: FlatLibrary) -> float:
    cores = math.ceil(len(flats) / library.flats_per_core_per_side)
    return sum(f.width_m for f in flats) + cores * library.core_width_m


def compose_tower(
    available_m: float, library: FlatLibrary, mix: _MixTracker, min_per_side: int
) -> list[FlatType] | None:
    flats: list[FlatType] = []
    pending: dict[str, int] = {}
    while True:
        for flat in mix.next_choices(library, pending):
            if _length([*flats, flat], library) <= available_m + 1e-9:
                flats.append(flat)
                pending[flat.bhk] = pending.get(flat.bhk, 0) + 2
                break
        else:
            break
    if len(flats) < min_per_side:
        return None
    for bhk, n in pending.items():
        mix.counts[bhk] = mix.counts.get(bhk, 0) + n
    return flats


def _build_tower(
    name: str, x0: float, y0: float, flats: list[FlatType], library: FlatLibrary, alpha: float
) -> Tower:
    """Lay out one tower in the rotated frame, then rotate it back onto the site."""
    depth = flats[0].depth_m
    width = library.tower_depth_m
    k = library.flats_per_core_per_side
    groups = [flats[i : i + k] for i in range(0, len(flats), k)]
    outlines, cores, y = [], [], y0
    for group in groups:
        half = math.ceil(len(group) / 2)
        for position, flat in enumerate(group):
            if position == half:
                cores.append(box(x0, y, x0 + width, y + library.core_width_m))
                y += library.core_width_m
            outlines.append(box(x0, y, x0 + depth, y + flat.width_m))
            outlines.append(box(x0 + width - depth, y, x0 + width, y + flat.width_m))
            y += flat.width_m
        if half >= len(group):
            cores.append(box(x0, y, x0 + width, y + library.core_width_m))
            y += library.core_width_m

    def back(p: Polygon) -> Polygon:
        return affinity.rotate(p, -alpha, origin=(0, 0))

    return Tower(
        name=name,
        footprint=back(box(x0, y0, x0 + width, y)),
        flats_per_side=tuple(flats),
        flat_outlines=tuple(back(p) for p in outlines),
        cores=tuple(back(p) for p in cores),
    )


def open_space_pockets(envelope, towers: list[Tower], gap_m: float) -> list[Polygon]:
    """Organized open space left over: inside the setback envelope, outside the block
    gaps (which may not count as tot-lot), at least 3 m wide and 50 m² per pocket."""
    taken = unary_union([t.footprint.buffer(gap_m / 2, join_style="mitre") for t in towers])
    free = envelope.difference(taken) if towers else envelope
    usable = opening(free, rules.OPEN_SPACE_MIN_WIDTH_M + 2 * EPS_M)
    return [p for p in _parts(usable) if p.area >= rules.OPEN_SPACE_MIN_POCKET_SQM + EPS_M]


def _one_layout(plot, envelope, angle, offset, library, request, gap,
                club=None, drive=None) -> LayoutOption | None:
    alpha = 90 - angle  # rotate the site so the towers' long axis runs along y
    rotated = affinity.rotate(envelope, alpha, origin=(0, 0))
    minx, _, maxx, _ = rotated.bounds
    width = library.tower_depth_m
    mix = _MixTracker(request.unit_mix)
    towers: list[Tower] = []
    x = minx + offset
    while x + width <= maxx + 1e-9:
        for lo, hi in free_stretches(rotated, x, width):
            y = lo
            while hi - y > 0:
                available = min(hi - y, request.max_tower_length_m)
                flats = compose_tower(available, library, mix, request.min_flats_per_side)
                if flats is None:
                    break
                tower = _build_tower(f"T{len(towers) + 1}", x, y, flats, library, alpha)
                towers.append(tower)
                y += _length(flats, library) + gap + EPS_M
        x += width + gap + EPS_M

    pockets = open_space_pockets(envelope, towers, gap)
    target = rules.OPEN_SPACE_MIN_FRACTION * plot.area
    while towers and sum(p.area for p in pockets) < target:
        towers.remove(min(towers, key=lambda t: t.saleable_sqft_per_floor()))
        pockets = open_space_pockets(envelope, towers, gap)
    if not towers:
        return None
    named = tuple(
        Tower(f"T{i}", t.footprint, t.flats_per_side, t.flat_outlines, t.cores)
        for i, t in enumerate(towers, 1)
    )
    return LayoutOption(
        orientation_deg=angle,
        towers=named,
        open_space=tuple(pockets),
        floors=request.floors,
        unit_mix_target=dict(request.unit_mix),
        plot_area_sqm=plot.area,
        club_house=club,
        driveway=drive,
    )


def solve(
    plot: Polygon,
    library: FlatLibrary,
    request: LayoutRequest,
    *,
    gross_area_sqm: float | None = None,
    abutting_road_m: float | None = None,
    master_plan_road_m: float | None = None,
) -> list[LayoutOption]:
    """Best distinct layouts for the plot, each already re-checked against the rules."""
    unknown = set(request.unit_mix) - library.categories
    if unknown:
        raise ValueError(f"unit_mix asks for {sorted(unknown)}, not in the flat library")
    height = request.height_m
    if height < rules.HIGH_RISE_THRESHOLD_M:
        raise ValueError(
            f"{height:g} m is not high-rise; Table III setbacks are not encoded yet"
        )
    band = rules.band_for_height(height)
    if band is None:
        raise ValueError(f"{height:g} m is above the encoded Table IV rows (55 m)")
    gap = band.min_open_space_m
    envelope = plot.buffer(-(band.min_open_space_m + EPS_M))
    if envelope.is_empty:
        return []

    # Amenities take their land first, as they do on a real site plan.
    drive = driveway_ring(plot, envelope, request.driveway_width_m)
    club = club_house(envelope, request.club_house_sqm) if request.club_house_sqm else None
    if request.club_house_sqm and club is None:
        raise ValueError(
            f"a club house of {request.club_house_sqm:,.0f} m² does not fit inside the setbacks"
        )
    if club is not None:
        envelope = envelope.difference(club.buffer(gap + EPS_M, join_style="mitre"))
        if envelope.is_empty:
            return []

    pitch = library.tower_depth_m + gap + EPS_M
    steps = max(1, int(pitch // SWEEP_STEP_M))
    candidates = [
        option
        for angle in orientations(plot)
        for i in range(steps)
        if (option := _one_layout(plot, envelope, angle, i * SWEEP_STEP_M, library, request, gap,
                                  club, drive))
    ]
    candidates.sort(key=lambda o: -o.score)

    # Options must differ in substance, not just by a few degrees of rotation.
    chosen: list[LayoutOption] = []
    seen: set[tuple] = set()
    for option in candidates:
        signature = (len(option.towers), option.total_flats, round(option.saleable_sqft, -3))
        if signature not in seen:
            seen.add(signature)
            chosen.append(option)
        if len(chosen) == request.options:
            break

    return [
        _with_findings(o, plot, request, gross_area_sqm, abutting_road_m, master_plan_road_m)
        for o in chosen
    ]


def _with_findings(option, plot, request, gross, road, master_road) -> LayoutOption:
    site = Site(
        gross_area_sqm=gross,
        net_area_sqm=plot.area,
        abutting_road_m=road,
        master_plan_road_m=master_road,
        open_space_sqm=option.open_space_sqm,
        net_plot=plot,
        open_space_pockets=option.open_space,
        buildings=tuple(
            Building(t.name, height_m=request.height_m, footprint=t.footprint)
            for t in option.towers
        ),
        club_house=option.club_house,
        driveway=option.driveway,
    )
    return LayoutOption(**{**option.__dict__, "findings": tuple(check_site(site))})


def area_statement(option: LayoutOption, request: LayoutRequest) -> AreaStatement:
    """The firm-format area statement for an option; identical towers are grouped."""
    groups: dict[tuple, list[str]] = {}
    for tower in option.towers:
        flats = tuple(f.name for f in tower.flats_per_side)
        key = (round(sqm_to_sqft(tower.footprint.area)), flats)
        groups.setdefault(key, []).append(tower.name.removeprefix("T"))
    return AreaStatement(
        site_area_sqyd=sqm_to_sqyd(option.plot_area_sqm),
        open_space_sqft=sqm_to_sqft(option.open_space_sqm),
        groups=[
            TowerGroup(
                name=f"TOWER - {', '.join(names)}",
                storeys=f"STILT + {request.floors} FLOORS",
                common_area_pct=request.common_area_pct,
                floors=[
                    FloorLine(
                        label="TYPICAL", area_sqft=area_sqft * len(names), count=request.floors
                    )
                ],
            )
            for (area_sqft, _), names in groups.items()
        ],
    )
