"""The full search as a strategy: what it proposes, and what it says of what it proposes (C2).

Everything runs on made-up land (search_support.py) through the real independent validator. The
acceptance criteria of docs/ARCHITECTURE.md section 6, "C2 Full search", each have a test here or
in test_search_columns.py and test_search_network.py: mixed heights (a part of the site that suits
only a lower band; a block lowered to let another stand; the legal maximum never meaning every
block at it), circulation generated with the blocks, nothing the validator fails offered, the
margins aimed at
when set and reported when missed, both readings of circulation inside the setback, every option
stating its UNVERIFIED items and the readings they rest on, and alternatives that hold under every
reading beside the ones that rest on a reading.
"""

import re

from optimizer_support import Clock
from search_support import (
    FAST,
    Made,
    made_up,
    margin,
    proposal_on_the_rectangle,
    rectangle,
    strategy,
)
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from siteplan import validator as independent
from siteplan.contracts import digest
from siteplan.contracts.common import Finding, Status
from siteplan.contracts.design_brief import ParetoPoint
from siteplan.contracts.resolved_rules import CIRCULATION_IN_SETBACK, STILT_IN_RULE_HEIGHT
from siteplan.contracts.validation import Check, Family, LegalVerdict, legal_verdict
from siteplan.optimizer import optimize
from siteplan.optimizer.interfaces import Budget
from siteplan.optimizer.search import FullSearchStrategy, Limits
from siteplan.optimizer.search.build import named_placements
from siteplan.optimizer.search.land import erode
from siteplan.optimizer.search.layout import Config, Failure, evaluate, make_run
from siteplan.optimizer.search.readings import ALL, profiles
from siteplan.optimizer.search.verdicts import UNIVERSAL, rests_on

TEST_CLASS = "normative"


def _judge(made: Made, candidate):
    return independent.validate(made.site, made.rules, made.brief, candidate, made.envelope)


def _roads(candidate):
    shapes = [s.to_shapely() for road in candidate.circulation.roads
              if road.kind.value != "APPROACH" for s in road.shapes]
    shapes += [s.to_shapely() for s in candidate.circulation.fire_hardstanding]
    return unary_union(shapes)


# --- Nothing the validator fails is offered ---------------------------------------------------


def test_every_proposal_passes_the_independent_validator_without_a_fail():
    made, proposal = rectangle(), proposal_on_the_rectangle()
    assert proposal.candidates
    ids = [c.candidate_id for c in proposal.candidates]
    assert len(ids) == len(set(ids))
    for candidate in proposal.candidates:
        report = _judge(made, candidate)
        assert candidate.strategy == "FULL"
        assert report.verdict.legal is not LegalVerdict.FAIL
        assert [d.item for d in report.cross_checks if d.blocks_pass] == []
        assert report.accounting.partition_problems == []
        assert [c.finding.rule for c in report.legal if c.finding.status is Status.FAIL] == []


def test_the_optimizer_core_returns_alternatives_made_by_the_full_search():
    made = rectangle()
    result = optimize(made.site, made.rules, made.brief, [strategy()], envelope=made.envelope,
                      prototypes=made.kit)
    assert 1 <= len(result.alternatives) <= len(ParetoPoint)  # one a point at most
    assert result.rejected == ()  # it judges its own candidates: the guard has nothing to refuse
    assert not result.budget_exhausted
    for alternative in result.alternatives:
        assert alternative.candidate.strategy == "FULL"
        assert alternative.report.verdict.legal is not LegalVerdict.FAIL
    assert any("configurations evaluated" in note for note in result.notes)


def test_a_layout_the_validator_fails_is_never_proposed():
    """The strategy's validator fails every candidate whose number ends in -1: none of them is
    proposed, and the notes say the validator failed them."""
    made = rectangle()
    plant = _FailsTheFirst()
    proposal = strategy(validator=plant).propose(made.context())
    assert plant.failed, "the planted failure was never judged"
    assert proposal.candidates
    proposed = {c.candidate_id for c in proposal.candidates}
    assert not proposed & set(plant.failed)
    assert any("the validator failed" in note for note in proposal.notes)


