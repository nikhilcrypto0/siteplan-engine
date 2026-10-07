"""Iterative repair of the layouts the full search lays out (C4-07). The club house stands where its
own band allows, as the validator holds it, and turns to the plot's own directions; when the ramp
then finds no room it is laid before the club house, and when the open space finds none the club
house keeps off it; and the most valuable layouts with blocks below 21 m are evaluated again with
the fringe keeping no room for the program, the exact half saying whether the program still has
room, a block given up at a time until it lays out. Made-up land; every layout still judged by
the independent validator.
"""

from __future__ import annotations

from functools import cache
from types import SimpleNamespace
from unittest.mock import patch

from search_support import l_plot, rectangle, strategy
from shapely.geometry import Point, box

from siteplan import validator as independent
from siteplan.contracts.validation import LegalVerdict
from siteplan.geometry import frontage
from siteplan.optimizer.search import FullSearchStrategy, ground
from siteplan.optimizer.search import layout as layout_module
from siteplan.optimizer.search import strategy as strategy_module
from siteplan.optimizer.search.build import build_candidate
from siteplan.optimizer.search.land import EMPTY, make_land
from siteplan.optimizer.search.layout import CLUB_FLOORS, RAMP_FIRST, make_run
from siteplan.optimizer.search.readings import profiles

TEST_CLASS = "normative"


def test_the_club_house_stands_where_its_own_band_allows():
    """On the 200 x 120 m rectangle the towers' zone is 10 m deep; a two-storey club house keeps
    Table III's 5 m on the sides. Ground 7 m from the east side is the club house's, not the
    open ground of before."""
    made = rectangle()
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit,
                   profiles(made.rules, made.brief, list(made.kit)))
    land = make_land(run.plot, zone_depth_m=10.0, strip_width_m=0.0, ring_width_m=run.q.road_m,
                     roads_may_use_setback=False)
    zones = ground.zones_of([], [], EMPTY, EMPTY, run.q.reach_m)
    buildable = ground.buildable_ground(run.plot, ground.open_ground(run.plot, land, zones))
    room = layout_module._club_ground(run, land, zones, CLUB_FLOORS, buildable)
    seven_from_the_east = Point(193.0, 60.0)
    assert room.contains(seven_from_the_east) and not buildable.contains(seven_from_the_east)
    assert not room.contains(Point(197.0, 60.0))  # within its own 5 m


@cache
def _laid_on(name: str) -> tuple:
    """The quick search on made-up land, every layout laid out with the program it was laid
    on, and every report the validator wrote."""
    made = l_plot() if name == "l_plot" else rectangle()
    laid, programs, reports = [], [], []
    real_lay, real_furnish = strategy_module.lay_out, layout_module._furnish
    real_validate = independent.validate

    def watched(run, ev):
        result, why = real_lay(run, ev)
        if result is not None:
            laid.append((run, ev, result))
        return result, why

    def furnishing(run, program, repair=None):
        out = real_furnish(run, program, repair)
        if repair is None and out[0] is not None:
            programs.append((run, program, out[0]))
        return out

    def validating(*args):
        report = real_validate(*args)
        reports.append(report)
        return report

    with patch.object(strategy_module, "lay_out", watched), \
            patch.object(layout_module, "_furnish", furnishing), \
            patch.object(strategy_module.independent, "validate", validating):
        proposal = strategy().propose(made.context())
    return made, laid, programs, reports, proposal


