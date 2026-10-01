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
# The three massing strategies an architect is shown. These are design choices, not law: no
# order limits a block's cores or length (constraints.py, ENGINE_DESIGN_ASSUMPTION).
BALANCED_MAX_CORES = 2
BALANCED_MAX_LENGTH_M = 75.0  # medium blocks: a two-core slab of the longest kind is ~100 m
CONVENTIONAL_MAX_CORES = 1
# (key, label, most cores in any tower, longest tower): A is whatever yields most; B medium
# blocks of up to two cores; C compact one-core towers.
STRATEGIES = (
    ("A", "Maximum yield", None, None),
    ("B", "Balanced development", BALANCED_MAX_CORES, BALANCED_MAX_LENGTH_M),
    ("C", "Conventional smaller towers", CONVENTIONAL_MAX_CORES, None),
)


def fits_strategy(towers, cores: int | None, length_m: float | None) -> bool:
    """Whether a set of towers is of a strategy's kind: no tower over its cores or its length,
    and (so balanced and conventional differ) the largest towers have exactly its cores, or,
    for the balanced kind, more than the conventional one."""
    most = max((len(t.cores) for t in towers), default=0)
    if length_m is not None and max((t.length_m for t in towers), default=0) > length_m + EPS_M:
        return False
    if cores is None:
        return True
    floor = CONVENTIONAL_MAX_CORES + 1 if cores > CONVENTIONAL_MAX_CORES else cores
    return floor <= most <= cores
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
    stilt_in_rule_height: bool = Field(
        True, description="Whether the stilt counts in the height that picks the Table IV row "
        "and the high-rise class. True is the engine's reading of rule 2(e) (an "
        "UNRESOLVED_INTERPRETATION); a test profile may set False. NBC's fire height always "
        "counts it")
    circulation_in_setback: bool = Field(
        False, description="Whether the perimeter driveway and fire lane may run inside the "
        "Table IV setback band, towers standing at the setback itself. False keeps the 9 m loop "
        "road outside the setback; a test profile may set True (reported UNVERIFIED)")
    conservative_parking: bool = Field(
        False, description="Test mode: when whose rules apply is not established, plan the "
        "stricter GHMC parking column instead of stopping to ask")
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
        """The physical height, stilt included: what NBC's fire rules measure."""
        return self.stilt_height_m + self.floors * self.floor_height_m

    @property
    def rule_height_m(self) -> float:
        """The height that picks the Table IV row and the high-rise class."""
        return self.height_m if self.stilt_in_rule_height else self.floors * self.floor_height_m


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
    height_m: float = 0.0  # the height the Table IV rules used
    dropped: tuple[str, ...] = ()  # why towers were dropped while the ground was laid
    physical_height_m: float = 0.0  # stilt included, as NBC measures it
    strategy: str = ""  # which massing strategy picked it (STRATEGIES)

    @property
    def max_cores(self) -> int:
        """The most cores any one tower has."""
        return max((len(t.cores) for t in self.towers), default=0)

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
            "strategy": self.strategy,
            "orientation_deg": round(self.orientation_deg, 1),
            "height_m": round(self.height_m, 2),
            "rule_height_m": round(self.height_m, 2),
            "physical_height_m": round(self.physical_height_m or self.height_m, 2),
            "towers_detail": [t.detail(self.floors) for t in self.towers],
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
    stopped: bool = False  # nothing was tried: an input is missing, or the site is not supported


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
    height = request.rule_height_m
    if height < rules.HIGH_RISE_THRESHOLD_M:
        raise ValueError(f"{height:g} m is not high-rise; Table III setbacks are not encoded yet")
    band = rules.band_for_height(height)
    if band is None:
        raise ValueError(f"{height:g} m is above the encoded Table IV rows")
    stop = stop_reason(plot, request, facts)
    if stop:
        return Search(stopped=True, problem=stop)
    percent, basis = parking_percent(facts.authority, facts.inside_cure,
                                     facts.jurisdiction_confirmed, request.conservative_parking)
    fr = frame(plot, band.min_open_space_m, facts.gross_area_sqm, facts.keep_out,
               facts.access_side, request.circulation_in_setback)
    if fr is None:
        return Search(problem="no land for towers inside the setbacks and the loop road")
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
    result.options = pick_strategies(passing, request.options)
    return result


