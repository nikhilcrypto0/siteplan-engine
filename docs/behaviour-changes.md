# Behaviour changes

A characterization test (tests/manifest.py) pins what the engine produces today. It may change
only together with a normative replacement test and an entry here: what changed, why, the
evidence, and the test that now holds the behaviour. Newest first.

## 2026-10-03: contracts 1.1

No characterization test changed on the integration branch. What now behaves differently, each
held by a normative test:

- **An access road's legal width is no longer marked confirmed merely because the project gave
  no status.** The adapter took any value without a status as the architect's (USER_CONFIRMED);
  a width read off a drawing (`abutting_road_status: UNVERIFIED_DRAWING_VALUE`, as on Suchitra)
  then travelled as confirmed. Its status now follows the declared source (certified right of
  way VERIFIED, declared on the site plan USER_CONFIRMED, drawing value UNVERIFIED), a status
  the project records still wins, and with nothing said it is UNVERIFIED.
  `test_a_road_width_is_never_confirmed_merely_because_nobody_said_how_it_is_known`.
- **A facility's ground is no longer classed by its name.** The adapter's ledger called a
  facility built when its name held CABIN, ROOM or SUBSTATION. It now follows the surface the
  firm's amenity library states (BUILT, HARD or SOFT); one that states none is entered as an
  amenity tagged SURFACE_UNSTATED. `test_a_facilitys_ground_follows_its_stated_surface`.
- **A building of exactly 21 m is a high-rise with its own band.** In 1.0 the band below the
  high-rise height ran up to and including 21 m, so a 21 m building fell among the non-high-rise
  heights that are not modelled.
  `test_a_building_of_exactly_the_high_rise_height_is_a_high_rise_with_its_own_row`.
- **A conditional height limit that is met anyway passes.** The dead-end limit (30 m, when the
  road ends at the plot) was UNVERIFIED for every height while nobody had said where the road
  leads; it is now PASS up to 30 m and UNVERIFIED only above it.
  `test_a_height_limit_is_judged_by_one_table`.
- **A site that cannot take a high-rise no longer carries a "21 m" limit.** It carries
  high-rise eligibility PROHIBITED, and nothing below 21 m is treated as passing until Table III
  is encoded (A2) and validated (D2).
  `test_a_prohibited_high_rise_says_nothing_about_lower_heights`.

## 2026-10-02: P0 (contracts, baseline, leak guard)

- **Dhulapally's regression moves from a blind run to a pinned debug run.** The blind run cannot
  run: since a3136f7 (10-01) the engine refuses to guess where a road strip lies, and the survey
  marks none. Replacements: `test_dhulapally_blind_run_stops_and_asks_where_the_strip_lies`
  (normative), `test_the_debug_baseline_is_reproduced` (characterization, both stilt readings,
  pinned in fixtures/baseline/dhulapally-debug-2026-10-02/). Evidence: the 10-01 code; the
  architect has not yet located the strip.
- **"Stilt + 10 fails on the road" is no longer asserted as law.** The removed
  `test_dhulapally_from_the_survey_alone_finds_the_height_the_law_and_the_ground_allow` assumed
  the stilt counts toward the Table IV height, an open reading. Replacement:
  `test_dhulapally_60_ft_road_allows_30_m_of_rule_height_under_either_reading` (normative: 30 m;
  9 floors above the stilt if it counts, 10 if not). Evidence: the architect confirmed the 60 ft
  road and that "Stilt + 8" means one stilt plus eight floors (2026-10-02); neither settles the
  stilt's place in the Table IV height.
- **Acceptance is blind by default and refuses the firm's finished plan.** A debug profile, a
  value tagged FIRM_FINISHED_PLAN, or a finished drawing given as the survey now needs `--debug`
  (`mode="debug"`). `test_a_test_profile_sets_its_values_labels_them_and_leaves_the_rules_alone`
  runs in debug mode and checks the DEBUG RUN header. Replacements: tests/test_blind_guard.py
  (normative), `test_dhulapally_blind_run_refuses_the_firms_finished_plan`.