class _FailsTheFirst:
    """The real validator, except that it adds a failing check to candidate number 1."""

    def __init__(self):
        self.failed: list[str] = []

    def validate(self, site, rules, brief, candidate, envelope=None):
        report = independent.validate(site, rules, brief, candidate, envelope)
        if not candidate.candidate_id.endswith("-1"):
            return report
        self.failed.append(candidate.candidate_id)
        planted = Check(family=Family.OTHER, finding=Finding(
            "Planted failure", Status.FAIL, "a planted fault", "no fault", "test"))
        legal = [*report.legal, planted]
        verdict = report.verdict.model_copy(update={
            "legal": legal_verdict(legal, report.cross_checks)})
        return report.model_copy(update={"legal": legal, "verdict": verdict})


# --- Readings ---------------------------------------------------------------------------------


def test_every_proposal_states_its_unverified_items_and_the_readings_they_rest_on():
    made, proposal = rectangle(), proposal_on_the_rectangle()
    for candidate in proposal.candidates:
        report = _judge(made, candidate)
        rests = rests_on(report)
        assert set(candidate.interpretation_basis) == {STILT_IN_RULE_HEIGHT,
                                                       CIRCULATION_IN_SETBACK}
        dependent = [c for c in candidate.caveats if "holds only if" in c]
        assert bool(dependent) is (not rests.holds_under_every_reading)
        for check in report.legal:
            finding = check.finding
            if finding.status is Status.UNVERIFIED and not finding.rule.startswith(UNIVERSAL):
                assert any(finding.rule in c for c in candidate.caveats), finding.rule
        for reading in rests.readings:
            assert any(reading in c for c in dependent)


def test_layouts_that_hold_under_every_reading_come_beside_those_that_rest_on_a_reading():
    made, proposal = rectangle(), proposal_on_the_rectangle()
    holds, rests = [], []
    for candidate in proposal.candidates:
        (holds if rests_on(_judge(made, candidate)).holds_under_every_reading
         else rests).append(candidate)
    assert holds and rests
    assert all(c.interpretation_basis == {STILT_IN_RULE_HEIGHT: ALL, CIRCULATION_IN_SETBACK: ALL}
               for c in holds)
    # the readings change the answer: a layout that rests on a reading is worth more than the best
    # that holds under all of them (a tenth floor if the stilt is not counted, ground in the
    # setback if circulation may use it)
    assert max(c.metrics.saleable_sqft for c in rests) > max(c.metrics.saleable_sqft
                                                             for c in holds)


def test_both_readings_of_circulation_inside_the_setback_are_searched():
    made, proposal = rectangle(), proposal_on_the_rectangle()
    net = made.site.net_plot.value.to_shapely()
    strict, loose = [], []
    for candidate in proposal.candidates:
        deepest = max(_floors_setback(made, candidate, t) for t in candidate.towers)
        zone = net.difference(erode(net, deepest))
        inside = _roads(candidate).intersection(zone).area
        reading = candidate.interpretation_basis[CIRCULATION_IN_SETBACK]
        (strict if reading == ALL else loose).append(inside)
        if reading == ALL:
            assert inside < 0.5, "a layout that holds under both readings keeps out of the setback"
    assert strict and loose and max(loose) > 100.0


def _floors_setback(made: Made, candidate, tower) -> float:
    """The deepest setback the tower asks under the readings of the stilt the candidate was built
    for (what the validator's zone is measured from, under each of them): its band by the
    contract's own lookup, Table III's row on the height above the stilt for a block below 21 m,
    and the larger of the band's front and side figures."""
    rule = made.rules.height
    floors = tower.floors_above_stilt
    stilt, floor = (made.brief.firm_standards.stilt_height_m.value,
                    made.brief.firm_standards.floor_to_floor_m.value)
    built_for = candidate.interpretation_basis[STILT_IN_RULE_HEIGHT]
    chosen = ["counted", "not_counted"] if built_for == ALL else [built_for]
    bands = [rule.band_for_block(floors * floor, stilt, stilt_counted=reading == "counted")
             for reading in chosen]
    return max(max(band.setback_m, band.front_m) for band in bands)


# --- Mixed heights ----------------------------------------------------------------------------


