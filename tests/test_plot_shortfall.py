"""Rule 7(a)(ii)'s high-rise plot minimum, read with rule 7(a)(iii)'s road-widening shortfall the
same way by the resolver and by the independent validator (`rules.high_rise_plot_met`).

A site left just short of the minimum by land it gave up for road widening may be counted, and
nothing in the engine settles whether it is: both stages leave it open (the resolver's plot-size
ground unmet but UNVERIFIED, the validator's plot-size check UNVERIFIED). Clearly short, or short
with no land given up, is a refusal in both; at or above the minimum, a pass in both. Made-up land:
the rectangle fixture, whose surrendered strip is the road widening, with its net plot resized."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from shapely.geometry import box
from validator_helpers import fixture

from siteplan import rules
from siteplan.contracts.accounting import DeductionKind
from siteplan.contracts.common import Status
from siteplan.legal.resolve import _plot_ground
from siteplan.provenance import Provenance
from siteplan.validator import blocks, context

TEST_CLASS = "normative"

MINIMUM = rules.MIN_HIGH_RISE_PLOT_SQM  # 2,000 m²
EDGE = MINIMUM * (1 - rules.ROAD_WIDENING_SHORTFALL_ALLOWANCE)  # 1,800 m²: the allowance's end
# A net plot, whether land was given up for road widening, and how both stages must read it.
CASES = [
    pytest.param(MINIMUM + 100, True, True, id="clearly above: met"),
    pytest.param(MINIMUM, True, True, id="exactly the minimum: met"),
    pytest.param(MINIMUM - 1, True, None, id="just short after road widening: open"),
    pytest.param(EDGE, True, None, id="at the allowance's end: open"),
    pytest.param(EDGE - 1, True, False, id="clearly below the allowance: short"),
    pytest.param(MINIMUM - 100, False, False, id="short, no land given up: short"),
]
STATUS = {True: Status.PASS, None: Status.UNVERIFIED, False: Status.FAIL}


def _site(net_sqm: float, surrendered: bool):
    """The rectangle fixture's site with its net plot set to `net_sqm`, keeping or dropping the
    strip it surrenders for road widening."""
    site = fixture("rectangle").site
    own = site.ownership
    kept = [d for d in own.deductions if surrendered or d.kind is not DeductionKind.SURRENDER]
    assert any(d.kind is DeductionKind.SURRENDER for d in kept) is surrendered
    own = own.model_copy(update={"deductions": kept,
                                 "net_sqm": own.net_sqm.model_copy(update={"value": net_sqm})})
    return site.model_copy(update={"ownership": own})


def _resolved(net_sqm: float, surrendered: bool) -> bool | None:
    """The resolver's plot-size ground, read back as met, open or short."""
    ground = _plot_ground(_site(net_sqm, surrendered))
    if ground.met:
        assert ground.status is not Provenance.UNVERIFIED
        return True
    return None if ground.status is Provenance.UNVERIFIED else False


@pytest.fixture(scope="module")
def judged():
    """The validator's own plot-size check on the rectangle fixture (its towers high-rise), with
    the net plot it measures replaced by a square of each case's area."""
    inputs = fixture("rectangle")
    ctx = context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate)
    assert ctx.high_rise_anywhere()

    def check(net_sqm: float, surrendered: bool) -> Status:
        side = math.sqrt(net_sqm)
        land = replace(ctx.land, net=box(0, 0, side, side))
        found = blocks.plot_size_check(replace(ctx, land=land, site=_site(net_sqm, surrendered)))
        return found.finding.status
    return check


@pytest.mark.parametrize(("net_sqm", "surrendered", "expected"), CASES)
def test_the_shared_reading(net_sqm, surrendered, expected):
    assert rules.high_rise_plot_met(net_sqm, surrendered) is expected


@pytest.mark.parametrize(("net_sqm", "surrendered", "expected"), CASES)
def test_the_resolver_reads_it_so(net_sqm, surrendered, expected):
    assert _resolved(net_sqm, surrendered) is expected


@pytest.mark.parametrize(("net_sqm", "surrendered", "expected"), CASES)
def test_the_validator_reads_it_so(judged, net_sqm, surrendered, expected):
    assert judged(net_sqm, surrendered) is STATUS[expected]


@pytest.mark.parametrize(("net_sqm", "surrendered", "expected"), CASES)
def test_the_validator_never_fails_what_the_resolver_leaves_open(judged, net_sqm, surrendered,
                                                                 expected):
    assert judged(net_sqm, surrendered) is STATUS[_resolved(net_sqm, surrendered)]
