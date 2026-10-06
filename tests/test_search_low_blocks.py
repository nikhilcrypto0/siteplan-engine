"""Blocks below 21 m in the full search (stream C3): wherever the envelope allows, each held to its
own Table III band, and every layout still judged by the independent validator.

The search lays no fire band round a block below 21 m, so it keeps its cellar out from under one:
a block over a cellar of more than 500 m², or of two levels, is an NBC special building held to
4.6's fire access whatever its height (Part 4 1.2(b)(6), contracts 1.3).

Everything runs on made-up land (search_support.py). The acceptance criterion of
docs/ARCHITECTURE.md section 6, "C3 Below 21 m", has its test here: on the made-up L-plot the 24 m
arm is tried for a block below 21 m and the reason it is or is not used is said, and where a block
fits there the objective decides. Beside it: the Table III figures a low floor count carries, the
front and side setbacks and the gaps of low blocks, rule 8(l)'s pathway when the search uses one,
no fire lane or turning room round a block that is not a high-rise, and the planting strip Table
III asks.
"""

from search_support import (
    l_plot,
    made_up,
    proposal_on_the_l_plot,
    rectangle,
    strategy,
)
from shapely.geometry import box
from shapely.ops import unary_union

from siteplan import validator as independent
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import HeightIntent, HeightMode
from siteplan.contracts.validation import LegalVerdict
from siteplan.optimizer.search import fringe
from siteplan.optimizer.search.land import Plot, setback_land
from siteplan.optimizer.search.layout import make_run
from siteplan.optimizer.search.readings import ALL, FloorClass, Profile, floor_classes, profiles
from siteplan.optimizer.search.strategy import _low_blocks
from siteplan.optimizer.search.verdicts import rests_on

TEST_CLASS = "normative"

ARM = box(0, 100, 24, 160)  # the L-plot's arm: 24 m wide, 60 m long
ROADS = ("APPROACH", "LOOP", "INTERNAL", "CUL_DE_SAC")


def _judge(made, candidate):
    return independent.validate(made.site, made.rules, made.brief, candidate, made.envelope)


def _check(report, rule):
    return next(c for c in report.legal if c.finding.rule == rule)


def _heights(made, tower):
    """(height above the stilt, physical height) of a placed tower, by the firm's standards."""
    standards = made.brief.firm_standards
    above = tower.floors_above_stilt * standards.floor_to_floor_m.value
    return above, above + (standards.stilt_height_m.value if tower.has_stilt else 0.0)


def _low(made, tower) -> bool:
    above, physical = _heights(made, tower)
    return physical < made.rules.height.high_rise_from_m.value  # low under every reading


def _shapes(candidate, *kinds):
    return unary_union([s.to_shapely() for r in candidate.circulation.roads
                        if r.kind.value in kinds for s in r.shapes])


def _arm_note(notes):
    (note,) = [n for n in notes if n.startswith("the narrow part of the plot at (12, 130)")]
    return note


# --- The floor counts below 21 m ---------------------------------------------------------------


def test_the_counts_below_21_m_carry_their_table_iii_figures():
    """On a plot over 2,500 m² Table III's row 11 gives 5 m on the sides up to 7 m of height above
    the stilt and 6 m up to 15 m, the Building Line of an 18 m (60 ft) road in front, 4 m; the gap
    between two such blocks is the side setback (rule 5(f)(xiii)) and the planting strip 1 m."""
    made = rectangle()
    by_floors = {c.floors: c for c in floor_classes(made.rules, made.brief, made.kit[0],
                                                    Profile(ALL, ALL))}
    assert {f for f, c in by_floors.items() if not c.high_rise} == {1, 2, 3, 4, 5}
    two, three = by_floors[2], by_floors[3]  # 6 m and 9 m above the 3 m stilt
    assert (two.setback_m, two.front, two.gap_m, two.strip_m) == (5.0, 4.0, 5.0, 1.0)
    assert (three.setback_m, three.front, three.gap_m, three.strip_m) == (6.0, 4.0, 6.0, 1.0)
    assert three.zone_m == 6.0 and three.physical_m == 12.0
    nine = by_floors[9]  # a high-rise: Table IV all round, its 2 m strip from a 9 m setback
    assert nine.high_rise and nine.front_m is None and nine.zone_m == nine.setback_m == 10.0
    assert nine.strip_m == 2.0 and by_floors[7].strip_m == 0.0


