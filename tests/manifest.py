"""Which tests are NORMATIVE and which CHARACTERIZATION (docs/ARCHITECTURE.md, section 0).

NORMATIVE: what must stay true whatever the implementation: a law value with its clause, a
contract or geometry invariant, an approval or security property, how an input is read, a fact
of a real drawing.

CHARACTERIZATION: what the prototype pipeline produces today: exact numbers, the legacy
generator's own choices (the fixed loop road, one height for every tower), or one reading of an
open question. Kept to catch unintended change. One may change only together with a normative
replacement test and an entry in docs/behaviour-changes.md giving the reason and the evidence.

Every test file is listed here: its default class, and the tests that differ from it.
tests/conftest.py marks each test and refuses an unlisted file; tests/test_manifest.py checks
that every name below is a real test.
"""

NORMATIVE, CHARACTERIZATION = "normative", "characterization"
N, C = NORMATIVE, CHARACTERIZATION

FILES: dict[str, tuple[str, dict[str, str]]] = {
    "test_access.py": (C, {
        "test_a_turn_with_something_in_its_way_is_found": N,
        "test_the_entrance_goes_on_the_side_the_access_road_runs": N,
        "test_a_road_that_meets_the_loop_once_is_a_dead_end": N,
        "test_a_jagged_access_side_still_gets_a_full_width_approach_road": N,
        "test_a_main_approach_narrower_than_the_rule_says_so_rather_than_its_drawn_width": N}),
    "test_acceptance.py": (C, {
        "test_the_comparison_reads_the_firms_plan_only_now_and_measures_both_the_same_way": N,
        "test_the_report_carries_every_section_the_acceptance_asks_for": N,
        "test_towers_are_read_back_from_the_delivered_dxf": N}),
    "test_adapters.py": (N, {}),
    "test_amenities.py": (C, {
        "test_a_small_scheme_gets_no_automatic_club_house": N,
        "test_parking_uses_the_ghmc_column_inside_ghmc_and_asks_when_cure_is_not_known": N}),
    "test_approval.py": (N, {}),
    "test_area_statement.py": (N, {}),
    "test_assistant.py": (N, {}),
    "test_blind_guard.py": (N, {}),
    "test_cases.py": (N, {
        "test_every_client_case_fails_only_where_we_already_know_why": C}),
    "test_checks.py": (N, {
        "test_non_high_rise_is_flagged_as_not_checked": C}),
    "test_client_fixtures.py": (N, {
        "test_rule_check_statuses": C,
        "test_the_debug_baseline_is_reproduced": C,
        "test_every_debug_option_passes_and_each_is_a_different_idea": C}),
    "test_constraints.py": (N, {}),
    "test_contracts.py": (N, {}),
    "test_dxf.py": (N, {}),
    "test_flat_import.py": (N, {}),
    "test_guards.py": (N, {}),
    "test_heights.py": (N, {
        "test_heights_run_from_one_above_the_legal_limit_down_to_the_lowest_high_rise": C}),
    "test_intake.py": (N, {
        "test_max_floors_are_worked_out_by_the_engine_not_typed": C}),
    "test_inventory.py": (N, {}),
    "test_layout.py": (N, {
        "test_unit_mix_is_close_to_the_request_and_best_option_is_first": C,
        "test_free_stretches_skip_a_notch_in_the_strip": C}),
    "test_llm.py": (N, {}),
    "test_manifest.py": (N, {}),
    "test_max_floors.py": (N, {}),
    "test_mcp_server.py": (N, {
        "test_a_project_from_answers_is_drawn_from_its_own_floors_and_the_firms_library": C}),
    "test_net_plot.py": (N, {}),
    "test_parking.py": (N, {
        "test_bays_leave_an_aisle_between_rows_and_double_loading_shares_it": C,
        "test_the_fewest_cellars_that_meet_the_need": C,
        "test_an_unsettled_jurisdiction_plans_for_the_stricter_column": C,
        "test_the_ramp_stays_out_of_the_setbacks_and_the_fire_lanes": C}),
    "test_pdf_survey.py": (N, {}),
    "test_project.py": (N, {}),
    "test_registration.py": (N, {}),
    "test_review_fixes.py": (N, {}),
    "test_roads.py": (N, {}),
    "test_rulebook.py": (N, {}),
    "test_rules.py": (N, {}),
    "test_sheet.py": (N, {}),
    "test_site_amenities.py": (N, {
        "test_each_facility_lands_by_its_own_anchor": C}),
    "test_strategies.py": (C, {
        "test_every_tower_is_reported_with_its_size_flats_and_cores": N}),
    "test_units.py": (N, {}),
    "test_water.py": (N, {
        "test_land_across_the_water_from_the_entrance_is_left_unbuilt": C}),
    "test_wizard.py": (N, {}),
}


def kind_of(file_name: str, test_name: str) -> str | None:
    """The class of one test, or None when its file is not listed."""
    if file_name not in FILES:
        return None
    default, exceptions = FILES[file_name]
    return exceptions.get(test_name, default)
