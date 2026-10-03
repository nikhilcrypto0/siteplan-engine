"""The PartitionLedger and the RuleLayers, recomputed from the candidate's own geometry."""

import pytest
from contract_fixtures import SITES
from validator_helpers import (
    fixture,
    move_tower,
    rectangle,
    select,
    shape,
    status,
)

from siteplan.contracts.accounting import (
    LayerKind,
    Permit,
    PhysicalUse,
    RuleLayers,
)
from siteplan.contracts.candidate import PlacedAmenity
from siteplan.contracts.common import Shape, Status
from siteplan.contracts.resolved_rules import (
    CIRCULATION_IN_SETBACK,
    FIRE_TURNING_RADIUS,
    STILT_IN_RULE_HEIGHT,
)

TEST_CLASS = "normative"
Z = Status
LEDGER = "Every square metre once"


def _net(inputs):
    return Shape.from_shapely(inputs.site.net_plot.value.to_shapely())


# --- the ledger ----------------------------------------------------------------------------


@pytest.mark.parametrize("site", SITES)
def test_the_recomputed_ledger_meets_its_invariants_on_every_fixture(site):
    inputs = fixture(site)
    report = inputs.report()
    ledger = report.accounting.partition
    assert ledger.problems(_net(inputs)) == []
    assert ledger.total_sqm() == pytest.approx(ledger.net_area_sqm, rel=1e-6)
    assert ledger.net_area_sqm == pytest.approx(inputs.site.ownership.net_sqm.value, rel=0.001)
    assert report.accounting.partition_problems == []
    assert status(report, LEDGER) is Z.PASS


def test_the_ledger_is_built_from_the_geometry_not_copied_from_the_candidates_own():
    inputs = fixture("rectangle").edited(lambda c: setattr(c, "partition", None))
    report = inputs.report()
    assert report.accounting.partition.by_use()[PhysicalUse.TOWER] > 4000
    assert report.cross_checks == [d for d in report.cross_checks
                                   if not d.item.startswith("partition")]


def test_what_nothing_claims_is_listed_piece_by_piece_with_its_area_and_its_reason():
    report = fixture("rectangle").report()
    left = [e for e in report.accounting.partition.entries
            if e.use is PhysicalUse.UNALLOCATED]
    assert len(left) >= 2
    assert all(e.reason and e.area_sqm > 0 and e.ref.startswith("unallocated ") for e in left)
    assert sum(e.area_sqm for e in left) == pytest.approx(
        report.recomputed.quantities["unallocated_sqm"])


def test_two_drawn_things_on_the_same_ground_are_a_conflict_with_its_area_and_the_ground_stays():
    def onto_the_road(candidate):  # T3 dragged onto the internal road to its north
        move_tower(candidate, "T3", 0.0, 4.0)
    report = fixture("rectangle").edited(onto_the_road).report()
    overlaps = [p for p in report.accounting.partition_problems if "TOWER" in p and "ROAD" in p]
    assert len(overlaps) == 1 and "overlap by" in overlaps[0] and "m²" in overlaps[0]
    assert status(report, LEDGER) is Z.FAIL
    ledger = report.accounting.partition
    assert ledger.problems(_net(fixture("rectangle"))) == []  # the ground was given to one use


def test_two_blocks_on_the_same_ground_are_a_conflict_too():
    def overlap(candidate):
        move_tower(candidate, "T3", -30.0, 0.0)  # T3 slid back over T2
    report = fixture("rectangle").edited(overlap).report()
    problems = report.accounting.partition_problems
    assert any("TOWER T2 and TOWER T3 overlap by" in p for p in problems)
    assert status(report, LEDGER) is Z.FAIL


def test_a_road_that_is_also_the_fire_tenders_route_is_one_road_entry_never_two_areas():
    report = fixture("rectangle").report()
    entries = report.accounting.partition.entries
    roads = [e for e in entries if e.use is PhysicalUse.ROAD]
    assert roads and all("FIRE_ACCESS" in e.tags for e in roads)
    assert not [p for p in report.accounting.partition_problems if "FIRE_HARDSTANDING" in p]


def test_a_bay_on_a_road_leaves_the_ground_to_the_road_and_is_reported():
    def park(candidate):
        candidate.program.bays.append(rectangle(60.0, 56.0, 62.5, 61.0))
    report = fixture("rectangle").edited(park).report()
    assert any("SURFACE_PARKING" in p and "ROAD" in p for p in report.accounting.partition_problems)


def test_ground_drawn_outside_the_net_plot_is_reported_and_left_out_of_the_ledger():
    def push(candidate):
        move_tower(candidate, "T3", 40.0, 0.0)
    inputs = fixture("rectangle")
    report = inputs.edited(push).report()
    assert any("lies outside the net plot" in p for p in report.accounting.partition_problems)
    assert report.accounting.partition.problems(_net(inputs)) == []


def test_a_play_area_on_the_tot_lot_is_the_tot_lots_ground_and_tagged_never_a_second_area():
    def add(candidate):
        candidate.program.amenities.append(PlacedAmenity(name="PLAY AREA", shape=rectangle(
            20.0, 13.0, 40.0, 20.0)))
    report = fixture("rectangle").edited(add).report()
    entries = report.accounting.partition.entries
    assert not [e for e in entries if e.ref == "PLAY AREA"]
    soft = [e for e in entries if e.use is PhysicalUse.SOFT_OPEN_SPACE]
    assert any("AMENITY:PLAY AREA" in e.tags for e in soft)
    assert report.accounting.partition_problems == []


