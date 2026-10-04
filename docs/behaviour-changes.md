# Behaviour changes

A characterization test (tests/manifest.py) pins what the engine produces today. It may change
only together with a normative replacement test and an entry here: what changed, why, the
evidence, and the test that now holds the behaviour. Newest first.

## 2026-10-04: Wave 2 integrated (A2, D2 and C2 on contracts 1.2)

No characterization test changed. C2 adds the full search, strategy FULL beside LEGACY, held by
its own normative tests (tests/test_search_*.py; test_search_client.py runs it on the two real
sites and skips on a clean clone). What the three streams change together:

- **The optimizer offers no floor count below 21 m until C3.** Before A2 such a count had no
  modelled band, so `feasible_floors` left it out by an accident of the data; with Table III
  encoded the rule is explicit (`FloorOption.below_high_rise`): the count is assessed on its band,
  never offered, and NOT_CHECKED, because floors.py does not read a band's permission yet (C3
  must). `test_optimizer_floors.py::test_a_count_below_the_high_rise_height_is_assessed_but_not_offered_yet`,
  `::test_where_a_high_rise_is_prohibited_no_count_is_offered_and_nothing_lower_either`.
- **The contract fixtures' low blocks are judged on Table III.** Sixteen validator tests were
  written when the fixtures shipped one unmodelled band below 21 m. Those about a band the rules do
  not model now build it themselves (`unmodelled_below`, tests/validator_low_helpers.py) and assert
  what they did; those about the fixtures' own blocks assert the Table III verdict: the small
  plot's 15 m block keeps 6 m on the sides and the 3 m Building Line in front
  (test_validator_blocks.py), its setback zone is that deep (test_validator_readings.py), the
  2-floor club house keeps row 11's 5 m (test_validator_low_blocks_site.py,
  test_validator_club_spacing.py), and a prohibited high-rise leaves every lower block's verdict
  as on an open site (test_validator_v11.py). The fixtures carry rule 8(l)'s 6 m pathway
  (test_validator_pathways.py) and a 2 m strip on the high-rise bands from 9 m, which gives the
  verdict rule 7(a)(viii) gave (test_validator_planting.py). Two tests that still passed but no
  longer compared what they say (`test_installing_modelled_bands_below_21_m_moves_no_check_of_a_high_rise_layout`,
  `test_the_high_rise_blocks_of_a_mixed_layout_are_judged_as_before_the_low_one_is_modelled`)
  compare against the unmodelled band again.
- **The small plot's hand-made layout is laid to Table III** (tests/contract_fixtures/build.py).
  It failed the open space (192 of the 300 m² asked counted: its pocket lay in the 6 m setback)
  and drew no strip. The pocket now stands between the block and the north setback (312 m²), a
  1 m strip runs round the plot broken at the driveway, and the gate is as deep as the strip.
  `test_validator_cross_checks.py::test_the_untouched_fixtures_have_no_blocking_discrepancy`.

## 2026-10-04: A2, Table III and the blocks below 21 m

No characterization test changed. What now behaves differently, each held by a normative test:

- **Every height below 21 m has a band** (contracts 1.2); under 1.1 one unmodelled band covered
  it all. A height above a row's last line is PROHIBITED; 18-21 m is UNVERIFIED with no setback
  (no order read gives one). tests/test_resolve_non_high_rise.py, tests/test_non_high_rise.py,
  `test_resolve.py::test_every_height_has_one_band_and_exactly_21_m_is_a_high_rise`.
- **A road under 12 m** gives the limit "below 21 m" (BOUNDED, upper edge excluded; it was
  NOT_EVALUATED), and a Group Development Scheme on it is permitted nothing lower.
  `test_resolve.py::test_a_road_under_the_first_row_prohibits_a_high_rise_and_permits_nothing_lower`,
  `test_contracts.py::test_a_road_too_narrow_for_a_high_rise_serves_nothing_from_21_m_and_leaves_the_rest_to_bands`,
  `test_resolve_non_high_rise.py::test_a_group_scheme_on_a_road_under_12_m_has_nothing_below_21_m_and_no_high_rise_either`.
- **A block of exactly 21 m on a road over 30 m keeps 7.5 m in front** (rule 7(a)(xi): the higher
  of Table IV and the Building Line), not 7 m.
  `test_resolve_non_high_rise.py::test_a_block_of_exactly_21_m_on_a_road_over_30_m_keeps_the_building_line_at_the_front`.
- **A road given in feet is reckoned as the order's round metres** (rule 5(f)(xvii): 60 ft is
  18 m). `test_rules.py::test_a_road_in_feet_is_reckoned_as_the_orders_metres`.
