"""A cellar dug only as far as the need takes it (C4-13): once the fewest levels are known, its
outline is cut square to the turn from the end the ramp comes down, to the piece the ramp reaches
that holds the need by floor area and by the cars laid out, the same on every level; and the
cellar setback a candidate reports is the rule's band, whatever part of the plot the cellar takes.
And (C4-17) it reaches under every block that may stand over a cellar, on the ground its ramp
reaches, before it grows for the need: a design choice (the lifts reach the parking), never a rule.
Made-up land only."""

from __future__ import annotations

from functools import cache

from search_support import l_plot, proposal_on_the_l_plot, proposal_on_the_rectangle, rectangle
from shapely.geometry import box
from shapely.ops import unary_union

from siteplan.contracts.accounting import LayerKind
from siteplan.optimizer.search.land import EMPTY, erode, plot_of, polygons
from siteplan.optimizer.search.layout import make_run
from siteplan.optimizer.search.parking_plan import SAFETY_SQM, plan_parking, ramp_length_m
from siteplan.optimizer.search.readings import profiles
from siteplan.validator import context as vctx

TEST_CLASS = "normative"
REACH_M = 0.5  # the validator's: a ramp this near the cellar reaches it
NOISE_SQM = 0.5  # the validator's: less overlap than this is drawing noise
NEAR = box(30.0, 60.0, 60.0, 84.0)  # a block by the ramp at x = 20
FAR = box(150.0, 40.0, 180.0, 64.0)  # a block 130 m from it, as Phase 5's T5 stood 114 m off


@cache
def _run():
    made = rectangle()  # 200 x 120 m
    return made, make_run(made.site, made.rules, made.brief, made.envelope, made.kit,
                          profiles(made.rules, made.brief, list(made.kit)))


def _ramp(x0: float):
    """A ramp of the rules' width and length running north from y = 30, its west edge at x0."""
    _, run = _run()
    return box(x0, 30.0, x0 + run.q.ramp_width_m, 30.0 + ramp_length_m(run.q))


def _plan(need_sqm: float, ramps=(), reach=(), clear_of=EMPTY):
    made, run = _run()
    share = max(run.q.parking_shares) / 100
    plan, why = plan_parking(run.plot.net, EMPTY, made.rules, run.q, [], [], list(ramps),
                             need_sqm / share, 0.0, clear_of, reach=list(reach))
    assert plan is not None, why
    return plan


def _covered(block, outline) -> bool:
    return block.difference(outline.buffer(0.01)).area < NOISE_SQM


def test_a_cellar_takes_only_the_ground_its_need_takes_and_the_ramp_reaches_it():
    """4,000 m² of parking asked: the whole plot under the setback was dug for it, about 22,000
    m² a level; now the piece by the ramp that holds it, by floor area and by cars laid out."""
    whole = _plan(4000.0)  # the first pass, before a ramp stands: the whole, as before
    ramp = _ramp(20.0)
    sized = _plan(4000.0, [ramp])
    assert sized.cellars.levels == whole.cellars.levels == 1
    assert sized.cellars.outline.area < 0.4 * whole.cellars.outline.area
    assert sized.cellars.outline.difference(whole.cellars.outline).area < 1e-6
    assert sized.provided_sqm >= sized.need_sqm + SAFETY_SQM
    assert sized.provided_sqm < 1.25 * sized.need_sqm  # the whole level gave about four times
    assert ramp.distance(sized.cellars.outline) <= REACH_M


def test_the_cellar_lies_at_the_end_the_ramp_comes_down():
    west = _plan(4000.0, [_ramp(20.0)]).cellars.outline
    east = _plan(4000.0, [_ramp(170.0)]).cellars.outline
    assert west.centroid.x < 60 and east.centroid.x > 140


def test_every_level_of_a_deeper_cellar_is_cut_to_what_it_still_needs():
    """More than one whole level asked: two levels (the setback of the deeper applied to both),
    each the same piece, smaller than the two whole levels would have been."""
    whole = _plan(28000.0)
    sized = _plan(28000.0, [_ramp(20.0)])
    assert sized.cellars.levels == whole.cellars.levels == 2
    assert sized.cellars.outline.area < 0.9 * whole.cellars.outline.area
    assert sized.provided_sqm >= sized.need_sqm + SAFETY_SQM


def test_the_cellar_setback_reported_is_the_rules_band_whatever_the_cellar_takes():
    """Every proposal on the rectangle: its CELLAR_SETBACK layer is the band of the setback it
    keeps from the plot line, never the ground the cellar leaves undug."""
    _, run = _run()
    net = run.plot.net
    checked = 0
    for laid in proposal_on_the_rectangle().candidates:
        if laid.program.cellars is None:
            continue
        band = net.difference(erode(net, laid.program.cellars.setback_m))
        layer = [s.to_shapely() for layer in laid.rule_layers.of(LayerKind.CELLAR_SETBACK)
                 for s in layer.shapes]
        assert abs(sum(s.area for s in layer) - band.area) < 1.0, laid.candidate_id
        checked += 1
    assert checked


