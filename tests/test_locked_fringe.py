"""A block the architect locks below the high-rise height (2026-10-19, the user: keep the main
body as it is and add only an arm block, with its own pathway): served as the fringe serves its own
blocks, the ring road along a pathway's width or a rule 8(l) pathway of at most 30 m laid first,
or no layout at all, with why; and its prototype found whichever pass's kit leaves it out (a
floor plate in the families' pass). Made-up land (search_support.py)."""

from functools import cache

import pytest
from search_support import l_plot, slim_prototype, strategy
from shapely import affinity
from shapely.ops import unary_union

from siteplan.contracts.candidate import PlacedTower
from siteplan.contracts.common import Shape
from siteplan.optimizer.interfaces import Budget, SearchContext
from siteplan.optimizer.search.build import placement_of
from siteplan.optimizer.search.layout import locked_standing, make_run
from siteplan.optimizer.search.readings import profiles
from siteplan.validator import routes

TEST_CLASS = "normative"
ARM_X = 12.0  # the middle of the L-plot's 24 m arm (x 0 to 24, y 100 to 160)


def _slim_at(y: float, name: str = "T9") -> PlacedTower:
    """The made-up slim block at two floors, running up the arm, centred at (ARM_X, y)."""
    slim = slim_prototype()
    foot = affinity.translate(affinity.rotate(slim.footprint.to_shapely(), 90, origin=(0, 0)),
                              ARM_X, y)
    return PlacedTower(name=name, prototype_id=slim.id, x=ARM_X, y=y, rotation_deg=90,
                       mirrored=False, floors_above_stilt=2, has_stilt=True,
                       footprint=Shape.from_shapely(foot))


@cache
def _proposal(y: float):
    made = l_plot(True)
    context = SearchContext(made.site, made.rules, made.brief, made.envelope, made.kit, 0,
                            Budget(), (_slim_at(y),))
    return strategy().propose(context)


def test_a_locked_low_block_in_the_arm_gets_its_own_pathway_and_keeps_its_place():
    proposal = _proposal(122.0)
    assert proposal.candidates, proposal.notes
    locked = _slim_at(122.0)
    for c in proposal.candidates:
        t9 = next(t for t in c.towers if t.name == "T9")
        assert (t9.x, t9.y, t9.rotation_deg) == (locked.x, locked.y, locked.rotation_deg)
        foot = c.placed_footprint(t9)
        paths = unary_union([s.to_shapely() for r in c.circulation.roads
                             if r.kind.value == "PATHWAY" for s in r.shapes])
        assert not paths.is_empty and foot.distance(paths) < 0.5, c.candidate_id
        way = next(w for w in routes.ways(c, 4.5) if w.tower == "T9")
        assert way.found, way.why


def test_a_locked_block_no_30_m_pathway_reaches_lays_nothing_and_says_why():
    proposal = _proposal(140.0)
    assert not proposal.candidates
    assert any("the locked T9 has neither the ring road along a pathway's width nor a "
               "pathway of at most 30 m to it" in n for n in proposal.notes), proposal.notes


def test_a_locked_blocks_prototype_is_found_when_the_passs_kit_leaves_it_out():
    """The families' pass searches without floor plates; a locked plate (here the made-up slim
    block, kept out of the kit) is still placed where it stands, never offered as a block of its
    own."""
    made = l_plot(False)  # the slim block is in no kit
    found = profiles(made.rules, made.brief, list(made.kit))
    tower = _slim_at(122.0)
    without = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found,
                       locked=[tower])
    assert "is not in the kit" in locked_standing(without, found[0])[1]
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found,
                   locked=[tower], locked_kit=[slim_prototype()])
    standing, why = locked_standing(run, found[0])
    assert not why and [s.name for s in standing] == ["T9"]
    assert slim_prototype().id not in {p.id for p in run.fringe_kit}  # never offered itself


def test_a_slide_moves_the_locked_high_rises_and_never_a_low_block():
    """2026-10-20: the slide is for the ring road round the high-rises; slid with them, a locked
    arm block below 21 m was carried into its front setback (Dhulapally: 3.82 m at the front),
    so a block below the high-rise height stays exactly where it stood."""
    made = l_plot(True)
    high = next(t for t in _proposal(122.0).candidates[0].towers if t.name != "T9")
    found = profiles(made.rules, made.brief, list(made.kit))
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found,
                   locked=[high, _slim_at(122.0)], lock_slide_m=1.0)

    profile = next(p for p in found if not locked_standing(run, p)[1])  # one T1's height is in

    def where(slide):
        standing, why = locked_standing(run, profile, slide)
        assert not why
        return {s.name: placement_of(s, s.name, s.frame) for s in standing}

    still, slid = where((0.0, 0.0)), where((1.0, 0.0))
    assert (slid[high.name].x - still[high.name].x,
            slid[high.name].y - still[high.name].y) == pytest.approx((1.0, 0.0))
    assert (slid["T9"].x, slid["T9"].y) == (still["T9"].x, still["T9"].y)
