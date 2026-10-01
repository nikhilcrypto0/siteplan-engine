"""Parking: Table V, the cellars and their ramp, and the bays that physically fit."""

import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from siteplan import rules
from siteplan.checks import Status
from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.parking import (
    BAY_DEPTH_M,
    BAY_WIDTH_M,
    ParkingStandards,
    cellar_outline,
    cellars_needed,
    parking_percent,
    place_ramp,
    ramp_size,
    surface_bays,
)

PLOT = box(0, 0, 150, 120)
LIBRARY = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3})  # 27 m, 9 m setbacks


@pytest.fixture(scope="module")
def option():
    return solve(PLOT, LIBRARY, REQUEST, abutting_road_m=18.0, authority="HMDA",
                 inside_cure=False, access_side="S")[0]


def test_bays_are_one_car_each_and_stay_inside_the_free_area():
    free = box(0, 0, 30, 20)
    bays = surface_bays(free, 0.0)
    assert bays
    for bay in bays:
        assert bay.area == pytest.approx(BAY_WIDTH_M * BAY_DEPTH_M)
        assert free.contains(bay.buffer(-0.01))


def test_bays_leave_an_aisle_between_rows_and_double_loading_shares_it():
    rows = sorted({round(b.bounds[1], 1) for b in surface_bays(box(0, 0, 30, 30), 0.0)})
    assert rows[1] - rows[0] >= BAY_DEPTH_M + 5.9  # a car length plus the aisle
    single = surface_bays(box(0, 0, 30, 32), 0.0, limit=1000)
    double = surface_bays(box(0, 0, 30, 32), 0.0, limit=1000, double_loaded=True)
    assert len(double) > len(single)


def test_no_bays_where_a_car_cannot_stand():
    assert surface_bays(box(0, 0, 2, 2), 0.0) == []


def test_the_cellar_keeps_its_setback_and_half_a_metre_more_per_extra_level():
    assert rules.cellar_setback_m(5000, 1) == 3.0
    assert rules.cellar_setback_m(5000, 3) == 4.0
    assert rules.cellar_setback_m(1500, 1) == 2.0
    assert rules.cellar_setback_m(800, 2) == 2.0
    outline = cellar_outline(PLOT, PLOT.area, 2)
    assert PLOT.exterior.distance(outline) == pytest.approx(3.5)


def test_the_ramp_is_one_of_5_4_m_at_1_in_8():
    assert ramp_size(ParkingStandards(cellar_floor_height_m=3.0)) == (5.4, 24.0)
    assert ramp_size(ParkingStandards(cellar_floor_height_m=3.3))[1] == pytest.approx(26.4)


def test_the_fewest_cellars_that_meet_the_need():
    assert cellars_needed(1000, 1200, [500, 480]) == 0
    assert cellars_needed(1000, 600, [500, 480]) == 1
    assert cellars_needed(1500, 600, [500, 480]) == 2
    assert cellars_needed(2000, 600, [500, 480]) is None


def test_an_unsettled_jurisdiction_plans_for_the_stricter_column():
    assert parking_percent("HMDA", False)[0] == 20.0
    assert parking_percent("CMC", True)[0] == 30.0
    assert parking_percent("GHMC", False)[0] == 30.0
    # Not known, and it decides the share: nothing to plan for, and the reason asks.
    percent, basis = parking_percent("HMDA", None)
    assert percent is None and "confirm the authority" in basis
    assert parking_percent(None, None)[0] is None
    percent, basis = parking_percent("CMC", True, jurisdiction_confirmed=False)
    assert percent is None
    # Only the named test mode plans the stricter column, and says so.
    percent, basis = parking_percent("CMC", True, jurisdiction_confirmed=False, conservative=True)
    assert percent == 30.0 and basis.startswith("CONSERVATIVE_ASSUMPTION")
    # GHMC is 30% whatever CURE is, so nothing needs asking.
    assert parking_percent("GHMC", None)[0] == 30.0


def test_a_ramp_starts_on_a_road_and_needs_room_for_its_length():
    road = box(0, 0, 100, 9)
    room = box(0, 9, 100, 60)
    ramp = place_ramp(room, road, 5.4, 24.0)
    assert ramp is not None and room.contains(ramp)
    assert ramp.distance(road) < 0.05
    assert place_ramp(box(0, 9, 100, 20), road, 5.4, 24.0) is None  # too shallow for 24 m


def test_every_layout_meets_table_v_and_counts_its_cars(option):
    plan = option.parking
    assert plan.provided_sqm >= plan.required_sqm
    assert plan.percent == 20.0
    assert plan.cellar_levels >= 1 and len(plan.ramps) == 1
    assert plan.cars["stilt"] > 0 and plan.cars["cellar 1"] > 0
    findings = {f.rule: f for f in option.findings}
    for rule in ("Parking (Table V)", "Visitors' parking", "Cellar setback", "Cellar ramp"):
        assert findings[rule].status is Status.PASS, (rule, findings[rule].measured)
    assert "cars fit" in findings["Parking (Table V)"].measured


def test_bays_never_sit_on_a_setback_road_fire_lane_building_or_the_tot_lot(option):
    envelope = PLOT.buffer(-9)
    roads = unary_union([r.shape for r in option.roads])
    for bay in option.parking_bays:
        inner = bay.buffer(-0.01)
        assert envelope.contains(inner)  # rule 13(b)(iii): over and above the setbacks
        assert not inner.intersects(roads)
        assert not inner.intersects(option.fire_lanes)  # NBC 4.6(c): never parked in
        assert not any(p.intersects(inner) for p in option.open_space)
        assert not any(t.footprint.intersects(inner) for t in option.towers)


def test_the_ramp_stays_out_of_the_setbacks_and_the_fire_lanes(option):
    ramp = option.ramps[0]
    assert PLOT.buffer(-9).contains(ramp.buffer(-0.01))
    assert option.fire_lanes.intersection(ramp).area < 0.5
    assert not any(t.footprint.intersects(ramp.buffer(-0.01)) for t in option.towers)
