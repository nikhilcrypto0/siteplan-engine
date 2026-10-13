"""The architect's answers to open readings (2026-10-13), recorded as his and not as a test's:
`resolve(..., answered=...)` marks a selected reading USER_CONFIRMED with his words as its source.
And his access test, the `fire_band` answer to opens_onto_road, offered only when a project selects
it: no length of facade on a road is asked; a block is served when its 6 m fire band (NBC Part 3
4.6(c)) meets a road along at least 6 m. Every other site's rules read as before. Made-up land."""

TEST_CLASS = "normative"

import pytest  # noqa: E402
from legal_fixtures import make_site  # noqa: E402
from shapely.geometry import box  # noqa: E402

from siteplan.contracts.common import Provenance  # noqa: E402
from siteplan.contracts.resolved_rules import (  # noqa: E402
    FIRE_BAND,
    FRONTAGE,
    OPENS_ONTO_ROAD,
    TOUCH,
    ResolvedRules,
)
from siteplan.legal.resolve import resolve  # noqa: E402
from siteplan.validator.roads import opens_onto  # noqa: E402

SITE = make_site(box(0, 0, 200, 120))
SAID = "the architect, 2026-10-13: a block's 6 m fire band meets a road along 6 m"


class _Block:
    footprint = box(0, 10, 30, 30)


def test_an_answered_reading_is_the_architects_not_a_tests():
    rules = resolve(SITE, selections={OPENS_ONTO_ROAD: FIRE_BAND},
                    answered={OPENS_ONTO_ROAD: SAID})
    reading = rules.interpretation(OPENS_ONTO_ROAD)
    assert reading.selected == FIRE_BAND and reading.status is Provenance.USER_CONFIRMED
    assert reading.sources[-1] == SAID
    tested = resolve(SITE, selections={OPENS_ONTO_ROAD: TOUCH})
    assert tested.interpretation(OPENS_ONTO_ROAD).status is Provenance.ASSUMED_FOR_TEST


def test_an_answer_to_an_open_reading_is_refused():
    with pytest.raises(ValueError, match="not a selected reading"):
        resolve(SITE, answered={OPENS_ONTO_ROAD: SAID})


def test_the_fire_band_answer_is_offered_only_when_selected():
    assert set(resolve(SITE).interpretation(OPENS_ONTO_ROAD).alternatives) == {TOUCH, FRONTAGE}
    chosen = resolve(SITE, selections={OPENS_ONTO_ROAD: FIRE_BAND})
    assert FIRE_BAND in chosen.interpretation(OPENS_ONTO_ROAD).alternatives
    ResolvedRules.model_validate(chosen.model_dump())  # the contract takes it


def test_a_block_is_served_when_its_fire_band_meets_a_road_along_6_m():
    six_away = box(-10, 0, 40, 4)  # the road's edge 6 m from the block
    seven_away = box(-10, 0, 40, 3)
    assert opens_onto(_Block, six_away, FIRE_BAND, None, 6.0) is True
    assert opens_onto(_Block, seven_away, FIRE_BAND, None, 6.0) is False
    corner = box(-10, -10, -5, 4)  # the band only nicks a road off the block's corner
    assert opens_onto(_Block, corner, FIRE_BAND, None, 6.0) is False
    assert opens_onto(_Block, six_away, FIRE_BAND, None, None) is None  # no width: unknown


def test_an_answer_never_takes_the_place_of_a_legal_source():
    """Recording an answer drops only the test profile's marker; every source the reading cites
    stays (it once replaced the last source, a legal one for a reading selected by default)."""
    from siteplan.contracts.resolved_rules import FIRE_TURNING_RADIUS
    from siteplan.legal.readings import SELECTED_BY_PROFILE

    default = resolve(SITE).interpretation(FIRE_TURNING_RADIUS)
    answered = resolve(SITE, answered={FIRE_TURNING_RADIUS: SAID}).interpretation(
        FIRE_TURNING_RADIUS)
    assert answered.sources == [*default.sources, SAID]
    selected = resolve(SITE, selections={OPENS_ONTO_ROAD: FIRE_BAND},
                       answered={OPENS_ONTO_ROAD: SAID}).interpretation(OPENS_ONTO_ROAD)
    assert SELECTED_BY_PROFILE not in selected.sources and selected.sources[-1] == SAID
    assert selected.sources[:-1] == resolve(SITE).interpretation(OPENS_ONTO_ROAD).sources
