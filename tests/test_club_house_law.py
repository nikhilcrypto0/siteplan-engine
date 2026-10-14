"""The club house: the law's ceiling and the client's 3 %, kept apart (2026-10-13).

Rule 15(a)(x) as G.O.Ms.No.7 of 2016 substituted it (read from its text, pp.4-5): from 100 units
an amenities block "shall be planned", "upto 3% of the total built up area (or) 50,000 Sft.
whichever is lower", not part of the residential blocks. The 3 % the architect approved for the
firm's schemes is a program requirement: the search lays it and never above the law's ceiling.

Every expected figure is worked out by hand: with 97,000 m² of towers, 3 % of all the built-up
area (the club house counted) is 0.03 x 97,000 / 0.97 = 3,000 m².
"""

from dataclasses import replace

import pytest
from search_support import proposal_on_the_rectangle, rectangle

from siteplan.contracts.common import Status
from siteplan.optimizer.search import ground
from siteplan.optimizer.search.quantities import quantities
from siteplan.validator import validate

TEST_CLASS = "normative"
TOWERS_SQM = 97_000.0
UNITS = 200


@pytest.fixture(scope="module")
def q():
    made = rectangle()
    return replace(quantities(made.site, made.rules, made.brief), club_share=0.03,
                   club_cap_sqm=50_000 * 0.09290304, club_from_units=100)


def test_with_no_share_asked_the_club_house_is_the_laws_ceiling(q):
    assert ground.club_size_sqm(q, TOWERS_SQM, UNITS) == pytest.approx(3_000.0)


def test_the_50000_sft_cap_lowers_the_ceiling_where_it_is_the_lower(q):
    capped = replace(q, club_cap_sqm=2_000.0)
    assert ground.club_ceiling_sqm(capped, TOWERS_SQM) == pytest.approx(2_000.0)
    assert ground.club_size_sqm(capped, TOWERS_SQM, UNITS, 0.03) == pytest.approx(2_000.0)


def test_the_share_the_brief_asks_is_laid_and_never_above_the_ceiling(q):
    assert ground.club_size_sqm(q, TOWERS_SQM, UNITS, 0.02) == pytest.approx(
        0.02 * 97_000 / 0.98)  # 1,979.6 m²: under the ceiling, laid as asked
    assert ground.club_size_sqm(q, TOWERS_SQM, UNITS, 0.04) == pytest.approx(3_000.0)


def test_below_the_units_the_clause_names_nothing_is_asked(q):
    assert ground.club_size_sqm(q, TOWERS_SQM, 99, 0.03) == 0.0


def test_the_search_lays_no_club_house_the_law_fails():
    made, proposal = rectangle(), proposal_on_the_rectangle()
    assert proposal.candidates
    for candidate in proposal.candidates:
        report = validate(made.site, made.rules, made.brief, candidate, made.envelope)
        club = next(c for c in report.legal if c.finding.rule == "Amenities (club house)")
        assert club.finding.status is not Status.FAIL, (candidate.candidate_id,
                                                        club.finding.measured)
