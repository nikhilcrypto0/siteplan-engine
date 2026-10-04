"""Rule 8(l)'s pathways (contracts 1.2: `RoadKind.PATHWAY`, `CirculationRules.pathway_width_m`).

A block up to 12 m high may take its access through a pathway branching out of an internal or loop
road instead of standing on one; a taller block opens onto an internal road. A drawn pathway must
branch out of a road and be as wide as the rules say; where they say nothing yet it is UNVERIFIED.

The pathway's width here is MADE UP (5.7 m): no figure below is a value of the order.
"""

from shapely.geometry import box
from validator_helpers import check, fixture, move_tower, shapes, status
from validator_low_helpers import all_low, flat_block, with_low_bands

from siteplan.contracts.candidate import RoadKind, RoadPiece
from siteplan.contracts.common import Status
from siteplan.validator import context

TEST_CLASS = "normative"
Z = Status
PATHWAYS = "Internal roads: blocks up to 12 m (pathways)"
SERVED = "Internal roads: every block served"
MADE_UP_WIDTH_M = 5.7


def _off_the_roads(floors=4):
    """T3 with no stilt (4 floors: 12 m, up to the pathway limit; 5: 15 m), 10 m from the nearest
    road: its top edge is at y = 43.84 and the internal road's lower edge at y = 53.85."""
    def build(inputs):
        return flat_block(inputs, "T3", floors, 3.0).edited(
            lambda c: move_tower(c, "T3", 0.0, -10.0))
    return build


def _with_width(inputs, width_m=MADE_UP_WIDTH_M):
    def edit(rules):
        circ = rules.circulation
        circ.pathway_width_m = circ.driveway_min_m.model_copy(update={
            "value": width_m, "clause": "MADE-UP (test): not rule 8(l)'s figure"})
    return inputs.with_rules(edit)


def _with_pathway(inputs, *, x0=109.0, width=6.0, y0=43.84, y1=53.85, kind=RoadKind.PATHWAY):
    """A pathway from T3's top edge up to the internal road (or short of it: `y1`)."""
    def edit(candidate):
        candidate.circulation.roads.append(RoadPiece(
            id="pathway-1", kind=kind, declared_width_m=width,
            shapes=shapes(box(x0, y0, x0 + width, y1))))
    return inputs.edited(edit)


def _served(**kw):
    return _with_pathway(_with_width(_off_the_roads()(with_low_bands(
        all_low(fixture("rectangle"), 4)))), **kw)


def test_a_block_up_to_12_m_reached_by_a_pathway_branching_out_of_a_road_is_served():
    c = check(_served().report(), PATHWAYS)
    assert c.finding.status is Z.PASS and c.finding.measured == "all 3 served, 1 by a pathway"
    assert "at least 5.7 m wide" in c.finding.required
    assert "rule 8(l)" in c.finding.clause and "MADE-UP" in c.finding.clause


def test_a_pathway_narrower_than_the_rules_say_fails():
    c = check(_served(width=4.5).report(), PATHWAYS)
    assert c.finding.status is Z.FAIL and "pathway-1 is 4.50 m wide" in c.finding.measured


def test_a_pathway_that_does_not_branch_out_of_a_road_fails():
    c = check(_served(y1=51.0).report(), PATHWAYS)  # stops 2.85 m short of the internal road
    assert c.finding.status is Z.FAIL
    assert "pathway-1 does not branch out of an internal or loop road" in c.finding.measured


def test_where_the_rules_give_no_pathway_width_a_pathway_is_unverified():
    """The contract fixtures carry rule 8(l)'s 6 m (A2); rules that give none leave it open."""
    shipped = _with_pathway(_off_the_roads()(with_low_bands(all_low(fixture("rectangle"), 4))))
    assert shipped.rules.circulation.pathway_width_m.value == 6.0
    inputs = shipped.with_rules(lambda r: setattr(r.circulation, "pathway_width_m", None))
    c = check(inputs.report(), PATHWAYS)
    assert c.finding.status is Z.UNVERIFIED
    assert "the rules give no pathway width yet" in c.finding.measured
    assert status(shipped.report(), PATHWAYS) is Z.PASS  # the drawn pathway is 6 m wide


def test_a_block_up_to_12_m_on_no_road_and_reached_by_no_pathway_has_no_way_in():
    inputs = _off_the_roads()(with_low_bands(all_low(fixture("rectangle"), 4)))
    c = check(inputs.report(), PATHWAYS)
    assert c.finding.status is Z.FAIL and c.finding.measured == (
        "T3 is reached by no road or pathway")


def test_a_pathway_does_not_serve_a_block_above_12_m():
    """A taller block opens onto an internal road: reached only by a pathway, it fails, and the
    check says why."""
    inputs = _with_pathway(_with_width(_off_the_roads(5)(with_low_bands(
        all_low(fixture("rectangle"), 4)))))
    c = check(inputs.report(), SERVED)
    assert c.finding.status is Z.FAIL
    assert c.finding.measured == ("not on a road: T3; a pathway reaches T3, and rule 8(l) allows "
                                  "one only for blocks up to 12 m")


def test_a_pathway_is_not_an_internal_road_for_rule_8m():
    """A 6 m pathway is narrower than 9 m and is not held to it: it is not a road."""
    report = _served().report()
    assert status(report, "Internal roads: loop and other roads") is Z.PASS
    assert status(report, "Driveways") is Z.PASS


def test_a_pathway_is_not_motorable_and_takes_ground_from_open_space_and_bays():
    inputs = _served()
    ctx = context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate)
    strip = box(109.0, 44.0, 115.0, 53.0)
    assert ctx.drawn.motorable.intersection(strip).area < 1e-6  # not a lane for a fire tender
    assert ctx.drawn.road_land.intersection(strip).area < 1e-6  # nor a road for a ramp's top
    assert ctx.drawn.paved_land.intersection(strip).area > 50.0  # but ground taken all the same


def test_when_the_rules_read_a_pathway_as_open_to_any_block_no_pathway_check_is_made():
    def read_otherwise(rules):
        rules.circulation.block_over_12m_on_road.value = False
    names = {c.finding.rule for c in _served().with_rules(read_otherwise).report().legal}
    assert PATHWAYS not in names and SERVED not in names


def test_a_pathway_drawn_where_no_block_needs_one_is_still_held_to_the_rule():
    """Every block is on a road, yet a pathway drawn off the road network is a FAIL on its own."""
    def stray(candidate):
        candidate.circulation.roads.append(RoadPiece(
            id="pathway-9", kind=RoadKind.PATHWAY, declared_width_m=6.0,
            shapes=shapes(box(60.0, 70.0, 66.0, 80.0))))
    inputs = _with_width(with_low_bands(all_low(fixture("rectangle"), 4))).edited(stray)
    c = check(inputs.report(), PATHWAYS)
    assert c.finding.status is Z.FAIL and "pathway-9 does not branch out" in c.finding.measured
