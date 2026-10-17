"""Up to ten genuinely different layouts shown, each described in one plain line with its verdict
(2026-10-16, the architect's roadmap, Stage A). Fewer when the site gives fewer, and the run says
why; never a copy. Made-up blocks and land; every expected word is worked out by hand from the
geometry the test builds."""

from optimizer_support import candidate, fixture, module_prototype, tower
from shapely.geometry import Point, box
from validator_helpers import fixture as validator_fixture

from siteplan.contracts.design_brief import Objectives
from siteplan.optimizer.objective import measure
from siteplan.optimizer.pareto import Scored, same_idea, select, shortfall
from siteplan.optimizer.search import Limits
from siteplan.optimizer.search.strategy import options_beyond_points
from siteplan.prototypes.plates import PLATE_SOURCE
from siteplan.service import describe

TEST_CLASS = "normative"

P1, P2 = module_prototype(1), module_prototype(2)  # 31 m and 62 m long, 24.13 m deep, along x
SITE, RULES, BRIEF = fixture()
NET = box(0, 0, 150, 100)


def _brief(**objectives):
    return BRIEF.model_copy(update={"objectives": Objectives(**objectives)})


def _slabs(candidate_id, floors=9, *, at=((40, 20), (110, 75)), rotation=0.0, open_space=300):
    (x1, y1), (x2, y2) = at
    return candidate(candidate_id, [tower("T1", P2, x1, y1, floors, rotation),
                                    tower("T2", P2, x2, y2, floors, rotation)], [P2],
                     open_space_sqm=open_space)


def _pool():
    """Four different ideas and a near-copy of the first (the same slabs moved 2 m)."""
    return [_slabs("slabs"),
            candidate("mixed", [tower("T1", P2, 40, 20, 8), tower("T2", P1, 100, 20, 8),
                                tower("T3", P1, 60, 75, 8)], [P1, P2], open_space_sqm=1200),
            candidate("five", [tower(f"T{i}", P1, 25 + 25 * i, 20 + 12 * (i % 3), 5)
                               for i in range(5)], [P1], open_space_sqm=2400),
            _slabs("near-copy", 8, at=((42, 21), (108, 74))),
            _slabs("turned", 8, rotation=90.0)]


def _scored(pool, brief):
    return [Scored(c, measure(c, brief)) for c in pool]


# --- only different ideas, and why fewer ---------------------------------------------------------


def test_ten_asked_shows_every_different_idea_and_no_copy():
    brief = _brief(options=10)
    pool = _scored(_pool(), brief)
    picks = [p.scored.candidate for p in select(pool, brief).picks]
    assert sorted(c.candidate_id for c in picks) == ["five", "mixed", "slabs", "turned"]
    assert not any(same_idea(a, b) for i, a in enumerate(picks) for b in picks[i + 1:])


def test_fewer_than_asked_says_how_many_passed_and_how_many_were_copies():
    brief = _brief(options=10)
    pool = _scored(_pool(), brief)
    said = shortfall(select(pool, brief), pool, brief)
    assert said == ("4 different layouts shown of the 10 asked: 5 passed the validator, and 1 of "
                    "the other 1 is the same idea as one shown (as many blocks, running the same "
                    "way, on mostly the same ground)")


def test_nothing_is_said_when_the_brief_asks_no_more_than_its_points():
    brief = _brief(options=3)
    pool = _scored(_pool(), brief)
    assert shortfall(select(pool, brief), pool, brief) is None


def test_asking_for_more_raises_only_what_is_judged_and_proposed():
    base = Limits()
    wider = base.for_options(10)
    assert (wider.judged_per_profile, wider.per_profile_proposed) == (10, 10)
    assert (wider.laid_per_profile, wider.attempts_per_profile, wider.heights, wider.offsets) == (
        base.laid_per_profile, base.attempts_per_profile, base.heights, base.offsets)
    assert base.for_options(2) == base


def test_only_a_brief_asking_more_than_its_points_raises_the_search():
    """The brief's four points are always shown; 3 options (the contract's default) asks no
    more, so the search runs as it did before Stage A, and 10 asks six more."""
    assert options_beyond_points(_brief(options=3)) == 0
    assert options_beyond_points(_brief(options=4)) == 0
    assert options_beyond_points(_brief(options=10)) == 10


# --- one plain line each -------------------------------------------------------------------------


def test_a_line_says_the_blocks_their_heights_and_the_way_they_run():
    line = describe.describe(_slabs("slabs"), NET)
    assert line.startswith(f"2 blocks: 2 x {P2.id} at S+9; running east-west")
    assert "running north-south" in describe.describe(_slabs("t", rotation=90.0), NET)
    # turned 45 degrees anticlockwise, the long side points to the north-east
    assert "running north-east to south-west" in describe.describe(
        _slabs("d", rotation=45.0), NET)
    assert "running north-west to south-east" in describe.describe(
        _slabs("e", rotation=-45.0), NET)


def test_a_line_says_where_the_open_space_is_and_that_no_club_house_stands():
    line = describe.describe(_slabs("slabs", open_space=400), NET)  # a 20 m square at the origin
    assert "open space 400 m² in 1 piece, the largest in the south-west" in line
    assert "no club house" in line


def test_where_names_the_centre_or_a_compass_point():
    assert describe.where(Point(75, 50), NET) == "the centre"
    assert describe.where(Point(10, 90), NET) == "the north-west"
    assert describe.where(Point(75, 95), NET) == "the north"
    assert describe.where(Point(140, 5), NET) == "the south-east"


def test_a_line_says_how_it_differs_from_the_most_alike_shown():
    slabs, turned, five = _slabs("slabs"), _slabs("turned", 8, rotation=90.0), _pool()[2]
    line = describe.describe(turned, NET, [slabs, five, turned])
    assert "unlike slabs, the most alike shown: heights S+8, not S+9, running north-south, " \
           "not east-west" in line
    assert describe.describe(slabs, NET, [slabs]).count("unlike") == 0  # nothing else shown


def test_a_plate_is_named_preliminary_in_its_line():
    plate = module_prototype(2, "plate-made-up").model_copy(update={"source": PLATE_SOURCE})
    layout = candidate("p", [tower("T1", plate, 40, 20, 9)], [plate])
    assert "1 block: 1 x plate-made-up (plate, PRELIMINARY) at S+9" in describe.describe(
        layout, NET)


def test_the_verdict_line_names_what_a_conditional_rests_on():
    """No site coordinates on the made-up land: the airport height can only be CONDITIONAL on
    that site fact, so the line must name it."""
    report = validator_fixture("rectangle").report()
    line = describe.verdict_line(report)
    assert line.startswith(report.verdict.legal.value)
    assert report.verdict.legal.value == "CONDITIONAL"
    assert "site facts not yet confirmed: " in line and "site coordinates" in line