# --- Setbacks, the front apart, and gaps -------------------------------------------------------


def test_a_low_blocks_land_keeps_the_building_line_in_front_and_the_side_setback_elsewhere():
    net = box(0, 0, 100, 80)
    plot = Plot(net, box(0, 0, 0, 0), (), "S")
    land = setback_land(plot, 4.0, 6.0)  # the 7-15 m band on an 18 m road
    assert land.contains(box(10, 4.01, 20, 20))  # 4 m from the front (south) is enough
    assert not land.contains(box(5.5, 10, 20, 20))  # 5.5 m from the west side is not
    assert land.contains(box(6.01, 10, 20, 73.99))  # 6 m from the sides and the back
    assert not land.contains(box(10, 10, 20, 74.5))
    unknown = setback_land(Plot(net, box(0, 0, 0, 0), (), None), 4.0, 6.0)
    assert not unknown.contains(box(10, 4.01, 20, 20))  # no front known: the larger all round
    assert unknown.contains(box(10, 6.01, 20, 20))


def test_two_low_blocks_keep_the_taller_ones_side_setback_and_a_high_rise_its_own_gap():
    made = rectangle()
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit,
                   profiles(made.rules, made.brief, list(made.kit)))
    q = run.q
    by_floors = {c.floors: c for c in run.classes["ALL-ALL"][made.kit[0].id]}
    assert fringe.need_m(q, by_floors[2], by_floors[2]) == 5.0
    assert fringe.need_m(q, by_floors[2], by_floors[5]) == 6.0  # rule 5(f)(xiii): the taller's
    assert fringe.need_m(q, by_floors[3], by_floors[9]) == 10.0  # beside a high-rise: its gap
    # never inside a high-rise's fire lane or the ground its tender turns on at a corner
    tight = FloorClass(7, 24.0, 7.0, 6.5, (), ())
    assert fringe.need_m(q, by_floors[1], tight) == max(q.lane_m, q.reach_m) > 6.5


def test_low_blocks_on_the_fringe_keep_their_own_setbacks_and_the_front_is_held_apart():
    """The slim block stands on the fringe at Table III's Building Line (4 m) from the access
    road's side, nearer than its 6 m side setback, which no high-rise could; the validator holds it
    to both and passes it."""
    made, proposal = l_plot(True), proposal_on_the_l_plot(True)
    net = made.site.net_plot.value.to_shapely()
    front = net.boundary.intersection(box(-1, -1, 151, 0.5))  # the south edge, y = 0
    at_front = []
    for candidate in proposal.candidates:
        report = _judge(made, candidate)
        for tower in candidate.towers:
            if not _low(made, tower):
                continue
            footprint = candidate.placed_footprint(tower)
            to_front = footprint.distance(front)
            if to_front < 6.0 - 1e-6 and _heights(made, tower)[0] > 7.0:  # a 7-15 m block
                assert to_front >= 4.0 - 1e-6
                setback = _check(report, f"All-round setback: {tower.name}")
                assert setback.finding.status is Status.PASS, setback.finding.measured
                assert "at the front" in setback.finding.measured
                at_front.append(tower.name)
    assert at_front, "no low block stands between its Building Line and its side setback"


# --- Rule 8(l): the pathway, and a taller block against the road -------------------------------


def test_a_pathway_branches_out_of_the_ring_road_to_a_block_up_to_12_m():
    made, proposal = l_plot(), proposal_on_the_l_plot()
    served = 0
    for candidate in proposal.candidates:
        paths = [r for r in candidate.circulation.roads if r.kind.value == "PATHWAY"]
        if not paths:
            continue
        report = _judge(made, candidate)
        check = _check(report, "Internal roads: blocks up to 12 m (pathways)")
        assert check.finding.status is Status.PASS and "by a pathway" in check.finding.measured
        loop = _shapes(candidate, "LOOP")
        for path in paths:
            shape = unary_union([s.to_shapely() for s in path.shapes])
            assert path.declared_width_m == made.rules.circulation.pathway_width_m.value == 6.0
            assert shape.distance(loop) <= 0.5  # it branches out of the loop road
            reached = [t for t in candidate.towers
                       if candidate.placed_footprint(t).distance(shape) <= 0.5]
            assert len(reached) == 1
            (tower,) = reached
            assert _heights(made, tower)[1] <= 12.0 + 1e-6  # rule 8(l): up to 12 m only
            assert candidate.placed_footprint(tower).distance(_shapes(candidate, *ROADS)) > 0.5
            served += 1
    assert served, "the search used no pathway on the L-plot"