def test_a_part_of_the_site_that_suits_only_a_lower_height_gets_a_lower_block_when_that_pays():
    """The firm keeps 3 m more than the law at every setback, so a tall block (setback 10 m, 13 m
    asked) needs ground a lower one (8 m, 11 m asked) does not. On a plot that narrows towards one
    end the end that only the lower height reaches takes the lower block, and the best layout is
    one that mixes them: worth more than the best layout of one height."""
    net = Polygon([(0, 0), (200, 0), (200, 84), (0, 100)])
    mixed = made_up(net, margins={"setback_extra_m": 3.0})
    uniform = made_up(net, margins={"setback_extra_m": 3.0}, mixed_heights=False)
    best = {}
    for label, made in (("mixed", mixed), ("uniform", uniform)):
        found = profiles(made.rules, made.brief, list(made.kit))
        run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found)
        for offset in range(0, 34, 2):
            ev = evaluate(run, Config(found[1], 0.0, float(offset), 9, None))
            if not isinstance(ev, Failure) and (label not in best or ev.value > best[label][0]):
                best[label] = (ev.value, ev, run)
    assert best["mixed"][0] > best["uniform"][0]
    _, ev, run = best["mixed"]
    heights = {s.choice.cls.floors for s in ev.standing}
    assert len(heights) > 1 and max(heights) <= 9
    net_plot = run.plot.net
    tallest = max(heights)
    asks = {s.choice.cls.floors: s.choice.cls.setback_m + run.q.setback_margin_m
            for s in ev.standing}
    lower = [p for p in named_placements(ev.standing, ev.frame)
             if p.standing.choice.cls.floors < tallest]
    assert lower
    # at least one lower block stands where a block of the tallest height could not: it is
    # nearer the boundary than the tallest height asks, and no nearer than its own height asks
    narrow = [p for p in lower
              if net_plot.boundary.distance(p.footprint) < asks[tallest] - 1e-6]
    assert narrow
    for p in narrow:
        assert net_plot.boundary.distance(p.footprint) >= asks[p.standing.choice.cls.floors] - 1e-6


def test_a_block_is_lowered_when_that_lets_the_other_stand_on_the_whole_site():
    """91 m of ground takes two 41 m blocks at 8 floors (a 9 m gap), where 9 floors (10 m) would
    leave room for one. Both are lowered, though 9 floors is what the law allows."""
    made = made_up(box(0, 0, 114, 60), kit_ids=("single-core-6",))
    found = profiles(made.rules, made.brief, list(made.kit))
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found)
    ev = evaluate(run, Config(found[1], 0.0, 0.0, 9, None))
    assert not isinstance(ev, Failure)
    assert [s.choice.cls.floors for s in ev.standing] == [8, 8]
    assert max(c.floors for c in run.classes[found[1].key][made.kit[0].id]) == 9
    one_tall = 8140 * 9  # the single 41 m block at 9 floors
    assert ev.value > one_tall


# --- Margins ----------------------------------------------------------------------------------


def test_the_design_margins_are_aimed_at_when_they_can_be_kept():
    made = made_up(box(0, 0, 200, 120), margins={"tower_gap_extra_m": 1.0,
                                                  "road_width_extra_m": 1.0,
                                                  "setback_extra_m": 1.0})
    proposal = strategy().propose(made.context())
    assert proposal.candidates
    assert not any("could not all be kept" in n for n in proposal.notes)
    kept = 0
    for candidate in proposal.candidates:
        report = _judge(made, candidate)
        assert report.verdict.legal is not LegalVerdict.FAIL
        if candidate.interpretation_basis != {STILT_IN_RULE_HEIGHT: ALL,
                                              CIRCULATION_IN_SETBACK: ALL}:
            continue  # a layout built for one reading aims its margins under that one only
        rows = [t for t in report.design_targets if t.margin > 0]
        assert {t.item.value for t in rows} >= {"setback", "tower_gap", "road_width"}
        assert all(t.meets_target for t in rows), [(t.item.value, t.provided, t.target)
                                                   for t in rows if not t.meets_target]
        assert not [c for c in candidate.caveats if "design target missed" in c]
        kept += 1
    assert kept


def test_a_margin_the_site_cannot_keep_is_reported_and_never_taken_for_law():
    """Open space of ten times the legal minimum cannot be had. The layouts keep the legal minimum
    and say what they miss; the legal verdict still holds them to the law alone."""
    made = made_up(box(0, 0, 200, 120), margins={"open_space_extra_fraction": 0.9})
    proposal = strategy().propose(made.context())
    assert proposal.candidates
    assert any("could not all be kept" in n for n in proposal.notes)
    for candidate in proposal.candidates:
        report = _judge(made, candidate)
        assert report.verdict.legal is not LegalVerdict.FAIL
        missed = [c for c in candidate.caveats if "design target missed (open_space" in c]
        assert missed and len(missed) == len(set(missed))
        assert any(t.item.value == "open_space" and not t.meets_target
                   for t in report.design_targets)
        assert any(c.finding.rule == "Design margins" and c.finding.status is Status.FAIL
                   for c in report.program)  # a program finding, never a legal one


