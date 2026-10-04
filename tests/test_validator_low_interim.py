"""INTERIM behaviours for blocks below 21 m, pinned alone so each can be flipped when contracts 1.2
lets ResolvedRules and the candidate say more. Each test names the one place in the validator that
changes and what the test becomes once it does.

  2. A block up to 12 m on no road is UNVERIFIED  (validator/roads.py `_pathway_check`). Needs
     `RoadKind.PATHWAY` and `CirculationRules.pathway_width_m`.
  4. Fire access below 21 m is NOT_CHECKED and names rule 15(a)(i)  (validator/fire.py
     `low_block_check`). Needs a figure for what 15(a)(i) asks of a fire vehicle's access.

Every band is MADE UP (tests/validator_low_helpers.py).
"""

from validator_helpers import check, fixture, move_tower, set_floors, status
from validator_low_helpers import (
    all_low,
    with_low_bands,
)

from siteplan.contracts.common import Status

TEST_CLASS = "normative"
Z = Status
COUNTED, NOT_COUNTED = "counted", "not_counted"
PATHWAYS = "Internal roads: blocks up to 12 m (pathways)"
BELOW = "Fire access below 21 m (rule 15(a)(i))"
RULE_15_A_I = ('"The building requirements and standards other than heights and setbacks '
               'specified in the National Building Code - 2005 shall be complied with."')


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
