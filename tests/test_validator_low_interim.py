"""INTERIM behaviours for blocks below 21 m, pinned alone so each can be flipped when contracts 1.2
lets ResolvedRules and the candidate say more. Each test names the one place in the validator that
changes and what the test becomes once it does.

  1. The front is not judged apart from the other sides  (validator/measure.py ALL_ROUND_NOTE, the
     setback figure `HeightClass.setback_m`, used by blocks.setback_checks and the club house).
     Needs `Band.front_setback_m`.
  2. A block up to 12 m on no road is UNVERIFIED  (validator/roads.py `_pathway_check`). Needs
     `RoadKind.PATHWAY` and `CirculationRules.pathway_width_m`.
  3. A low block's band is picked on the reading's own height  (validator/context.py `build`).
     Needs a way to say Table III leaves the stilt out always (rule 5(c)), e.g. `Band.stilt_counts`.
  4. Fire access below 21 m is NOT_CHECKED and names rule 15(a)(i)  (validator/fire.py
     `low_block_check`). Needs a figure for what 15(a)(i) asks of a fire vehicle's access.

Every band is MADE UP (tests/validator_low_helpers.py).
"""

from validator_helpers import check, fixture, move_tower, set_floors, status
from validator_low_helpers import (
    access_road_of,
    all_low,
    floors_of,
    with_low_bands,
)

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT

TEST_CLASS = "normative"
Z = Status
COUNTED, NOT_COUNTED = "counted", "not_counted"
PATHWAYS = "Internal roads: blocks up to 12 m (pathways)"
BELOW = "Fire access below 21 m (rule 15(a)(i))"
RULE_15_A_I = ('"The building requirements and standards other than heights and setbacks '
               'specified in the National Building Code - 2005 shall be complied with."')


# --- 1. the front ------------------------------------------------------------------------------


def test_interim_the_front_is_not_judged_apart_from_the_other_sides():
    """INTERIM (flips with contracts 1.2, `Band.front_setback_m`). Table III gives the Building
    Line at the front apart from the setback on the other sides, and ResolvedRules carries one
    all-round figure. So the same block 3.69 m from a boundary is judged the same whether that
    boundary is the front (the side the access road runs on) or not, and the check says so.

    Once the front has its own figure: a block near the front is held to it and one near a side
    to the other, so these two findings differ wherever the two figures do, and the note no longer
    says the front is not judged on its own."""
    def near_the_south_boundary(candidate):
        move_tower(candidate, "T2", 0.0, -26.02)  # 29.71 - 26.02 = 3.69 m from the south side

    def road_on(side):
        return lambda site: setattr(site.access.side, "value", side)

    base = with_low_bands(all_low(fixture("rectangle"))).edited(near_the_south_boundary)
    on_the_south = check(base.with_site(road_on("S")).report(), "All-round setback: T2")
    on_the_north = check(base.with_site(road_on("N")).report(), "All-round setback: T2")
    assert on_the_south.finding.status is Z.FAIL  # 3.69 m is under band B's 3.70 m
    assert on_the_south.finding == on_the_north.finding
    assert "Building Line" in on_the_south.finding.note
    assert "not judged on its own" in on_the_south.finding.note


# --- 2. pathways -------------------------------------------------------------------------------


def test_interim_a_block_up_to_12_m_on_no_road_is_unverified_because_a_pathway_is_not_drawn():
    """INTERIM (flips with contracts 1.2, `RoadKind.PATHWAY` and `pathway_width_m`). Rule 8(l)
    lets such a block take a 6 m pathway branching out of an internal road, and the candidate
    cannot draw one: so it is neither a pass nor a fail.

    Once it can: a pathway drawn at least the rule's width, branching from an internal road and
    reaching the block, is a PASS; one drawn narrower, or reaching nothing, is a FAIL; a block
    with none and no road is a FAIL, as a block above 12 m is."""
    def off_the_roads(candidate):
        set_floors(candidate, "T3", 3)  # 3 m stilt + 9 m: exactly 12 m
        move_tower(candidate, "T3", 0.0, -10.0)  # 34 m from the nearest road
    c = check(fixture("rectangle").edited(off_the_roads).report(), PATHWAYS)
    assert c.finding.status is Z.UNVERIFIED
    assert c.finding.measured == "on no road: T3; a pathway is not drawn"
    assert "cannot show a pathway" in c.finding.note


# --- 3. the stilt ------------------------------------------------------------------------------


def test_interim_a_low_blocks_band_is_picked_on_the_readings_own_height():
    """INTERIM (flips with contracts 1.2, a way to say rule 5(c) leaves the stilt out of Table
    III's height always). 4 floors on a 3 m stilt are 15 m if the stilt counts (band B) and 12 m
    if not (band A), so the block is judged on a different band under each reading: stricter when
    the stilt counts, never a false PASS, and UNVERIFIED where the two readings part.

    Once Table III leaves the stilt out: both readings give 12 m, band A, and every result below
    is the same under both readings (a block 3.51 m from the boundary passes band A's 2.3 m)."""
    stilted = with_low_bands(floors_of(fixture("rectangle"), T1=4, T2=4, T3=4))
    report = stilted.report()
    t1 = next(t for t in report.recomputed.towers if t.name == "T1")
    assert t1.rule_height_m_by_reading == {COUNTED: 15.0, NOT_COUNTED: 12.0}
    assert t1.band_by_reading == {COUNTED: "non-high-rise 12-18 m",
                                  NOT_COUNTED: "non-high-rise 0-12 m"}
    assert t1.required_setback_m_by_reading == {COUNTED: 3.7, NOT_COUNTED: 2.3}

    near = stilted.edited(lambda c: move_tower(c, "T2", -7.5, 0.0))  # 3.51 m from the boundary
    setback = check(near.report(), "All-round setback: T2")
    assert setback.finding.status is Z.UNVERIFIED
    assert setback.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.FAIL, NOT_COUNTED: Z.PASS}

    narrow = check(access_road_of(stilted, 8.0).report(), "Abutting road width (for T1)")
    assert narrow.finding.status is Z.UNVERIFIED  # band B asks 8.4 m, band A none
    assert narrow.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.FAIL, NOT_COUNTED: Z.PASS}


# --- 4. fire access ----------------------------------------------------------------------------


def test_interim_fire_access_below_21_m_is_not_checked_and_names_rule_15_a_i():
    """INTERIM (flips with contracts 1.2, a figure for what 15(a)(i) asks of a fire vehicle's
    access). A low block is not held to the high-rise lanes; rule 15(a)(i) holds it to the
    National Building Code's requirements other than heights and setbacks, and the resolved rules
    carry no value for them, so nothing numeric is judged: NOT_CHECKED, listed beside the verdict.

    Once there is a figure: a PASS or FAIL on it, per block, and this one check is replaced."""
    report = with_low_bands(all_low(fixture("rectangle"))).report()
    c = check(report, BELOW)
    assert c.finding.status is Z.NOT_CHECKED and BELOW in report.not_checked
    assert "rule 15(a)(i), p.20" in c.finding.note and RULE_15_A_I in c.finding.note
    assert "no value" in c.finding.note and "nothing numeric is judged" in c.finding.note
    assert "other than heights and setbacks" in c.finding.required
    assert status(report, "Fire access") is Z.INFO  # the high-rise lanes: no high-rise block
