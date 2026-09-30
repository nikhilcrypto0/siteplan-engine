"""Stage 2a layout solver: towers from the flat library, placed with every site requirement active.

A deterministic test-fit search. No language model is involved and no geometry is guessed:
1. for the height asked, `grounds.frame` fixes the towers' land (the plot less the Table IV
   setback, or less the green strip and the 9 m loop road where those need more), the loop road,
   the main entrance on the access side and the green strip;
2. for orientations along the plot's longest edges, column offsets swept across one pitch, and
   tower lengths explored (no rule and no firm standard limits a block's length), columns of
   towers are laid a corridor apart, each corridor a 9 m internal road (rule 8(m));
3. `grounds.lay` gives the fire bands, the club house, the cellars and ramp and the tot-lot their
   land on what the roads leave, dropping the smallest tower until all of them fit;
4. the best placements are laid exactly, furnished with the facilities and surface bays, and
   checked by the rule checker, which measures the drawing again. A layout that fails any rule is
   a rejected candidate, never an option. The options are the best that pass, each genuinely
   different from the others.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator
from shapely.geometry import Polygon
from shapely.ops import unary_union

from siteplan import rules
from siteplan.access import Entrance, RoadPiece
from siteplan.area_statement import AreaStatement, FloorLine, TowerGroup
from siteplan.checks import Building, Finding, Site, Status, check_site
from siteplan.geometry import angle_gap
from siteplan.grounds import Context, Frame, Ground, firm_up, frame, lay
from siteplan.library import FlatLibrary
from siteplan.parking import (
    ParkingPlan,
    ParkingStandards,
    bay_area_sqm,
    parking_percent,
    surface_bays,
)
from siteplan.site_amenities import CLEARANCE_M as AMENITY_CLEARANCE_M
from siteplan.site_amenities import AmenityLibrary, PlacedAmenity, place_amenities
from siteplan.towers import Placement, Tower, orientations, place
from siteplan.units import sqm_to_sqft, sqm_to_sqyd

EPS_M = 0.01
SWEEP_STEP_M = 2.0
# No order limits a block's length (G.O.Ms.No.65 of 2019 deleted the 40 m note) and the firm has
# set none, so the search tries whole free stretches and two shorter caps.
EXPLORED_TOWER_LENGTHS_M: tuple[float | None, ...] = (None, 60.0, 45.0)
SHORTLIST = 10  # placements laid exactly, of the hundreds ranked by area alone
SAME_IDEA_OVERLAP = 0.5  # two layouts sharing this much tower ground are one idea
ANGLE_FAMILY_DEG = 10.0  # towers running within this of each other run the same way


class LayoutRequest(BaseModel):
    """What the architect (or, in Stage 2b, the LLM from a brief) asks the solver for."""

    floors: PositiveInt = Field(description="Floors above the stilt")
    stilt_height_m: PositiveFloat = 3.0
    floor_height_m: PositiveFloat = 3.0
    unit_mix: dict[str, float] = Field(
        description="Share of flats per category, e.g. {'2BHK': 0.7, '3BHK': 0.3}"
    )
    common_area_pct: float = Field(22.0, ge=0, le=100)
    club_house: bool = Field(True, description="Reserve an amenities block before the towers")
    club_house_sqm: float | None = Field(
        None, gt=0, description="Amenities built-up area; left out, it follows rule 15(a)(x)"
    )
    club_house_floors: PositiveInt = Field(
        2, description="Storeys in the amenities block; it needs a footprint of a fraction"
    )
    max_tower_length_m: PositiveFloat | None = Field(
        None, description="The firm's longest block, if it has one; left out, lengths are "
        "explored, since no rule limits them")
    min_flats_per_side: PositiveInt = 2
    cellar_floor_height_m: PositiveFloat = Field(
        3.0, description="Floor to floor of a cellar: the rise each 1 in 8 ramp climbs")
    cellar_utilities_pct: float = Field(
        rules.CELLAR_UTILITIES_MAX_FRACTION * 100, ge=0,
        le=rules.CELLAR_UTILITIES_MAX_FRACTION * 100,
        description="Share of each cellar kept for utilities; rule 13(c)(xi) allows up to 10%")
    max_cellars: int = Field(3, ge=0, le=6, description="The deepest the search will dig: a "
                             "search bound, not a rule")
    options: int = Field(3, ge=1, le=10)
    maximise: bool = Field(
        False, description="floors is the most the rules allow; search every height from there "
        "down and keep the layouts that pass")

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
class SiteFacts:
    """What the site brings to a layout besides its shape."""

    gross_area_sqm: float | None = None
    abutting_road_m: float | None = None
    master_plan_road_m: float | None = None
    authority: str | None = None
    inside_cure: bool | None = None
    keep_out: Polygon | None = None
    access_side: str | None = None
    road_dead_end: bool | None = None
    street_joins_12m: bool | None = None
    jurisdiction_confirmed: bool = True
    site_coordinates: tuple[float, float] | None = None


@dataclass(frozen=True)
class LayoutOption:
    orientation_deg: float
    towers: tuple[Tower, ...]
    open_space: tuple[Polygon, ...]
    floors: int
    unit_mix_target: dict[str, float]
    plot_area_sqm: float
    findings: tuple[Finding, ...] = ()
    club_house: Polygon | None = None  # footprint; it may have more than one floor
    club_house_floors: int = 1
    parking_bays: tuple[Polygon, ...] = ()
    amenities: tuple[PlacedAmenity, ...] = ()
    amenities_missed: tuple[str, ...] = ()
    roads: tuple[RoadPiece, ...] = ()
    fire_lanes: Polygon | None = None
    green_strip: Polygon | None = None
    entrance: Entrance | None = None
    ramps: tuple[Polygon, ...] = ()
    parking: ParkingPlan | None = None
    height_m: float = 0.0
    dropped: tuple[str, ...] = ()  # why towers were dropped while the ground was laid

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
    def tower_floor_sqm(self) -> float:
        """Every floor of every tower, wall to wall: the gross residential floor area."""
        return sum(t.footprint.area for t in self.towers) * self.floors

    @property
    def flats_own_sqm(self) -> float:
        """The flats' own outlines, every floor: what is left of the plate without the corridor,
        the lifts and the stairs."""
        return sum(sum(f.area for f in t.flat_outlines) for t in self.towers) * self.floors

    @property
    def common_core_sqm(self) -> float:
        """Corridors, lift and stair cores: the plate less the flats."""
        return self.tower_floor_sqm - self.flats_own_sqm

    @property
    def saleable_sqft(self) -> float:
        """What the flats sell as: each flat's own sale area from the flat library, times the
        flats placed. The plate is not saleable area; the flats are."""
        return sum(t.saleable_sqft_per_floor() for t in self.towers) * self.floors

    @property
    def built_up_sqft_per_floor(self) -> float:
        return sum(sqm_to_sqft(t.footprint.area) for t in self.towers)

    @property
    def club_house_sqm(self) -> float:
        """The amenities block's built-up area, all its floors."""
        return 0.0 if self.club_house is None else self.club_house.area * self.club_house_floors

    @property
    def built_up_sqm(self) -> float:
        """Every floor of every block, amenities included: what the rules measure against."""
        return self.tower_floor_sqm + self.club_house_sqm

    @property
    def open_space_sqm(self) -> float:
        return sum(p.area for p in self.open_space)

    @property
    def open_space_share(self) -> float:
        return self.open_space_sqm / self.plot_area_sqm

    @property
    def mix_error(self) -> float:
        """Half the summed gap between achieved and requested shares (0 = exact, 1 = disjoint)."""
        return mix_error(self.flats_per_floor, self.unit_mix_target)

    @property
    def score(self) -> float:
        return self.saleable_sqft * (1 - self.mix_error)

    @property
    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.status is Status.FAIL]

    def summary(self) -> dict:
        counts = self.flats_per_floor
        total = sum(counts.values()) or 1
        tower_floor = sqm_to_sqft(self.tower_floor_sqm)
        return {
            "orientation_deg": round(self.orientation_deg, 1),
            "height_m": round(self.height_m, 2),
            "towers": len(self.towers),
            "tower_lengths_m": [round(t.length_m, 1) for t in self.towers],
            "flats_per_floor": counts,
            "flats_by_type": {k: n * self.floors for k, n in sorted(counts.items())},
            "unit_mix_achieved": {k: round(v / total, 3) for k, v in sorted(counts.items())},
            "total_flats": self.total_flats,
            # The four areas are not interchangeable (see AGENTS.md).
            "tower_floor_sqft": round(tower_floor),
            "flats_own_sqft": round(sqm_to_sqft(self.flats_own_sqm)),
            "common_core_sqft": round(sqm_to_sqft(self.common_core_sqm)),
            "core_share_pct": round(self.common_core_sqm / self.tower_floor_sqm * 100, 1)
            if self.tower_floor_sqm else 0.0,
            "saleable_sqft": round(self.saleable_sqft),
            "saleable_basis": "each flat's sale area in the flat library, times the flats placed",
            "built_up_sqft": round(sqm_to_sqft(self.built_up_sqm)),
            "built_up_sqft_per_floor": round(self.built_up_sqft_per_floor),
            "amenity_sqft": round(sqm_to_sqft(self.club_house_sqm)),
            "open_space_sqm": round(self.open_space_sqm, 1),
            "open_space_share_pct": round(self.open_space_share * 100, 2),
            "mix_error": round(self.mix_error, 3),
            "club_house_sqm": round(self.club_house_sqm, 1),
            "club_house_footprint_sqm": round(self.club_house.area, 1) if self.club_house else 0,
            "roads": [r.as_dict() for r in self.roads],
            "fire_lanes_sqm": round(self.fire_lanes.area, 1) if self.fire_lanes else 0,
            "parking": self.parking.as_dict() if self.parking else {},
            "parking_sqft": round(sqm_to_sqft(self.parking.provided_sqm)) if self.parking else 0,
            "surface_parking_bays": len(self.parking_bays),
            "amenities": [a.as_dict() for a in self.amenities],
            "amenities_with_no_room": list(self.amenities_missed),
            "rule_findings": {f.rule: f.status.value for f in self.findings},
            "towers_dropped_because": list(self.dropped),
        }


