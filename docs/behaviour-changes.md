# Behaviour changes

A characterization test (tests/manifest.py) pins what the engine produces today. It may change
only together with a normative replacement test and an entry here: what changed, why, the
evidence, and the test that now holds the behaviour. Newest first.

## 2026-10-03: D (the validator) on contracts 1.1

One characterization test changed, with its normative replacement:

- **A block of exactly 21 m is judged on Table IV's first row (7 m, a 12 m road).** Under 1.0
  the bands had no row for exactly 21 m, so the validator held such a block to the row above and
  called a shortfall UNVERIFIED (the "seam"). 1.1 gives that height a band of its own, and the
  validator now reads the band the contract gives (`HeightRules.band_for`), as the optimizer
  does. `test_a_block_at_exactly_the_high_rise_threshold_is_held_to_its_own_row`
  (characterization: Tower 5 of the made-up case, 7 m round it, now PASS as today's checker
  says); normative: `test_a_block_exactly_at_the_threshold_is_a_high_rise_on_table_ivs_first_row`,
  `test_a_road_short_of_the_21_m_row_fails_a_block_of_exactly_21_m`,
  `test_a_gap_short_of_the_21_m_row_fails_two_blocks_of_exactly_21_m`,
  `test_a_club_house_too_close_to_a_block_exactly_21_m_high_fails`.

What else now behaves differently, each held by a normative test:

- **Every height limit is judged by `HeightLimit.evaluate`.** A conditional limit met anyway
  passes; one that does not apply is listed as INFO; a limit on unconfirmed inputs settles
  nothing. `test_a_limit_is_judged_as_the_contract_judges_it`.
- **High-rise eligibility is checked.** A block of 21 m or more where the rules prohibit a
  high-rise FAILs; an unsettled eligibility is UNVERIFIED; nothing below 21 m passes.
  `test_a_high_rise_where_the_site_may_take_none_fails_and_nothing_lower_passes`.
- **Organised open space counts a facility's ground from its stated use and surface and the
  rule, under every reading of the two open questions.** A built facility on the tot-lot takes
  its ground out (FAIL where that leaves too little); a paved court or a paved tot-lot is
  UNVERIFIED (the rule's "etc." and a tot-lot's surface are open); a facility whose use or surface
  the brief does not state is never counted on the strength of its name; a facility that
  qualifies off the drawn pockets counts too, under the same location tests. The test suite on
  the real drawings now gives the brief the use and surface the repo's researched amenity list
  states (`examples/amenities.hyderabad.json`), as the firm's own file does not state them.
  tests/test_validator_amenities.py.
- **The open-space width test is clipped to the ground it is given.** It had counted ground
  past corners the pockets cut (13.38 m² on one Dhulapally option).
  `test_the_width_test_never_counts_ground_outside_the_pocket_it_is_given`.
- **A placed facility that states another use or surface than the brief is a blocking
  discrepancy.** `test_a_placed_facility_that_says_another_use_than_the_brief_blocks_a_pass`.
- **Design targets are reported beside the verdict** (legal minimum, target, provided); a missed
  target is a program finding, never a legal one.
  `test_a_missed_design_target_is_a_program_finding_and_never_moves_the_legal_verdict`.
- **A marked electricity line is said, UNVERIFIED** (rule 3(c)(i)).
  `test_a_marked_electricity_line_is_said_never_passed`.
- **The five-acre amenity check is gone** (rule 9(o)/10(i), row and cluster housing).
  `test_no_five_acre_amenity_share_is_held_against_a_group_scheme`.
- **A ramp's fire clearance is read from the rules** (`parking.ramp_fire_clearance_m`), not a
  constant in the validator.

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

## 2026-10-03: D (independent validator)

No existing test changed. `siteplan.validator.validate` is new and `checks.py`, `access_checks.py`
and `parking_checks.py` are untouched, so their logic still exists in two places until the legacy
generator retires. Where the validator's verdict differs from today's checker, each case is
pinned and explained in a characterization test:

- **On the four contract fixtures** (`test_validator_characterization.py`) its statuses equal the
  generator's claims except two: `rectangle`, "Fire access: the street joins a 12 m street" (the
  generator ran without the architect's answer and said UNVERIFIED; the site model holds it, so
  PASS), and `small_plot`, "Setbacks (Table III)" (a hand-made claim; under 21 m Table III
  applies, which neither models, so NOT_CHECKED).
- **On the firm's Dhulapally case** it fails exactly where `siteplan cases` does (the known list).
- **On the generator's own Dhulapally options** under both readings of the stilt
  (`test_validator_client_run.py`, client data, skips without it) there is no FAIL, and every
  claim is reproduced except "Peripheral green strip" under `not_counted`: the options were
  planned as if the stilt is not counted and draw no strip, but if it counts the setback reaches
  9 m and a strip is asked for, so the validator says UNVERIFIED naming the reading where the
  checker says INFO.
- **Checks the checker does not make** (each found by an adversarial review that drew a layout
  the first version of the validator passed, each pinned by a test): a gate is as wide as its
  opening, stands in the boundary on the side the street runs, and only such a gate starts a lane
  or relaxes the planted strip; the roads are one network entered from a gate (no floating
  piece, a loop that closes, a main approach from the gate to the loop, a way in drawn as a
  driveway is not one); the club house keeps a Table IV gap from each tower; the master plan's
  road width counts only where the strip is surrendered; a prototype floor shorter than the
  firm's is said; bays are rectangles a car fits in and ramps are measured across and reach the
  cellar; what a facility's surface is comes from the brief's request of that name (without it a
  play area on the tot-lot leaves the open space UNVERIFIED, because the adapters do not yet fill
  `AmenityRequest.surface` from the firm's library); a club house as tall as a high-rise can
  never pass on its size alone. On the generator's real options (Dhulapally and Suchitra) none
  of these produces a FAIL, and the open space is UNVERIFIED without the facility surfaces in the
  brief and PASS with the firm's.
- **Legal layouts it must not fail** (found by a review that drew what an architect or an
  optimizer would; `test_validator_false_fails.py`): a gate at a corner of the plot is measured
  along the edge it lies on; a second entrance on a second surveyed road is UNVERIFIED, not
  failed; a plot turned a hair keeps both edges a diagonal road side faces; a ramp or
  cul-de-sac that bends or folds is UNVERIFIED on its length, not failed on the length of its
  box (a straight one that is short still fails); a 9 m loop drawn as chords of an arc passes;
  a shape that only touches itself is no defect; a seed, a score or a claim is recorded, not
  measured; rules that name another Table V column than the site's jurisdiction does are held
  to both. Shapes are snapped to a micrometre grid, so drawn shared edges are shared.
- **A bad shape gets a report, not a crash** (`test_validator_robustness.py`): a polygon that
  crosses itself anywhere in a candidate is mended to be measured and named in a blocking
  cross-check; a net plot that crosses itself or encloses nothing is refused like a missing one;
  a candidate holding nan or infinity fails as unmeasurable; an error the geometry library cannot
  get past is an UNVERIFIED report carrying its message (the validator's own mistakes still
  raise).
- **Stricter by design**: a result that holds under only some readings of an open question is
  UNVERIFIED naming the reading (the checker knows only the reading it planned for); an input
  nobody confirmed (a road width read off a drawing) settles nothing; a block at exactly 21 m,
  which falls between the resolved Table IV rows, is held to the row above and, short of it, is
  UNVERIFIED rather than FAIL. Circulation inside the setback is UNVERIFIED on the generator's
  layouts: its roads and fire lanes lie in the setback, which passes if circulation may stand
  there and fails if not, and the rules leave that reading open.

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
