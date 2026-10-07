"""Floor counts kept or dropped on everything a count asks and rests on (C4-06).

Of two floor counts of a prototype the shorter was dropped whenever the taller asked the same
setback and gap. That hid a shorter count that asks less of something else: NBC's own 15 m line
(the nbc_fire_height reading, contracts 1.3) holds a block of 15 m or more to 4.6's fire access,
which the search lays round no block below 21 m, so a block of 18 m stands only under the state's
line where one of 12 m stands under both. A count is now dropped only behind a taller one that
matches it on all of it; and a profile built to hold under every reading offers no block below 21
m that NBC's line would hold, so its layouts hold under that reading too. Made-up land.
"""

from __future__ import annotations

from functools import cache
from unittest.mock import patch

from search_support import l_plot, strategy

from siteplan.contracts.resolved_rules import NBC_FIRE_HEIGHT
from siteplan.optimizer.search import FullSearchStrategy
from siteplan.optimizer.search.columns import choices_for
from siteplan.optimizer.search.readings import ALL, Profile, floor_classes

TEST_CLASS = "normative"


def _kept(profile: Profile) -> tuple[set[int], set[int]]:
    """The floor counts the L-plot's first prototype takes under a profile, and those kept."""
    made = l_plot()
    prototype = made.kit[0]
    classes = floor_classes(made.rules, made.brief, prototype, profile)
    kept = {c.cls.floors for c in choices_for([prototype], {prototype.id: classes})}
    return {c.floors for c in classes}, kept


def test_a_count_below_nbcs_line_is_kept_beside_a_taller_one_above_it():
    """Under a single reading of the stilt, three floors (12 m) and five (18 m) ask the same 6 m
    setback and gap; NBC's line holds the five-floor block to 4.6's fire access and not the
    three-floor one, so both are kept. Four floors (15 m) asks nothing less than five and is
    held as five is: dropped. One floor asks nothing less than two: dropped."""
    offered, kept = _kept(Profile("not_counted", ALL))
    assert {1, 2, 3, 4, 5} <= offered
    assert {2, 3, 5} <= kept
    assert not {1, 4} & kept


def test_a_profile_built_for_every_reading_offers_no_low_block_nbcs_line_would_hold():
    every, _ = _kept(Profile(ALL, ALL))
    single, _ = _kept(Profile("not_counted", ALL))
    assert {1, 2, 3} <= every and not {4, 5} & every  # 15 m and above: held under NBC's line
    assert {4, 5} <= single  # a profile that rests on a reading may rest on the state's line
    assert {7, 8, 9} <= every  # the high-rises are held to 4.6 by law and given fire lanes


@cache
def _judged_on_the_l_plot() -> list:
    found = []
    real = FullSearchStrategy._choose

    def recording(self, judged, brief):
        found.extend(judged)
        return real(self, judged, brief)

    with patch.object(FullSearchStrategy, "_choose", recording):
        strategy().propose(l_plot().context())
    return found


def test_the_layouts_built_for_every_reading_hold_under_every_reading_of_nbcs_line():
    judged = [j for j in _judged_on_the_l_plot() if j.profile.every_reading(l_plot().rules)]
    low = [j for j in judged if any(t.floors_above_stilt < 7 for t in j.candidate.towers)]
    assert low  # layouts with blocks below 21 m were judged in that profile
    for j in judged:
        assert NBC_FIRE_HEIGHT not in j.rests.readings, j.candidate.candidate_id
