"""What a candidate is worth to the architect: five numbers, each worked out from the candidate's
own prototypes and placements, never from the generator's claims (`metrics` may be wrong).

- saleable area: every tower's prototype saleable area per floor times its floors;
- units: flats, floors counted the same way;
- open space: the area of the open-space ground the candidate draws;
- mix fit: 1 less how far the flats' shares are from the brief's unit mix;
- conventionality: how ordinary the blocks are, 1 for a block with one core and falling as cores
  are added (a long multi-core slab is the less conventional building). More towers break a tie
  between equally conventional layouts: smaller, more numerous blocks come first.

All are bigger-is-better, so a Pareto front over them (pareto.py) means what it says.
The architect's priorities (DesignBrief.objectives.priorities) are weights over these, used only
to find the balanced compromise; a priority left out counts as 1.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from siteplan.contracts import CandidateLayout, DesignBrief

AXES = ("saleable_area", "units", "open_space", "mix_fit", "conventionality")


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

    @property
    def yield_score(self) -> float:
        """Saleable area less what the mix misses by: what "maximum yield" maximises."""
        return self.saleable_sqft * self.mix_fit

    @property
    def vector(self) -> tuple[float, ...]:
        """The five bigger-is-better numbers, in AXES order."""
        return (self.saleable_sqft, float(self.units), self.open_space_sqm, self.mix_fit,
                self.conventionality)

    def as_dict(self) -> dict[str, float]:
        return {"saleable_sqft": self.saleable_sqft, "units": float(self.units),
                "open_space_sqm": self.open_space_sqm, "mix_fit": self.mix_fit,
                "conventionality": self.conventionality, "towers": float(self.towers),
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
    return Scores(
        saleable_sqft=saleable, units=sum(flats.values()),
        open_space_sqm=sum(shape.area_sqm for shape in candidate.program.open_space),
        mix_fit=1 - mix_error(dict(flats), brief.program.unit_mix.value),
        conventionality=sum(conventionality) / towers if towers else 0.0, towers=towers)


def priority_weights(brief: DesignBrief) -> tuple[float, ...]:
    """The brief's priorities as weights in AXES order. An unknown name is an error: a priority
    that silently counted for nothing would be worse than none."""
    given = brief.objectives.priorities
    unknown = sorted(set(given) - set(AXES))
    if unknown:
        raise ValueError(f"unknown priorities {unknown}; the objective's axes are {list(AXES)}")
    weights = tuple(float(given.get(axis, 1.0)) for axis in AXES)
    if any(w < 0 for w in weights) or not sum(weights):
        raise ValueError(f"priorities must not be negative and not all zero: {given}")
    return weights
