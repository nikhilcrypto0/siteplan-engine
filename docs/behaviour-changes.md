# Behaviour changes

A characterization test (tests/manifest.py) pins what the engine produces today. It may change
only together with a normative replacement test and an entry here: what changed, why, the
evidence, and the test that now holds the behaviour. Newest first.

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
- **A bad shape gets a report, not a crash** (`test_validator_robustness.py`): a polygon that
  crosses itself anywhere in a candidate is mended to be measured and named in a blocking
  cross-check; a net plot that crosses itself or encloses nothing is refused like a missing one;
  a candidate holding nan or infinity fails as unmeasurable.
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
