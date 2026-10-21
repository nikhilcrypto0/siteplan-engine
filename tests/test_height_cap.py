"""The client's cap on the height and the club house's storeys (2026-10-21, the user for
Dhulapally: Stilt + 9 at most, under NBC's 30 m line, never Stilt + 10; the club house at 4
floors). Both are the client's choices, never law: an answers file states them, the project
carries them with where they came from, the brief keeps the cap as a range from Stilt + 1 (lower
blocks still allowed) even when asked for the most the rules allow, and the search never lays a
block above it. Made-up land."""

from search_support import made_up, strategy
from shapely.geometry import box
from test_intake import ANSWERS, _draft

from siteplan.adapters.legacy_site import Readings, brief, request
from siteplan.contracts.common import Provenance
from siteplan.contracts.design_brief import HeightMode
from siteplan.contracts.resolved_rules import (
    CIRCULATION_IN_SETBACK,
    STILT_IN_RULE_HEIGHT,
    WhenOpen,
)
from siteplan.intake import WorkspaceDefaults, build_project
from siteplan.project import Project

TEST_CLASS = "normative"


def _project(**more) -> Project:
    return Project.model_validate(build_project(_draft(), ANSWERS | more))


def test_an_answers_file_caps_the_floors_and_sets_the_club_house_storeys():
    p = _project(floors_at_most="9", club_house_floors="4")
    assert p.layout.maximise and p.layout.floors_at_most == 9 and p.layout.floors <= 9
    assert p.layout.club_house_floors == 4
    for key in ("floors_at_most", "club_house_floors"):
        assert p.status[key] is Provenance.USER_CONFIRMED and p.sources[key]
    plain = _project()
    assert plain.layout.floors_at_most is None and plain.layout.club_house_floors == 2


def test_the_cap_reaches_the_brief_as_a_range_and_back():
    b = brief(_project(floors_at_most="9", club_house_floors="4"))
    h = b.height_intent
    assert h.mode is HeightMode.RANGE and h.floors_range == (1, 9)
    assert b.program.club_house.floors == 4
    back = request(b, Readings({STILT_IN_RULE_HEIGHT: "not_counted",
                                CIRCULATION_IN_SETBACK: "allowed"}, WhenOpen.STOP),
                   floors_for_max=9)
    assert back.maximise and back.floors_at_most == 9
    assert brief(_project()).height_intent.mode is HeightMode.MAX_LEGAL  # no cap: as before


def test_the_most_the_rules_allow_stays_within_the_cap():
    from siteplan.service.brief import design  # noqa: PLC0415
    from siteplan.service.models import HeightChoice, Intent  # noqa: PLC0415

    p = _project(floors_at_most="9")
    made = design(p, WorkspaceDefaults(), None,
                  Intent(height=HeightChoice.MOST_THE_RULES_ALLOW), "the most")
    assert made.height_intent.mode is HeightMode.RANGE and made.height_intent.floors_range == (1, 9)


def test_the_search_lays_no_block_above_the_cap():
    made = made_up(box(0, 0, 200, 120))
    capped = made.brief.model_copy(deep=True)
    capped.height_intent = capped.height_intent.model_copy(
        update={"mode": HeightMode.RANGE, "floors_range": (1, 6), "floors_above_stilt": None})
    inputs = made.__class__(made.site, made.rules, capped, made.envelope, made.kit)
    found = strategy().propose(inputs.context()).candidates
    assert found and all(t.floors_above_stilt <= 6 for c in found for t in c.towers)
