"""A single-loaded block: one row of flats along the corridor, about half the depth of a
double-loaded one, for ground no double-loaded block can stand on (docs/behaviour-changes.md,
2026-10-13).

Made-up flats only (the contract fixtures' library). What holds: the family composes at half the
depth and its geometry closes; it is a design choice the firm asks for by name, so it is not in
the default kit and every prototype composed before it is unchanged.
"""

from __future__ import annotations

import pytest
from optimizer_support import LIBRARY
from shapely.ops import unary_union

from siteplan.contracts.prototype import PrototypeFamily
from siteplan.prototypes import compose_library
from siteplan.prototypes.compose import BY_REQUEST, FAMILY_PLANS, servable_families

TEST_CLASS = "normative"

MIX = {"2BHK": 0.5, "3BHK": 0.5}
EVERY = [*servable_families(LIBRARY), *BY_REQUEST]


def _kit(families=None):
    return {p.id: p for p in compose_library(LIBRARY, MIX, families=families)}


def test_the_default_kit_has_no_single_loaded_block():
    assert PrototypeFamily.SINGLE_LOADED not in servable_families(LIBRARY)
    assert all(p.family is not PrototypeFamily.SINGLE_LOADED for p in _kit().values())


def test_every_prototype_composed_before_is_unchanged_when_the_firm_asks_for_the_slim_block():
    before, after = _kit(), _kit(EVERY)
    assert set(before) < set(after)
    for pid, was in before.items():
        assert after[pid].model_dump() == was.model_dump(), pid


def test_the_single_loaded_block_is_about_half_the_depth():
    kit = _kit(EVERY)
    slim = next(p for p in kit.values() if p.family is PrototypeFamily.SINGLE_LOADED)
    double = next(p for p in kit.values() if p.family is PrototypeFamily.SINGLE_CORE_SMALL)
    # the corridor is shared; only the rows of flats differ, so the slim block is the corridor
    # and one row where the other is the corridor and two
    assert slim.depth_m == pytest.approx(LIBRARY.corridor_width_m + LIBRARY.flats[0].depth_m)
    assert double.depth_m == pytest.approx(LIBRARY.corridor_width_m
                                           + 2 * LIBRARY.flats[0].depth_m)
    assert slim.depth_m < double.depth_m / 1.7
    assert slim.length_m == pytest.approx(double.length_m)  # the same flats along the corridor


def test_it_carries_one_row_of_flats_and_half_the_saleable_area():
    kit = _kit(EVERY)
    slim = next(p for p in kit.values() if p.family is PrototypeFamily.SINGLE_LOADED)
    double = next(p for p in kit.values() if p.family is PrototypeFamily.SINGLE_CORE_SMALL)
    plan = FAMILY_PLANS[PrototypeFamily.SINGLE_LOADED]
    assert plan.single_loaded and plan.sides == 1
    assert slim.per_floor.flats == plan.flats_per_side == double.per_floor.flats / 2
    assert slim.per_floor.saleable_sqft == pytest.approx(double.per_floor.saleable_sqft / 2)


def test_its_geometry_closes_with_the_corridor_against_one_wall():
    slim = next(p for p in _kit(EVERY).values()
                if p.family is PrototypeFamily.SINGLE_LOADED)
    footprint = slim.footprint.to_shapely()
    flats = unary_union([m.shape.to_shapely() for m in slim.modules])
    cores = unary_union([c.shape.to_shapely() for c in slim.core_zones])
    corridor = unary_union([c.to_shapely() for c in slim.corridor])
    parts = unary_union([flats, cores, corridor])
    assert parts.difference(footprint).area == pytest.approx(0)  # nothing outside the block
    assert footprint.difference(parts).area == pytest.approx(0)  # and no gap inside it
    assert flats.intersection(corridor).area == pytest.approx(0)
    assert flats.intersection(cores).area == pytest.approx(0)
    # the corridor runs along one wall, the flats along the other
    _, low, _, high = footprint.bounds
    assert corridor.bounds[1] == pytest.approx(low)
    assert flats.bounds[3] == pytest.approx(high)
    assert corridor.bounds[3] <= flats.bounds[1] + 1e-9


def test_it_stands_where_a_double_loaded_block_cannot():
    """The point of it: Dhulapally's arm is 32.8 m across, which leaves 22.8 m between Table III's
    shallowest 5 m side setbacks. The made-up arm here is the same width."""
    kit = _kit(EVERY)
    slim = next(p for p in kit.values() if p.family is PrototypeFamily.SINGLE_LOADED)
    double = next(p for p in kit.values() if p.family is PrototypeFamily.SINGLE_CORE_SMALL)
    arm_m, side_setback_m = 32.8, 5.0
    between = arm_m - 2 * side_setback_m
    assert double.depth_m > between  # no block of the kit composed before fits
    assert slim.depth_m < between