def test_a_block_on_the_fringe_above_12_m_stands_against_a_road():
    """The slim block stands only on the fringe (the columns take the deeper blocks); above 12 m
    rule 8(l) gives it no pathway, so it opens onto the ring road itself."""
    made, proposal = l_plot(True), proposal_on_the_l_plot(True)
    tall = 0
    for candidate in proposal.candidates:
        roads = _shapes(candidate, *ROADS)
        for tower in candidate.towers:
            if tower.prototype_id == "slim-2" and _heights(made, tower)[1] > 12.0:
                assert candidate.placed_footprint(tower).distance(roads) <= 0.5
                tall += 1
    assert tall


# --- Fire: no lane round a block below 21 m, never one inside a high-rise's ------------------


def test_a_low_block_never_stands_in_a_high_rises_fire_lane_or_turning_ground():
    for slim in (False, True):
        made, proposal = l_plot(slim), proposal_on_the_l_plot(slim)
        run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit,
                       profiles(made.rules, made.brief, list(made.kit)))
        for candidate in proposal.candidates:
            report = _judge(made, candidate)
            towers = {t.name: candidate.placed_footprint(t) for t in candidate.towers}
            low = [t.name for t in candidate.towers if _low(made, t)]
            for tower in candidate.towers:
                if tower.name in low:
                    continue
                for name in low:
                    assert towers[tower.name].distance(towers[name]) >= max(
                        run.q.lane_m, run.q.reach_m)
                fire = _check(report, f"Fire access: {tower.name}")
                assert fire.finding.status is not Status.FAIL, fire.finding.measured


def _all_low():
    """A made-up plot whose brief asks for one to five floors above the stilt: every block is
    below 21 m."""
    notation = rectangle().brief.height_intent.notation
    return made_up(box(0, 0, 160, 100), floors=HeightIntent(
        notation=notation, mode=HeightMode.RANGE, floors_range=(1, 5)))


def test_a_layout_of_blocks_below_21_m_lays_no_fire_lane_and_draws_table_iii_planting():
    """Under the state's line NBC 4.6 asks nothing of a block below 21 m that is not a special
    building, and the search keeps its cellar out from under one, so no hardstanding is laid round
    such a block; a block of NBC's own 15 m or more is held under the other reading, so what it
    lacks there is UNVERIFIED, never FAIL. The validator lists the rest of rule 15(a)(i) as
    NOT_CHECKED, and the 1 m strip Table III asks (rule 5(f)) runs round the plot, broken only at
    the gate."""
    made = _all_low()
    proposal = strategy().propose(made.context())
    assert proposal.candidates
    for candidate in proposal.candidates:
        assert all(_low(made, t) for t in candidate.towers)
        assert candidate.circulation.fire_hardstanding == []
        report = _judge(made, candidate)
        assert report.verdict.legal is not LegalVerdict.FAIL
        below = _check(report, "Fire access below 21 m (rule 15(a)(i))")
        assert below.finding.status is Status.NOT_CHECKED
        strip = _check(report, "Peripheral green strip")
        assert strip.finding.status is Status.PASS, strip.finding.measured
        drawn = unary_union([s.to_shapely() for s in candidate.program.green_strip])
        assert drawn.area >= 0.9 * made.site.net_plot.value.to_shapely().length


# --- Nothing the validator fails, and what each layout rests on --------------------------------


def test_no_layout_with_a_low_block_is_offered_that_the_validator_fails():
    used = 0
    for slim in (False, True):
        made, proposal = l_plot(slim), proposal_on_the_l_plot(slim)
        for candidate in proposal.candidates:
            report = _judge(made, candidate)
            assert report.verdict.legal is not LegalVerdict.FAIL
            assert [c.finding.rule for c in report.legal if c.finding.status is Status.FAIL] == []
            assert [d.item for d in report.cross_checks if d.blocks_pass] == []
            assert report.accounting.partition_problems == []
            used += any(_low(made, t) for t in candidate.towers)
            if not rests_on(report).holds_under_every_reading:
                assert any("holds only if" in c for c in candidate.caveats)
    assert used


