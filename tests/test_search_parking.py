"""A cellar dug only as far as the need takes it (C4-13): once the fewest levels are known, its
outline is cut square to the turn from the end the ramp comes down, to the piece the ramp reaches
that holds the need by floor area and by the cars laid out, the same on every level; and the
cellar setback a candidate reports is the rule's band, whatever part of the plot the cellar takes.
Made-up land only."""

from __future__ import annotations

from functools import cache

from search_support import proposal_on_the_rectangle, rectangle
from shapely.geometry import box

from siteplan.contracts.accounting import LayerKind
from siteplan.optimizer.search.land import EMPTY, erode
from siteplan.optimizer.search.layout import make_run
from siteplan.optimizer.search.parking_plan import SAFETY_SQM, plan_parking, ramp_length_m
from siteplan.optimizer.search.readings import profiles

TEST_CLASS = "normative"
REACH_M = 0.5  # the validator's: a ramp this near the cellar reaches it


@cache
def _run():
    made = rectangle()  # 200 x 120 m
    return made, make_run(made.site, made.rules, made.brief, made.envelope, made.kit,
                          profiles(made.rules, made.brief, list(made.kit)))


def _ramp(x0: float):
    """A ramp of the rules' width and length running north from y = 30, its west edge at x0."""
    _, run = _run()
    return box(x0, 30.0, x0 + run.q.ramp_width_m, 30.0 + ramp_length_m(run.q))


def _plan(need_sqm: float, ramps=()):
    made, run = _run()
    share = max(run.q.parking_shares) / 100
    plan, why = plan_parking(run.plot.net, EMPTY, made.rules, run.q, [], [], list(ramps),
                             need_sqm / share, 0.0)
    assert plan is not None, why
    return plan


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
