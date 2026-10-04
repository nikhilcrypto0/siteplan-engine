"""A tower the prototype generator laid, as a LEGACY_RECTANGLE prototype: the same footprint, flat
for flat and core for core, wherever on a made-up plot it stands and however it is turned."""

import dataclasses

import pytest
from shapely import affinity
from shapely.geometry import Polygon, box

from siteplan.adapters import Readings, candidate_from_option
from siteplan.contracts import TowerPrototype
from siteplan.contracts.prototype import PrototypeFamily
from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.prototypes import legacy_tower, problems

TEST_CLASS = "normative"

LIBRARY = FlatLibrary(
    flats=[{"name": "2A", "bhk": "2BHK", "width_m": 10.0, "depth_m": 11.0, "saleable_sqft": 1190},
           {"name": "3A", "bhk": "3BHK", "width_m": 13.5, "depth_m": 11.0,
            "saleable_sqft": 1690}],
    core_width_m=7.5)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3}, conservative_parking=True)
L_PLOT = Polygon([(0, 0), (180, 0), (180, 90), (90, 90), (90, 170), (0, 170)])
PLOTS = {
    "rectangle": box(0, 0, 150, 100),
    "L-plot": L_PLOT,
    # turned to angles no multiple of 90 degrees, so the towers' own turn is never a lucky one
    "rectangle turned 31 degrees": affinity.rotate(box(0, 0, 150, 100), 31.0, origin=(0, 0)),
    "L-plot turned 117.3 degrees": affinity.rotate(L_PLOT, 117.3, origin=(0, 0)),
}
EPS = 1e-6  # m², what two footprints may differ by and still be one


@pytest.fixture(scope="module")
def layouts():
    """Every option the generator gives on each made-up plot: (plot name, plot, option)."""
    found = [(name, plot, option) for name, plot in PLOTS.items()
             for option in solve(plot, LIBRARY, REQUEST)]
    assert {name for name, _, _ in found} == set(PLOTS), "every made-up plot must give options"
    return found


def _legacy(name: str, option, tower):
    return legacy_tower(tower, option.floors, f"{name.replace(' ', '-')}-{tower.name}",
                        "made-up library")


def test_a_legacy_rectangle_is_the_towers_footprint_where_it_stood(layouts):
    turns = set()
    for name, _, option in layouts:
        for tower in option.towers:
            prototype, placed = _legacy(name, option, tower)
            world = placed.world(prototype.footprint.to_shapely())
            assert world.symmetric_difference(tower.footprint).area < EPS
            assert placed.footprint.to_shapely().symmetric_difference(tower.footprint).area < EPS
            turns.add(round(placed.rotation_deg % 90, 1))
    assert any(turn not in (0.0, 90.0) for turn in turns), "no tower stood at an odd angle"


def test_every_flat_and_core_of_a_legacy_tower_stands_where_it_did(layouts):
    for name, _, option in layouts:
        for tower in option.towers:
            prototype, placed = _legacy(name, option, tower)
            assert len(prototype.modules) == len(tower.flat_outlines)
            for module, outline, flat in zip(
                    prototype.modules, tower.flat_outlines,
                    (f for f in tower.flats_per_side for _ in range(2)), strict=True):
                assert placed.world(module.shape.to_shapely()).symmetric_difference(
                    outline).area < EPS
                assert (module.type_id, module.category) == (flat.name, flat.bhk)
            assert len(prototype.core_zones) == len(tower.cores)
            for zone, core in zip(prototype.core_zones, tower.cores, strict=True):
                assert placed.world(zone.shape.to_shapely()).symmetric_difference(core).area < EPS
            pieces = [*tower.flat_outlines, *tower.cores,
                      *(placed.world(c.to_shapely()) for c in prototype.corridor)]
            assert all(tower.footprint.buffer(1e-6).contains(piece) for piece in pieces)
            assert sum(piece.area for piece in pieces) == pytest.approx(
                tower.footprint.area, rel=0.02)  # nothing missing, nothing counted twice


def test_a_legacy_rectangle_keeps_every_number_the_tower_had(layouts):
    for name, _, option in layouts:
        for tower in option.towers:
            prototype, placed = _legacy(name, option, tower)
            counts = tower.flats_per_floor()
            assert prototype.family is PrototypeFamily.LEGACY_RECTANGLE
            assert prototype.per_floor.flats == sum(counts.values())
            assert prototype.per_floor.flats_by_type == counts
            assert prototype.per_floor.saleable_sqft == pytest.approx(
                tower.saleable_sqft_per_floor())
            assert prototype.per_floor.gross_floor_sqm == pytest.approx(tower.footprint.area)
            assert prototype.cores == len(tower.cores)
            assert (prototype.length_m, prototype.depth_m) == (tower.length_m, tower.width_m)
            assert placed.floors_above_stilt == option.floors
            assert prototype.length_m >= prototype.depth_m
            assert problems(prototype) == []  # it closes, in its own frame
            assert TowerPrototype.model_validate_json(prototype.model_dump_json()) == prototype


def test_a_legacy_tower_that_does_not_pair_its_flats_is_refused(layouts):
    _, _, option = layouts[0]
    tower = option.towers[0]
    broken = dataclasses.replace(tower, flat_outlines=tower.flat_outlines[:-1])
    with pytest.raises(ValueError, match="flat outlines"):
        legacy_tower(broken, option.floors, "broken")


def test_the_adapter_makes_its_prototypes_with_the_same_function(layouts):
    readings = Readings.of(REQUEST).selections
    for name, plot, option in layouts:
        candidate = candidate_from_option(
            option, plot, candidate_id=name.replace(" ", "-"), site_ref="site", rules_ref="rules",
            brief_ref="brief", readings=readings, library_note="made-up library")
        for tower, used, placed in zip(option.towers, candidate.prototypes_used,
                                       candidate.towers, strict=True):
            assert (used, placed) == _legacy(name, option, tower)