def test_under_the_law_no_layout_offers_a_special_building_without_its_fire_access():
    """NBC 4.6 holds a block over a cellar of more than 500 m², or of two levels, to the lanes a
    high-rise keeps (Part 4 1.2(b)(6), through rule 15(a)(i)). No layout the search offers fails a
    block's fire access, and no block it lays no fire band for stands over its cellar."""
    for slim in (False, True):
        made, proposal = l_plot(slim), proposal_on_the_l_plot(slim)
        assert proposal.candidates
        for candidate in proposal.candidates:
            report = _judge(made, candidate)
            fire = [c for c in report.legal if c.finding.rule.startswith("Fire access: ")]
            assert all(c.finding.status is not Status.FAIL for c in fire), [
                (c.finding.rule, c.finding.measured) for c in fire
                if c.finding.status is Status.FAIL]
            cellars = candidate.program.cellars
            under = unary_union([s.to_shapely() for s in cellars.outline]) if cellars else None
            for tower in candidate.towers:
                if under is not None and _low(made, tower):
                    assert candidate.placed_footprint(tower).intersection(under).area < 0.5


# --- The acceptance criterion: the L-plot's arm --------------------------------------------------


def test_the_arm_is_tried_for_a_low_block_and_says_why_none_stands_there():
    """The arm is 24 m wide. A block below 21 m keeps 5 m from both its sides there (Table III,
    row 11, up to 7 m above the stilt), which leaves 14 m; the kit's blocks are 24.13 m deep, so
    none fits, and the search says so, with the numbers, rather than leave the arm out unasked."""
    proposal = proposal_on_the_l_plot()
    note = _arm_note(proposal.notes)
    assert "1,440 m² and 24.0 m wide" in note and "none fits" in note
    assert "at most 14.0 m" in note and "24.13 m deep" in note
    for candidate in proposal.candidates:
        assert not any(candidate.placed_footprint(t).intersection(ARM).area > 1.0
                       for t in candidate.towers)


def test_where_a_block_fits_the_arm_the_objective_decides_and_the_layouts_say_which_did():
    """With a made-up 13.13 m deep block in the kit, a two-floor block fits the arm (14 m between
    its 5 m side setbacks). Whether a layout stands one there is the objective's to decide:
    layouts with one and without one are judged side by side, and the note counts the proposals
    that did. A block there is low, served by the ring road or a pathway branching out of it, and
    passes the validator."""
    made, proposal = l_plot(True), proposal_on_the_l_plot(True)
    note = _arm_note(proposal.notes)
    assert "one fits (slim-2 at 2 floors)" in note
    in_arm = [c for c in proposal.candidates
              if any(_mostly_in_arm(c.placed_footprint(t)) for t in c.towers)]
    assert f"{len(in_arm)} of the {len(proposal.candidates)} layouts proposed" in note
    assert in_arm and len(in_arm) < len(proposal.candidates)  # with one, and without
    for candidate in in_arm:
        report = _judge(made, candidate)
        assert report.verdict.legal is not LegalVerdict.FAIL
        for tower in candidate.towers:
            footprint = candidate.placed_footprint(tower)
            if not _mostly_in_arm(footprint):
                continue
            assert _low(made, tower) and _heights(made, tower)[1] <= 12.0
            assert _check(report, f"Height permitted: {tower.name}").finding.status is (
                Status.PASS)
            reach = _shapes(candidate, *ROADS, "PATHWAY")
            assert footprint.distance(reach) <= 0.5


def _mostly_in_arm(footprint) -> bool:
    return footprint.intersection(ARM).area > footprint.area / 2


def test_a_profile_with_counts_on_both_sides_of_21_m_is_searched_with_low_blocks_and_without():
    """So the objective decides between layouts with blocks below 21 m and layouts without: each
    kind is evaluated and laid out on its own quota, and they are judged side by side."""
    made = rectangle()
    found = profiles(made.rules, made.brief, list(made.kit))
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found)
    assert all(_low_blocks(run, p) == (False, True) for p in found)
    low = _all_low()
    only = profiles(low.rules, low.brief, list(low.kit))
    run_low = make_run(low.site, low.rules, low.brief, low.envelope, low.kit, only)
    assert all(_low_blocks(run_low, p) == (True,) for p in only)
