"""The client's orientation (2026-10-19, the architect's Vastu: every tower's long faces look
north and south): carried from the project or answers file into the brief as a required
preference with its source, held by the search, judged by the program check, never law.
Made-up land (search_support.py, contract_fixtures)."""

import math
from functools import cache

import pytest
from contract_fixtures.build import project as fixture_project
from search_support import Made, made_up, strategy
from shapely import affinity
from shapely.geometry import box
from validator_helpers import fixture

from siteplan import validator as independent
from siteplan.adapters import Readings, request
from siteplan.adapters import brief as make_brief
from siteplan.contracts import digest
from siteplan.contracts.common import Provenance, SourceKind, Status
from siteplan.contracts.design_brief import DesignBrief, SoftPreference
from siteplan.contracts.resolved_rules import (
    CIRCULATION_IN_SETBACK,
    STILT_IN_RULE_HEIGHT,
    WhenOpen,
)
from siteplan.contracts.validation import Family
from siteplan.layout import TowerOrientation
from siteplan.optimizer.preferences import Orientation, required_orientation
from siteplan.validator.shapes import oriented_box

TEST_CLASS = "normative"
SOURCE = "the architect, 2026-10-19: Vastu, long faces north and south"
NORTH_SOUTH = SoftPreference(kind="orientation", params={"axis_deg": 0.0}, required=True,
                             status=Provenance.USER_CONFIRMED, source_kind=SourceKind.ARCHITECT,
                             source=SOURCE)


def _requiring(made: Made, wish: SoftPreference = NORTH_SOUTH) -> Made:
    brief = made.brief.model_copy(deep=True)
    brief.objectives.soft_preferences = [wish]
    return Made(made.site, made.rules, DesignBrief.model_validate(brief.model_dump()),
                made.envelope, made.kit)


def _off_axis(candidate, tower) -> float:
    angle, _, _ = oriented_box(candidate.placed_footprint(tower))
    turn = math.degrees(angle) % 180.0
    return min(turn, 180.0 - turn)


@cache
def slanted() -> Made:
    """200 x 120 m turned 25 degrees: every edge of it runs off the north-south grid."""
    return made_up(affinity.rotate(box(0, 0, 200, 120), 25, origin=(0, 0)))


def _within(tolerance: float) -> SoftPreference:
    return NORTH_SOUTH.model_copy(update={"params": {"axis_deg": 0.0,
                                                     "tolerance_deg": tolerance}})


@cache
def _proposals(required: bool, tolerance: float = 0.0):
    wish = _within(tolerance) if tolerance else NORTH_SOUTH
    made = _requiring(slanted(), wish) if required else slanted()
    return made, strategy().propose(made.context())


# --- The contract and the files -------------------------------------------------------------


def test_a_brief_without_a_requirement_keeps_its_digest():
    brief = fixture("rectangle").brief
    wished = SoftPreference(kind="orientation", params={"axis_deg": 0.0})
    assert "required" not in wished.model_dump() and "source" not in wished.model_dump()
    assert digest(DesignBrief.model_validate(brief.model_dump())) == digest(brief)


def test_only_an_orientation_can_be_required():
    with pytest.raises(ValueError, match="only orientation can be required"):
        SoftPreference(kind="max_towers", params={"towers": 3}, required=True)


def test_the_project_files_orientation_reaches_the_brief_with_its_source_and_back():
    project = fixture_project("made-up", {"boundary": box(0, 0, 200, 120),
                                          "net": box(0, 0, 200, 120), "side": "S",
                                          "road_ft": 60, "dead_end": False, "join": True,
                                          "floors": 8})
    project.layout.orientation = TowerOrientation(axis_deg=0, source=SOURCE,
                                                  status="USER_CONFIRMED")
    brief = make_brief(project)
    [wish] = brief.objectives.soft_preferences
    assert (wish.kind, wish.params, wish.required) == ("orientation", {"axis_deg": 0.0}, True)
    assert (wish.status, wish.source_kind, wish.source) == (
        Provenance.USER_CONFIRMED, SourceKind.ARCHITECT, SOURCE)
    assert required_orientation(brief.objectives.soft_preferences) == Orientation(0.0, 0.0)
    readings = Readings({STILT_IN_RULE_HEIGHT: "counted",
                         CIRCULATION_IN_SETBACK: "not_allowed"}, WhenOpen.STOP)
    back = request(brief, readings, floors_for_max=8).orientation
    assert back == project.layout.orientation


# --- The search -----------------------------------------------------------------------------


def test_with_no_requirement_the_slanted_plot_gets_blocks_along_its_edges():
    made, proposal = _proposals(required=False)
    assert proposal.candidates
    turned = [_off_axis(c, t) for c in proposal.candidates for t in c.towers]
    assert max(turned) > 10  # the plot's own directions are tried, so the test below means it