# --- Bounds -----------------------------------------------------------------------------------


def test_the_same_seed_gives_the_same_proposal():
    made = rectangle()
    quick = Limits(offsets=2, heights=1, laid_per_profile=2, attempts_per_profile=8,
                   judged_per_profile=1, per_profile_proposed=1)
    first = strategy(quick).propose(made.context(seed=5))
    again = strategy(quick).propose(made.context(seed=5))
    assert first.candidates
    assert [digest(c) for c in first.candidates] == [digest(c) for c in again.candidates]
    assert first.notes == again.notes


def test_the_time_budget_stops_the_search_and_says_so():
    made = rectangle()
    clock = Clock(step=1.0)
    context = made.context(budget=Budget(3.0, clock))
    proposal = strategy().propose(context)
    assert proposal.budget_exhausted
    assert any("stopped on the time budget" in n for n in proposal.notes)
    evaluated = int(re.search(r"(\d+) configurations evaluated", proposal.notes[0]).group(1))
    assert evaluated <= 12  # three seconds of a clock that ticks once a look, not the 48 there are
    free = strategy().propose(made.context())
    assert not free.budget_exhausted


# --- What it will not do ----------------------------------------------------------------------


def test_where_no_floor_count_is_open_it_says_so_and_lays_nothing():
    """A 30 ft road serves no high-rise, and a group development scheme on it may take no block
    below 21 m either (rule 8(b) asks 12 m): no count is open at all."""
    narrow = made_up(box(0, 0, 200, 120), road_ft=30)
    proposal = strategy().propose(narrow.context())
    assert proposal.candidates == ()
    assert any("no floor count open" in n and "neither a high-rise nor a block below 21 m" in n
               for n in proposal.notes)


def test_a_site_under_the_group_development_size_is_said_to_be_unsupported():
    small = made_up(box(0, 0, 60, 50))
    proposal = strategy().propose(small.context())
    assert proposal.candidates == ()
    assert any("Group Development" in n for n in proposal.notes)


def test_with_no_prototypes_or_no_net_plot_it_says_what_is_missing():
    made = rectangle()
    none = strategy().propose(Made(made.site, made.rules, made.brief, made.envelope,
                                   ()).context())
    assert none.candidates == () and "prototypes" in none.notes[0]
    unplaced = made.site.model_copy(update={"net_plot": None})
    stop = strategy().propose(Made(unplaced, made.rules, made.brief, made.envelope,
                                   made.kit).context())
    assert stop.candidates == () and "net plot is not known" in stop.notes[0]


def test_an_access_side_nobody_has_given_is_assumed_and_said():
    made = made_up(box(0, 0, 200, 120), side=None)
    proposal = strategy().propose(made.context())
    assert proposal.candidates
    for candidate in proposal.candidates:
        assert any(c.startswith("ASSUMED: nobody has said which side the access road") for c in
                   candidate.caveats)


def test_blocks_keep_out_of_a_water_buffer_the_plot_is_crossed_by():
    nala = LineString([(100, -5), (100, 125)])
    made = made_up(box(0, 0, 200, 120), nala=nala)
    proposal = strategy().propose(made.context())
    assert proposal.candidates
    buffer = unary_union([s.to_shapely() for e in made.envelope.exclusions for s in e.shapes])
    assert buffer.area > 1000
    for candidate in proposal.candidates:
        for tower in candidate.towers:
            assert candidate.placed_footprint(tower).intersection(buffer).area < 0.01
        report = _judge(made, candidate)
        water = [c for c in report.legal if c.finding.rule == "Water-body buffer"]
        assert [c.finding.status for c in water] == [Status.PASS]
        assert report.verdict.legal is not LegalVerdict.FAIL


def test_the_limits_bound_what_a_run_looks_at():
    made = rectangle()
    tight = Limits(offsets=1, heights=1, laid_per_profile=1, attempts_per_profile=3,
                   judged_per_profile=1, per_profile_proposed=1)
    proposal = FullSearchStrategy(limits=tight).propose(made.context())
    assert len(proposal.candidates) <= 4 * tight.per_profile_proposed + 1
    assert margin(0.0).value == 0.0 and FAST.offsets == 3
