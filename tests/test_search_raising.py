"""Raising a laid layout's blocks to the tallest each one's own place allows (2026-10-12, the
architect: "taller in the middle, lower at the edges"; raising.py). A block laid lower than its
place allows rises again; every block it raises keeps its own setback and the gap the taller of
two asks to every neighbour, the planted strip its band asks only where the land has it all round;
a layout already at its tallest is left alone. The raised layout is laid out again and judged by
the validator like any other (the strategy's `_raise`). Made-up land."""

TEST_CLASS = "normative"

from dataclasses import replace  # noqa: E402
from functools import cache  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from search_support import rectangle, strategy  # noqa: E402

from siteplan.optimizer.search import strategy as strategy_module  # noqa: E402
from siteplan.optimizer.search.build import placement_of  # noqa: E402
from siteplan.optimizer.search.raising import _strip_all_round, _with_class, raised  # noqa: E402


@cache
def _laid():
    """The rectangle's laid layouts, as the raise pass is given them."""
    seen = []
    real = strategy_module.raised

    def keep(run, ev, *args, **kwargs):
        seen.append((run, ev))
        return real(run, ev, *args, **kwargs)

    with patch.object(strategy_module, "raised", keep):
        strategy().propose(rectangle().context())
    return seen


def _lowered(run, ev):
    """The layout with its first column block one floor class lower, where it has one."""
    first = ev.standing[0]
    ladder = run.classes[ev.config.profile.key][first.choice.prototype.id]
    lower = [c for c in ladder if c.floors < first.choice.cls.floors
             and c.high_rise == first.choice.cls.high_rise]
    if not lower:
        return None
    low = max(lower, key=lambda c: c.floors)
    standing = (_with_class(first, low), *ev.standing[1:])
    value = sum(s.choice.value for s in [*standing, *(f.standing for f in ev.fringe)])
    return replace(ev, standing=standing, value=value)


def test_a_block_laid_lower_than_its_place_allows_rises_again():
    tried = 0
    for run, ev in _laid():
        low = _lowered(run, ev)
        if low is None:
            continue
        tried += 1
        up = raised(run, low)
        assert up is not None
        assert up.standing[0].choice.cls.floors >= ev.standing[0].choice.cls.floors
        assert up.value > low.value
    assert tried


def test_every_raised_block_keeps_its_setback_and_the_taller_ones_gap():
    for run, ev in _laid():
        low = _lowered(run, ev)
        up = raised(run, low) if low is not None else None
        if up is None:
            continue
        net = run.plot.net
        blocks = [*up.standing, *(f.standing for f in up.fringe)]
        prints = [placement_of(s, "T", up.frame).footprint for s in blocks]
        for s, own in zip(blocks, prints, strict=True):
            assert own.distance(net.exterior) + 1e-6 >= s.choice.cls.zone_m
        for i, (a, pa) in enumerate(zip(blocks, prints, strict=True)):
            for b, pb in zip(blocks[i + 1:], prints[i + 1:], strict=True):
                need = max(a.choice.cls.gap_m, b.choice.cls.gap_m)
                assert pa.distance(pb) + 1e-6 >= need


def test_a_layout_already_at_its_tallest_is_left_alone():
    for run, ev in _laid():
        top = {pid: max(c.floors for c in classes)
               for pid, classes in run.classes[ev.config.profile.key].items() if classes}
        if all(s.choice.cls.floors == top[s.choice.prototype.id] for s in ev.standing) \
                and not ev.fringe:
            assert raised(run, ev) is None


def test_the_planted_strip_counts_only_all_round():
    from shapely.geometry import box

    net = box(0, 0, 100, 60)
    whole = net.difference(net.buffer(-2.0, join_style="mitre"))
    assert _strip_all_round(net, whole, 2.0) == pytest.approx(2.0)
    half = whole.intersection(box(0, 0, 50, 60))
    assert _strip_all_round(net, half, 2.0) == 0.0
    assert _strip_all_round(net, box(0, 0, 0, 0).buffer(0), 2.0) == 0.0