def test_a_required_orientation_lays_every_block_on_the_axis():
    made, proposal = _proposals(required=True)
    assert proposal.candidates
    for candidate in proposal.candidates:
        for tower in candidate.towers:
            assert _off_axis(candidate, tower) < 1e-6, (candidate.candidate_id, tower.name)
    assert any("the orientation the brief requires" in n for n in proposal.notes)


def test_the_program_check_meets_a_squared_layout_and_never_touches_the_legal_verdict():
    made, proposal = _proposals(required=True)
    for candidate in proposal.candidates:
        report = independent.validate(made.site, made.rules, made.brief, candidate,
                                      made.envelope)
        [check] = [c for c in report.program if c.finding.rule == "Orientation"]
        assert check.family is Family.PROGRAM and check.finding.status is Status.PASS
        assert SOURCE in check.finding.clause
        assert not any(c.finding.rule == "Orientation" for c in report.legal)


def test_a_layout_off_the_axis_does_not_meet_the_requirement():
    made, proposal = _proposals(required=False)
    candidate = max(proposal.candidates,
                    key=lambda c: max(_off_axis(c, t) for t in c.towers))
    required = _requiring(made)
    restated = candidate.model_copy(update={"brief_ref": digest(required.brief)})
    report = independent.validate(required.site, required.rules, required.brief, restated,
                                  required.envelope)
    [check] = [c for c in report.program if c.finding.rule == "Orientation"]
    assert check.finding.status is Status.FAIL
    assert "degrees from it" in check.finding.measured
    unrequired = independent.validate(made.site, made.rules, made.brief, candidate,
                                      made.envelope)
    assert not [c for c in unrequired.program if c.finding.rule == "Orientation"]
    assert report.verdict.legal == unrequired.verdict.legal


# --- A tolerance (2026-10-19: squaring cost 28% of the flats; the architect is asked which
# tolerance Vastu allows) -------------------------------------------------------------------


def test_a_tolerance_brings_every_direction_into_its_window():
    ten = Orientation(0.0, 10.0)
    assert ten.clamp(25) == 10 and ten.clamp(5) == 5 and math.isclose(ten.clamp(115), 170)
    assert sorted(round(a, 6) for a in ten.allowed([25, 115])) == [0, 10, 170]
    assert Orientation(0.0).allowed([25, 115]) == [0.0]  # no tolerance: the axis alone
    # a window of five degrees is not taken for the axis, as the search's own 5 degrees would
    assert sorted(Orientation(0.0, 5.0).allowed([])) == [0.0, 5.0, 175.0]


@pytest.mark.parametrize("tolerance", [-1, 50, "ten", True])
def test_a_tolerance_that_is_not_0_to_45_degrees_is_refused(tolerance):
    with pytest.raises(ValueError, match="tolerance_deg"):
        SoftPreference(kind="orientation", params={"axis_deg": 0, "tolerance_deg": tolerance},
                       required=True)


def test_the_project_files_tolerance_reaches_the_brief_and_back():
    project = fixture_project("made-up", {"boundary": box(0, 0, 200, 120),
                                          "net": box(0, 0, 200, 120), "side": "S",
                                          "road_ft": 60, "dead_end": False, "join": True,
                                          "floors": 8})
    project.layout.orientation = TowerOrientation(axis_deg=0, tolerance_deg=15, source=SOURCE)
    brief = make_brief(project)
    [wish] = brief.objectives.soft_preferences
    assert wish.params == {"axis_deg": 0.0, "tolerance_deg": 15.0}
    assert required_orientation(brief.objectives.soft_preferences) == Orientation(0.0, 15.0)
    readings = Readings({STILT_IN_RULE_HEIGHT: "counted",
                         CIRCULATION_IN_SETBACK: "not_allowed"}, WhenOpen.STOP)
    assert request(brief, readings, floors_for_max=8).orientation == project.layout.orientation


def test_a_required_window_lays_every_block_within_it_and_uses_it():
    """On the plot turned 25 degrees a window of 20 degrees lets the blocks turn 20 of the 25
    towards its edges: every block within it, and the window used, not the axis alone."""
    made, proposal = _proposals(required=True, tolerance=20)
    assert proposal.candidates
    turned = [_off_axis(c, t) for c in proposal.candidates for t in c.towers]
    assert max(turned) <= 20 + 1e-6 and max(turned) > 1
    assert any("within 20 degrees of 0 degrees" in n for n in proposal.notes)
    for candidate in proposal.candidates:
        report = independent.validate(made.site, made.rules, made.brief, candidate,
                                      made.envelope)
        [check] = [c for c in report.program if c.finding.rule == "Orientation"]
        assert check.finding.status is Status.PASS
        assert "within 20 degrees" in check.finding.required
