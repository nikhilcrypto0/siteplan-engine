"""Columns of more than one depth in a layout (C4-04).

The columns took the kit's main depth (the one most of its prototypes come in) and left the other
depths to the fringe. Where the kit has blocks of other depths, each column may now be of
whichever depth adds the most saleable area for the width it takes (its depth and the street
beside it), and the layout keeps the columns of the main depth alone when those add more. Made-up
land and the made-up slim block (13.13 m deep beside the kit's 25.79 m).
"""

from __future__ import annotations

from dataclasses import replace
from functools import cache
from unittest.mock import patch

from search_support import Made, l_plot, rectangle, slim_prototype, strategy
from shapely.geometry import box

from siteplan.optimizer.search import strategy as strategy_module
from siteplan.optimizer.search.columns import choices_for
from siteplan.optimizer.search.frame import Frame
from siteplan.optimizer.search.land import make_land
from siteplan.optimizer.search.layout import Config, Failure, _columns, evaluate, make_run
from siteplan.optimizer.search.readings import profiles

TEST_CLASS = "normative"


@cache
def _run():
    made = rectangle()
    slim = Made(made.site, made.rules, made.brief, made.envelope, (*made.kit, slim_prototype()))
    found = profiles(slim.rules, slim.brief, list(slim.kit))
    run = make_run(slim.site, slim.rules, slim.brief, slim.envelope, slim.kit, found)
    profile = next(p for p in found if p.key == "ALL-allowed")
    classes = {pid: [c for c in got if c.floors <= 9 and c.high_rise]
               for pid, got in run.classes[profile.key].items()}
    deep = choices_for(run.kit, classes)
    others = choices_for([p for p in run.fringe_kit if round(p.depth_m, 2) != run.depth_m],
                         classes)
    return run, profile, deep, others


def _land_wide(width_m: float):
    """Land for the columns, `width_m` across and 90 m along, inside the made-up rectangle's
    setbacks; in a frame turned so the columns run along y."""
    run, profile, _, _ = _run()
    land = make_land(run.plot, zone_depth_m=10.0, strip_width_m=0.0, ring_width_m=run.q.road_m,
                     roads_may_use_setback=False)
    return replace(land, cluster_land=box(20.0, 20.0, 20.0 + width_m, 110.0))


def _street(choices) -> float:
    run = _run()[0]
    return max(run.q.road_m, max(c.cls.gap_m for c in choices) + run.q.gap_margin_m)


def test_a_column_of_another_depth_takes_the_width_the_main_depth_leaves():
    run, profile, deep, others = _run()
    assert others and {round(c.depth_m, 2) for c in others} == {13.13}
    street = _street([*deep, *others])
    two_deep_one_slim = 2 * run.depth_m + 13.13 + 2 * street + 0.5
    land = _land_wide(two_deep_one_slim)
    config = Config(profile, 90.0, 0.0, 9)
    alone, alone_total = _columns(run, config, Frame(90.0), land, deep, street)
    mixed, mixed_total = _columns(run, config, Frame(90.0), land, deep, street, others)
    assert {round(s.choice.depth_m, 2) for s in alone} == {run.depth_m}
    assert {round(s.choice.depth_m, 2) for s in mixed} == {run.depth_m, 13.13}
    assert mixed_total > alone_total
    columns = sorted({s.column for s in mixed})
    assert columns == list(range(len(columns)))  # numbered in order, so streets join neighbours
    by_column = {c: [s for s in mixed if s.column == c] for c in columns}
    for left, right in zip(columns, columns[1:], strict=False):
        gap = min(s.x0 for s in by_column[right]) - max(s.x1 for s in by_column[left])
        assert gap >= street - 1e-6  # a street's width between neighbouring columns


def test_where_the_main_depth_fills_the_land_the_columns_are_as_before():
    run, profile, deep, others = _run()
    street = _street([*deep, *others])
    land = _land_wide(2 * run.depth_m + street + 0.5)  # two deep columns and no more
    config = Config(profile, 90.0, 0.0, 9)
    alone = _columns(run, config, Frame(90.0), land, deep, street)
    mixed = _columns(run, config, Frame(90.0), land, deep, street, others)
    assert mixed[1] == alone[1]
    assert [(s.choice.key, s.x0, s.y0) for s in mixed[0]] == \
        [(s.choice.key, s.x0, s.y0) for s in alone[0]]


def test_mixing_depths_never_lays_less_than_the_main_depth_alone():
    run, profile, deep, others = _run()
    street = _street([*deep, *others])
    config = Config(profile, 90.0, 0.0, 9)
    for width in range(40, 150, 7):
        land = _land_wide(float(width))
        alone = _columns(run, config, Frame(90.0), land, deep, street)[1]
        mixed = _columns(run, config, Frame(90.0), land, deep, street, others)[1]
        assert mixed >= alone, width


def test_no_block_lays_no_column():
    run, profile, _, _ = _run()
    land = _land_wide(80.0)
    assert _columns(run, Config(profile, 90.0, 0.0, 9), Frame(90.0), land, [], 12.0) == ([], 0.0)


@cache
def _laid_on_the_slim_l_plot() -> list[tuple[bool, set[float]]]:
    """Every layout the quick search lays out on the L-plot with the slim block in its kit, in the
    order laid, but those its iterative repair (C4-07) lays after all of them: whether its
    configuration let the kit's other depths stand in columns, and the depths its columns
    hold."""
    laid = []
    real = strategy_module.lay_out

    def watched(run, ev):
        result, why = real(run, ev)
        if result is not None and ev.config.fringe_room:
            laid.append((ev.config.mixed_depths,
                         {round(s.choice.depth_m, 2) for s in ev.standing}))
        return result, why

    with patch.object(strategy_module, "lay_out", watched):
        strategy().propose(l_plot(True).context())
    return laid


def test_the_configurations_before_c4_04_stand_the_main_depth_alone_and_are_laid_first():
    laid = _laid_on_the_slim_l_plot()
    main = _run()[0].depth_m
    before = [depths for mixed, depths in laid if not mixed]
    assert before and all(depths == {main} for depths in before)
    first_mixed = next(i for i, (mixed, _) in enumerate(laid) if mixed)
    assert not any(mixed for mixed, _ in laid[:first_mixed])
    assert all(mixed for mixed, _ in laid[first_mixed:])  # laid after every other, so the
    # layouts the search found before keep their place, their time and their numbers


def test_columns_of_two_depths_reach_the_exact_layout():
    laid = _laid_on_the_slim_l_plot()
    mixed = [depths for is_mixed, depths in laid if is_mixed]
    assert mixed and all(len(depths) == 2 for depths in mixed)


def test_a_configuration_stands_other_depths_in_columns_only_when_it_lets_them():
    run, profile, _, _ = _run()
    mixed_found = 0
    for angle in (0.0, 90.0):
        for offset in (0.0, 11.38, 22.75):
            for floors in (8, 9):
                for depths in (False, True):
                    ev = evaluate(run, Config(profile, angle, offset, floors,
                                              mixed_depths=depths))
                    if isinstance(ev, Failure):
                        continue
                    held = {round(s.choice.depth_m, 2) for s in ev.standing}
                    if depths:  # never the same columns as without them
                        assert held == {run.depth_m, 13.13}
                        mixed_found += 1
                    else:
                        assert held == {run.depth_m}
    assert mixed_found
