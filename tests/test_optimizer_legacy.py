"""The prototype generator wrapped as the LEGACY strategy (C1): the same replies as the generator,
the starting floors worked out from the law's metres, a time budget, and a plain "nothing to
try" where the generator cannot be asked. Made-up land only."""

import pytest
from optimizer_support import (
    LIBRARY,
    Clock,
    fixture,
    intent,
    legacy_run,
    max_legal,
    rules_with_dead_end,
)
from shapely.geometry import LineString, Polygon

from siteplan.adapters import Readings, option_keys, request
from siteplan.contracts import CandidateLayout, digest
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import HeightMode
from siteplan.contracts.resolved_rules import (
    ALL,
    CIRCULATION_IN_SETBACK,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.heights import heights_to_try, legal_findings, search_heights
from siteplan.layout import LayoutRequest, SiteFacts, search
from siteplan.mcp_server import OPTION_KEYS
from siteplan.optimizer import Budget, LegacyStrategy, SearchContext
from siteplan.optimizer.floors import STILT_COUNTED, STILT_NOT_COUNTED, assess_floor_count
from siteplan.optimizer.legacy import DEFAULT_READINGS, heights_for, water_keep_out
from siteplan.units import ft_to_m

TEST_CLASS = "normative"

SITE, RULES, BRIEF = fixture()  # 150 x 100 m, a 60 ft road on the south, one road end unknown
PLOT = Polygon(SITE.net_plot.value.outer)
MIX = BRIEF.program.unit_mix.value
COUNTED = Readings({STILT_IN_RULE_HEIGHT: STILT_COUNTED, CIRCULATION_IN_SETBACK: "not_allowed"},
                   RULES.jurisdiction.when_open)


def _facts(site=SITE, **changes):
    """What the generator is told about the rectangle, written out by hand."""
    return SiteFacts(**{
        "gross_area_sqm": site.ownership.gross_sqm.value, "abutting_road_m": ft_to_m(60),
        "authority": "HMDA", "inside_cure": False, "access_side": site.access.side.value,
        "road_dead_end": site.access.dead_end.value,
        "street_joins_12m": site.access.joins_12m_street.value, "jurisdiction_confirmed": True,
        **changes})


def _reply(option, i):
    return {k: ({"option": i, "floors_above_stilt": option.floors} | option.summary())[k]
            for k in OPTION_KEYS}


def _same_replies(candidates, options, mix):
    assert len(candidates) == len(options) >= 1
    for i, (made, option) in enumerate(zip(candidates, options, strict=True), 1):
        assert option_keys(made, i, mix) == _reply(option, i), i


# --- the same replies as the generator ---------------------------------------------------------


def test_one_height_gives_the_replies_the_generator_gives():
    run = legacy_run(maximise=False)  # the brief's own "Stilt + 8"
    options = search(PLOT, LIBRARY, request(BRIEF, COUNTED), _facts()).options
    _same_replies(run.proposal.candidates, options, MIX)


def test_every_height_gives_the_replies_the_generator_gives():
    run = legacy_run()
    brief = max_legal(BRIEF)
    direct = search_heights(PLOT, LIBRARY, request(brief, COUNTED, floors_for_max=9), _facts())
    _same_replies(run.proposal.candidates, direct.options, MIX)
    table = [(r.floors, r.verdict, r.reasons()) for r in run.found.results]
    assert table == [(r.floors, r.verdict, r.reasons()) for r in direct.results]
    assert [floors for floors, *_ in table] == [10, 9, 8, 7, 6]


def test_land_with_a_nala_gives_the_replies_the_generator_gives():
    site, rules, brief = fixture("nala_plot")
    run = LegacyStrategy(LIBRARY).run(SearchContext(site, rules, brief))
    plot = Polygon(site.net_plot.value.outer)
    keep_out = LineString([(75, -5), (75, 125)]).buffer(9.0)
    facts = _facts(site, abutting_road_m=ft_to_m(60), keep_out=keep_out)
    _same_replies(run.proposal.candidates, search(plot, LIBRARY, request(brief, COUNTED), facts)
                  .options, brief.program.unit_mix.value)
    assert water_keep_out(site, rules).symmetric_difference(keep_out).area < 1e-6


def test_a_water_body_with_no_lines_stops_the_run_rather_than_being_ignored():
    site, rules, brief = fixture("nala_plot")
    undrawn = site.model_copy(update={"water": [site.water[0].model_copy(update={"lines": []})]})
    run = LegacyStrategy(LIBRARY).run(SearchContext(undrawn, rules, brief))
    assert run.proposal.candidates == () and "no drawn lines" in run.proposal.notes[0]


def test_the_wrapped_run_is_the_same_every_time():
    again = LegacyStrategy(LIBRARY).run(SearchContext(SITE, RULES, BRIEF))
    first = legacy_run(maximise=False)
    assert again.proposal.candidates == first.proposal.candidates


# --- what each candidate says about itself -----------------------------------------------------


def test_a_candidate_names_its_strategy_its_inputs_its_readings_and_its_seed():
    run = LegacyStrategy(LIBRARY).run(SearchContext(SITE, RULES, BRIEF, seed=7))
    assert run.proposal.strategy == "LEGACY"
    for i, made in enumerate(run.proposal.candidates, 1):
        assert made.strategy == "LEGACY" and made.seed == 7
        assert made.candidate_id == f"legacy-counted-not_allowed-{i}"
        assert (made.site_ref, made.rules_ref, made.brief_ref) == (
            digest(SITE), digest(RULES), digest(BRIEF))
        assert made.envelope_ref is None  # the generator never looked at an envelope
        assert made.interpretation_basis == DEFAULT_READINGS
        assert made.pareto_tag and made.pareto_tag.startswith("Option ")  # the generator's label
        assert CandidateLayout.model_validate_json(made.model_dump_json()) == made


# --- the starting floors come from metres --------------------------------------------------------


def test_the_search_starts_from_the_most_the_law_allows_not_from_a_typed_number():
    run = legacy_run()
    assert run.request.floors == 9 and run.request.maximise  # 3 m stilt + 9 x 3 m = 30 m
    assert [r.floors for r in run.found.results] == [10, 9, 8, 7, 6]
    assert run.found.results[0].verdict == "FAIL (law)"  # one above, so the report says why


def test_a_reading_that_leaves_the_stilt_out_starts_one_floor_higher():
    clock = Clock()
    budget = Budget(1.5, clock)  # the first height only: 11 floors, which the law rules out
    readings = {STILT_IN_RULE_HEIGHT: STILT_NOT_COUNTED, CIRCULATION_IN_SETBACK: "not_allowed"}
    run = LegacyStrategy(LIBRARY, readings=readings).run(
        SearchContext(SITE, RULES, max_legal(BRIEF), budget=budget))
    assert run.request.floors == 10  # 10 x 3 m = 30 m
    assert [(r.floors, r.verdict) for r in run.found.results] == [(11, "FAIL (law)")]


def test_a_road_that_ends_at_the_plot_lowers_the_start_under_the_reading_that_drops_the_stilt():
    site, rules = rules_with_dead_end(True)
    clock = Clock()
    run = LegacyStrategy(LIBRARY, readings={
        STILT_IN_RULE_HEIGHT: STILT_NOT_COUNTED, CIRCULATION_IN_SETBACK: "not_allowed"}).run(
        SearchContext(site, rules, max_legal(BRIEF), budget=Budget(1.5, clock)))
    assert run.request.floors == 9  # 33 m physical is over NBC's 30 m on a dead end
    first = run.found.results[0]
    assert (first.floors, first.verdict) == (10, "FAIL (law)")
    assert "Dead-end road" in " ".join(first.reasons())


@pytest.mark.parametrize("dead_end", [None, True, False])
@pytest.mark.parametrize("reading", [STILT_COUNTED, STILT_NOT_COUNTED])
def test_floors_from_metres_and_the_generators_legal_findings_agree_on_every_height(
        reading, dead_end):
    """The law side of the generator (heights.legal_findings) and floors.py are two routes to
    the same answer for each count: it fails the law in one exactly when it does in the other."""
    site, rules = rules_with_dead_end(dead_end)
    brief = max_legal(BRIEF)
    big = Polygon([(0, 0), (150, 0), (150, 100), (0, 100)])
    for floors in range(1, 14):
        asked = LayoutRequest(floors=floors, unit_mix=MIX,
                              stilt_in_rule_height=reading == STILT_COUNTED)
        if asked.rule_height_m < 21:
            continue  # below the high-rise height the generator has no rules to apply
        legal = legal_findings(floors, asked, _facts(site), big)
        option = assess_floor_count(rules, brief, None, reading, floors, site=site)
        generator_fails = any(f.status is Status.FAIL for f in legal)
        assert (not option.feasible) is generator_fails, (reading, dead_end, floors)
        dead = next((f for f in legal if f.rule == "Dead-end road"), None)
        (physical,) = [c for c in option.limits if c.measure.value == "PHYSICAL_HEIGHT"]
        assert physical.status is (dead.status if dead else Status.PASS), (floors,)


# --- the heights tried ---------------------------------------------------------------------------


def _asked(floors=9, **fields):
    return LayoutRequest(floors=floors, unit_mix=MIX, **fields)


def test_a_fixed_height_is_tried_alone_and_the_most_is_tried_top_down():
    fixed = intent(BRIEF, mode=HeightMode.FIXED, floors_above_stilt=8)
    assert heights_for(_asked(8), fixed.height_intent) == [8]
    most = max_legal(BRIEF).height_intent
    assert heights_for(_asked(9, maximise=True), most) == heights_to_try(
        _asked(9, maximise=True)) == [10, 9, 8, 7, 6]


def test_a_range_and_a_lowest_floor_count_narrow_the_heights_tried():
    ranged = intent(BRIEF, mode=HeightMode.RANGE, floors_range=(7, 8)).height_intent
    assert heights_for(_asked(8), ranged) == [8, 7]  # 9 is over the range, 6 is under it
    at_least = intent(BRIEF, mode=HeightMode.MAX_LEGAL, min_floors_above_stilt=8).height_intent
    assert heights_for(_asked(9, maximise=True), at_least) == [10, 9, 8]


def test_heights_below_the_high_rise_height_are_left_out_not_drawn():
    low = intent(BRIEF, mode=HeightMode.FIXED, floors_above_stilt=3).height_intent
    assert heights_for(_asked(3), low) == []  # 12 m: Table III is not encoded
    wide = intent(BRIEF, mode=HeightMode.RANGE, floors_range=(2, 8)).height_intent
    assert heights_for(_asked(8), wide) == [8, 7, 6]  # nothing under 21 m


def test_the_search_hooks_default_to_the_generators_own_behaviour():
    asked = _asked(9, maximise=True)
    default = search_heights(PLOT, LIBRARY, asked, _facts())
    assert [r.floors for r in default.results] == [10, 9, 8, 7, 6]
    none = search_heights(PLOT, LIBRARY, asked, _facts(), stop=lambda: True)
    assert none.results == [] and none.options == []
    one = search_heights(PLOT, LIBRARY, asked, _facts(), heights=[10])
    assert [(r.floors, r.verdict) for r in one.results] == [(10, "FAIL (law)")]


# --- the time budget -----------------------------------------------------------------------------


def test_a_budget_that_runs_out_stops_the_search_and_says_which_heights_were_not_tried():
    clock = Clock()
    budget = Budget(2.5, clock)  # checked before each height: two are started, a third is not
    readings = {STILT_IN_RULE_HEIGHT: STILT_NOT_COUNTED, CIRCULATION_IN_SETBACK: "not_allowed"}
    run = LegacyStrategy(LIBRARY, readings=readings).run(
        SearchContext(SITE, RULES, max_legal(BRIEF), budget=budget))
    assert [r.floors for r in run.found.results] == [11, 10]
    assert run.proposal.budget_exhausted
    assert "heights not tried: stilt + 9, stilt + 8, stilt + 7" in run.proposal.notes[-1]
    assert run.proposal.candidates  # what stilt + 10 gave is returned, not dropped
    assert {c.towers[0].floors_above_stilt for c in run.proposal.candidates} == {10}


def test_a_budget_already_spent_tries_nothing_and_says_so():
    clock = Clock()
    budget = Budget(0.5, clock)
    run = LegacyStrategy(LIBRARY).run(SearchContext(SITE, RULES, max_legal(BRIEF), budget=budget))
    assert run.found.results == [] and run.proposal.candidates == ()
    assert run.proposal.budget_exhausted and "time budget" in run.proposal.notes[-1]


def test_without_a_budget_every_height_is_tried():
    assert not legacy_run().proposal.budget_exhausted


# --- nothing to try ------------------------------------------------------------------------


def _run(site=SITE, rules=RULES, brief=BRIEF):
    return LegacyStrategy(LIBRARY).run(SearchContext(site, rules, brief))


def test_a_site_whose_net_plot_is_not_known_gets_no_layout_and_the_reason():
    unknown = SITE.model_copy(update={"net_plot": None})
    run = _run(unknown)
    assert run.proposal.candidates == () and "net plot is not known" in run.proposal.notes[0]
    assert run.found is None


def test_a_plot_with_a_hole_is_not_laid_out():
    ring = SITE.net_plot.value
    holed = SITE.model_copy(update={"net_plot": SITE.net_plot.model_copy(update={
        "value": ring.model_copy(update={"holes": [[(60, 40), (90, 40), (90, 60)]]})})})
    assert "without holes" in _run(holed).proposal.notes[0]


def test_a_brief_with_no_stilt_is_not_laid_out_because_the_generator_always_has_one():
    run = _run(brief=intent(BRIEF, mode=HeightMode.FIXED, floors_above_stilt=8, has_stilt=False))
    assert run.proposal.candidates == () and "stilt" in run.proposal.notes[0]


def test_a_fixed_height_below_the_high_rise_height_says_why_nothing_was_tried():
    run = _run(brief=intent(BRIEF, mode=HeightMode.FIXED, floors_above_stilt=3))
    assert run.proposal.candidates == () and "high-rise" in run.proposal.notes[0]


def test_a_fixed_height_the_law_rules_out_gives_the_generators_own_reason():
    run = _run(brief=intent(BRIEF, mode=HeightMode.FIXED, floors_above_stilt=10))
    assert run.proposal.candidates == ()
    assert "Abutting road width" in run.proposal.notes[0] and "24 m" in run.proposal.notes[0]


def test_when_the_brief_allows_no_legal_count_the_law_is_named():
    run = _run(brief=intent(BRIEF, mode=HeightMode.MAX_LEGAL, min_floors_above_stilt=12))
    assert run.proposal.candidates == () and run.found is None
    assert "no high-rise floor count open" in run.proposal.notes[0]


def test_a_reading_the_generator_does_not_have_is_refused():
    with pytest.raises(ValueError, match="no reading 'centreline'"):
        LegacyStrategy(LIBRARY, readings={"fire_turning_radius": "centreline"}).run(
            SearchContext(SITE, RULES, BRIEF))
    with pytest.raises(ValueError, match="no reading 'half_counted'"):
        LegacyStrategy(LIBRARY, readings={STILT_IN_RULE_HEIGHT: "half_counted"}).run(
            SearchContext(SITE, RULES, BRIEF))


# --- one strategy for each reading the rules leave open ------------------------------------------


def test_one_strategy_is_made_for_each_combination_of_open_readings():
    strategies = LegacyStrategy.for_readings(RULES, LIBRARY)
    assert RULES.interpretation(STILT_IN_RULE_HEIGHT).selected == ALL
    assert [(s.readings[STILT_IN_RULE_HEIGHT], s.readings[CIRCULATION_IN_SETBACK])
            for s in strategies] == [
        ("counted", "allowed"), ("counted", "not_allowed"),
        ("not_counted", "allowed"), ("not_counted", "not_allowed")]


def test_a_reading_the_rules_have_settled_gives_one_strategy_not_two():
    settled = [i.model_copy(update={"selected": "counted"}) if i.id == STILT_IN_RULE_HEIGHT else i
               for i in RULES.interpretations]
    rules = RULES.model_copy(update={"interpretations": settled})
    assert [s.readings[STILT_IN_RULE_HEIGHT]
            for s in LegacyStrategy.for_readings(rules, LIBRARY)] == ["counted", "counted"]


def test_a_candidate_says_which_readings_it_was_made_under():
    clock = Clock()
    readings = {STILT_IN_RULE_HEIGHT: STILT_NOT_COUNTED, CIRCULATION_IN_SETBACK: "not_allowed"}
    run = LegacyStrategy(LIBRARY, readings=readings).run(SearchContext(
        SITE, RULES, max_legal(BRIEF), budget=Budget(2.5, clock)))
    assert run.proposal.candidates
    assert all(c.interpretation_basis == readings for c in run.proposal.candidates)
    assert run.proposal.candidates[0].candidate_id.startswith("legacy-not_counted-not_allowed-")