def mix_error(counts: dict[str, int], target: dict[str, float]) -> float:
    total = sum(counts.values()) or 1
    keys = set(counts) | set(target)
    return 0.5 * sum(abs(counts.get(k, 0) / total - target.get(k, 0)) for k in keys)


@dataclass(frozen=True)
class Rejected:
    """A layout that was drawn and failed, or could not be drawn at all, and why."""

    towers: int
    orientation_deg: float
    reasons: tuple[str, ...]
    saleable_sqft: float = 0.0


@dataclass
class Search:
    options: list[LayoutOption] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    considered: int = 0  # placements ranked
    problem: str = ""  # why there is nothing at all, when there is nothing


def solve(plot: Polygon, library: FlatLibrary, request: LayoutRequest, *,
          amenities: AmenityLibrary | None = None, standards: ParkingStandards | None = None,
          **facts) -> list[LayoutOption]:
    """The best distinct layouts for the plot that pass every rule the checker applies."""
    return search(plot, library, request, SiteFacts(**facts), amenities, standards).options


def search(plot: Polygon, library: FlatLibrary, request: LayoutRequest, facts: SiteFacts,
           amenities: AmenityLibrary | None = None,
           standards: ParkingStandards | None = None) -> Search:
    """Every passing layout worth showing at this height, and the candidates that failed."""
    unknown = set(request.unit_mix) - library.categories
    if unknown:
        raise ValueError(f"unit_mix asks for {sorted(unknown)}, not in the flat library")
    height = request.height_m
    if height < rules.HIGH_RISE_THRESHOLD_M:
        raise ValueError(f"{height:g} m is not high-rise; Table III setbacks are not encoded yet")
    band = rules.band_for_height(height)
    if band is None:
        raise ValueError(f"{height:g} m is above the encoded Table IV rows")
    fr = frame(plot, band.min_open_space_m, facts.gross_area_sqm, facts.keep_out,
               facts.access_side)
    if fr is None:
        return Search(problem="no land for towers inside the setbacks and the loop road")
    percent, basis = parking_percent(facts.authority, facts.inside_cure,
                                     facts.jurisdiction_confirmed)
    standards = standards or ParkingStandards(
        cellar_floor_height_m=request.cellar_floor_height_m,
        utilities_fraction=request.cellar_utilities_pct / 100, max_cellars=request.max_cellars)
    ctx = Context(request.floors, request.club_house, request.club_house_sqm,
                  request.club_house_floors, percent, basis, standards)
    ranked, failures = _rank(fr, library, request, ctx)
    result = Search(considered=len(ranked))
    if not ranked:
        common = "; ".join(reason for reason, _ in failures.most_common(2))
        result.problem = ("no placement keeps a tower once the roads, fire lanes and the rest "
                          f"are laid: {common or 'no tower fits the towers land'}")
    passing: list[LayoutOption] = []
    for placement in _shortlist(ranked, request):
        ground, reasons = lay(fr, placement, ctx)
        if ground is None:
            result.rejected.append(Rejected(len(placement.towers), placement.angle_deg,
                                            tuple(reasons)))
            continue
        option = _furnish(fr, ground, placement.angle_deg, request, amenities, ctx, facts)
        if option.fails:
            result.rejected.append(Rejected(
                len(option.towers), option.orientation_deg,
                tuple(f"{f.rule}: {f.measured}" for f in option.fails), option.saleable_sqft))
        else:
            passing.append(option)
    result.options = pick_distinct(passing, request.options)
    return result