def test_the_ramp_laid_first_gives_a_layout_the_validator_does_not_fail():
    """The programs the rectangle's first layouts were laid on, furnished again with the ramp
    before the club house: where the cellars need a ramp it stands clear of the club house, and
    the layout built from it the validator does not fail."""
    made, laid, programs, _, _ = _laid_on("rectangle")
    by_program = {id(furnished): (run, program) for run, program, furnished in programs}
    checked = 0
    for _, ev, result in laid[:4]:
        run, program = next(by_program[k] for k in by_program
                            if by_program[k][1].placements == result.placements)
        furnished, why = layout_module._furnish(run, program, RAMP_FIRST)
        assert furnished is not None, why
        if not furnished.ramps:
            continue
        clear = furnished.ramps[0].buffer(ground.CLEARANCE_M, join_style="mitre")
        assert furnished.club is None or furnished.club.intersection(clear).area < 1e-6
        again = layout_module.Laid(**{**result.__dict__, "club": furnished.club,
                                      "ramps": furnished.ramps, "pockets": furnished.pockets,
                                      "facilities": furnished.facilities,
                                      "facilities_missed": furnished.missed,
                                      "cellars": furnished.plan.cellars,
                                      "cars": layout_module._cars(furnished.plan)})
        candidate = build_candidate(again, site=made.site, rules=made.rules, brief=made.brief,
                                    plot=run.plot, q=run.q, profile=ev.config.profile,
                                    envelope=run.envelope, candidate_id="ramp-first", seed=0,
                                    notes=[])
        report = independent.validate(made.site, made.rules, made.brief, candidate,
                                      made.envelope)
        assert report.verdict.legal is not LegalVerdict.FAIL
        checked += 1
    assert checked


def test_the_repair_lays_out_more_valuable_layouts_after_all_the_others():
    """On the L-plot the repair lays out layouts of the fringe that keeps no room, each worth more
    than every layout of its profile and kind it was tried from would be without it, after all
    the others; the validator fails none of the search's layouts."""
    _, laid, _, reports, proposal = _laid_on("l_plot")
    repaired = [i for i, (_, ev, _) in enumerate(laid) if not ev.config.fringe_room]
    assert repaired and repaired == list(range(repaired[0], len(laid)))  # after all the others
    for i in repaired:
        _, ev, _ = laid[i]
        same = [e.value for _, e, _ in laid[:repaired[0]]
                if e.config.profile.key == ev.config.profile.key and e.config.low_blocks]
        assert same and ev.value > min(same)
    assert all(r.verdict.legal is not LegalVerdict.FAIL for r in reports)
    assert any(c.candidate_id in {f"full-{laid[i][1].config.profile.key}-{i + 1}"
                                  for i in repaired} for c in proposal.candidates)


def test_a_layout_is_never_repaired_twice():
    """The repair's layouts are tried once each: none is the same as another laid out."""
    _, laid, _, _, _ = _laid_on("l_plot")
    signatures = [strategy_module._signature(ev) for _, ev, _ in laid]
    assert len(signatures) == len(set(signatures))


def test_the_repair_is_a_pass_of_its_own_the_others_keep_their_numbers():
    """The layouts laid before the repair are laid as without it: switching the repair off
    changes none of their numbers or values."""
    _, laid, _, _, _ = _laid_on("l_plot")
    before = [(ev.config.key, ev.value) for _, ev, _ in laid if ev.config.fringe_room]
    seen = []
    real = strategy_module.lay_out

    def watched(run, ev):
        result, why = real(run, ev)
        if result is not None:
            seen.append((ev.config.key, ev.value))
        return result, why

    with patch.object(FullSearchStrategy, "_improve", lambda *args: []), \
            patch.object(strategy_module, "lay_out", watched):
        strategy().propose(l_plot().context())
    assert seen == before


def test_a_stilt_holds_cars_only_where_a_car_can_drive_into_it():
    """Rule 13(c)(viii)'s 4.5 m driveway, as the validator reads the way into a stilt: a block
    with 20 m of its outline on a road is entered, one that meets the road at a corner is not
    (C4-07: the generator counted every stilt's cars, the validator only the entered ones)."""
    road = box(0, 0, 100, 9)
    entered, corner = box(10, 9, 30, 40), box(100, 9, 120, 40)
    assert frontage(entered, road, 0.5) >= 20.0 - 1e-9
    assert frontage(corner, road, 0.5) < 4.5
    q = SimpleNamespace(driveway_m=4.5)
    assert layout_module._stilts([entered, corner], road, q) == [entered]


def test_the_validator_counts_every_stilt_the_generator_counted():
    """On the made-up rectangle and L-plot, no layout the validator judges leaves a stilt out of
    its parking that the generator's plan counted."""
    for name in ("rectangle", "l_plot"):
        _, _, _, reports, _ = _laid_on(name)
        for report in reports:
            parking = next(c for c in report.legal if c.finding.rule == "Parking (Table V)")
            assert "not counted, the stilt of" not in parking.finding.measured