def test_a_cellar_reaches_every_block_that_may_stand_over_it_then_grows_only_for_the_need():
    """9,000 m² asked, a block by the ramp and one 130 m away: before, the cellar grew evenly round
    the ramp and the far block's lifts reached no parking; now both stand over it, and it still
    digs about what the need asks, not the whole level."""
    whole = _plan(9000.0)
    ramp = _ramp(20.0)
    plan = _plan(9000.0, [ramp], reach=[NEAR, FAR])
    outline = plan.cellars.outline
    assert plan.cellars.levels == 1
    assert _covered(NEAR, outline) and _covered(FAR, outline)
    assert plan.provided_sqm >= plan.need_sqm + SAFETY_SQM
    assert plan.provided_sqm < 1.1 * plan.need_sqm
    assert ramp.distance(outline) <= REACH_M
    assert outline.area < 0.6 * whole.cellars.outline.area


def test_a_small_need_digs_no_more_than_the_hull_of_the_ramp_and_the_blocks():
    """The blocks alone give more than 4,000 m²: the cellar is the hull of the ramp's and the
    blocks' boxes (the turn is 0, so the frames agree), never the box round all three."""
    ramp = _ramp(20.0)
    plan = _plan(4000.0, [ramp], reach=[NEAR, FAR])
    outline = plan.cellars.outline
    hull = unary_union([box(*g.bounds) for g in (ramp, NEAR, FAR)]).convex_hull
    assert outline.difference(hull.buffer(1e-6)).area < 1e-6
    assert _covered(NEAR, outline) and _covered(FAR, outline)
    everything = box(*unary_union([ramp, NEAR, FAR]).bounds)
    assert outline.area < 0.8 * everything.intersection(_plan(4000.0).cellars.outline).area


def test_a_cellar_goes_round_a_block_with_no_fire_band_to_reach_a_block():
    """A low block (no fire band, so no cellar under it) stands across most of the plot between
    the ramp and the far block: the cellar runs round it and still reaches the far block."""
    wall = box(95.0, 12.0, 105.0, 100.0)
    ramp = _ramp(20.0)
    plan = _plan(9000.0, [ramp], reach=[NEAR, FAR], clear_of=wall)
    outline = plan.cellars.outline
    assert plan.cellars.levels == 1
    assert _covered(FAR, outline)
    assert outline.intersection(wall).area < 1e-6
    assert ramp.distance(outline) <= REACH_M


def test_a_block_no_ground_joins_to_the_ramp_is_left_alone():
    """A low block across the whole plot cuts the far block off: the near one is reached, the far
    one is left alone rather than forced, and nothing runs under the low block."""
    wall = box(95.0, 0.0, 105.0, 120.0)
    plan = _plan(4000.0, [_ramp(20.0)], reach=[NEAR, FAR], clear_of=wall)
    outline = plan.cellars.outline
    assert _covered(NEAR, outline)
    assert FAR.intersection(outline).area < 1e-6
    assert outline.intersection(wall).area < 1e-6


def test_no_layout_leaves_a_block_that_may_have_a_cellar_without_one():
    """Every proposal on the made-up plots that digs a cellar: each block the validator does not
    hold low under any reading (so a cellar may stand under it) has its part on the ground the
    ramp reaches under the cellar. Before C4-17 the cellar grew evenly round the ramp, ran under
    ground no block needed and left far blocks' lifts with no parking (T1, T3 and T5 at 19% on the
    rectangle)."""
    _, run = _run()
    bay_sqm = run.q.bay_m[0] * run.q.bay_m[1]
    checked = 0
    for made, proposal in ((rectangle(), proposal_on_the_rectangle()),
                           (l_plot(), proposal_on_the_l_plot()),
                           (l_plot(True), proposal_on_the_l_plot(True))):
        plot = plot_of(made.site, made.envelope)
        for laid in proposal.candidates:
            cellars = laid.program.cellars
            if cellars is None or not cellars.levels:
                continue
            ctx = vctx.build(made.site, made.rules, made.brief, laid)
            low = {t.name for t in ctx.low_rise_anywhere()}
            under = unary_union([s.to_shapely() for s in cellars.outline])
            ramps = unary_union([s.to_shapely() for s in laid.program.ramps])
            room = erode(plot.net, cellars.setback_m).difference(plot.excluded).difference(
                unary_union([t.footprint for t in ctx.towers if t.name in low]))
            side = min(polygons(room), key=lambda p: p.distance(ramps))
            for t in ctx.towers:
                wanted = t.footprint.intersection(side)
                if t.name in low or wanted.area < bay_sqm:
                    continue
                assert _covered(wanted, under), (laid.candidate_id, t.name)
                checked += 1
    assert checked
