"""What a candidate is worth to the architect: seven numbers, each worked out from the candidate's
own prototypes, placements and ground, never from the generator's claims (`metrics` may be
wrong).

- saleable area: every tower's prototype saleable area per floor times its floors;
- units: flats, floors counted the same way;
- open space: the usable part of the open space the candidate draws (C4-12): at least
  OPEN_WIDE_M across, where a lawn, a court or a play area fits, and within OPEN_REACH_M of a
  block, where residents see and reach it; the whole area is kept beside it, unscored (every area
  here is read to 0.01 m², so two layouts the same to a drawing's precision tie, and a later
  measure chooses);
- mix fit: 1 less how far the flats' shares are from the brief's unit mix;
- conventionality: how ordinary the blocks are, 1 for a block with one core and falling as cores
  are added (a long multi-core slab is the less conventional building). More towers break a tie
  between equally conventional layouts: smaller, more numerous blocks come first;
- site use (C4-11): 1 less the share of the net plot that no use takes and no rule keeps open
  (the residual: the candidate's ledger's UNALLOCATED ground less its rule layers' setbacks, gaps,
  fire bands, turning ground, buffers and green strip). Ground a rule keeps open is no waste; what
  is left over for nothing is;
- quality (C4-11): a plain mean of five measures, each 0 to 1, of an ordinary scheme: the share of
  the plot not paved for roads; the share of the blocks of its most used prototype; the share
  running its most used way; the share facing a road or pathway along at least a pathway's width
  (rule 8(l)'s 6 m, the stricter reading of "opens onto", so a block a road meets only at a
  corner counts against the layout under both readings); and 1 over 1 and the residual's pieces
  of FRAGMENT_SQM or more. A score of the search's, never a rule: nothing fails for it.

All are bigger-is-better, so a Pareto front over them (pareto.py) means what it says.
The architect's priorities (DesignBrief.objectives.priorities) are weights over these, used only
to find the balanced compromise; a priority left out counts as 1.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

import shapely
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan import rules
from siteplan.contracts import CandidateLayout, DesignBrief
from siteplan.contracts.accounting import LayerKind, PartitionLedger, PhysicalUse, RuleLayers
from siteplan.contracts.design_brief import Priority
from siteplan.geometry import frontage, opening

AXES = tuple(priority.value for priority in Priority)  # the brief names its priorities by these
FRAGMENT_SQM = 50.0  # a piece of leftover ground this big counts as a fragment (C4-11)
TOUCH_M = 0.5  # a block's outline this close to pavement faces it (the search's own copy)
AREA_DECIMALS = 2  # areas are scored to 0.01 m², so their last digits never choose (C4-11)
OPEN_WIDE_M = 12.0  # open space this wide holds a lawn, a court or a play area (C4-12)
OPEN_REACH_M = 30.0  # and this near a block, its residents see and reach it (C4-12)
KEPT_OPEN = (LayerKind.SETBACK, LayerKind.BLOCK_GAP, LayerKind.FIRE_CLEAR_BAND,
             LayerKind.TURNING_SECTOR, LayerKind.WATER_BUFFER, LayerKind.GREEN_STRIP_ZONE)


def mix_error(counts: dict[str, int], target: dict[str, float]) -> float:
    """Half the summed gap between achieved and requested shares (0 = exact, 1 = disjoint)."""
    total = sum(counts.values()) or 1
    return 0.5 * sum(abs(counts.get(kind, 0) / total - target.get(kind, 0))
                     for kind in set(counts) | set(target))


@dataclass(frozen=True)
class Scores:
    saleable_sqft: float
    units: int
    open_space_sqm: float
    mix_fit: float
    conventionality: float
    towers: int
    site_use: float = 0.0  # 0 where the candidate draws no ledger: unknown is not good
    quality: float = 0.0
    open_space_usable_sqm: float = 0.0  # the open-space axis (C4-12); open_space_sqm is the whole

    @property
    def yield_score(self) -> float:
        """Saleable area less what the mix misses by: what "maximum yield" maximises."""
        return self.saleable_sqft * self.mix_fit

    @property
    def vector(self) -> tuple[float, ...]:
        """The seven bigger-is-better numbers, in AXES order."""
        return (self.saleable_sqft, float(self.units), self.open_space_usable_sqm, self.mix_fit,
                self.conventionality, self.site_use, self.quality)

    def as_dict(self) -> dict[str, float]:
        return {"saleable_sqft": self.saleable_sqft, "units": float(self.units),
                "open_space_sqm": self.open_space_sqm, "mix_fit": self.mix_fit,
                "conventionality": self.conventionality, "towers": float(self.towers),
                "site_use": self.site_use, "quality": self.quality,
                "open_space_usable_sqm": self.open_space_usable_sqm,
                "yield_score": self.yield_score}


def measure(candidate: CandidateLayout, brief: DesignBrief) -> Scores:
    flats: Counter[str] = Counter()
    saleable = 0.0
    conventionality = []  # one number a tower: 1 for a single core, 1/2 for two, and so on
    for tower in candidate.towers:
        prototype = candidate.prototype(tower.prototype_id)
        per_floor, floors = prototype.per_floor, tower.floors_above_stilt
        saleable += per_floor.saleable_sqft * floors
        for kind, count in per_floor.flats_by_type.items():
            flats[kind] += count * floors
        conventionality.append(1 / max(1, prototype.cores))
    towers = len(candidate.towers)
    site_use, quality = _ground_scores(candidate)
    open_space = unary_union([shape.to_shapely() for shape in candidate.program.open_space])
    reach = reach_of(unary_union([candidate.placed_footprint(t) for t in candidate.towers]))
    return Scores(
        saleable_sqft=saleable, units=sum(flats.values()),
        open_space_sqm=round(sum(shape.area_sqm for shape in candidate.program.open_space),
                             AREA_DECIMALS),
        mix_fit=1 - mix_error(dict(flats), brief.program.unit_mix.value),
        conventionality=sum(conventionality) / towers if towers else 0.0, towers=towers,
        site_use=site_use, quality=quality,
        open_space_usable_sqm=usable_open_sqm(open_space, reach))


def reach_of(blocks: BaseGeometry) -> BaseGeometry:
    """The ground within OPEN_REACH_M of the blocks, drawn once for a caller that asks often."""
    return blocks.buffer(OPEN_REACH_M)


def usable_open_sqm(open_space: BaseGeometry, reach: BaseGeometry) -> float:
    """The open space a lawn, a court or a play area fits in (at least OPEN_WIDE_M across) that
    is near enough a block for its residents to see and reach (within the `reach` of the blocks,
    reach_of), to 0.01 m² (C4-12). The generator seeks it and the objective scores it, the same
    measure."""
    if open_space.is_empty or reach.is_empty:
        return 0.0
    wide = opening(open_space, OPEN_WIDE_M).intersection(open_space)
    return round(wide.intersection(reach).area, AREA_DECIMALS)


def _ground_scores(candidate: CandidateLayout) -> tuple[float, float]:
    """Site use and quality (C4-11), from the candidate's own ledger and rule layers; (0, 0) for a
    candidate that draws neither, whose ground is not known."""
    ledger, layers = candidate.partition, candidate.rule_layers
    if ledger is None or layers is None or not ledger.net_area_sqm:
        return 0.0, 0.0
    net = ledger.net_area_sqm
    residual = _residual(ledger, layers)
    residual_sqm = round(residual.area, AREA_DECIMALS)
    pieces = sum(1 for part in shapely.get_parts(residual) if part.area >= FRAGMENT_SQM)
    roads = round(sum(e.area_sqm for e in ledger.entries if e.use is PhysicalUse.ROAD),
                  AREA_DECIMALS)
    towers = candidate.towers
    repeated = _commonest(t.prototype_id for t in towers)
    one_way = _commonest(round(t.rotation_deg) % 180 for t in towers)  # 0 and 180 run one way
    pavement = unary_union([s.to_shapely() for road in candidate.circulation.roads
                            for s in road.shapes])
    reached = sum(frontage(candidate.placed_footprint(t), pavement, TOUCH_M)
                  >= rules.PATHWAY_WIDTH_M for t in towers) / len(towers) if towers else 0.0
    quality = (max(0.0, 1 - roads / net) + repeated + one_way + reached
               + 1 / (1 + pieces)) / 5
    return max(0.0, 1 - residual_sqm / net), quality


def _commonest(values: Iterable[object]) -> float:
    """The share of the values that are the commonest one (0 when there are none)."""
    counts = Counter(values)
    return max(counts.values()) / counts.total() if counts else 0.0


def _residual(ledger: PartitionLedger, layers: RuleLayers) -> BaseGeometry:
    """The ledger's UNALLOCATED ground less what a rule keeps open: setbacks, block gaps, fire
    bands, the ground a tender turns on, buffers and the green strip."""
    left = unary_union([s.to_shapely() for e in ledger.entries
                        if e.use is PhysicalUse.UNALLOCATED for s in e.shapes])
    kept = unary_union([s.to_shapely() for layer in layers.layers if layer.kind in KEPT_OPEN
                        for s in layer.shapes])
    return left.difference(kept) if not kept.is_empty else left


def priority_weights(brief: DesignBrief) -> tuple[float, ...]:
    """The brief's priorities as weights in AXES order. The contract refuses a name that is not
    one of the axes and a negative weight, so a priority can never silently count for nothing."""
    given = brief.objectives.priorities
    weights = tuple(float(given.get(Priority(axis), 1.0)) for axis in AXES)
    if not sum(weights):
        raise ValueError(f"priorities must be not all zero: {given}")
    return weights