- **The envelope draws land for every permitted band below 21 m**, says why a band has none, and
  draws the planting strips as layers. tests/test_envelope_non_high_rise.py,
  tests/test_envelope.py, tests/test_envelope_client.py.
- **The high-rise front setback is cited to rule 7(a)(xi), p.14**, not rule 12(b), p.17 (the
  U-type commercial rule it had been cited to).
  `test_rules.py::test_the_high_rise_front_is_rule_7_a_xi_and_not_the_commercial_courtyard_rule_it_was_cited_to`.
- **`rules.height_rules(height, plot_sqm, road_m)` answers Table III** when given the plot (it said
  "not encoded"). tests/test_rules.py.
- **The orders list names what was read for rule 5** and what is still unread (`ORDERS` in
  legal/resolve.py).
  `test_resolve.py::test_the_orders_are_listed_with_how_each_was_read_and_the_unread_ones_named`.

Not settled by the text, and left open: a setback for 18-21 m; the gap between a low block and a
high-rise (8(j) "as the case may be", both readings evaluated); whether the stilt counts toward the
high-rise class (5(c) leaves it out only for Table III). The prototype's checks.py, layout.py and
max_floors.py still say Table III is not encoded; they are prototype code, left as they are.

## 2026-10-04: contracts 1.2

No behaviour changed and no test changed but the version test: every addition is a field or a
method nothing reads yet (A2's resolver, D2's checks and C3's search will), and a 1.1 document is
now refused. `test_the_contracts_are_version_1_2_and_refuse_an_older_document`.

## 2026-10-04: D2, the validator for blocks below 21 m, on contracts 1.2

No characterization test changed, and on every input whose blocks are all high-rise, or whose
blocks below 21 m sit in a band the rules do not model (everything A1 emits today), no status moved:
27 runs of the contract fixtures, the made-up firm case and their variants were dumped before and
after each stage (contracts 1.1, then 1.2) and diffed check by check (verdicts, statuses,
per-reading results, recomputed measures and design targets); the only differences are the new
checks below and the wording of what is said about a block below 21 m. Each change is held by a
normative test on made-up bands (tests/validator_low_helpers.py; tests/test_validator_low_blocks.py,
_low_blocks_site.py, _front.py, _permission.py, _pathways.py, _planting.py, _envelope_front.py).
Where ResolvedRules models a band below 21 m (`Band.modelled`, with a setback), a block in it is
judged on it:

- **Which band.** `HeightRules.band_for_block`, the lookup the optimizer makes: the class (high-rise
  or not) from the rule height under the reading of the stilt, then, below 21 m, the row on the
  height above the stilt, which rule 5(c) leaves the stilt out of whatever the reading says. 4
  floors on a 3 m stilt are in one row under both readings, and the report says it ("15.00 m, read
  as 12.00 m above the stilt"). Which block is the taller of two is read on the height each band was
  read on.
- **Setback, the front apart.** The stretches of the plot line facing `site.access.side` are held to
  the band's `front_m` and the rest to its `setback_m`, high-rise bands too (a band that gives no
  front figure is held all round, as before). With the access side not known a block passes only if
  it clears the larger figure on every side and fails only if it misses the smaller one somewhere,
  UNVERIFIED between. The setback zone the bays, ramps, open space and roads in the setback are
  judged against is edge-wise too (all round at the larger where the side is not known: never more
  lenient); the design targets keep the tightest side, not the larger figure all round. The check
  names its band's own table, and a high-rise's Table IV front clause is no longer cited for a block
  that is not one.
- **Gap.** Between two blocks below 21 m the tallest block's side setback (`gap_m`, else `setback_m`,
  the figure for every side but the front) governs whatever `mixed_height_spacing` says, because
  rule 5(f)(xiii) says so in terms (p.11: "The space between 2 blocks shall not be less than the
  side setback of the tallest block as mentioned in Table - III"): the check quotes it. A low block
  beside a high-rise, and two high-rise blocks, are evaluated under every reading, as before.
- **Road.** "Abutting road width" also holds a block below 21 m to its band's `min_road_m` (it was
  made only where a high-rise stood; all-low layouts now get it). Its name, and its verdict for
  high-rise blocks, are unchanged. `min_road_m` None on a modelled band is "not stated": that block
  is named and not judged; 0.0 is "asks none".