def stop_reason(plot: Polygon, request: LayoutRequest, facts: SiteFacts) -> str | None:
    """Why nothing can be tried on this site at any height, before anything is drawn: the site
    is not a Group Development Scheme (layouts without rule 8(m) roads are not supported), or
    whose rules apply is open and decides the parking share. None when the search can run."""
    site_sqm = facts.gross_area_sqm or plot.area
    if not rules.is_group_development(site_sqm):
        return (f"site {site_sqm:,.0f} m², under the {rules.GROUP_DEVELOPMENT_MIN_SITE_SQM:,.0f} "
                "m² of a Group Development Scheme (rule 2(c)): rule 8(m)'s internal roads do not "
                "apply, and layouts without them are not supported yet")
    percent, basis = parking_percent(facts.authority, facts.inside_cure,
                                     facts.jurisdiction_confirmed, request.conservative_parking)
    return basis if percent is None else None


def _rank(fr: Frame, library: FlatLibrary, request: LayoutRequest, ctx: Context
          ) -> tuple[list[tuple[float, Placement]], Counter]:
    """Every placement, its towers cut down until the ground fits by area, best first; and
    why the placements that kept no tower lost their last one."""
    pitch = library.tower_depth_m + fr.corridor_m + EPS_M
    steps = max(1, int(pitch // SWEEP_STEP_M))
    lengths = ((request.max_tower_length_m,) if request.max_tower_length_m
               else EXPLORED_TOWER_LENGTHS_M)
    # Every length explored, and the smaller blocks the balanced and conventional strategies
    # look for: at most two cores, and one.
    firm = request.max_tower_length_m  # the firm's longest block always wins over a strategy's

    def capped(length: float | None) -> float | None:
        return lengths[0] if length is None else (min(length, firm) if firm else length)

    shapes = [*((cap, None) for cap in lengths),
              *((capped(length), cores) for _, _, cores, length in STRATEGIES if cores)]
    ranked: list[tuple[float, Placement]] = []
    failures: Counter = Counter()
    for angle in orientations(fr.plot):
        for i in range(steps):
            for cap, cores in shapes:
                placement = place(fr.envelope, angle, i * SWEEP_STEP_M, library,
                                  request.unit_mix, request.min_flats_per_side, fr.corridor_m,
                                  cap, cores)
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
    # The best few of each strategy's blocks reach the checker, whatever their rank by area.
    for _, _, cores, length in STRATEGIES:
        if cores is None:
            continue
        fitting = [p for _, p in ranked if fits_strategy(p.towers, cores, length)]
        for placement in fitting[:3]:
            best_of.setdefault(("strategy", cores, id(placement)), placement)
    chosen = list(best_of.values())[:size + 6]
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


def pick_strategies(options: list[LayoutOption], count: int) -> list[LayoutOption]:
    """One option per massing strategy (STRATEGIES), each the best that passes within its
    limit on cores per tower and a different idea from those already chosen; then, if more are
    asked, the best remaining distinct ideas. A strategy nothing passes for is left out."""
    chosen: list[LayoutOption] = []
    ranked = sorted(options, key=lambda o: -o.score)
    for key, label, cores, length in STRATEGIES:
        for option in ranked:
            if not fits_strategy(option.towers, cores, length):
                continue
            if any(option is kept or same_idea(option, kept) for kept in chosen):
                continue
            chosen.append(LayoutOption(**{**option.__dict__,
                                          "strategy": f"Option {key}: {label}"}))
            break
    wanted = len(chosen) + max(0, count - len(STRATEGIES))  # more only when more are asked
    for option in ranked:
        if len(chosen) >= wanted:
            break
        if not any(option is kept or same_idea(option, kept) for kept in chosen):
            chosen.append(option)
    return chosen


def missing_strategies(options: list[LayoutOption]) -> list[str]:
    """The strategies no passing layout was found for, said plainly, never filled in."""
    found = {o.strategy for o in options}
    def kind(cores: int, length: float | None) -> str:
        size = f", none longer than {length:g} m" if length else ""
        return f"towers of {cores} core{'s' if cores > 1 else ''}{size}"

    return [f"Option {key}: {label}: no layout of {kind(cores, length)} passed every rule"
            for key, label, cores, length in STRATEGIES
            if cores and f"Option {key}: {label}" not in found]


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
        ramps=plan.ramps, parking=plan, height_m=request.rule_height_m, dropped=ground.dropped,
        physical_height_m=request.height_m,
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
        buildings=tuple(Building(t.name, height_m=option.height_m, footprint=t.footprint,
                                 physical_height_m=option.physical_height_m or None)
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