def _rank(fr: Frame, library: FlatLibrary, request: LayoutRequest, ctx: Context
          ) -> tuple[list[tuple[float, Placement]], Counter]:
    """Every placement, its towers cut down until the ground fits by area, best first; and
    why the placements that kept no tower lost their last one."""
    pitch = library.tower_depth_m + fr.corridor_m + EPS_M
    steps = max(1, int(pitch // SWEEP_STEP_M))
    caps = ((request.max_tower_length_m,) if request.max_tower_length_m
            else EXPLORED_TOWER_LENGTHS_M)
    ranked: list[tuple[float, Placement]] = []
    failures: Counter = Counter()
    for angle in orientations(fr.plot):
        for i in range(steps):
            for cap in caps:
                placement = place(fr.envelope, angle, i * SWEEP_STEP_M, library,
                                  request.unit_mix, request.min_flats_per_side, fr.corridor_m,
                                  cap)
                if not placement.towers:
                    continue
                ground, reasons = lay(fr, placement, ctx, quick=True)
                if ground is None:
                    failures[reasons[-1] if reasons else "no tower fits"] += 1
                    continue
                kept = Placement(placement.angle_deg, ground.towers, placement.columns,
                                 placement.depth_m, placement.corridor_m)
                ranked.append((_placement_score(kept, request), kept))
    ranked.sort(key=lambda pair: -pair[0])
    return ranked, failures


def _placement_score(placement: Placement, request: LayoutRequest) -> float:
    counts: dict[str, int] = {}
    for tower in placement.towers:
        for bhk, n in tower.flats_per_floor().items():
            counts[bhk] = counts.get(bhk, 0) + n
    sale = sum(t.saleable_sqft_per_floor() for t in placement.towers) * request.floors
    return sale * (1 - mix_error(counts, request.unit_mix))


def _shortlist(ranked, request: LayoutRequest) -> list[Placement]:
    """The placements worth laying exactly: the best of every massing (a tower count and a
    direction) first, so different ideas reach the checker, then the next best of any."""
    size = max(SHORTLIST, request.options * 3)
    best_of: dict[tuple, Placement] = {}
    for _, placement in ranked:
        best_of.setdefault(_massing(placement.towers, placement.angle_deg), placement)
    chosen = list(best_of.values())[:size]
    seen = {id(p) for p in chosen}
    for _, placement in ranked:
        if len(chosen) >= size:
            break
        if id(placement) not in seen:
            chosen.append(placement)
            seen.add(id(placement))
    return chosen


def _massing(towers, angle_deg: float) -> tuple[int, int]:
    """How many towers, running which way (to the nearest ANGLE_FAMILY_DEG, modulo 180)."""
    return len(towers), round((angle_deg % 180) / ANGLE_FAMILY_DEG) % round(180 / ANGLE_FAMILY_DEG)


def pick_distinct(options: list[LayoutOption], count: int) -> list[LayoutOption]:
    """The best options that are genuinely different ideas (see same_idea), best first."""
    chosen: list[LayoutOption] = []
    for option in sorted(options, key=lambda o: -o.score):
        if any(same_idea(option, kept) for kept in chosen):
            continue
        chosen.append(option)
        if len(chosen) == count:
            break
    return chosen


def same_idea(a: LayoutOption, b: LayoutOption) -> bool:
    """Two layouts are one idea when they have as many towers running the same way on mostly
    the same ground, whatever their height: one floor less is not another scheme."""
    if len(a.towers) != len(b.towers):
        return False
    if angle_gap(a.orientation_deg, b.orientation_deg) > ANGLE_FAMILY_DEG:
        return False
    ground_a = unary_union([t.footprint for t in a.towers])
    ground_b = unary_union([t.footprint for t in b.towers])
    union = ground_a.union(ground_b).area
    return union > 0 and ground_a.intersection(ground_b).area / union >= SAME_IDEA_OVERLAP


def _furnish(fr: Frame, ground: Ground, angle: float, request: LayoutRequest,
             amenities: AmenityLibrary | None, ctx: Context, facts: SiteFacts) -> LayoutOption:
    """Lay the facilities and the surface bays on what is left, count the cars, and check."""
    towers = tuple(Tower(**{**t.__dict__, "name": f"T{i}"}) for i, t in enumerate(ground.towers, 1))
    road_land = unary_union([r.shape for r in ground.roads])
    facilities: tuple[PlacedAmenity, ...] = ()
    missed: tuple[str, ...] = ()
    free = ground.free
    if amenities is not None and free is not None:
        anchors = {"gate": fr.entrance.gate.centroid, "edge": fr.plot.exterior.interpolate(0.0)}
        if ground.club is not None:
            anchors["club"] = ground.club.centroid
        if ground.tot_lot:
            anchors["open space"] = max(ground.tot_lot, key=lambda p: p.area).centroid
        found, missed_names = place_amenities(free, amenities, angle, anchors, ground.tot_lot)
        facilities, missed = tuple(found), tuple(missed_names)
        if facilities:
            free = free.difference(unary_union(
                [f.shape.buffer(AMENITY_CLEARANCE_M, join_style="mitre") for f in facilities]))
    reachable = [p for p in _parts(free) if p.distance(road_land) <= 0.5]
    bays = tuple(surface_bays(unary_union(reachable), angle)) if reachable else ()
    spare = free.difference(unary_union(bays)) if (free is not None and bays) else free
    plan = firm_up(fr, ground, towers, ctx, angle, len(bays), spare, road_land)

    option = LayoutOption(
        orientation_deg=angle, towers=towers, open_space=ground.tot_lot, floors=request.floors,
        unit_mix_target=dict(request.unit_mix), plot_area_sqm=fr.plot.area,
        club_house=ground.club, club_house_floors=request.club_house_floors,
        parking_bays=bays, amenities=facilities, amenities_missed=missed, roads=ground.roads,
        fire_lanes=ground.fire_lanes, green_strip=fr.green, entrance=fr.entrance,
        ramps=plan.ramps, parking=plan, height_m=request.height_m, dropped=ground.dropped,
    )
    return LayoutOption(**{**option.__dict__, "findings": tuple(_check(option, fr, facts))})


def _parts(shape) -> list[Polygon]:
    if shape is None or shape.is_empty:
        return []
    return [shape] if isinstance(shape, Polygon) else [p for p in getattr(shape, "geoms", [])
                                                       if isinstance(p, Polygon)]


def _check(option: LayoutOption, fr: Frame, facts: SiteFacts) -> list[Finding]:
    obstructions = (*(a.shape for a in option.amenities), *option.parking_bays,
                    *option.open_space, *option.ramps)
    site = Site(
        gross_area_sqm=facts.gross_area_sqm,
        net_area_sqm=fr.plot.area,
        abutting_road_m=facts.abutting_road_m,
        master_plan_road_m=facts.master_plan_road_m,
        open_space_sqm=option.open_space_sqm,
        net_plot=fr.plot,
        open_space_pockets=option.open_space,
        buildings=tuple(Building(t.name, height_m=option.height_m, footprint=t.footprint)
                        for t in option.towers),
        club_house=option.club_house,
        club_house_built_up_sqm=option.club_house_sqm,
        built_up_sqm=option.built_up_sqm,
        surface_parking_sqm=bay_area_sqm(len(option.parking_bays)),
        units=option.total_flats,
        authority=facts.authority,
        inside_cure=facts.inside_cure,
        water_buffer=facts.keep_out,
        roads=option.roads,
        entrance=option.entrance,
        fire_lanes=option.fire_lanes,
        green_strip=option.green_strip,
        obstructions=obstructions,
        parking_plan=option.parking,
        road_dead_end=facts.road_dead_end,
        street_joins_12m=facts.street_joins_12m,
    )
    return check_site(site)


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