- **Permission.** A new "Height permitted: T" check, for each block below 21 m in a modelled band
  (and for a high-rise block whose band's own permission is not ALLOWED), reads
  `HeightRules.band_permission`: PROHIBITED fails the block, naming `permission_note`; UNVERIFIED
  leaves it UNVERIFIED. A modelled band with no figures (a stretch the site may not take) leaves the
  block's other checks NOT_CHECKED, saying the band gives none and why. A prohibited high-rise
  (eligibility) still fails only blocks of 21 m or more, exactly 21 m included, and permits nothing
  below: a block below it is held to its own band's permission alone.
- **Club house.** Its setback (front apart) and its gap to each tower go through its band when that
  is below 21 m and modelled; one as tall as a high-rise is unchanged (it cannot pass), one in a band
  the rules do not model is NOT_CHECKED as before.
- **A band the rules mark UNVERIFIED settles nothing** (setback, gap, road, permission, club house):
  UNVERIFIED, never PASS or FAIL, as `HeightLimit.evaluate` does for a limit on unconfirmed inputs.
  **A band that is not modelled stays NOT_CHECKED**, never PASS; the cell names the band's own table.
- **Rule 8(l).** A pathway (`RoadKind.PATHWAY`) is not a road: it is not held to rule 8(m)'s 9 m, is
  not motorable, and takes ground from open space and bays. A block up to 12 m (physical height,
  exactly 12 m included) on no road is served by a pathway that branches out of an internal or loop
  road and is as wide as `pathway_width_m`; narrower, or not branching, is a FAIL; where the rules
  give no width yet it is UNVERIFIED; a block on no road and no pathway has no way in (FAIL). A
  block above 12 m reached only by a pathway fails, and the check says a pathway is for blocks up to
  12 m. The "every block served: all 0 blocks" PASS that said nothing is no longer made when no block
  is above 12 m.
- **Fire access below 21 m (rule 15(a)(i)).** A low block is not held to the NBC high-rise lanes. A
  NOT_CHECKED check names each such block (and the stilt reading it is low under), quotes rule 15(a)(i)
  (p.20) and says the rule gives no figure for what it asks of access. The high-rise fire checks are
  untouched, and a block high-rise under only one reading of the stilt is still UNVERIFIED there.
- **Planting.** The strip a band asks (`Band.green_strip_m`, along `ALL` the plot line or the
  `FRONTAGE`) is held against the drawn strip: missing ground or a strip narrower than asked fails;
  a frontage that cannot be placed (access side not known) is UNVERIFIED. A strip lies within the
  setbacks and is never added to them. A high-rise band that carries none is held to the high-rise
  strip as before (rule 7(a)(viii)); a band below 21 m that carries none asks none.
- **Envelope cross-check.** A band's front setback and permission are compared (an envelope that is
  more lenient than the law blocks a pass), and its buildable land is recomputed inset all round by
  the larger of the band's two setbacks.
- **Not carried, so not checked:** the transfers of setback that rule 5(f)(viiii), (ixi) and (xi) allow
  (the validator is stricter than the order for a layout that uses one), and the Fire Services
  clearance a taller residential building needs (a permission, not a layout).

## 2026-10-03: Wave 1 integrated on contracts 1.1; the independent validator guards the optimizer

No characterization test changed here. What now behaves differently, each held by a normative
test:

- **The optimizer's validator is stream D's** (`siteplan.validator`, the default in
  `optimize`); the interim validator, which restated the generator's own claims, is deleted.
  Made-up blocks with no roads or open space are now refused as the illegal layouts they are;
  the tests of the optimizer's mechanics give their made-up candidates a labelled test validator
  (`optimizer_support.Claims`) instead. `test_the_independent_validator_is_the_default_and_a_validator_can_be_given`,
  `test_the_guard_refuses_what_the_independent_validator_fails_with_no_claim_needed`,
  `test_every_reading_of_the_stilt_is_run_and_the_pool_keeps_them_apart` (the generator's own
  layouts through the real validator: UNVERIFIED, none FAIL).
- **A1 (legal envelope):** the dead-end limit is always listed, UNKNOWN while nobody has said
  where the road leads and DOES_NOT_APPLY when it runs on; a road or plot too small for a
  high-rise gives eligibility PROHIBITED, never a "21 m" limit, and no band is drawn; a road
  that meets every row is UNBOUNDED; a block of exactly 21 m has its own band (7 m) in the
  envelope; the five-acre fields are gone. tests/test_resolve.py, tests/test_envelope.py.
- **C1 (optimizer core):** a block of exactly 21 m is offered (6 floors on a 3 m stilt when it
  counts, 7 when not); a count beyond a limit on unconfirmed inputs is still not offered and is
  labelled UNVERIFIED, not FAIL; where the road runs on, the dead-end limit is INFO; eligibility
  is checked on every count of 21 m or more; the legacy generator says when design margins were
  asked for and not applied. tests/test_optimizer_floors.py, tests/test_optimizer_legacy.py.
- **B (prototypes):** none; the prototypes carry schema 1.1.

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
