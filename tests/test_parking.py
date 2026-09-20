"""Surface parking bays and the entry / exit gates."""

import pytest
from shapely.geometry import LineString, box

from siteplan.checks import Status
from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.parking import BAY_DEPTH_M, BAY_WIDTH_M, gates, surface_bays

PLOT = box(0, 0, 150, 120)
LIBRARY = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3})


@pytest.fixture(scope="module")
def option():
    return solve(PLOT, LIBRARY, REQUEST, abutting_road_m=18.0, authority="HMDA")[0]


def test_bays_are_one_car_each_and_stay_inside_the_free_area():
    free = box(0, 0, 30, 20)
    bays = surface_bays(free, 0.0)
    assert bays
    for bay in bays:
        assert bay.area == pytest.approx(BAY_WIDTH_M * BAY_DEPTH_M)
        assert free.contains(bay.buffer(-0.01))


def test_bays_leave_an_aisle_between_rows():
    bays = surface_bays(box(0, 0, 30, 30), 0.0)
    rows = sorted({round(b.bounds[1], 1) for b in bays})
    assert len(rows) >= 2
    assert rows[1] - rows[0] >= BAY_DEPTH_M + 5.9  # a car length plus the aisle


def test_no_bays_where_a_car_cannot_stand():
    assert surface_bays(box(0, 0, 2, 2), 0.0) == []


def test_bays_never_sit_on_the_setback_the_tot_lot_or_a_building(option):
    envelope = PLOT.buffer(-9)
    for bay in option.parking_bays:
        assert envelope.contains(bay.buffer(-0.01))          # rule 13(b)(iii)
        assert not any(t.footprint.intersects(bay.buffer(-0.01)) for t in option.towers)
        assert not any(p.intersects(bay.buffer(-0.01)) for p in option.open_space)


def test_the_gates_sit_on_the_frontage_and_face_the_site():
    frontage = LineString([(0, 0), (150, 0)])
    placed = gates(PLOT, frontage, 9.0)
    assert [name for name, _ in placed] == ["ENTRY", "EXIT"]
    for _, gate in placed:
        assert gate.centroid.y > 0            # reaches into the site, not out of it
        assert PLOT.intersects(gate)


def test_an_option_carries_gates_and_counts_its_bays(option):
    summary = option.summary()
    assert summary["surface_parking_bays"] == len(option.parking_bays) > 0
    assert len(option.gates) == 2


def test_surface_bays_count_towards_the_parking_rule(option):
    parking = next(f for f in option.findings if f.rule == "Parking")
    assert "surface" in parking.measured
    assert parking.status in {Status.PASS, Status.NEEDS_INPUT}
    assert "20%" in parking.required