def test_land_left_inside_a_water_buffer_is_buffer_land_counted_once():
    inputs = fixture("nala_plot")
    ledger = inputs.report().accounting.partition
    assert ledger.by_use()[PhysicalUse.BUFFER_LAND] > 1500
    assert ledger.problems(_net(inputs)) == []


def test_the_candidates_own_broken_ledger_is_reported_and_blocks_a_pass():
    def drop_the_towers(candidate):
        candidate.partition.entries = [e for e in candidate.partition.entries
                                       if e.use is not PhysicalUse.TOWER]
    report = fixture("rectangle").edited(drop_the_towers).report()
    blocking = [d for d in report.cross_checks if d.item == "partition invariant"]
    assert blocking and all(d.blocks_pass for d in blocking)
    assert any(p.startswith("claimed partition:") for p in report.accounting.partition_problems)
    assert report.accounting.partition.problems(_net(fixture("rectangle"))) == []  # ours is whole


def test_where_the_candidates_ledger_and_ours_differ_by_use_it_is_recorded_without_blocking():
    def inflate(candidate):
        for entry in candidate.partition.entries:
            if entry.use is PhysicalUse.SURFACE_PARKING:
                entry.shapes = [shape(rectangle(1, 1, 60, 60).to_shapely())]
                entry.area_sqm = entry.shapes[0].area_sqm
    report = fixture("rectangle").edited(inflate).report()
    differ = [d for d in report.cross_checks if d.item == "partition: SURFACE_PARKING"]
    assert differ and not differ[0].blocks_pass


# --- the rule layers -------------------------------------------------------------------------


def _layers(report) -> RuleLayers:
    return report.accounting.rule_layers


def test_setback_layers_follow_the_stilt_reading_and_never_simply_allow_a_road_in_them():
    report = fixture("rectangle").report()
    setbacks = _layers(report).of(LayerKind.SETBACK)
    assert {layer.id for layer in setbacks} == {"setback [counted]", "setback [not_counted]"}
    counted = next(x for x in setbacks if x.id.endswith("[counted]"))
    assert counted.area_sqm == pytest.approx(
        fixture("rectangle").site.net_plot.value.area_sqm
        - 132.0 * 82.0, abs=1.0)  # the net plot less its 9 m inset: 150 x 100 less 132 x 82
    assert counted.interpretation_ref == STILT_IN_RULE_HEIGHT
    permits = {p.use: p for p in counted.permits}
    assert permits[PhysicalUse.TOWER].permit is Permit.FORBIDDEN
    for use in (PhysicalUse.ROAD, PhysicalUse.FIRE_HARDSTANDING):
        assert permits[use].permit is Permit.CONDITIONAL
        assert permits[use].interpretation_ref == CIRCULATION_IN_SETBACK
    assert all(p.permit is not Permit.ALLOWED for layer in setbacks for p in layer.permits)


def test_a_settled_stilt_reading_gives_one_unqualified_setback_layer():
    inputs = fixture("rectangle").with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, "counted"))
    setbacks = _layers(inputs.report()).of(LayerKind.SETBACK)
    assert [x.id for x in setbacks] == ["setback"] and setbacks[0].interpretation_ref is None


def test_every_kind_of_regulatory_geometry_is_present_for_a_generated_layout():
    kinds = {x.kind for x in _layers(fixture("rectangle").report()).layers}
    assert kinds >= {LayerKind.SETBACK, LayerKind.BLOCK_GAP, LayerKind.FIRE_CLEAR_BAND,
                     LayerKind.FIRE_ACCESS_ROUTE, LayerKind.TURNING_SECTOR,
                     LayerKind.GREEN_STRIP_ZONE, LayerKind.QUALIFYING_OPEN_SPACE,
                     LayerKind.RAMP_FORBIDDEN, LayerKind.BAYS_FORBIDDEN,
                     LayerKind.CELLAR_SETBACK}
    assert LayerKind.WATER_BUFFER in {x.kind for x in _layers(
        fixture("nala_plot").report()).layers}


def test_the_tenders_turns_are_a_layer_per_tower_and_name_the_open_reading_of_the_radius():
    turns = _layers(fixture("rectangle").report()).of(LayerKind.TURNING_SECTOR)
    assert {x.applies_to for x in turns} == {"T1", "T2", "T3"}
    assert all(x.interpretation_ref == FIRE_TURNING_RADIUS for x in turns)


def test_the_clear_band_round_each_high_rise_forbids_building_parking_and_play_in_it():
    band = _layers(fixture("rectangle").report()).of(LayerKind.FIRE_CLEAR_BAND)[0]
    forbidden = {p.use for p in band.permits if p.permit is Permit.FORBIDDEN}
    assert {PhysicalUse.TOWER, PhysicalUse.SURFACE_PARKING,
            PhysicalUse.SOFT_OPEN_SPACE} <= forbidden


def test_layer_ids_are_unique_and_a_report_with_its_layers_survives_json():
    from siteplan.contracts import ValidationReport

    report = fixture("l_plot_with_arm").report()
    ids = [x.id for x in _layers(report).layers]
    assert len(ids) == len(set(ids))
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report
