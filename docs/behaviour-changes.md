# Behaviour changes

A characterization test (tests/manifest.py) pins what the engine produces today. It may change
only together with a normative replacement test and an entry here: what changed, why, the
evidence, and the test that now holds the behaviour. Newest first.

## 2026-10-18: the stilt reading carries the Bachupally permit as supporting evidence

- **What changed.** The sources of `stilt_in_rule_height` gain HMDA's TG-bPASS permit
  004812/BP/HMDA/1054/MED/2024 of 08-08-2024 (Bachupally, Survey No. 306/P): Block A, 2 cellars +
  1 stilt + 12 upper floors, permitted at 35.4 m = 12 x 2.95 m, its height without the stilt
  (`legal/readings.BACHUPALLY_PERMIT`; the inventory entry says the same). The reading stays open:
  ALL by default, the architect's selection not settling it, both readings judged.
- **Why.** The architect's request of 2026-10-18; the figures were read off the permit itself. It
  names no setback, so it does not show which Table IV row the authority applied.
- **Tests.** `tests/test_service_proposals_baseline.py` (characterization) is re-pinned: the rules'
  digest moves, so the proposed and shown digests move; the notes, the 39 proposed, the ten shown,
  the model's answer and the approval page are unchanged. The normative test is
  `test_the_bachupally_permit_supports_the_stilt_reading_and_settles_nothing`
  (`tests/test_project_inputs.py`).

## 2026-10-18: alternatives round locked blocks may use every block in the firm's library

- **What changed.** `service.around.alternatives` takes the site's workspace and gives the search
  every block the firm's flat library there gives the stored brief, composed as `propose_layouts`
  composed the run's own kit (`service.search_kit`, formerly `service._kit`: the families for the
  brief's mix and the floor plates its land takes, within the firm's longest block), with the
  chosen layout's own blocks beside them, which win on an id they share. It used to take only the
  blocks the run's shown and proposed layouts used. A workspace that names no flat library is
  refused with that reason; the CAD tool asks for the site's `workspace` in the sites file.
- **Why.** The architect's decision 3 of 2026-10-18: "let alternatives use every block type in
  the firm's library from the workspace, not only those the run used."
- **Tests.** `tests/test_layout_around.py` (normative): the search round the locks is given the
  library's blocks and the run's (it fails with the old kit), a workspace with no library is
  refused, and the CAD tool asks for the workspace.

## 2026-10-18: round a locked block, the search lays only tot-lot and roads the validator allows

- **What changed.** In a search round locked blocks (Stage D), `layout.evaluate` sizes the setback
  zone (and the planted strip) from the deepest any block standing needs, the locked ones included,
  where it took only the configuration's own blocks; and a configuration whose street or link road
  would cross a locked block is not offered, with the reason "street-N would run through a locked
  block" (`layout._through_locked`). A search with nothing locked is unchanged.
- **Why.** On Dhulapally's debug run, with T1 locked at Stilt + 10 and ten alternatives asked, the
  validator refused ten of the fifteen layouts judged: eight for too little countable tot-lot,
  because the generator laid open space 8 or 9 m in where the validator's setback zone, as deep as
  the locked Stilt + 10 block asks, starts 10 m in (3,623.5 m² summed over those layouts, inside
  the setback); and five for a tower under a road, a street between two columns running on
  through the locked block. With the fix: fifteen judged, none refused. The validator is
  unchanged (figures kept locally, client data).
- **Tests.** `tests/test_search_round_locked.py` (normative, made-up rectangle): the land a
  configuration lays open space on starts as deep as the locked block's zone; no street or link
  runs through a locked block, and the configuration that would is refused with that reason; and
  the search round a taller lock judges no layout refused, its tot-lot counted. All three fail on
  the old generator (1,136 m² of interior inside the 10 m zone; street-1 over 164 m² of the
  block; one layout refused for the tot-lot and its roads).

## 2026-10-16: a cellar reaches under every block that may stand over one, then the need (C4-17)

- **What changed.** The full search sized a cellar (C4-13) as a box square to the turn grown
  evenly round its ramp until it held the need. Now the growth starts from the hull of the ramp's
  box and the boxes of the parts, on the ground the ramp reaches, of every block that may stand
  over a cellar (a block with a fire band; a part smaller than a bay is left out), grows first
  until the piece holds those parts, and then only as far as the need asks, by floor area and by
  cars laid out (`parking_plan._sized`, its new `reach`; `layout._Program.reaching`). A block
  below the high-rise height still gets no cellar (`clear_of`: the search lays no fire band round
  it, and a cellar would make it an NBC special building); a block cut off from the ramp's ground
  is left alone; with no such block the cellar is exactly C4-13's.
- **Why.** Every block's lifts reaching the parking is a design choice the architect asked for,
  never a rule (constraints.py, the C4-13 entry). On the real sites' debug runs (figures kept
  locally, client data) the cellar ran under ground no block needed while the block farthest
  from the ramp stood mostly off it. Re-run: the same layouts, flats and verdicts on both sites,
  every block that may stand over a cellar now wholly over it, for at most a few per cent more
  cellar, the cars still meeting the need.
- **Tests.** `tests/test_search_parking.py` (normative): a far block is reached and the cellar
  stays within 1.1 times the need; a small need digs no more than the hull of the ramp and the
  blocks; the cellar runs round a low block to reach a block, and leaves alone one no ground
  joins to the ramp; and every proposal on the made-up rectangle and L-plots that digs a cellar
  has each block the validator does not hold low under it (this fails on the old growth:
  `full-not_counted-allowed-20` left T2 uncovered).
- **The service baseline's digests move** (`tests/test_service_proposals_baseline.py`,
  characterization): the notes, the fifteen proposed, the four shown, the answer and the approval
  page are the same; only `proposed_sha256` and `shown_digests` move, every proposal there digging
  a one-level cellar whose outline is now cut the new way. The normative replacement is
  `tests/test_search_parking.py`.

## 2026-10-17: alternatives round locked blocks (Stage D)

- **What changed.** Nothing a run without locked blocks proposes, shows or judges moves; laying
  alternatives round locked blocks is added.
  - The full search takes locked blocks (`SearchContext.locked`, `Run.locked`): each stands in
    a frame of its own exactly where it stood (`layout.locked_standing`, its placement checked
    to `LOCK_EXACT_M`, 1 mm), at its own height, under its own name (`Standing.name`; the
    search's blocks take the next names free). New columns keep off the ground round it
    (`_locked_room`: the gap any block that may stand asks); the ring road is fitted round the
    columns and the locked blocks and never drops a locked one (`network.fit_cluster`'s
    `fixed`); the raising pass never raises or moves one. The roads, fire lanes, club house,
    tot-lot and parking are laid as for any layout.
  - `service/around.py`: on a layout with blocks locked (Stage C's lock), the search on the run's
    stored inputs and its own kit, every candidate held to the locked blocks and passed by the
    optimizer's guard, up to N genuinely different ones chosen (`pareto.select`, as Stage A),
    each saved as a version of the chosen layout with what it broke. Locked blocks off the net
    plot or on each other are refused before any search; when nothing can be laid the search's
    own reasons are returned, never an empty answer; when fewer than asked are found, why
    (`Around.short`: how many passed, how many were copies, how many the validator failed).
  - FreeCAD: `alternatives_around` lays them, draws the first and gives each one's line and
    verdict.
- **Why.** The architect's roadmap, 2026-10-17: locked buildings fixed to the millimetre, the
  rest placed and laid again round them, every alternative judged and kept as a version.
- **Tests.** `tests/test_layout_around.py` (normative, made-up land); the search's own tests
  unchanged (nothing locked, nothing different).

## 2026-10-17: the sheet's label short and within the plot, the verdict in full in a note

- **What changed.** A layout drawn in FreeCAD (`cad.live.show_layout`) says its verdict on the
  sheet in a few words (`describe.verdict_short`: how many readings, facts, gaps or rules it
  rests on or fails), drawn 5 m high (`scene.SHEET_TEXT_M`, readable when a whole site is
  shown; the other labels stay 2 m) with every line wrapped to the plot's width
  (`scene.wrapped`). The verdict in
  full and why it could not be exported are a note below the plot on a layer of their own
  (`scene.DETAIL`, `scene.sheet_note`). A screenshot (`Session.screenshot`, the siteplan-cad
  tool `screenshot`) hides that layer for the shot, so the view is framed on the plot and its
  short label, and shows it again after.
- **Why.** Found live in FreeCAD 1.1.3 (2026-10-17): the one-line verdict ran hundreds of
  metres wide, so fitting the view zoomed out until the plot was a third of the picture and
  nothing on the label could be read; the in-memory stand-in only kept the text.
- **Tests.** `tests/test_layout_versions.py`: the label no wider than the plot (the old one-line
  verdict on the test's layout is 174 m on a 150 m plot), the full verdict a note below the plot
  on its own layer, a screenshot showing the plot and label without the note.

## 2026-10-16: a layout edited by hand, each edit a judged version (Stage C)

- **What changed.** Nothing a run proposes, shows or judges moves; editing is added.
  - Edits (`service/edits.py`): a block moved or turned (about its own middle), the club house
    or a tot-lot piece moved, blocks locked; a layout dragged in FreeCAD read back (a block
    must be its own outline moved and turned, `RIGID_TOL_M`, else it is refused as reshaped).
    Each edit is a version (`versions.make_version`), judged by the validator, with what it
    broke written into it (`versions.what_broke`: every legal check that held in the parent
    and holds no more, and every discrepancy that now blocks a pass). A locked block stays
    locked down the line and an edit that would move it is refused.
  - Roads, fire lanes and parking stay as drawn; nothing is laid again (Stage D). An edited
    layout drops what the generator worked out from where things stood (its ledger, rule
    layers, claims, scores and Pareto tag) and claims only the open space the validator counts,
    so no stale figure of the generator's is reported as a discrepancy (found on Dhulapally: a
    club house moved onto open ground kept the generator's open-space figure).
  - FreeCAD (`siteplan-cad`): move_block, turn_block, move_club_house, move_tot_lot_piece,
    lock_blocks, read_layout_from_cad; each saves the version, draws it and says what broke.
- **Why.** The architect's roadmap, 2026-10-16: architect control, every change through the
  independent validator, roads and parking kept as drawn and what broke named.
- **Tests.** `tests/test_layout_edits.py` (normative, made-up land, every figure worked by
  hand); `tests/test_cad.py`'s list of tools.

## 2026-10-16: any layout of a run in FreeCAD, and versions in the run's folder (Stage B)

- **What changed.** Nothing a run proposes, shows or judges moves; two things are added.
  - Versions (`service/versions.py`, `versions.make_version`): a layout of a run, unchanged or
    edited, kept in `out/<run_id>/versions/<id>/` with its parent and the parent's digest, its
    edits and its report. Written once; saving again makes another (`<layout>-v<n>`). Made only
    for the run's own inputs; judged by the validator when saved and whenever used
    (`judge.judge_again` reaches a version, so validate_candidate and export_candidate do),
    refused when its files, its inputs or any parent along its line changed. Saved through
    FreeCAD (the CAD session) alone: `Service` and the model's host keep their nine operations.
  - FreeCAD (`siteplan-cad` tools `show_layout`, `keep_layout`; a site's `runs` folder in the
    sites file): any layout of a run drawn vertex for vertex after a fresh judgement, its sheet
    saying DEBUG RUN or STUDY where they apply, its verdict with what it rests on,
    PRELIMINARY for floor plates (and on each plate tower), and for a version what it is a
    version of and its edits; the previous layout's objects are removed; a blind site refuses
    a DEBUG run.
- **Why.** The architect's roadmap, 2026-10-16: open any layout in FreeCAD, keep it as its own
  version, every change through the independent validator.
- **Tests.** `tests/test_layout_versions.py` (normative); `tests/test_cad.py`'s list of tools.

## 2026-10-16: up to ten genuinely different layouts shown, each described (Stage A)

- **What changed.** A service run shows the brief's four points and then the next different
  ideas by yield, up to 10 (`service.brief.SHOWN_LAYOUTS`; the brief's `options`, 3 before).
  - Two layouts are one idea as before (`pareto.same_idea`: as many blocks, running the same way,
    on mostly the same ground); no copy is shown.
  - When fewer than asked are found, the run's notes say how many passed the validator and how
    many of the rest are the same idea as one shown (`pareto.shortfall`).
  - The full search judges and proposes at least as many for each profile as the brief asks
    (`Limits.for_options`), only when it asks to see more than its points
    (`strategy.options_beyond_points`): a brief asking 3 (the contract's default, fewer than its
    four points) runs exactly as before. What it lays out is unchanged.
  - Each layout shown carries `description` (its blocks, heights, the way they run, where the
    open space and the club house are, how it differs from the most alike shown) and `verdict`
    (PASS, CONDITIONAL with what it rests on, or FAIL with the rules), measured by
    `service.describe`.
- **Why.** The architect's roadmap, 2026-10-16: about ten genuinely different layouts per site,
  only different ones, each told apart in plain words with its verdict.
- **Tests.** `tests/test_shown_layouts.py` (normative): only different ideas, the shortfall
  said, the quotas raised and nothing else, the words worked out by hand from the geometry.
  `tests/test_service_proposals_baseline.py` (characterization) re-pinned, with a test that
  every layout shown is a different idea, described, with its verdict, and none fails.

## 2026-10-13: floor plates searched beside the families, never in their place (audit, phase 6)

- **What changed.** The full search used to take the families and the floor plates as one kit,
  and each column's best sequence could take a plate in a family's place.
  - Now the families' search runs exactly as it does without plates, on its own quotas.
  - The plates then have a pass of their own (`Limits.plate_share`, half of each quota, on the
    time the families leave; skipped, and said so, when none is left). The families stand
    beside them and still set the main column depth; only configurations with a plate are laid
    out, their ids starting `full-plates-`. A repair or a raise of one that gives the plate up is
    kept all the same (a layout only this pass reached is never lost), and one whose blocks the
    families' search already judged is kept once, as theirs.
  - What both passes judged is ranked together by the same selection, and the notes say what
    the plates' pass did and how many of the proposed are its.
- **Why.** On made-up land (200 x 120 m, the plate tests' flats) the merged kit lost family
  layouts the families alone judged. One configuration came out with a plate at 597,596 sft
  where its family version made 600,630.
- **Tests.**
  - `tests/test_search_plates_additive.py`: everything a families-only run judges is still
    judged, unchanged by digest, with plates added. That test fails on the old merged kit (six
    family layouts gone).
  - Every layout the plates add is the plates' pass, some keep a plate, and the pass keeps a
    layout only it found and drops a copy of a family's. On 200 x 60 m a plate layout is
    proposed and beats every family layout judged.
  - The pass is bounded and noted, and a spent budget leaves it unsearched and says so.
  - `tests/test_service_plates.py` holds as before.
- **The service baseline moves back to the families' four**
  (`tests/test_service_proposals_baseline.py`, characterization). The four layouts shown on its
  made-up land are again the four shown before plates joined the search: maximum yield and
  robust are the same candidates to the digest. Balanced is `-109` (376 flats) where the merged
  kit showed `-218` (384 flats, no plate in it). `-218` was a repair (C4-07) of one of the merged
  run's most valuable layouts, a set the plates had entered, and neither pass now repairs it.
  The open-space option is `ALL-77` (306 flats) where it was the plates' `ALL-ALL-134` (120
  flats), which lies beyond their half quota. Three of the fifteen proposed are the plates'. The
  normative replacement is `tests/test_search_plates_additive.py`.

## 2026-10-13: one reading of the rules across the pipeline (regulatory audit, phase 4)

- **The steps read the rules as the resolver and the validator do (D11).**
  - Step 4 draws the 2 m planting strip only along sides whose setback is 9 m or more. That is
    rule 7(a)(viii) as G.O.Ms.No.7 of 2016 substituted it, which the architect confirmed on
    2026-10-13 (the steps' citation test now admits G.O.7 for it).
  - Until now step 4 drew the strip on every side, the 2012 wording. The fire lane runs just
    inside the strip, or from the edge where a side keeps none, and its room is measured side by
    side.
  - A height below 21 m in step 5's height map reads its band from the resolver
    (`steps.setbacks.below_high_rise`, `legal.non_high_rise.stretches`). A height of 18 to 21 m,
    where no order read gives a setback, is reported CONDITIONAL with the resolver's reason.
    Its setback is still drawn at Table IV's first row, said to be a stand-in.
  - Step 2 still reads the plot from the written area (the net plot is step 3's), and step 4
    stops on the net plot as before, so the outcome is the engine's.
  - FreeCAD draws step 4's own shapes, so it follows.
- **One reading of which road width Table IV reads (D9).** Where the rules carry
  `table_iv_road_width` (a master-plan width is known), the validator judges both the existing
  width and the master-plan width (counted once its strip is surrendered). The result is
  CONDITIONAL where they differ. Before, it took the master-plan width whenever land was
  surrendered.
- **Thresholds (D12).**
  - The validator holds the 12 m pathway limit with the generator's height tolerance.
  - A main approach road wider than rule 8(m)'s 9 to 18 m is CONDITIONAL with the gap named,
    never a PASS.
  - Exact tests for 9 m (the strip), 18 to 21 m and 4,000 m².
- **No layout outside a study without its tot-lot.** The optimizer's guard and the export judge
  refuse a candidate that draws no tot-lot where the report asks one (`guard.tot_lot_missing`),
  whatever the validator could tell. A study still may, labelled STUDY and never exported.
- **Tests:** `tests/test_pipeline_consistency.py`.

## 2026-10-13: the club house's ceiling and the client's 3%; Table V row 4 open (audit, phase 3)

**The club house (D13).**
- **What the 2016 text says.** G.O.Ms.No.7 of 2016, Amendment 15, read from its text (pp.4-5):
  "upto 3% of the total built up area (or) 50,000 Sft. whichever is lower shall be planned and
  developed for common amenities ... Amenities block shall not be part of the residential
  blocks". It substituted the 2012 "minimum 3%".
- **The legal check is that text as written.** The validator's "Amenities (club house)" is:
  - required from 100 units (none drawn is a FAIL; under the old "up to" reading it passed);
  - no larger than the ceiling (FAIL above it, under every reading);
  - apart from the residential blocks.
  - It is no longer judged under `amenity_share`. The resolver carries that reading settled by
    the text (VERIFIED, LEGAL_RULE) and applies the cap.
- **The 3% the architect approved is the firm's program.** The brief's club house gains size
  `SHARE` with a `share` (`layout.APPROVED_CLUB_SHARE`, 0.03, the project's
  `club_house_share`). The program check holds the layout to it: NOT MET when short, never a legal
  FAIL.
- **The generator lays the brief's share, never above the ceiling** (`ground.club_ceiling_sqm`).
  - The 0.2 m² slack it kept above 3% is gone, since 3% is now also the ceiling.
  - A stated size larger than the ceiling is held to it.
- **Tests:** `tests/test_club_house_law.py`; the club tests of `test_validator_site_checks.py`,
  `test_validator_edges.py` and `test_validator_club_spacing.py` restated on the new check;
  `test_resolve.py` and `test_constraints.py`, which pinned the share as an open reading.

**Table V row 4 (D3).**
- **What the 2024 orders print.** G.O.Ms.No.143 and No.144 of 24.09.2024, Amendment 4 (read on
  G.O.144's page image, p.2), print row 4 as 30 | 30 | 30 | 25 | 25 | 25 where the 2012 text has
  30 | 20 | 20 | 20 | 20 | 20. Their operative words only add row 5.
- **Which edition is in force is the open reading `table_v_row_4`** (carried ALL).
  - Outside GHMC and CURE the resolver plans the stricter 30% (`ParkingRules.share_pct`,
    UNRESOLVED_INTERPRETATION); the 2024 figure is carried as `share_pct_elsewhere_2024`.
  - The validator judges Table V and visitors' parking under both editions there; a layout between
    them is CONDITIONAL on the reading.
  - The search plans the stricter. A project may select an edition.
  - No constant changed. GHMC and CURE sites, both client sites among them, are unaffected (30%
    either way).
- **Tests:** `tests/test_table_v_row_4.py`; `test_resolve.py` (an HMDA site outside CURE planned
  at 30%).
- **The service proposals baseline is re-pinned.** Its made-up HMDA site now plans parking at 30%,
  and the club house keeps no slack.
  - Maximum yield, balanced and robust are the same layouts.
  - The open-space option is the same 5 x S+3 under a new number.
  - One unshown proposal is a different 5 x S+8 (272 flats for 256).
  - The approval page is the same.

## 2026-10-13: a project's own inputs reach production (regulatory audit, phase 2)

**What changed.**
- **A project file carries any selected reading with its source.** The new `layout.readings`
  holds the reading, who chose it and when, and whether the architect confirmed it
  (USER_CONFIRMED) or it is a study assumption (ASSUMED_FOR_TEST).
  - `legal/site.resolve_project` passes them to `resolve` for the service and `siteplan
    envelope`. The source is appended beside the reading's legal ones, never in place of them.
  - The validator still judges every reading. A reading stated two ways is refused.
  - The service's `resolve_rules` lists the readings evaluated as the validator judges them
    (every one, unless settled), with each reading's sources.
  - The approval page shows each selection's source and says every reading is still judged.
- **The application's status and date are site inputs** (`SiteIn.application_status`,
  `application_date`, carried to `Jurisdiction`).
  - G.O.Ms.No.95 of 2026 (dated 21-03-2026) names no commencement date and no transitional
    clause. Where the application was received before that date, or nobody says when, the rules
    carry the 2012 high-rise line (18 m, read on G.O.168 p.3).
  - The validator then reports a block of 18 to 21 m CONDITIONAL ("High-rise line for this
    application"). It names the order's missing commencement date as the gap, or the application's
    unknown date as the missing fact.
  - A scheme not yet filed, or received on or after the date, is judged on 21 m alone.
  - Every report names the rule set it applied ("Rule set applied", INFO).
- **Fixed, a regression from phase 1:**
  - The open-space cross-check compared the generator's claimed open space with what counts
    under every reading, but the generator plans for the readings the study selected.
  - With the stilt reading selected (as Dhulapally's project selects it) every layout was refused
    for a blocking discrepancy, and the service proposed nothing.
  - The cross-check now compares under the selection (`open_space_study_counting_sqm`). The
    open-space check itself still judges every reading.
- **The search names a layout it refuses for a check failing under the selected readings.** It
  used to say "a blocking discrepancy".

**Tests.** `tests/test_project_inputs.py`: through `Service`, a project selecting `nbc_line`, the
stilt not counted and roads in the setback reaches the rules (sources kept), the search (layouts
proposed, built for the stilt left out), the validator and the stored reports. A client
requirement never moves the rules. The application date makes an 18 to 21 m block CONDITIONAL.
Also `tests/test_rules.py` (the 2012 line, quoted from its page).

## 2026-10-13: PASS, CONDITIONAL, FAIL and NOT_CHECKED (regulatory audit, phase 1; contracts 1.4)

**What changed.**
- **Every reading the law leaves open is evaluated.**
  - The validator evaluates every reading of a question the law leaves open, whatever a study
    selected. A selection by the architect or a profile no longer narrows validation.
  - Only a settled question is evaluated on its selected reading alone (`Interpretation.settled`:
    VERIFIED, or not a question of law, such as the engine's approach width).
  - The five checks that read the selection directly (`context.stilt_readings`, fire, open
    space, blocks, land checks) and the ledger's and layers' zones evaluate them too.
- **The open reading `stilt_raise`** (0.15 m covered parking or a 0.45 m plinth) is judged
  under the other raise wherever a block's height lies near a figure of the height or fire rules
  (`validator/raise_readings.py`).
- **UNVERIFIED is now CONDITIONAL** (`Status.UNVERIFIED` is kept as its alias). A CONDITIONAL
  check:
  - keeps each reading's result in `by_reading`;
  - names what it rests on in `rests_on`: an open reading with the result under each and the
    study's selection, a site fact, a gap in the rules, or a measurement;
  - gives its result under the study's selections in `selected_status`.
  The report adds `verdict.study`, and a 1.4 report refuses a CONDITIONAL that names nothing.
- **A violation under every reading stays FAIL.** A FAIL under the selection alone is
  CONDITIONAL with `selected_status` FAIL.
- **Generation and export still keep to the selection.** The optimizer's guard (`held_to`) and
  the service's export judge refuse on the study's verdict.
- **The 45 t loading** is a specification, NOT_CHECKED beside the verdict.
- **Reports list the scope register's requirements** under `not_checked`.
- **A report stored as 1.3** reads its UNVERIFIED as CONDITIONAL and dumps exactly as stored
  (only its results are respelt, never a layer's CONDITIONAL permit).
- **The qualifying open-space layer** is one layer per spacing reading where the ground differs,
  never their intersection.

**Why.** The audit found that a study's selection, such as the stilt not counted or the outer-edge
turning radius, made results PASS that fail under a reading the law has not ruled out (found on
the client studies; the details stay in the local audit, out of the repository).

**Characterization repinned** (`tests/test_validator_characterization.py`, the DIFFERENT list):
- on the made-up fixtures, the fire access of each block is CONDITIONAL on `fire_turning_radius`.
  The made-up 6.88 m lanes are short of the 7.76 m the centreline reading needs;
- the main approach is CONDITIONAL, because the made-up rules leave `approach_width` open;
- the 45 t loading is NOT_CHECKED;
- a case is compared with the checker under the checker's own reading of mixed-height spacing,
  now settled for that comparison (`tests/validator_cases.py`).

**Beyond the validator:**
- **The legacy checker shares the status.** Its UNVERIFIED reads CONDITIONAL too (`siteplan
  check`, the client baselines).
- **The pinned client baselines are read through that rename** (`client_baseline.pinned`). A
  rerun on 2026-10-13 differs from the pin by the rename alone, under both stilt readings.
- **The service's search picks differently in one place.** It breaks ties toward layouts that rest
  on fewer readings and checks. A layout now rests on more of them, so on the made-up land one
  proposal not shown moves (`-87` takes `-91`'s place). The four shown are the same.
  - `tests/test_service_proposals_baseline.py` is re-pinned.
  - The search's note no longer says the 45 t loading is UNVERIFIED.
  - The model-facing text speaks of CONDITIONAL items; the request fields are unchanged.
- **Judged under every reading, no layout on the made-up rectangle holds under them all.** Today's
  generator builds its "every reading" profile on the stilt's and circulation's readings only.
  Each layout still rests on the turning radius, the stilt's raise or the gap between blocks of
  different heights. `test_search_strategy` now settles those three to test the two it is about.

**Tests.**
- Normative: `tests/test_verdict_model.py`, with expected outcomes written out by hand.
- `tests/test_validator_readings.py`.
- Tests of other matters settle the turning radius on the outer edge (`validator_helpers.
  outer_edge`), or now assert CONDITIONAL with the selection's result.

## 2026-10-13: the register and its wording corrected (regulatory audit, phase 0; no verdict changes)

From the regulatory audit of 2026-10-13. No check, figure or verdict changes.
- **The validator's note on rule 15(a)(i)** quoted the 2012 text ("National Building Code -
  2005"). G.O.Ms.No.50 of 2019, Amendment-1, substituted it with NBC 2016, the reading the
  checks already used. It now quotes the text in force (`validator/fire.LOW_FIRE_RULE`). Test:
  `tests/test_validator_low_blocks_site.py`.
- **The inventory rows that claimed more than the code does are corrected:**
  - the stilt row: both readings are evaluated, and Stilt + N is the floor arrangement;
  - Table II's 100-unit road: not checked;
  - the long-block note: displayed by step 4, never applied;
  - the amenity cap: tested only with the reading open.
- **The rule 8(k) row** no longer says Dhulapally fits; that is a site question.
- **A new register of what is not checked** (`scope.py`), listed in the inventory. It covers:
  - the building services the firm designs by hand: STP and solid waste, services plan, EV
    charging, dual piping, digital infrastructure;
  - conditions of the permission: TDR loading above the 10th floor, the authority, the fire NOC;
  - checks that need a site fact: the approach road's surface, areas without high-rise, defence.
  Tests: `tests/test_scope.py`.
- **The number audit now names every open reading** the resolver carries:
  - five had no row: `tot_lot_surface`, `open_space_other_uses`, `green_strip_order`,
    `table_iv_road_width`, `visitor_parking_in_setback`;
  - the fire-turning row no longer calls its reading the conservative one (it is the lenient
    one);
  - the height datum, the ground at each block, is recorded as an engine assumption.
  Test: `test_every_reading_the_resolver_carries_has_a_row`.
- **Recording the architect's answer** (`resolve(..., answered=...)`) replaced a reading's last
  source, a legal clause for a reading selected by default. It now drops only the test profile's
  marker. Test: `test_an_answer_never_takes_the_place_of_a_legal_source`.

## 2026-10-13: floor plates sized to the land join the search, each PRELIMINARY

The architect asked for blocks shaped to land the firm's families do not fit, competing
everywhere rather than only where the families fail. `prototypes/compose.py` gains `PlateSpec`
and `compose_plate` (the families and single rows are now composed through it, byte for byte
the same: every prototype of both example libraries was dumped before and after);
`prototypes/plates.py` composes, for the brief's own mix, single rows of 3, 4, 6 and 8 flats
(enclosed corridor and open gallery, kept apart, each with its own schedule) and double-loaded
plates of 2 to 6 flats a side, keeps those that stand whole in a region of a band's land (the
envelope's width profiles, the net plot before its setbacks left out; width and length only
screen, the rectangle is tested against the region's shape), and gives the search a diverse
shortlist of 8 beside the families (`kit_for`). Each flat type keeps its library saleable; a
plate's area schedule (gross, flats, cores, corridor or gallery, effective loading) says when its
geometry needs more common floor than the firm's loading pays for, and never raises the saleable.
Every plate is PRELIMINARY: its prototype's source says what is assumed (derived flat frontages,
core and corridor sizes, and egress, lifts, accessibility, ventilation and gallery counting not
checked); the validator adds an INFO program finding, "Floor plate: PRELIMINARY", to a layout
that uses one (no legal check changes); the approval page and `list_prototypes` (which now takes
the survey) name each plate with its schedule. The search's main column depth is still set by
the families alone: a plate of that depth joins their columns, another depth competes through the
mixed-depth and fringe configurations.

Evidence, the production service on made-up land with the example library, families alone
against families and plates: an L with a 34 m arm, where no family fits, 0 layouts against 5
(the most 85 flats, 113,650 sft, the three shown program MET); a 40 m wide slanted strip, 2
against 8 (the same 96-flat maximum, and program-MET options of 64 and 48 flats from single rows
where the families' are PARTLY_MET); an irregular pentagon, the same 360-flat maximum yield, plates
in 8 of 15 proposals, the balanced option 300 flats MET where it was 260 PARTLY_MET, the
open-space option 158 flats where it was 186 and the robust one PARTLY_MET where it was MET. A
first shortlist that also tried each flat type alone lost the pentagon's 360-flat layout (a
3BHK-only plate sells the most a floor, won the columns and missed the mix), so plates are
composed for the brief's mix only; and a plate that is one of the library's own blocks (the same
size, cores and flats a floor) is not offered, so the shortlist holds only new blocks. On the two
real sites (DEBUG runs, figures kept out of git) the plates were screened and offered but the
search showed no layout built from one: the maximum yield was the same layout, while the
secondary alternatives moved with the larger set the search judges (one balanced option fewer
flats, one open-space option fewer flats). The service's own baseline on made-up land moves the
same way (`tests/test_service_proposals_baseline.py`, re-pinned: maximum yield and robust the same
layouts, the balanced option more flats, the open-space option a 120-flat layout of plates).
Tests (normative): `tests/test_plates.py`, `tests/test_service_plates.py`; the service's tests of
the firm's longest block (`tests/test_service_standards.py`) now hold the families and the plates
alike to it.

## 2026-10-13: the architect's answers are recorded as his; a fire-band test of access

- `resolve(..., answered={reading: who})` records a selected reading as the architect's answer
  (USER_CONFIRMED, his words as its source) where a selection alone is a test's
  (ASSUMED_FOR_TEST). An answer to a reading left open is refused.
- `opens_onto_road` may also carry `fire_band`, offered only when a project selects it
  (`resolved_rules.OPTIONAL_READINGS`; the contract takes an optional answer only then, so every
  stored contract and every other site reads as before). The architect: no rule asks a length of
  facade on a road; a block over 12 m is served by the internal roads (G.O.168 8(l), 8(m)) and,
  for NBC, "the approach to the building and open spaces on all its sides shall be not less than
  6 m" (Part 3 4.6(c)): under `fire_band` a block is served when its fire band, the rules' clear
  width (`fire.clear_width_m`) drawn round it, meets a road along at least that width
  (`validator.roads.opens_onto`).
- Dhulapally's runs take his answers of 2026-10-13: roads may run in the setback
  (`circulation_in_setback: allowed`; the strip planted, no ramp in the front setback, no parking
  in the fire band, all checked as before), NBC's own 15 m line for fire access below 21 m
  (`nbc_fire_height: nbc_line`), and `opens_onto_road: fire_band`.

Tests (normative): `tests/test_architects_answers.py`.

## 2026-10-12: the full search lays no tot-lot in front of the gate

The architect's rule (2026-10-11, kept by `siteplan steps` since): nothing in front of the gate,
its way straight in. The full search's open space had no such rule, and on Dhulapally's first
proposal laid 29.6 m² of a pocket there. The stretch of the plot line the gate opens, swept
straight in across the plot (`layout.gate_way_in`), is now taken out of the room the pockets may
use. A design rule of the architect's, not an order's; the validator is unchanged. Tests
(normative): `tests/test_gate_way.py`. Characterization re-pinned: in
`tests/test_search_road_ground.py` two proposals on each made-up L-plot had pockets in front of
the gate (shown by switching `gate_way_in` off, which restores the old pins exactly); they give
way to another three-street layout (`L_THREE_GATE`) and the proposals come in another order. On
the main L-plot the two it replaced had kept the way clear already: the way in cuts the open land
the pockets are chosen from, which moves the choice; on the slim one they had 0.20 m² in it. In
`tests/test_service_proposals_baseline.py` the open-space option shown, `full-not_counted-ALL-67`
(330 flats), laid 38.28 m² of a pocket in front of the gate; it is `-77` (306 flats, 4,477 m² of
tot-lot, none there), maximum yield, balanced and robust the same layouts. Checked on both L-plots
and the service's land with the independent validator: every proposal has its one gate met by the
approach road, no pocket in its way in, and no legal FAIL (two proposals on the slim L-plot and two
on the service's land miss the unit mix, as before). New tests: `tests/test_gate_way.py` (a slanted
side, the way stopping at the plot line, both L-plots) and the baseline's
`test_no_layout_proposed_or_shown_lays_open_space_in_front_of_the_gate`.

## 2026-10-12: a project may take G.O.168's own 2012 wording of the planting strip

The architect: his seven files carry G.O.168's 2012 text of rule 7(a)(viii), where every high-rise
keeps a 2 m planting strip all round whatever its setback, not G.O.Ms.No.7 of 2016's, where only a
setback of 9 m and above does. A new open reading, `green_strip_order` (`go7_2016` the engine's
default, `go168_2012`), carried only when a project selects it, so no other site's rules, digests
or pinned output move. Selected, the green strip's threshold is 0 m (clause
`rules.GREEN_STRIP_2012_CLAUSE`) and every high-rise band asks the strip; the search lays it and
the validator checks it from the same figure. Dhulapally does not select it: the architect
(2026-10-13) points to G.O.Ms.No.50 of 2019, which keeps "all other amendments covered in
G.O.Ms.No.7 MA dt 05.01.2016 ... as it is", so the 2016 threshold stands. Tests (normative):
`tests/test_green_strip_order.py`.

## 2026-10-12: the search raises each block to the tallest its own place allows

The architect, on the Dhulapally study: room in height, not land; "taller in the middle, lower at
the edges", for every site. After the repair pass the search tries each profile's most valuable
layouts again with every block raised, a floor class at a time, while the class it rises to keeps
its own setback from the plot line, the planted strip its band asks (only where the land has it all
round), the setback zone the ring was laid for (where the profile keeps roads out of setbacks),
the taller one's gap to every neighbour, and its class of building (a pathway-served block stays
within 12 m); a block at a column's end that the gap to its neighbour in the column holds down is
moved along the column, on the land the columns may stand on, and where that layout does not lay
out (a tender's turn at the ring's corner, say) the raise is tried in place
(`optimizer/search/raising.py`, `FullSearchStrategy._raise`). What lays out is laid out again (the
club house, cellars and ramp for the flats it now holds) and judged by the validator like any other
layout, beside the one it came from. Tests (normative): `tests/test_search_raising.py`.

On Dhulapally's study the probe's in-place raises were found to need the 2 m planted strip (from
a 9 m setback, G.O.Ms.No.7 of 2016), which a layout laid for Stilt + 8 does not have all round;
and every tower already touched the ring road and its streets, so no column could spread for 10 m
gaps.

## 2026-10-12: a study mode (buildings and the club house only)

The architect asked for a study of Dhulapally with no tot-lot, open space or facility, so the land
the buildings and the one club house leave shows where the 10% tot-lot can go later.
`Objectives.study` (default off, left out of a stored brief when off, so no digest moves):

- the search lays no open space and no facility and keeps no room for them
  (`quantities`: the open space to lay is 0; `Run.reserve_target_sqm` keeps no facility room;
  `_furnish` lays none);
- the validator is unchanged and still fails the missing tot-lot (G.O.168 rule 7(a)(vii));
- the optimizer alone, asked for a study, does not refuse a layout for that one check
  (`guard.held_to`, `why_refused(..., study=True)`, the strategy's own judging); every other
  FAIL and every blocking cross-check refuses it as before, and the service's export never
  passes `study`;
- every result carries the caveat STUDY, NOT A LEGAL LAYOUT (`strategy.STUDY_CAVEAT`).

Nothing changes when the flag is off. Tests (normative): `tests/test_study_mode.py`.

## 2026-10-12: step 4 keeps the whole setback at a corner; towers labelled with their height

- **The firm's amenity file is a catalogue, not a program.** A project lays a facility only
  when the file marks it REQUIRED or the project asks for it by name
  (`LayoutRequest.amenities_wanted`, `adapters.legacy_site._wanted`); a name the file does not
  have is refused. Before, every item went into the brief and, with no class stated, was read as
  PREFERRED, so the search laid all it had room for: on Dhulapally the researched Hyderabad list
  (pool, kids' pool, badminton, tennis, cricket net, play, yoga deck, seniors' seating, security
  cabin) filled the north arm. No rule makes any of them mandatory; the club house (rule
  15(a)(x)) and the tot-lot (7(a)(vii)) are laid as before. Tests (normative):
  `test_adapters.py::test_the_firms_amenity_file_is_a_catalogue_a_project_lays_only_what_it_asks_for`,
  and the library-as-stated test now asks for every item by name. The client validator tests
  that compare with today's (legacy) layout, which lays every item it is given, now ask for each
  by name too (`test_validator_client_run.py`, `test_validator_client_suchitra.py`), so the
  brief and the layout name the same facilities as before.

- **The land left never comes nearer a side than its setback** (the architect approved the fix,
  2026-10-12). Step 4 drew each side's setback band as the side widened, whose round ends are
  chords inside the circle, so at an inside corner the land left came up to 12 mm inside a 10 m
  setback (found in CAD: 9.988 m). Each corner of a side is now also covered by a polygon drawn
  round the circle, its edges touching it (`steps/setbacks._reach`); a straight side keeps
  exactly its setback. Dhulapally's step 4 (debug): the land left 11,871.4036 m² where it was
  11,871.7256 (0.32 m² less), every side's nearest approach now exactly 10.000000 m. The search's
  own envelope (`legal/bands.py`) cuts with mitred offsets, which never come nearer, and is
  unchanged. Test (normative): `test_steps.py::test_the_land_left_never_comes_nearer_a_side_than_its_setback_even_at_a_corner`.
- **A tower in CAD says its height** ("T1 · Stilt + 9 · 12 flats a floor"; the text in the
  drawing on three lines): the flats a floor alone read like a floor count.
  `render.TowerShape.floors_above_stilt` carries it. Test (normative):
  `test_cad.py::test_a_tower_is_labelled_with_its_height_and_its_flats_a_floor`.
- **A hole a hair inside its outer edge reaches CAD as the C it is** (`cad/scene.parts`): a fire
  lane broken at one place came as a polygon whose hole ran 1e-12 m inside its edge, closer than
  FreeCAD tells apart, so FreeCAD cut it into faces and the read-back saw one. Test (normative):
  `test_cad.py::test_a_hole_a_hair_inside_its_outer_edge_reaches_cad_as_the_c_it_is`.

## 2026-10-12: a flat is its share of the floor, and cores are compact

The architect (2026-10-12): treat a flat's saleable area as the flat and its share of the
corridors, lifts and stairs times the loading. The firm's statement agrees: its 474,912 sft of
tower floor times 1.22 is its 579,392 sft saleable to the foot. The composer had taken a flat's
width x depth (the saleable less the loading) as the flat alone and added the cores and corridor
to it, each core a 7.5 m slice across the block's whole depth, so on the firm's Dhulapally debug
run a flat used 131.8 m² of floor where it sells on 91.4: the common area was counted twice.

- `FlatLibrary.area_basis` (default PLATE_SHARE): a flat's width x depth is its share of the
  floor; the block is as long as the shares over its depth and the cores and corridor are laid
  out of it, each flat's own area its share of what they leave, so a flat of a type is the same
  size whether or not it wraps a core. FLAT_ONLY is the old reading, kept for a library that
  asks for it.
- `FlatLibrary.core_depth_m` (default 8 m, `COMPACT_CORE_DEPTH_M`): a core 7.5 m along the
  corridor and 8 m across it, the ground behind it going to the flats either side; null spans
  the whole depth, as before. 7.5 x 8 m leaves 44 m² beside the corridor, within the 36-56 m²
  built of the six cores measured on the firm's Suchitra typical floor. An
  ENGINE_DESIGN_ASSUMPTION in `constraints.py`, for the firm's own core drawings to settle.
- A block shorter than it is deep is drawn a quarter turned, its long side along x as every
  prototype's frame asks (the firm's four-flat block from its Suchitra flats had been 23.2 x
  25.8 m and failed the kit's own frame check).

- Frontages are rounded to the micrometre and every block is an even number of micrometres long
  (`compose._even_length`): a narrowed flat's frontage falls off the grid, and a block an odd
  number of micrometres long could not be centred on it, so its footprint ran a micrometre
  longer than its `length_m`; the search, spacing blocks end to end by `length_m`, left 7.9999995
  m where 8 m was asked and the validator failed four made-up layouts (rightly: the guard kept
  them out). None fails now.
- A single-row family (`PrototypeFamily.SINGLE_ROW`, `compose.compose_single_rows`, 3 and 4 flats
  a floor): one row of the library's flats beside its corridor, one core in line, each flat as
  large as its type in the double-loaded blocks; ENGINE-COMPOSED and PRELIMINARY in its source.
  It is composed only when a caller asks (the service's kit is unchanged). The contract gains the
  family value; every stored contract reads as before, so the version stays 1.3.
- The search's note on a narrow part where no block fits said "17.8 m, less than ... 13.96 m";
  wide enough but too short now says so (`strategy.why_none_fits`).

No rule, road width, separation or validator check changes; the legacy towers (towers.py) read
neither switch. Characterization moved with it: `test_service_proposals_baseline.py` (the
made-up land's maximum yield 4 x S+10, 480 flats and 651,200 sft, where it was 3 x S+10, 360 and
488,400; no facility laid, the brief asking for none; with both this and the amenity change
switched off the notes, proposals, four shown and answer are as before and only the digests
move, a flat's outline written from another first corner). Normative tests whose numbers move
with the shorter blocks: `test_service_standards.py` (of the example kit, three blocks are within
the 45 m longest block where two were). Tests (normative): `tests/test_prototypes_plate.py`; in `test_prototypes.py` the
full-depth and legacy-equivalence tests now compose the old way explicitly
(`_old_way`), and `examples/prototypes.example.json` is regenerated. The search's own tests keep
their made-up blocks as pinned (`optimizer_support.LIBRARY` declares FLAT_ONLY and a full-depth
core): they test the search on given blocks, not the composer.

## 2026-10-12: the pinned entrance, the club house in two places, a wide street's own width

Three changes to the full search, asked for by the architect after the Dhulapally debug layouts
(2026-10-12). No rule, road width, separation or validator check changes.

- **A pinned entrance stays put.** `Access.gate` (`SiteIn.gate_m` in a project) pins the gate to
  a stretch of the net plot's edge; `legal.frontage.access_zones` then gives that stretch alone,
  so no layout moves the entrance. Evidence: on Dhulapally the search slid the gate 48 to 57 m
  along a 213 m west side, away from the survey's GATE on the R6 road; pinned, every layout's gate
  lies within 1 m of it. A site model without a gate is stored, and digested, as before (the field
  is left out). Tests (normative): `tests/test_entrance_pin.py`, including the full search on a
  made-up plot keeping every gate on the pinned 14 m (left to itself it takes the middle).
- **The club house is tried in two places** (`layout._furnish_where_best`): nearest the gate, as
  before, and nearest the far corner of the open ground (an arm of the plot, say); the furnishing
  leaving the more usable open space (the objective's own measure) is kept, then the fewer cellar
  levels, the gate's between equals. One club house, sized by the same 3% rule. Evidence: on
  Dhulapally's debug run the BALANCED layout's club house now stands in the north arm. This moves
  one of the L-plot's eight proposals in `test_search_road_ground.py` (characterization):
  `full-not_counted-ALL-30` (ring, a street, the approach and a pathway) gives way to
  `full-not_counted-ALL-16` (the same without the pathway, `L_ONE`); proven to be this change
  alone by switching the second place off, which restores the old pin. It also moves the
  service's made-up baseline (`test_service_proposals_baseline.py`, characterization): the same
  four shown in flats and saleable area (maximum yield 360 flats and 488,400 sft, now its twin
  `-85`; balanced the same 4 x S+10, renumbered `-91`; open space and robust unchanged), four
  lower proposals others, several with the club house at the far end; with the second place
  switched off, the proposals, the four shown and the answer are as before. Tests (normative):
  `tests/test_club_positions.py`.
- **A street paved wider than the rule's declares its own width** (`build._declared_m`): a
  corridor two columns share is paved across, and declaring the rule's 9 m under-reported it.
  The validator still measures the pavement and takes the lesser of measured and declared, so no
  verdict can loosen. In the service's baseline this alone moves the digests of the two shown
  layouts with a wide shared street. Tests (normative): `tests/test_street_width.py`.

## 2026-10-11: `siteplan steps` step 5 (the tot-lot)

Stage 3 of the stage-wise build: step 5 (`steps/tot_lot.py`, `steps/buildings.py`), the architect's way (2026-10-12): the buildings first and the tot-lot last, shown together. A height map down to Stilt + 7; the firm's blocks (its kit and a slim block of one row of its flats) in straight rows along each arm's longest edge, round a loop or a spine road; the gate (`steps/gate.py`) marked on every step's picture; the tot-lot (10% of the whole plot for a high-rise site or a Group Development Scheme, rules 7(a)(vii) and 8(g); 5% above 750 m², 5(f)(vi)) in the blocks' leftovers, never in a gap between blocks, a setback, a fire lane, a road or in front of the gate; blocks shortened or dropped, flats counted, when it would fall short; whole options side by side for the architect to choose one. No club house in this stage. `Inputs` carries the workspace, so a step can read the firm's flat library. No layout, check or verdict changes: the search, the validator and the legacy path read none of it.

rules.py gains `OPEN_SPACE_2012_CLAUSE`, `GROUP_SCHEME_OPEN_SPACE_CLAUSE` and
`BLOCK_GAP_NOT_OPEN_SPACE_CLAUSE` and `AMENITY_2012_CLAUSE` (the 2012 wording, pp.13-15 and 21). The rules' fingerprint moves with
them, so the service's made-up baseline is re-pinned: the same notes, proposals, shown four,
approval page and answer; only the digests move. Rule 5(f)(vi) (5% below high-rise) is now
applied by the steps (inventory).

Tests (normative): `tests/test_steps.py` (the 10%, 5% or none; the height map stepping down to the
lowest block; the firm's settings; the slim block; an arm no building fits taking the club house
and keeping off the edge; every corner on even land; a sharp corner cut straight across and a
pocket stopping at its side's end; a water buffer holding the tot-lot; the stops; the picture;
step 5 in the five-questions, carried and seven-files guards).

## 2026-10-11: `siteplan steps` steps 2 and 4 (the height the main road allows; setbacks)

Stage 2 of the stage-wise build: step 2 (`steps/main_road_height.py`) reads the height the main
road allows from Table IV (Table III below it) and counts the floors in the shortest storey the
architect's seven files allow (NBC's 2.75 m room and a 0.15 m slab, 2.9 m), the stilt separate and
not counted (the architect's rule of 2026-10-11); a road is a dead end only when the answers name
it one (his rule, same day). Step 4 (`steps/setbacks.py`) keeps Table IV's column 4 round the net
plot (below high-rise Table III's front towards the bigger road and column 10 elsewhere), the front towards a road the higher of
that and the Building Line, the 2012 green strip inside, the water's buffer laid over, and shows
the lower heights, G.O.50's long-block note and rule 16(e)'s concession, none taken. No layout,
check or verdict changes: the search, the validator and the legacy path read none of it.

rules.py gains `NO_OPENING_*`, `LONG_BLOCK_*` and `long_block_open_space_m` (G.O.50's two notes
under Table IV, as the page of the architect's file prints them; G.O.Ms.No.65 of 2019, outside
the seven files, deleted the second and the engine's other parts still follow it),
`GREEN_STRIP_2012_CLAUSE`, `TABLE_III_2012_CLAUSE`, `STILT_MIN_HEIGHT_2012_CLAUSE`,
`ROOM_HEIGHT_MIN_M` and `ROOM_HEIGHT_CLAUSE`. The rules' fingerprint moves with them, so the
service's made-up baseline (`tests/test_service_proposals_baseline.py`) is re-pinned: the same
notes, proposals, shown four, approval page and answer; only the digests move. Rule 5(f)(iii)
(the front towards the bigger road) is now applied by the steps (inventory).

Tests (normative): `tests/test_steps.py` (step 2: the 60 ft road's stilt + 10, Table III below
Table IV, a drawn or unchecked width asked, a dead end only when named, the stop, the side view;
step 4: Table IV all round with the green strip and the fire lane, Table III's front and column
10, the water laid over and not added, the concession shown, the stop, a power line asked; the
carried guard and the seven-files check now hold steps 2 to 4).

## 2026-10-10: `siteplan steps`, the architect's steps 1 and 3 for any project

Stage 1 of the stage-wise build: step 1 (copy the survey) and step 3 (road widening) move out of
one site's scripts into the engine (`steps/`), each with a report that answers five questions and
lists everything the engine decided by itself. No layout, check or verdict changes: the search,
the validator and the legacy path read none of it. rules.py gains the values the steps show (the
12 m site-plan band, NBC 2016 Part 2 12.2.3(e); the splay table, G.O.168 5(f)(xiv); rule 16(a)-(f)
and 17(b)(i) and the water buffer, rule 3(a)(ii), as the 2012 order words them), and `roads.Road` keeps the edge lines a road was
measured on and the ground between them (new fields with defaults; nothing read before changes).

The rules' fingerprint (`legal.resolve.rules_digest`, every value in rules.py) moves with the new
values, so every ResolvedRules carries a new `rules_digest` and every candidate a new `rules_ref`
and `envelope_ref`. Characterization re-pinned: the service's made-up baseline
(`tests/test_service_proposals_baseline.py`): the same notes, the same 15 proposals, the same four
shown and the same approval page; the proposals' digest and the four shown digests move, and the
model's answer is unchanged.

Tests (normative): `tests/test_steps.py` (25 tests on made-up land: the survey copy, where each
road meets the plot, the access road, water named and not drawn, the strip placed or judged by its
side, splays, the stopped reports, broken outlines, the blind guard, the command).

## 2026-10-10: a height starts at the ground, and the storeys start above it

Rule 2(e) measures a height from the abutting road, or on undulated terrain from the average of
the corresponding ground level, and NBC 2016 Part 2 2.6 from "the average level of the ground
around and contiguous to the building ... to the terrace of last livable floor". The engine
measured from the stilt floor. NBC 2016 Part 3 12.1 (read on the page image of p.43), which rule
15(a)(vi) brings to "all buildings" as a requirement of parts of a building, raises the lowest
floor above the ground: a plinth of 450 mm (12.1.1), covered parking 150 mm (12.1.2). So storeys
that exactly reached a limit were over it: a 3 m stilt and nine 3 m floors are 30.15 m from the
ground, not 30 m. Found in the Dhulapally final check under the new approach (2026-10-10).

- `rules.COVERED_PARKING_RAISE_M` (0.15 m) and `rules.PLINTH_MIN_M` (0.45 m), each with its
  clause. A parking stilt is taken as covered parking: 12.1.2's heading names covered parking and
  its sentence only courtyards. The open reading `stilt_raise` carries it, the plinth being the
  stricter reading `resolve`'s selections may take; it reaches the optimizer and the validator
  only, the floors calculator and the legacy request reading the default from rules.py, and a
  project file does not carry it yet. Under ALL the larger raise is taken, which holds under both:
  a count that holds only at 0.15 m is held back, not UNVERIFIED. A block with no stilt and the
  club house stand on the plinth.
- The raise is in every height with the stilt in it: the physical height (NBC's: the 30 m dead
  end, the 15 m line, rule 8(l)'s 12 m) and the rule height under the counted reading. Where the
  stilt is left out (rule 5(c) for Table III; the not_counted reading of Table IV) the whole stilt
  floor is, its raise with it (our reading), so Table III's rows and the not_counted reading are
  as they were.
- `HeightRules.lowest_floor_raise_m` is the one lookup: the optimizer (`floors.assess_floor_count`,
  the open-space pockets' setbacks in `search.build`, the club house's band in `search.layout`)
  and the validator (`measure.TowerGeometry`, `clubhouse._club_height_m`). The floors calculator
  (`max_floors`: `siteplan floors`, the `max_floors` tool, intake's "max", the acceptance report's
  limit line) and the legacy request (`LayoutRequest.height_m`, so the legacy search's legality and
  its setback rows) and the acceptance report's heights read rules.py. Not yet the legacy checker
  (`siteplan check`, the cases): it measures a building as its file gives it, a sanctioned plan's
  or a project's stilt + floors, without the raise (a project's stilt + 8 of 3 m storeys checks
  at 27 m and 9 m where the rest of the engine asks 27.15 m and 10 m).
- Contracts extended, not bumped: `HeightRules` gains `stilt_raise_m`, `plinth_m` and
  `raise_interpretation`, optional and left out of the dump when absent, and `stilt_raise` is not a
  reading the contract requires. Every stored 1.3 contract reads, keeps its digest, and is judged
  as it was proposed: no raise. The hand-built contract fixtures are such contracts, so the
  validator's and optimizer's tests written on them keep their heights; `with_raise` gives them
  the raise where a test is about it.
- With the engine's default 3 m storeys, with the stilt counted, every count is 0.15 m over a
  Table IV edge: one floor fewer at each road limit (a 60 ft road: stilt + 8, was 9; a 40 ft road:
  6, was 7; a dead end: 8, was 9) and the next row's setback for each count (stilt + 7 is 24.15 m:
  9 m, was 8). Without the stilt counted only NBC's physical height moves (stilt + 10 is 33.15 m).
  Storeys a little under 3 m keep the old figures: 2.9 m storeys and a 2.9 m stilt give stilt + 9
  or 10 at 30 m. Rule 8(l)'s pathway now reaches a stilt + 3 of 3 m storeys only if it stays 12 m
  or under (12.15 m does not).
- Levels are not modelled: on a slope or over a raised cellar deck the stilt floor can stand
  higher above the average ground than the minimum.

Tests (normative): `tests/test_heights_from_the_ground.py` (new: what the raise changes in the
optimizer, the validator, a block with no stilt, the exact edges on a 2.85 m stilt, the legacy
request, the validator's dead end at 30 m, rule 8(l)'s pathway up to 12 m, the club house's
height in the optimizer and the validator alike; rules stored without it unchanged),
`tests/test_acceptance.py` (the report's legal height reads 27.15 m), `tests/test_rules.py` (the values, their clauses,
rule 15(a)(vi) quoted from p.20 of the order), `tests/test_resolve.py` (the reading, a stricter
selection, a stored contract that reads with no raise and dumps as stored), and re-pinned:
`tests/test_max_floors.py`, `tests/test_heights.py`, `tests/test_mcp_server.py`,
`tests/test_client_fixtures.py` (the floor counts), `tests/test_optimizer_legacy.py` (the
generator's legal findings agree with floors.py on rules with the raise),
`tests/test_review_fixes.py` (a height's label reads 27.15 m). The made-up firms of
`tests/search_support.py`, `tests/test_layout.py` and the jagged access side in
`tests/test_access.py` take a 2.85 m stilt, so their stilt floor tops out 3 m up and their
heights are as before.

Characterization re-pinned:
- `tests/test_intake.py`: "max" on a 60 ft road at 3 m storeys is stilt + 8.
- `tests/test_acceptance.py`: the calculator's limit is stilt + 8, the first height tried 9 (30.15 m,
  past the road's 30 m), and with the stilt left out the physical height is the rule height and
  3.15 m.
- `tests/test_service_proposals_baseline.py`: the same maximum-yield, balanced and open-space
  layouts (the not_counted profiles); the robust one, holding under every reading, is S+7, S+7,
  S+3 (204 flats, 276,760 sft) where it was 3 x S+7; 119 laid out where 116 were.
- `tests/test_optimizer_characterization.py`: the generator's own three massings are compared at
  stilt + 8, its tallest now (stilt + 9 is 30.15 m); the points land on the same three.
- `tests/test_validator_client_run.py`, `tests/test_validator_client_suchitra.py`,
  `tests/test_optimizer_client_baseline.py` (client data): the validator judges the real options
  on rules with the raise. The generator plans for one reading of the stilt and the validator
  weighs both, and with 3 m storeys the two readings now land in different Table IV rows, so the
  validator is held to today's checker under the reading the generator planned for (its verdict
  by reading), and which checks part from it only under the other reading, and how, is pinned
  (`ON_THE_OTHER_READING`). On the runs planned with the stilt left out, the S+8 options claim open space that
  lies in the 10 m setback the counted reading asks (27.15 m): the validator blocks that
  cross-check, and those options' verdict is FAIL (`STRICTER_CROSS_CHECKS`, which each test holds
  to what really blocks). Suchitra's seam test puts its tower back on 7 floors, exactly 21 m
  without the stilt, since its options are now S+6. The LEGACY run starts at stilt + 8 (stilt
  counted) or 10.
- The Dhulapally debug baseline (`tests/client_baseline.py`, client data, gitignored): with the
  stilt counted the heights tried run 9 (30.15 m, FAIL on the road) down to 6 and the best layouts
  are 3 x S+6 (288, 276 and 252 flats; 344,100 sft saleable at best) where they were S+7 (336,
  308, 280 flats; 401,450 sft), every count taking the next Table IV row's setback; with the stilt
  left out nothing moves. Rebuild it where it is kept: `uv run python tests/client_baseline.py`.

## 2026-10-07: C4-16, the architect's soft preferences scored

The brief has carried soft preferences all along (`Objectives.soft_preferences`: a kind, its
parameters and a weight), and nothing read them: a wish given was dropped unsaid. The objective now
scores them (`optimizer/preferences.py`) as an eighth axis, preference (`Priority.PREFERENCE`, the
enum extended, contracts not bumped): the weighted mean of how well a layout meets each preference
the engine understands, from 0 to 1, and 1 for every layout when the brief gives none, so that
then nothing moves. The kinds: orientation (`axis_deg`: the blocks' long sides along a direction),
max_towers (`towers`), keep_away_from_road (`m`: the share of blocks that far from the entrances)
and club_near_entrance (`m`). A preference is never a rule: nothing fails for one, and the
validator does not read them. One of another kind, or with a parameter missing or not a number, is
not weighed, and the search's notes name it, as they name the ones weighed.

Tests: `tests/test_objective_preferences.py` (normative: no preference scores every layout 1;
each kind's score; a kind not understood is named and not weighed, the others still are; between
two layouts equal on every other axis the balanced option follows an orientation preference; the
search's notes name what was weighed and what was not). Characterization re-pinned: the service's
made-up baseline (its brief gives no preference: the same proposals, the same four shown and the
same answer; the shown digests move, each alternative's scores carrying the number).

- Dhulapally, Run B prime's request (the C4 benchmark, 16-preferences): the brief gives none, and
  the same layouts are judged, proposed and shown. Tried once with "at most four blocks" (an
  experiment, not a benchmark): weighed and named in the notes; at its weight of 1, and with the
  preference's priority at 4, the balanced option stays the five-block 383,302 sft layout (a 20%
  shortfall on one axis of eight); with the priority at 20 it is a three-block layout of 388,908
  sft. A soft preference nudges; the brief's priority says how hard.

## 2026-10-07: C4-15, the turn at every road junction

The validator swept the fire tender's turns at every corner of a block held to NBC 4.6 and at
every bend of the loop road, never where a road joins another: the approach, a street or a link
meeting the loop. A new check, "Fire access: turns at the road junctions" (`fire`,
`turning.junction_turns`), sweeps every corner of the fire roads (loop, perimeter lane, street,
approach, cul-de-sac; not a pathway or a driveway) that is no bend of the loop, under each reading
of the 9 m as the loop check does: FAIL where something stands in a turn under every reading,
UNVERIFIED under some. Three kinds of corner are no junction and are not swept: one on the plot's
boundary (the gate, where the tender turns on the street outside), one that doubles back (the tip
of a slit the drawing leaves) and one either side of which is shorter than the lane is wide (a
jog, not a wall a tender drives along). The generator keeps its program (club house, ramp,
facilities, tot-lots, bays) off every reading's junction turns, refuses a layout a block or the
planted strip stands in one of under every reading, and the approach planner passes over a gate
position whose turn into the ring is blocked so for the next (`network.find_entrance`).

Measured first without the three exclusions, 13 of Dhulapally's 23 judged layouts had a junction
turn blocked under the outer-edge reading and all 23 under the centreline one, and the generator
refused 96 tries; every one of those came from the gate's corners, slit tips the union of the road
pieces leaves, or a one-metre jog where an approach meets the loop. With them, no judged
Dhulapally layout has a junction turn blocked and the search lays out the same layouts.

Tests: `tests/test_junction_turns.py` (normative: on the made-up rectangle the turns at each end of
its street are swept and no other, not at a loop bend, the gate or the approach's jog; a kiosk on
the loop where the street joins it fails the junction check while the loop check still passes;
the tip of a 15 m slit is swept by neither side; the approach planner takes the next gate when a
block stands where the shortest approach turns into the ring). Characterization re-pinned: the
service's made-up baseline (the same proposals, the same four shown and the same answer; two
proposals not shown lay the same facilities off a junction turn).

- Dhulapally, Run B prime's request (the C4 benchmark, 15-junctions): the same 23 layouts judged,
  the same proposals and the same four shown; no junction turn blocked; one legal FAIL (the
  validator's 9.00 m gap read as 8.9999989), unchanged; runtime 107 s to 108 s.

## 2026-10-07: C4-14, an approach that crosses the open-space reserve when it must

A configuration may keep one end of the plot for the open space (`Config.reserve`), and the
approach was kept off that end as off a block. Where the end lay across every way in from the
access road, no straight approach reached the ring and the configuration was lost: on the made-up
plots 4 of 59 tries on the rectangle, 4 of 78 on the L-plot and 33 of 141 on the slim L-plot, every
one of them this case (drawn: the reserve ran the whole width of the access side). Now the approach
keeps off the reserve when it can and, when that end lies across every way in, crosses it, a road
through the park, the open space then taken from the ground round it (`layout.lay_out`); blocks,
water, the clusters and the other rings stay ground no approach crosses. No made-up plot loses a
configuration to the approach now. The planner's straight approach found a way in every other try
on every plot tested, Dhulapally included, so no bent or slanted approach was built.

Tests: `tests/test_search_network.py` (normative: on the L-plot, blocks turned a quarter and the
south end kept for the open space; kept off it no approach reaches the ring, and the configuration
now lays out with its approach through the reserve; the same end kept with the blocks upright, the
approach keeps off it). Characterization re-pinned: the service's made-up baseline (the
configurations recovered are laid out among the others, so those after them are numbered on:
balanced is the same 4 x S+10 as `-90`; maximum yield `-86` is now another 3 x S+10 of the same
saleable area that leaves less ground to no use, 985 m² of its open space usable where 570; the
open-space and robust ones the same); the road ground (eight proposals with their approach through
the park, four road sets new).

- Dhulapally, Run B prime's request (the C4 benchmark, 14-approach): unchanged, the same 23 layouts
  judged, the same proposals and the same four shown; the approach found a way in every try.

## 2026-10-07: C4-13, a cellar dug only as far as its need

The full search's parking plan stacked whole cellar levels, each the whole plot under the rule
13(c)(x) setback, until the need was met; one Dhulapally level holds about 15,000 m² of parking, so
nearly every layout dug one whole level and the parking laid out ran a median 30% over Table V's
need (the GHMC column, the conservative test mode), up to 106%. With no parking margin asked
(`parking_extra_fraction`, 0), all of that was the last level's rounding. Now (`parking_plan`):

- The fewest levels are found as before, on the whole outline. Then the outline is a rectangle
  square to the configuration's turn grown round the ramp, the piece of the plot under the setback
  inside it that the ramp reaches, the same on every level (`_sized`). Its size is placed for the
  floor the need asks, by area and by the cars at the density the whole level was counted at, and
  grown while the cars counted on it leave it short (at most four counts); the whole outline is
  kept when no smaller piece holds the need. A cut square from one end of the cellar was tried
  first and kept too much on Dhulapally's L-shaped plot (a ramp 50 m in from the end left 448 cars
  where 300 were asked).
- Before a ramp stands (the first pass, which only decides whether one is needed) the whole
  outline is kept, as before.
- The cellar setback a candidate reports (`LayerKind.CELLAR_SETBACK`) is the rule's band, the plot
  less the plot eroded by the setback, whatever part of the plot the cellar takes. It was the plot
  less the cellar, which a sized cellar would have turned into most of the plot labelled as law;
  the validator's own layer was already the band.

The validator is unchanged and measures the cellar as drawn (its floor, its cars, its setback from
the plot line, the ramp reaching it, the NBC special building per piece under a block); every
layout judged on Dhulapally passes its parking.

Tests: `tests/test_search_parking.py` (normative, on the made-up rectangle: 4,000 m² asked takes a
cellar of 4,808 m² by the ramp, providing 4,140 m², where the whole level of 22,116 m² provided
19,440; the cellar lies at the ramp's end, west or east; two levels both sized; the setback layer
the band for every proposal). Characterization re-pinned: the service's made-up baseline (the same
proposals, the same four shown and the same answer; only the digests move).

- Dhulapally, Run B prime's request (the C4 benchmark, 13-parking): the same layouts judged,
  proposed and shown; parking laid out against the need, median 4.8% over (worst 9.9%) where it was
  30.5% (106%); the alternatives shown: maximum yield 15,180 m² against 14,678 where 17,240,
  balanced 13,860 against 13,365 where 16,100, open space 8,940 against 8,531 where 15,880, robust
  10,680 against 10,237 where 15,240; one legal FAIL (the validator's 9.00 m gap read as
  8.9999989), unchanged; runtime 104 s to 108 s (the cars counted on the pieces tried).

## 2026-10-07: C4-12, the open space taken where it is usable

The open space was taken biggest pocket first (`fit.choose_pockets`), so on Dhulapally it was
most often the far arm of the plot or a long wedge (the open-space option's: one strip of 3,580 m²,
64% of it within 30 m of a block), and the objective counted every square metre of it alike. One
measure now (`objective.usable_open_sqm`): the part of the open space at least 12 m across
(`OPEN_WIDE_M`: a lawn, a court or a play area fits) and within 30 m of a block (`OPEN_REACH_M`:
its residents see and reach it), both engine design assumptions in constraints.py, never rules:
the law's open space (rule 15's pockets 3 m wide and 50 m²) is the validator's and unchanged.

- The generator takes the most usable pockets first, the biggest between equals, and cuts the
  last from its more usable end (`choose_pockets`, `_trim`; given no value they work as before).
- The objective's open-space axis scores the usable part (`Scores.open_space_usable_sqm`); the
  whole area stays beside it, reported, and the hand-made scores of the pareto tests carry both.
- The trade-off: far ground the open space used to take is left to the facilities or, beyond
  them, unallocated. On the same Dhulapally layouts 0 to 416 m² more is unallocated; that ground
  was open space in name, not ground residents reach.

Tests: `tests/test_search_open_space.py` (normative: the measure, wide and near, a narrow strip and
a far square none; the generator taking a pocket beside the blocks before a bigger far one; the
last pocket cut from its usable end; the axis scoring the usable part and keeping the whole);
`tests/test_optimizer_pareto.py` (its one test whose tower stood 50 m from the open space the
helper draws at the origin stands it beside it). Characterization re-pinned: the service's made-up
baseline (maximum yield `-86`, the 3 x S+10, 570 of its 1,836 m² of open space usable; balanced the
4 x S+10 `-88`, 1,341 m² usable; the open-space option S+9, S+9 and five S+5 of 311,940 sft, 1,605
m² usable, where it was S+9, S+9, S+5, S+5; the robust one the same); the road ground (two, two and
four of the plots' proposals others, two road sets new).

- Dhulapally, Run B prime's request (the C4 benchmark, 12-open-space): maximum yield the same 3 x
  S+10 of 432,120 sft, 5 of 9 facilities where 4, 96 m² more unallocated; balanced 5 blocks (S+9 x
  4, S+5) of 383,302 sft and 318 flats where it was 350,852 and 292, all its open space usable, 8 of
  9 facilities where 3, 5,077 m² unallocated where 4,366, every block on a road along 26 m or more;
  the open-space option 3 x S+10, two blocks of one core and one of two, 239,180 sft and 200 flats,
  all of its 2,026 m² of open space usable, 7 of 9 facilities, where it was S+8 x 3 and S+5 of
  302,484 sft and 252 flats, open space the far strip above; this one leaves 8,094 m² unallocated
  (5,674 before), the most of the options shown, the price of single-core blocks; robust unchanged
  (287,016 sft, holding under every reading); one legal FAIL, the validator's 9.00 m gap read as
  8.9999989, unchanged.

## 2026-10-07: C4-11, site use and the quality of a scheme scored

The objective (`optimizer/objective.py`) scores two more numbers, both the search's, never rules
(nothing fails for them; the validator is untouched), and the brief may weigh them
(`Priority.SITE_USE`, `Priority.QUALITY`: the enum gains members, contracts not bumped):

- Site use: 1 less the share of the net plot that no use takes and no rule keeps open, the
  candidate's ledger's UNALLOCATED ground less its rule layers' setbacks, block gaps, fire bands,
  turning ground, buffers and green strip (`KEPT_OPEN`; a cellar's setback, a no-ramp or no-bay
  zone and the fire route keep nothing open at grade). Most of Dhulapally's unallocated ground is
  such ground: among the layouts judged, 4,062 to 7,540 m² is left unallocated, of which 242 to
  1,838 m² no rule explains.
- Quality: the plain mean of five measures of an ordinary scheme, each 0 to 1: the share of the
  plot not paved for roads; the share of the blocks of the commonest prototype; the share running
  the commonest way (0 and 180 degrees one way); the share facing a road or pathway along at least
  a pathway's width (rule 8(l)'s 6 m, the stricter reading of "opens onto", so a block a road meets
  only at a corner counts against the layout whichever reading holds); and 1 over 1 and the
  leftover pieces of 50 m² or more (`FRAGMENT_SQM`).

How the alternatives are chosen (`optimizer/pareto.py`, `strategy._to_judge`):

- The conventional open-space point weighs quality beside open space and conventionality; between
  layouts a point's own measure ties on, maximum yield, robust and conventional take the one that
  leaves less ground to no use (the compromise weighs site use already).
- The objective reads its areas to 0.01 m² (`AREA_DECIMALS`): the last digit of a floating-point
  area chose between twin layouts (the made-up baseline's `-86` dominated `-85` on 1836.0000000015675
  m² of open space against ...567).
- Each profile judges first the best of its front for each point the brief asks for (`pareto.leaders`;
  all but ROBUST, whose readings only a report gives), then the rest of the front by yield. The
  front of seven axes is wider than the six judged, and taken by yield alone it passed over
  Dhulapally's open-space option (`not_counted-ALL-70`), whose place a 6-tower layout with a block
  the ring road meets only at a corner took.
- `frontage` moved from `optimizer.search.ground` to `siteplan.geometry`, shared by the search and
  the objective (the validator keeps its own copy).

Tests: `tests/test_objective_ground.py` (normative: which layers keep ground open and which do
not, no ledger scoring nothing, quality's five parts, a corner touch against a road along a side
and a pathway, the new axes on the front and in the weights, the conventional point's plainer
scheme, the ties by site use, the last digits never choosing, the full search's candidates scored
on their own ground); `tests/test_search_frontier.py` (the front's most open layout judged though
yield would pass it by). Characterization re-pinned: the service's made-up baseline (maximum yield
`-85`, the twin of `-86`; balanced S+9, S+9, S+5 of 374,440 sft and 3,612 m² of open space where
it was 4 x S+10 of 440,800 sft and 1,836 m²; open space S+9, S+9, S+5, S+5 with 4,379 m², the most
of any judged, where it was 4 x S+8 and S+3; robust the same 3 x S+7; every digest moves, each
candidate's scores carrying the two numbers); the road ground of the three made-up plots (11 of 24
proposals other layouts, five road sets new); the legacy nala plot's labels swap (equal yields go
to C, which uses its ground; the open-space label to A, whose tower faces the loop road along its
side where C's grazes its rounded corner).

- Dhulapally, Run B prime's request (the C4 benchmark, 11-objective): maximum yield `-86`, the
  same 432,120 sft as `-85` on 53 m² less unallocated ground (4 of 9 facilities where `-85` placed
  5); balanced 5 towers (S+9 x 4, S+5), 350,852 sft and 292 flats, 4,366 m² unallocated, where it
  was 6 towers of 362,678 sft and 302 flats on 5,747 m², one of whose blocks the ring road met only
  at a corner (1.3 m of frontage; every block now faces a road along 24 m or more); the open-space
  and robust alternatives the same; one legal FAIL, the validator's 9.00 m gap read as 8.9999989
  (unchanged, a finding for the architect, not the search).

## 2026-10-07: C4-10, the facilities laid in the order that places the most

The facilities were laid first-fit in the order the firm lists them (since C4-08 what the brief
requires first), each where the ground nearest the gate holds it, so one large facility laid
early could leave no room for two others. The order is now searched (`ground.place_facilities`,
`_orders`): the firm's own, each of its rotations (each facility first in turn) and the largest
first, always within the classes (required, preferred, optional) in that order; the one that
places the most required facilities, then preferred, then optional is kept, the firm's between
equals, and the search stops at an order that places them all. Missed ones are named in the
firm's order. Measured first over Dhulapally's 126 facility placements: rotations and the
largest first place 53 more facilities in all than the firm's order (8 random shuffles: 54).

- Made-up land (`tests/test_search_program_classes.py`, normative): in a 34 x 21 m room a 33 x 10
  m deck listed first leaves no room for two 15 m courts, which side by side both stand: the two
  courts are kept, the deck named; a required facility is still laid before preferred ones,
  whatever order would place more. The quick search lays the same layouts; the service's made-up
  baseline proposes and shows the same, and only the facilities of the most saleable layout move
  (its digest and the answer re-pinned).
- Dhulapally, Run B prime's request (the C4 benchmark): the same layouts judged, proposed and
  shown; their facilities 152 where they were 144 (the 23 judged), 753 m² less ground left
  unallocated among them; the open-space alternative places 5 of 9 where it placed 4.

## 2026-10-07: C4-09, the frontier kept, and a robust alternative shown

Two changes to what the search keeps and what the architect sees.

- Judging (`strategy._to_judge`): each profile's six layouts the validator judges were its six
  most saleable, which a profile filled with copies of one scheme a step apart (the made-up
  baseline judged four 3 x S+9 of the same saleable area). Now the front of the objective's axes
  comes first (the most saleable, the most open space, the most conventional, and every layout
  nothing beats on all), then the rest by yield, and a layout that is the same idea as one
  already taken (`pareto.same_idea`) waits until no other is left.
- A fourth alternative (`ParetoPoint.ROBUST`, contracts extended, not bumped: the enum gains a
  member, so every stored 1.3 contract still reads): the layout that rests on the fewest open
  readings of the rules, none when it holds under every reading the validator evaluates, the most
  saleable between equals. Its readings come from the guard's report (`core._rests`,
  `Scored.rests`); a candidate whose report was not read never fills it. It is filled right after
  the most saleable, a different idea as every alternative is, and is left unfilled, said, when a
  layout chosen before it holds under every reading. It ranks by its own measure, not the front
  of the other axes first as the other points do: that front is drawn over yield, open space and
  the rest, none of them the readings, so the best layout that holds under every one may be one
  it dominates (on Dhulapally it put a 244,070 sft layout before the 287,016 sft one). A brief
  lists its points; one that lists none asks for all four. (A first version let it show the most
  saleable scheme at a lower height; the real sites' tests hold every alternative to another
  idea, the selector's rule, and it was put back.)

- Made-up land: `tests/test_optimizer_pareto.py` (normative: ROBUST is the least dependent
  different idea, the most saleable between equals, not the near-copy of a shown scheme; by its
  own measure, not the front of the other axes; unfilled when the layout shown first holds or no
  report was read; fewer open questions before fewer checks), `tests/test_search_frontier.py` (normative: the quota goes to different ideas
  before copies; copies when nothing else is left; the front before a more saleable layout
  another beats on every axis). The best proposal of every profile on the rectangles and the
  L-plots is the same as on C4-08; which layouts are judged and proposed moves, and the road
  ground is re-pinned. The service's tests count four alternatives shown and choose them again
  with each proposal's readings; the real sites' tests (`tests/test_search_client.py`,
  `tests/test_service_client.py`) allow one alternative a point, four.
- The service's made-up baseline (re-pinned): 15 proposed where 10 were; shown the 4 x S+10
  balanced layout again (440,800 sft, judged once more now that copies wait), and for the open
  space 4 x S+8 + S+3 and for ROBUST 3 x S+7, both holding under every reading.
- Dhulapally, Run B prime's request (the C4 benchmark): shown the most saleable 3 x S+10 (432,120
  sft), balanced a six-block S+7, S+7, S+5 x 4 (362,678), conventional S+8 x 3 + S+5 (302,484) and
  ROBUST the 4 towers S+9, S+9, S+3, S+3 (287,016 sft), which holds under every reading: the best
  such layout the search found, now one of the alternatives the architect sees. 15 proposed where
  12 were; the one layout the validator fails is still the micrometre gap of C4-07.

## 2026-10-06: C4-08, what the law asks, what the program requires, what the firm prefers

Three classes of constraint, kept apart. What the law asks (the validator's legal checks) is
never traded. What the brief requires is the program, and a layout without it fails the program.
What it prefers or leaves optional is a preference: said when it is not placed, never a failure.

A facility of the firm's library came to the brief as PREFERRED (the library had no word for its
priority), and the validator failed the program for every preferred facility with no room, so
the whole library was held mandatory: on Dhulapally every layout's program was PARTLY_MET for want
of facilities nobody had required.

- A library item may now say REQUIRED, PREFERRED or OPTIONAL (`AmenityItem.priority`), passed to
  the brief (`adapters.legacy_site.amenity_request`); one that says nothing stays PREFERRED.
- The validator's program checks (`validator.program._amenity_checks`): a REQUIRED facility not
  placed fails the program, as before; a PREFERRED one is INFO ("not placed (preferred): no room
  found for it"), as an OPTIONAL one was. The legal checks are untouched.
- The generator lays the facilities the brief requires before those it prefers, and those before
  the optional ones, the firm's order within each (`ground.PRIORITY_ORDER`). A facility is laid
  after the blocks and never displaces one.
- Tried and not kept: reckoning in the cheap half's room estimate only the facilities the brief
  requires, instead of a flat 300 m² (`layout.FACILITY_ROOM_SQM`). On made-up land the estimate
  then promised blocks the exact half could not furnish, and the best of two profiles fell (the
  L-plot's not_counted-ALL from 290,040 to 272,380 sft, the slim L-plot's from 304,440 to
  272,380) while others rose 2-5%. The 300 m² stays a margin of the cheap half's; since C4-07
  the exact half and the repair decide what the best layouts hold.

- `tests/test_validator_program.py` (normative): a required facility with no room fails the
  program; a preferred one is said with the reason, an optional one noted. It replaces the test
  that failed the program for a preferred facility. `tests/test_search_program_classes.py`
  (normative): with room for one, a required facility stands before a preferred one the firm
  lists first; a library that says nothing leaves a facility preferred, one that says is heard.
- The quick search lays the same layouts as on C4-07; the service's made-up baseline proposes and
  shows the same, and only the program verdicts in the model's answer move (re-pinned).

## 2026-10-06: C4-07, the layouts laid out are repaired

The exact half (`layout.lay_out`) laid the program in one order and gave up at the first thing
without room, and the search never went back to a layout it had laid. Four changes:

- The club house stands where its own band allows (`layout._club_ground`): Table III's setbacks
  for its height, as the validator holds it (rule 15(a)(x) makes it a building of its own), not
  beyond the tallest tower's setback, a wider band, which kept it off an arm or a strip of the
  plot it may use; and it turns to the plot's own directions too. On Dhulapally every "no room
  for the club house" went (about 20 in a search), and the best layout places 4 of the 9
  facilities where it placed 1.
- When the ramp then finds no room, the program is laid again with the ramp first, since it has
  the least choice of ground (beside a road, outside every setback), and the club house after it
  (`RAMP_FIRST`); when the open space finds none, again with the club house kept off the ground
  the open space may take (`CLUB_OFF_OPEN`). On Dhulapally 4 of 7 ramp failures lay out so.
- The fringe draws no pathway longer than NBC 4.3.2.2's 30 m (`fringe._from_face`): it drew one
  as long as the ring was far, which the validator failed (68 m) once the fringe was packed
  harder. A generator gap, not new law: the validator has held the 30 m since contracts 1.3.
- The parking plan counts the cars of a stilt only where a car can drive into it
  (`layout._stilts`): a driveway's width of the block's outline (rule 13(c)(viii)) facing a road,
  a fire lane or a pathway, as the validator has held it since contracts 1.3 (`ground.frontage`
  is the generator's own copy of its measure). It counted every stilt: on Dhulapally a repaired
  layout of six blocks planned 662 cars where the validator counted 626, short of Table V's 30%
  column (UNVERIFIED while whose column applies is open; a FAIL where it is GHMC's). It now
  plans the cellar that holds them.
- The search repairs what it laid out (`FullSearchStrategy._improve`): the most valuable layouts
  of each profile with blocks below 21 m are evaluated again with the fringe keeping no room for
  the program (`Config.fringe_room`), the exact half alone saying whether the club house, the
  ramp and the open space still have room, and a block of the fringe is given up at a time
  (`strategy._cuts`) until one lays out or stands no more than the layout it came from. Those
  are laid out after all the others; the validator judges them like any other.

- Made-up land (`tests/test_search_repair.py`, normative): the club house's ground includes the
  band between its own 5 m and the towers' 10 m; the ramp laid first stands clear of the club
  house in layouts the validator does not fail; the repair lays out layouts worth more than
  those of their profile after all the others, none twice, the others as without it, and the
  validator fails none; a pathway is never drawn longer than 30 m
  (`tests/test_search_fringe_search.py`). C4-04's test of the order laid reads the passes before
  the repair.
- The quick search: the rectangle's layouts 3-11% larger (the club house in the setback band
  leaves the towers more ground); the L-plots' with blocks below 21 m 8-22% larger. Road ground
  re-pinned (`tests/test_search_road_ground.py`).
- The service's made-up baseline (re-pinned): 116 laid out where 112 were, 10 proposed, 3 of
  them holding under every reading. More configurations lay out and fill each profile's quota
  before some laid on C4-06 are reached, and the judge's six of each profile by yield take more
  layouts of equal value; the balanced option shown is the repair's 5-block layout (371,440 sft)
  where it was 4 x S+10 (440,800, laid out but not among the six judged), and the open-space one
  is 4 x S+9 (rests on a reading) where it was 4 x S+8 (holds under every reading). The selector
  weighs neither robustness nor variety yet (C4-09).
- Dhulapally, Run B prime's request (the C4 benchmark): the best layout (3 x S+10, 432,120 sft)
  unchanged, with 4-5 of 9 facilities where it had 1 and 5,160-5,213 m² unallocated where it had
  5,490; the best that holds under every reading 287,016 sft (4 towers S+9, S+9, S+3, S+3) where
  it was 266,474; not_counted-ALL's best 338,494 where it was 331,292; 126 laid out where 112.
  One layout the validator failed: two blocks a street of exactly 9.000000 m apart, the gap their
  floor count asks, which the validator measures 8.9999989 m after snapping its shapes to a
  micrometre grid, a micrometre more than its 1e-6 m tolerance. Rejected, never offered; the
  validator's tolerance is the firm's to decide, not changed here.

## 2026-10-06: C4-06, floor counts kept on everything they ask and rest on

Of two floor counts of a prototype the shorter was dropped whenever the taller asked the same
setback and gap (`columns.choices_for`, and the fringe's `options`). That hid a shorter count that
asks less of something else. Since contracts 1.3 the validator evaluates NBC's own 15 m high-rise
line (the nbc_fire_height reading): under it a block of 15 m or more, stilt included, is held to
4.6's fire access, which the search lays round no block below 21 m. So a five-floor block (18 m)
stands only under the state's line, where a three-floor one (12 m) asking the same 6 m setback
and gap stands under both, and the five-floor one hid it.

- A count is now dropped only behind a taller one alike in all it asks and rests on
  (`readings.resources`): the ground (the larger setback, the gap, the planting strip), the fire
  access it is held to under some reading (a high-rise, or below one held by NBC's line,
  `FloorClass.nbc_held`), and the unsettled inputs it rests on.
- The profile built to hold under every reading (`Profile.every_reading`) takes no block below
  21 m that NBC's line holds, so its layouts hold under that reading too, as readings.py promises
  of it; it had rested on the state's line since contracts 1.3. The profiles built for a single
  reading of the stilt or of circulation may still rest on the state's line, as they rest on
  their own reading. No interpretation changes: the validator evaluates both lines as before.

- Made-up land (`tests/test_search_floor_options.py`, normative): under a single reading of the
  stilt, three floors are kept beside five, four and one are dropped; the profile built for every
  reading offers one to three floors below 21 m, not four or five; and on the L-plot every layout
  it judges holds under both lines, some with blocks below 21 m. `tests/test_search_readings.py`
  and two tests of `tests/test_search_low_blocks.py` read the four- and five-floor counts under a
  profile that may rest on a reading.
- The quick search's proposals: the layouts meant for every reading on the L-plots and the
  rectangle trade their five-floor blocks for three-floor ones (the rectangle's 348 flats are 324)
  and hold under both lines; the others are as on C4-05. The L-plots' and the rectangle's road
  ground is re-pinned (`tests/test_search_road_ground.py`).
- The service's made-up baseline (re-pinned): 3 of the 12 proposals hold under every reading again
  (C4-05: 1), and the open-space option shown is the 4 x S+8 layout that does, as on C4-04.
- Dhulapally, Run B prime's request (the C4 benchmark): the first layout that holds under every
  reading the validator evaluates, full-ALL-ALL-1: 4 towers, S+7, S+7, S+3, S+3, 222 flats,
  266,474 sft, 10.6% open space, 7 of 9 amenities, no legal FAIL; it is the open-space option
  shown. All six judged in that profile hold under every reading. The best layout (3 x S+10, 360
  flats) and the balanced one are unchanged. The 7-5-5-5 layout Run C exported (316,888 sft) is
  no longer built: under today's validator it holds only under the state's line, a reading added
  after Run C.

## 2026-10-06: C4-05, the fringe's search: every kind of block tried, and the plot's directions

The blocks on the ground the ring road leaves (the fringe, stream C3) were placed by one greedy
pass, upright in the configuration's direction, and three things kept it from blocks that fit:

- its tries were shared by every kind of block: when the most valuable kind's nearest twelve
  places all left too little room for the rest of the layout, or no pathway reached them, the
  pass ended, and a smaller or a lower block that would have stood was never looked at. Each
  kind now has its own twelve (`fringe._best`);
- it stood blocks only in the configuration's direction, so a band of ground turned from the
  columns took none it could not hold upright. The fringe is now also laid in the plot's own
  directions, along and across its longest edges, two of them (`fringe.FRINGE_DIRECTIONS`), and
  the most valuable is kept, the configuration's between equals; a block laid so carries its
  frame (`Standing.frame`, as a turned cluster's do since C4-03);
- its grid ran from the near edge of each piece of ground a metre at a time, so a block stood
  flush against the far edge, where a ring road on that side is, only when the width came to a
  whole number of metres. The far edge is now a place too (`fringe._steps`).

Measured first on Dhulapally (Run B prime's request, every fringe the search laid, 671): separate
tries beat the shared ones in 162 and the plot's directions in 268, and the two together add
about 7.0 million sft over all of them, for about 35 s.

- Made-up land (`tests/test_search_fringe_search.py`, normative): a kind none of whose places
  leaves the room gives way to a smaller one; where the most valuable kind stands the search is as
  before; a band turned 30° or 140° from the columns takes blocks turned with it, flush against
  its road; a block stands flush against either edge of its ground.
- The quick search's proposals: on the L-plot those with blocks below 21 m are 249,340, 241,960,
  230,680 and 220,920 sft where they were 216,780, 210,400, 198,120 and 189,360 (15-17% more); on
  the L-plot with the slim block 8-14% more; on the rectangles the same. The L-plots' road ground
  is re-pinned (`tests/test_search_road_ground.py`).
- The slim L-plot's arm: layouts with a block there are still laid out (two), and the note says
  so, but the larger layouts that leave the arm outrank them, so none is proposed. Its test
  (`tests/test_search_low_blocks.py`) asked that one be proposed, an outcome of the objective on
  that land rather than a rule; it now judges every layout laid out with a block in the arm,
  proposed or not, with the validator, and checks the block is low, served and passes.
- The service's made-up baseline (`tests/test_service_proposals_baseline.py`, re-pinned): four
  proposals of the lower profiles are others, none smaller (a 224-flat layout is now 232), and the
  open-space option shown is 4 x S+9 (252 flats) where it was 4 x S+8 (224). 1 of the 12
  proposals holds under every reading where 3 did: the 3 x S+7 layout that does is still judged,
  unchanged, but an S+8, S+8, S+5 layout of the same flats and saleable area is proposed in its
  place, since the selector has no robustness objective yet (C4-09).
- Dhulapally, Run B prime's request (the C4 benchmark): no legal FAIL; the best layout (3 x S+10,
  360 flats) and the three shown are those of C4-04, the best of the profiles with blocks below
  21 m larger (ALL-ALL 309,686 to 316,888 sft, 264 flats, the 7-5-5-5 layout Run C exported;
  not_counted-ALL 321,246 to 331,292), 12 proposed where 10 were; 79.6 s where it took 45.8.

## 2026-10-06: C4-04, columns of more than one depth in a layout

The columns took the kit's main depth (the one most of its prototypes come in); blocks of the
kit's other depths stood only on the fringe. Each configuration is now searched once more, after
all of the others and in an order of its own (`Config.mixed_depths`), with each column of
whichever depth adds the most saleable area for the width it takes, its depth and the street
beside it; that configuration keeps the main depth's columns where they add more, and counts as a
layout of its own only when a column of another depth stands in it, else it is the same as the
first. A kit of one depth (Dhulapally's, the made-up rectangle's and L-plot's) searches exactly as
before.

The first version let every configuration take the other depths. On the made-up L-plot with the
slim block those configurations rated highest in the cheap half, by filling the strip the main
depth leaves, and then failed the exact half, since that strip was where the club house went:
every one of them ran out of room for the club house, the cellar ramp or the approach, and on the
way one deep-only layout that had laid out before was no longer laid. So the configurations with
other depths are laid out after all of the others, with quotas of their own: they take neither
the others' place, nor their time, nor their numbers.

- Made-up land (`tests/test_search_depths.py`, normative): on land as wide as two deep columns,
  a slim one and their streets, a slim column stands beside the deep ones and the columns add
  more than the deep ones alone; where only deep columns fit, they are as before; mixing never
  adds less than the main depth alone; a configuration stands another depth in its columns only
  when it lets it, and then always does; and on the slim L-plot every configuration of before is
  laid out first, columns of the main depth alone, and layouts with columns of two depths reach
  the exact half (22 on the slim L-plot, 20 on the slim rectangle, none before).
- What they give there: the best of them is 16-23% below the best deep-only layout of each
  profile, since the room a mixed plan needs for the club house is an end of the plot kept clear,
  which takes more than its slim column adds; none is proposed, and the proposals and every
  characterization pin are unchanged. A multi-depth kit takes about twice as long (4.4 to 8.1 s,
  6.3 to 11.8 s), a kit of one depth no longer.
- Dhulapally, Run B prime's request (the C4 benchmark): its kit is of one depth, so the search is
  unchanged.

## 2026-10-06: C4-03, a further cluster turned to its own ground

A further cluster (C4-02) stood in its configuration's direction, so a wing turned from the plot's
main lines took its blocks at an angle the wing does not run. It is now tried in that direction
and in its own ground's (`layout.zone_angles`: the principal axis of the ground it would stand on,
along and across its longest edges; no two within the turned frame's 5°, four at most), and the
most valuable that can be joined is kept. Its blocks carry their frame (`Standing.frame`) to the
placement, the fringe sees them turned, and the club house and the facilities may turn to any
cluster's direction. Two refusals keep the layout what the validator holds it to:

- a further cluster whose ring would run over a laid cluster, or a laid ring over it: a ring
  turned to its own ground reaches further out at its mitred corners than along its sides, and on
  Dhulapally such a corner stood 1-2 m² on a tower of the first cluster;
- a further cluster whose ring meets a laid ring at an angle (joined where their pavements meet,
  with no link road): where two rings overlap askew, the corner of one sticks out of the other in
  a wedge the validator measures narrower than a road (6.65 m on one Dhulapally layout). A turned
  cluster stands apart, joined by a link road. This refuses some askew meetings that would have
  passed (two Dhulapally layouts of 352 and 340 flats); telling them apart needs the generator to
  measure the joined rings as the validator does, left for later.

A defect of C4-02 shows once three clusters stand more often: the ground left for a further
cluster was the blocks' land less the laid clusters, not less the link roads laid between them,
so a third cluster could stand over the link that joins the first two (117 m² of one on the
made-up squares). The links, with a street's room round them, are taken out too.

- Made-up land (`tests/test_search_orientation.py`, normative): on an L whose arm is turned 30°
  from its body, a configuration at the body's angle stands its further cluster in the arm's own
  direction, joined by a link road. The quick search on the long L proposes 620, 558, 522 and 464
  flats where C4-02 proposed 560, 504, 498 and 460; the two squares joined by a neck and the
  service's made-up baseline are unchanged.
- Dhulapally, Run B prime's request (the C4 benchmark): no legal FAIL; the best layout and the
  three shown are those of C4-02.

## 2026-10-06: C4-02, more than one cluster of blocks, each round its own ring road

The full search fitted the blocks into one convex outline with a ring road round it, so a plot of
two wings one convex outline cannot take in (two squares joined by a narrow neck) left a wing
empty; where the one cluster's ramp then had no road to stand beside, nothing was laid at all.
Every configuration is now also tried with further clusters (`Config.more_clusters`): columns are
laid on the ground the first cluster leaves (less every laid cluster grown by the street between
two columns, so the blocks keep their gap and the rings stay off each other's blocks), fitted round
a ring road of their own, and joined to a ring already laid by a link road (`network.link`, the
shortest straight road between the two rings' centre lines that lies on ground a road may take,
found every 2 m along the further ring). Where the two rings' pavements meet a road wide they are
joined there, and the link is an edge of the network with no pavement of its own; a link shorter
between the rings than a road is wide is no road (the validator would see its two ends as one
junction) and that cluster is not laid. At most three clusters. The variants come after every
other configuration, in an order of their own, so those are evaluated as before.

- Made-up land (`tests/test_search_clusters.py`, normative): on two 120 m squares joined by a 50 m
  neck the strictest profile, which proposed nothing, proposes layouts of two clusters joined by a
  link; the others take both wings (540 flats where 444 were, under not_counted-allowed).
- The service's made-up baseline: 768 configurations evaluated where 384 were, the same twelve
  proposed and three shown; re-pinned.
- Dhulapally, Run B prime's request (the C4 benchmark): 2,304 configurations, 112 laid out, 24
  judged, no legal FAIL; four judged layouts stand two clusters joined where their rings meet, one
  of them among the ten proposed; the best is unchanged (three towers of stilt + 10, 360 flats),
  as the north arm leaves no ground a cluster with its ring fits (13 m of it, a block is 25.8 m).

## 2026-10-06: C4-01, the full search draws every road from a centre-line graph

`optimizer/search/road_graph.py`: the roads are a graph of nodes (an entrance, a junction, the
block a pathway serves, the anchor of a loop) and edges along each road's centre line, and every
road's pavement is drawn from its centre line, never the other way round. The ring's centre line
runs half a road out from the cluster's outline, a street's down its corridor from the ring's
centre line to the ring's, the approach's from the gate to the ring's, a pathway's from its block.
The graph says whether the roads are one network with no road that stops with nowhere to go; a
layout whose roads are not is refused, with the reason, before anything is built on it. The
validator measures the pavement as before: the graph is the search's, not a claim it trusts.

- The same ground: `tests/test_search_road_ground.py` (characterization, pinned on C4-01a) holds
  every road of the 22 candidates the quick search proposes on made-up land to its area before
  the graph, to 0.01 m². `tests/test_search_road_graph.py` (normative) holds the network: one
  piece, the ring a loop cut at every junction, the streets between junctions on it, the approach
  from the entrance, the pathways from the blocks they serve, the pavement moving with its line.
- The generator's ledger is drawn on the validator's micrometre grid (`build.GRID_M`): with the
  roads drawn from centre lines, a street's edge and a fire lane's met with other last digits,
  and the contract's full-precision check read two Dhulapally layouts' street and fire lane as
  overlapping by 232 m², so the guard failed them. On the grid their edge is exactly shared.
- What still turns on the last digits, left to C4-09 and C4-10 (the frontier, the amenity
  search): the open-space pockets taken largest first, where two are the same size; two layouts
  the selector scores the same; the club house's and a facility's place, whose scanning grid
  starts at the edge of the ground it scans. On made-up land `full-not_counted-ALL-61` is
  proposed for `-62` (the same blocks, flats and saleable area) and `full-ALL-ALL-6` shown for
  `-5` (the same blocks, flats, saleable area and open space); re-pinned.
- Dhulapally, Run B prime's request (the C4 benchmark): the same 1,152 configurations, 112 laid
  out, 24 judged and no legal FAIL as C4-01a, the same eleven proposed and the same three shown;
  on two layouts that are not shown a facility or the club house moved.

## 2026-10-06: C4-01a, the search's choices no longer turn on the last digits of its geometry

Drawing the roads from centre lines (C4-01) lays the same ground with other last digits, and that
alone changed what the full search laid out. Three defects were behind it, fixed here first:

- **The ring road's narrowness** (`network.cluster_of`). The ring was opened at exactly a road's
  width to find where the ground cuts it narrower than a road. A ring drawn at exactly that width
  (the Dhulapally ASSUMPTION_TEST inputs give no firm margin over rule 8(m)'s 9 m) shrinks to a
  line, and GEOS grows that line back unstably: at some turns the whole ring read as narrow when
  the ground had cut only the 2 m tip of a mitred corner. The check now asks directly whether a
  road a hair under the rule's width, laid against the cluster's outline with its turns rounded,
  lies on the ring's ground. A cut deeper into a side than the ring's margin over a road is
  refused as before; the tip of a corner beyond a road's width is no longer a narrowing.
- **The fringe** (`fringe._best`, `fringe._grid`). Between equally valuable blocks the fringe took
  the one nearest the ring, and a block the ring touches is 0 m or, by noise, 1e-13 m away: noise
  chose. Distances and places now rank to the millimetre (`TIE_M`), and a block whose edge lies on
  its ground's edge stands on it (`CONTAIN_TOL_M`, a micrometre), its bounds check included.
- **The generator's ledger** (`build.partition`). Each claim went into a cascaded union with the
  claims so far. On one Dhulapally layout GEOS 3.13 returned that union without a block lining the
  ring road's hole, the ledger counted the block's 1,582 m² as UNALLOCATED too, and the
  validator's partition cross-check failed the layout, rightly. One binary union at a time now.

Evidence and tests:

- `tests/test_search_ties.py` (normative): the corner-tip cut at the turns the old check refused
  (14.4°, 25.8°, 27.3°), a 1 m cut into a side still refused, the fringe's tie and edge, and the
  ledger counting every square metre once on made-up land. Five of its eleven fail on 1c4fd2e.
- Made-up land: the service's twelve proposals, the three shown, the model's answer and the
  approval page are unchanged; only the digests move (re-pinned). On the slim L-plot the quick
  search proposes `full-not_counted-ALL-13`/`-14` and `full-ALL-ALL-2`/`-3` (five blocks, one
  with a pathway) where it proposed `-12`/`-13` and `-1`/`-2` (four blocks, two with pathways);
  `tests/test_search_road_ground.py` is pinned on C4-01a.
- Dhulapally, Run B prime's request (the C4 benchmark, `out/dhulapally-C4-BENCHMARK-20261006/`):
  the same 1,152 configurations, 112 laid out and 24 judged, no legal FAIL, 11 proposed where 12
  were. The best layout is the same (three towers of stilt + 10, 360 flats, 432,120 sft); the
  balanced and the open-space options shown are others.

## 2026-10-06: the agent loop and the service guard against the logged Qwen defects

No characterization test changed: on a fresh out folder the approval page, the answer and the
search are as before. KNOWN_QWEN_DEFECTS.md (the assumption-test and workflow folders) logged
three defects of qwen3.8-27b-sglang as the orchestrator; each now has an engine-side guard, since
words in a prompt alone had not held:

- D1, an opaque id copied wrong and a duplicate search hidden: the loop refuses, and never sends,
  a call naming a run_id or candidate_id that no tool result and not the brief has given, and
  tells the model the ones that were (`loop.unknown_identifier`); a proposal on exactly the inputs
  of an approved run says so on its approval page, before the person approves it again, and in
  the answer's notes (`store.approved_runs_of`). The system message says to copy identifiers
  exactly, never to search again for a new id, and to name every run_id in the answer.
- D2, counts in prose: every result reaches the model beside the count of each list in it
  (`loop.counts`), and the system message says never to count a list itself.
- D3, invented browser steps: the system message names the only two approval pages (before a
  search, before each export) and says choosing among candidates happens in the conversation.

Tests: `test_every_list_in_a_result_comes_with_its_count_so_the_model_never_counts`,
`test_an_identifier_no_result_or_brief_gave_is_refused_with_the_ones_that_were`,
`test_the_system_message_names_the_two_approval_points_and_the_identifier_rules`,
`test_a_wrong_identifier_is_refused_by_the_loop_and_never_sent` (tests/test_agent_loop.py) and
`test_a_request_that_repeats_an_approved_run_says_so_before_it_is_approved`
(tests/test_service_proposals.py). Two loop tests now expect the counts beside a result, and the
export test's new session names its run and candidate in the brief, as an architect would. Not yet
seen on a live Qwen run (the GB10 is down): the next run is audited against all three.

## 2026-10-06: the search keeps its cellar out from under blocks below 21 m

The full search lays fire lanes round its high-rise blocks only, and its cellar was the whole plot
inset by the cellar setback, so under contracts 1.3 every block it stood below 21 m was over a
cellar of more than 500 m², a special building whose fire access the validator failed (the entry
below). `optimizer.search.parking_plan.plan_parking` now takes the footprints of the blocks laid
with no fire band (`clear_of`, from `layout.lay_out`) and the cellar outline leaves them out, so
none of them is a special building. The cellar is smaller by those footprints and may need more
levels. Not checked, as before: whether every part of a cellar with holes in it is reached from
its ramp.

- Made-up land (the PR #17 baseline): the twelve proposals, the notes and the model's answer are
  main's again, and the same three are shown; only the proposals' digests move (contracts 1.3,
  and the cellars cut round the low blocks). Re-pinned.
- `tests/test_search_low_blocks.py`: the six tests that ran under the MADE-UP
  `no_special_buildings` rule run under the law again, and the rule is gone from
  `search_support.py`; the test of special buildings also holds that no block laid without a fire
  band stands over the cellar.
- Dhulapally, Run B prime's request (diagnostic, not a run:
  `out/dhulapally-CELLAR-FIX-CHECK-DIAGNOSTIC-20261006/`): Run B prime's twelve are proposed again
  and the same three shown (85, 86, 63). None of the twelve holds under every reading where Run B
  prime had three: `full-ALL-ALL-1`, `-4` and `-5` stand stilt + 5 blocks with no fire band, which
  pass under the state's 21 m line and fail under NBC's own 15 m (`nbc_line`), so they rest on
  that reading. Seen on the drawings: the cellar is cut round those blocks, which still have no
  road or fire lane round them, the generator's next step.

## 2026-10-06: contracts 1.3, the access a block below 21 m is held to

Read on 2026-10-06 from the NBC 2016 page images (`fixtures/rules/sources/nbc`), brought in by
G.O.168 rule 15(a)(i) as G.O.Ms.No.50 of 2019 substituted it (the Code's requirements "other than
heights and setbacks"). The validator changes; the optimizer's search, `select()` and the
generator do not, but the guard is the validator, so what the search proposes changes with it.

- **NBC 4.6 for special buildings, as law.** 4.6 is "for high rise buildings and special
  buildings"; Part 4 1.2(b)(6) makes a special building of one "with two basements or more, or
  with one basement of area more than 500 m²", at any height. A block standing over such a cellar
  (`Context.special`) is held to every fire check a high-rise is: the lanes and corner turns, the
  loop's turns, reach from the gate, the entrance, nothing on the lanes, the street join, the
  dead end and the 45 t. The generator's cellar is the plot inset by its setback, so on a layout
  with a cellar every block is held, and the generator does not yet give a block below 21 m the
  fire band: such layouts now fail and the guard rejects them. A cellar drawn without its outline
  leaves each block perhaps special: what fails only on that is UNVERIFIED.
- **NBC's own 15 m line** (Part 4 2.38, the stilt included as 2.6 measures) is the open reading
  `nbc_fire_height` (`state_line`, `nbc_line`), carried ALL.
- **A block 4.6 does not hold under a reading has nothing asked of it there: PASS under that
  reading** (it was NOT_CHECKED, which made a block held under only some readings UNVERIFIED even
  where it passed wherever it was held). The site-wide fire checks (street join, dead end,
  entrance, nothing on the lanes, 45 t, no layout drawn) are evaluated under each reading too, so
  one that fails only where a reading holds a block is UNVERIFIED, never FAIL.
- **"Opens onto a road"** is the open reading `opens_onto_road` (`touch`, `frontage`), carried
  ALL, in rule 8(l)'s two checks: a block above 12 m that only touches a road at a corner is
  UNVERIFIED (on the made-up rectangle, T1 faces the loop road for 1.5 m and the internal road
  for 73 m).
- **NBC 4.3.2.2's pathway, no longer than 30 m**, is a new check for every block reached by a
  pathway (`roads._pathway_length_check`): measured along a straight pathway; bounded between the
  straight line and half the outline of any other, UNVERIFIED in between.
- **A stilt counts as parking only where a car can drive in** (`parking.stilt_reached`, the
  engine's reading): an unbroken 4.5 m (rule 13(c)(viii)'s driveway) of the block faces a road,
  a fire lane or a rule 8(l) pathway; the parking finding names a stilt it leaves out. The
  generator still counts every stilt.
- Bays, the open space, the land ledger and the rule layers keep a special building's fire band
  as they keep a high-rise's; the egress note covers special buildings (NBC Part 4 applies to
  them).

Tests that changed:

- Normative, rewritten because the law they held changed:
  `tests/test_validator_low_blocks_site.py` (a block below 15 m over no cellar is held to nothing
  in 4.6; over the cellar it is a special building held to all of it; the rest of rule 15(a)(i)
  stays NOT_CHECKED with what is judged elsewhere named; a 15 m block over no cellar is held
  under `nbc_line` only, so what it lacks is UNVERIFIED, never FAIL);
  `tests/test_validator_roads_fire.py` (a block that is a high-rise only if the stilt counts now
  PASSes where it passes wherever it is held, and is UNVERIFIED where it fails there: it was
  UNVERIFIED either way; two tests about driveways and rule 8(l) select the `touch` reading, the
  frontage question being `test_validator_access_law.py`'s), and the 12 m boundary test in
  `tests/test_validator_edges_roads_fire.py` likewise; `tests/test_resolve.py` (seven readings
  carried ALL; the audit maps its two new open entries to them); `tests/test_contracts.py`
  (version 1.3, a 1.2 document refused).
- `tests/test_search_low_blocks.py`: the six tests of where the search stands blocks below 21 m
  (their setbacks and front, rule 8(l)'s pathway, a fringe block against the road, the all-low
  layout's planting, the arm) run under the MADE-UP rule of `search_support.no_special_buildings`
  (no cellar makes a special building), because under the law the search offers no layout with
  such a block over its cellar. The test that nothing offered fails the validator runs under
  both, and a new test holds the law: no layout offers a special building without its fire
  access.
- Characterization: `tests/test_service_proposals_baseline.py` re-pinned. On the made-up land the
  search still proposes 12, the validator now fails five (low blocks over the cellar without the
  fire band; `full-not_counted-ALL-59` leaves the twelve, `full-not_counted-ALL-61` joins), the
  same three are shown at the same points, their digests and the model's answer follow the
  contract, and the approval page is unchanged. `tests/test_validator_client_suchitra.py`
  compares rule 8(l)'s two checks under the `touch` reading, the one today's checker takes.

New normative tests: `tests/test_validator_access_law.py` (14), and the contract, resolver,
inventory and number-audit tests for the new values and readings.

On Dhulapally (diagnostic, not a run; Run B prime's exact request on this branch):

Run B prime's exact request through this branch's service steps and full search, seed 0
(`out/dhulapally-ACCESS-LAW-CHECK-DIAGNOSTIC-20261006/`, client data, never committed):
1,152 configurations, 112 laid out, 24 judged, as before; 7 proposed where 12 were, and the
validator fails 11. The three shown: `full-not_counted-allowed-85` (MAX_YIELD) and
`full-not_counted-allowed-86` (BALANCED) as before, `full-not_counted-ALL-62` (CONVENTIONAL) for
`-63`; every block in them stands in a road or fire lane on all sides (seen on the drawings), and
their only access items left UNVERIFIED are the street join, the dead end (33 m) and the 45 t.
None of the seven holds under every reading (3 of 12 did): the layouts that did were the ones
with stilt + 5 blocks over the cellar, now special buildings without a fire band. Run C's
`full-ALL-ALL-1` now FAILs fire access for T2, T3 and T4 (amenities, the tot-lot and the planted
strip in their 6 m band, no lane round them), is UNVERIFIED on frontage (T2 faces a road for
3.3 m) and leaves T2's stilt out of the parking (which still passes). The firm's own plan
(post-blind, DEBUG) keeps its nine FAILs: it draws no cellar, so no special building; its stilt +
6 block is held under `nbc_line` only and passes.

## 2026-10-05: the loop offers each tool's schema with its references written out

No characterization test changed; the host's schemas, its checks and the MCP tool list are
untouched. In the first real run (Qwen3.8-27B on SGLang, `--tool-call-parser qwen3_coder`) Qwen
wrote `propose_layouts`'s `intent` as the right object, and the host received it as text and
refused the call three times: the parser types each parameter by its own schema
(`infer_type_from_json_schema`) and follows no `$ref`, and `intent` was offered as
`{"$ref": "#/$defs/Intent"}`, the only object parameter of the nine. The loop now offers each
schema with its local references replaced by the definitions they name (`loop.written_out`), so
every parameter carries its own type; a reference it cannot write out (recursive, remote or
missing) leaves the schema as listed. The loop never turns a model's text into an object itself.
`test_every_parameter_the_model_is_offered_carries_its_own_type` and
`test_a_reference_that_cannot_be_written_out_leaves_the_schema_as_listed` hold it, and the
sandbox run test now compares the offered parameters with the written-out schemas.

## 2026-10-04: the agent loop: a model drives the nine tools from inside the sandbox

No characterization test changed and nothing the engine computes changed: the engine, the
ToolHost, the service and its contracts, the validator, the optimizer, the legacy path and the
MCP server's tool surface are untouched. Outside `siteplan/agent/`: `pyproject.toml` (the console
script `siteplan-agent`), the number audit's exemptions, and three test updates named below. No
real model was contacted; each behaviour is held by a normative test against a scripted
OpenAI-compatible server on 127.0.0.1 (`tests/fake_model.py`, `tests/test_agent_loop.py`).

- **The loop** (`agent/loop.py`, run in the sandbox by the launcher): each turn sends the model
  server (`POST {endpoint}/chat/completions`, `agent/model.py`, httpx with `trust_env=False`) a
  short factual system message, the brief and the host's nine tools as OpenAI function tools,
  exactly as the host lists them over MCP; each tool call goes to the host through the harness
  once, and its result back to the model, until the model answers without a tool call. A name the
  host does not list, or arguments that are not a JSON object, is refused in the loop and never
  sent. The endpoint and model id are configuration (`agent/settings.py`: arguments, a JSON file,
  defaults), so an A/B run against another model is one argument.
- **Hard limits, each a stop with its reason**: turns (30), tool calls (40), failed tool calls in
  a row (4), the same tool and arguments (the third is not run), a model request's time (600 s)
  and the run's (3600 s), a response's body (1 MiB; a larger one stops the run and the record
  keeps what was read, marked) and a tool result as the model gets it (64,000 characters, cut
  with a visible marker). A tool call is never retried; model requests are retried only when
  configured (`model_retries`, default 0), and a retry repeats the request, never a tool call.
  SIGINT or SIGTERM to the launcher stops the run in order: the agent is asked to stop, closes
  its MCP session and records why; the host ends with its stream, or is stopped after a grace
  when an approval it waits on can no longer be answered (nothing runs, nothing is approved).
- **The record lives outside the sandbox** (`agent/transcript.py`, `<out>/agent/<run>/`). The
  launcher now relays the MCP stream instead of joining the two processes' pipes directly, and
  owns every channel out of the sandbox: `mcp.jsonl` is the stream as relayed (the host's side of
  what the agent asked, which the agent cannot alter); `transcript.jsonl` holds the launcher's
  steps, the agent's events from a pipe of its own (each model request, with the SHA-256 of the
  bytes sent and the messages added since the last, so every request can be rebuilt; each
  response whole; tool calls, results and refusals; the stop; times) and its stderr. The children
  run in their own sessions so a Ctrl-C reaches the launcher alone. The architect's terminal
  shows the model's messages and each tool call.
- **A fault the loop tests found in the harness** (`agent/harness.py`): its reading thread read
  `sys.stdin` itself. When the agent ended while the host still held the stream open (a model
  error, a timeout, a stop during an open approval), Python's shutdown closed `sys.stdin`, waited
  on that thread's lock and aborted the process ("Fatal Python error: _enter_buffered_busy",
  exit -6): a race, which failed six of the new file's tests on its first run. The stream is now
  read through a buffer of its own on a copy of stdin; every loop run asserts the agent's stderr
  is empty and its exit status is its own, and that guard was seen to fail with the old reader.
- **The Seatbelt profile no longer lets the agent look any path up.** `(allow file-read-metadata)`
  was global, so the model process could stat anything outside the workspace and `out` (asked of
  the kernel with `sandbox_check`: `~/.ssh`, `~/Documents`, `/etc/hosts`, `/Applications` and the
  engine's own `cli.py` were all allowed). It is now `sandbox.lookups`: Seatbelt's
  `path-ancestors` of the runtime, the package, the scratch folder and the interpreter's links,
  and those links themselves (the same filter Apple's `system.sb` uses for firmlinks). Every
  path the agent may read lies in a tree whose `file-read*` allow already covers lookups, so only
  lookups of unreadable paths went. Seatbelt reports no metadata decision (a deliberately denied
  stat, and one allowed through `(with report)`, both left the log empty), so the log could not
  list what a session needs; the evidence is behavioural: the preflight, the stand-in's tour, the
  transport tests and every loop run pass under it. With the old rule, the new stand-in probe
  "look up a file elsewhere" succeeds and the engine's modules are visible (an import is refused
  with PermissionError); with the new one the lookup is denied and an import finds no module.
  `test_agent_sandbox.py` now pins the rule, the probe and the "not found" engine imports.
- Test updates beside the new file: `test_agent_transport.py` lets the agent package import
  httpx (the SDK's own HTTP client); `test_agent_sandbox.py` as above; `test_constraints.py`
  exempts the new agent modules, whose numbers bound the agent's run and are no number of a
  layout.

## 2026-10-04: a transport around the ToolHost, and a sandbox for the model process

No characterization test changed and nothing the engine computes changed: outside the new
`siteplan/agent/` package only `pyproject.toml` (one console script) and the number audit's
exemptions moved. No model is connected. Each new behaviour is held by a normative test.

- **`siteplan-agent-tools` serves the `ToolHost` over MCP on stdio** (`agent/server.py`). MCP
  because agent harnesses speak it and the project already depends on its SDK (`mcp<2`); stdio
  because it opens no listener. The SDK's low-level server lists exactly `ToolHost.tools()` (the
  nine names, descriptions, input and output schemas) and sends each call to `ToolHost.call`
  with its arguments as sent. The SDK's own input check is off: with it on, a refused field came
  back as "Input validation error: ... ('_status' was unexpected)", telling the caller what to
  change; now every refusal is the host's own sentence and the reason stays in
  `<out>/logs/agent-tools.log`. The server answers nothing but tools (prompts, resources and
  logging are "Method not found") and asks the client nothing, so an approval exists only on the
  page the host opens in the architect's browser. Calls run one at a time, off the event loop.
  tests/test_agent_transport.py: all nine called through the transport, the listing equal to
  `ToolHost.tools()`, unknown tools and extra or invalid fields refused in the host's words, the
  approval token never in a line the model's side received, a proposal run only after the click
  and nothing run after a rejection, a tower moved into the setback refused at export without
  the architect being asked, UNVERIFIED exported only with exactly its items and an approval the
  audit records, and the agent package importing only the service (in `server.py`), the SDK and
  the standard library.
- **The model process runs sandboxed, joined to the host only by the stream** (`agent/launch.py`,
  `agent/sandbox.py`, the model's side `agent/harness.py`). Writes only in a private scratch
  folder; no read of the workspace, `out` or the engine; no exec but its own interpreter; no
  network but one port on this machine; a bare environment. macOS: sandbox-exec with a Seatbelt
  profile over Apple's `system.sb`, verified on this Mac (macOS 27.0.1) from inside a Claude
  Code session, where a nested profile applied. Probing showed Seatbelt reads a rule on a named
  operation before a wildcard's and a filtered rule before an unfiltered one, whatever their
  order: a closing `(deny file-read* ...)` did not take back an earlier `file-read-metadata`
  allow, so the closing deny names the operations, and the launcher refuses any overlap between
  what the model may read and the workspace or `out`. Linux: bubblewrap, mounting only what may
  be read; written and unit-tested, not yet run. A sandbox that cannot be applied, or one that
  starts and does not hold (`SandboxLeak`), refuses to start, before the host starts.
  tests/test_agent_sandbox.py: the scripted stand-in (`agent/standin.py`) reaches the nine tools
  through the launcher, and every write, read, exec, connection and engine import it tries fails
  with the workspace byte for byte unchanged; a model endpoint opens its port and no other; and
  each refusal starts nothing.

## 2026-10-04: engine fallbacks are the engine's; one reading of the road-widening plot shortfall

No characterization test changed. Two corrections to the hardening pass:

- **A standard the engine fills in is labelled the engine's, never the firm's**
  (service/standards.py). A value from the approved project file or the workspace is FIRM_STANDARD;
  a fallback the engine supplies because neither sets one is source kind ENGINE_DEFAULT, basis
  ENGINE_DESIGN_ASSUMPTION, whatever its status. The DesignBrief, the service's facts (each now
  says its basis) and the lines the architect approves all carry it.
  `test_service_standards.py::test_an_engine_fallback_is_never_labelled_the_firms` and the
  updated assertions beside it.
- **The validator reads the high-rise plot minimum as the resolver does.** Rule 7(a)(iii) may
  count a net plot left short of the 2,000 m² minimum by up to 10% when land was given up for
  road widening; nothing in the engine settles whether it does. The resolver already left such a
  site's plot-size ground UNVERIFIED; the validator's plot-size check failed it. Both now call
  `rules.high_rise_plot_met`: at or above the minimum, PASS; inside the allowance after road
  widening, UNVERIFIED in both, never a FAIL; further short, or short with no land given up, FAIL
  in both. The resolver's output is unchanged; the legacy checker, the height search and the
  floors calculator still hold the plain minimum (regression only). tests/test_plot_shortfall.py
  (each boundary case through the shared reading, the resolver and the validator).

## 2026-10-04: the service keeps the project's firm standards, writes down every approval, and has a host boundary

No characterization test changed, and contracts stay at 1.2. Nothing the legacy path produces
changed: `approval.ApprovalDesk.ask`, which the MCP server calls, answers exactly as before (it
now reads `ApprovalDesk.answer`, which tells a rejection from no answer). Each change is held by a
normative test.

- **The firm's standards are the approved project file's, else the workspace's, else the
  engine's default** (`service/standards.py`). Before, the service took every standard from the
  workspace file and wrote it over the project file's own, so a longest block the architect set
  in the project (Suchitra's 56 m) was dropped. Now the stilt and floor heights, the common-area
  loading, the cellar storey's height, the cellar utilities share, the deepest cellar and the
  longest block are each the project file's when the file states it (a value the file records
  as the engine's default yields to the workspace's own), else the workspace's, else the
  engine's default labelled ASSUMED_FOR_TEST; the flat and amenity libraries are the
  workspace's, as the legacy path finds them beside the project. For a project made through
  intake both pipelines take the same values. Each reaches the DesignBrief with source kind
  FIRM_STANDARD (an engine default was ENGINE_DEFAULT before), its status and a source naming
  the project file, the workspace file or the engine's default; the design margins are the
  workspace's, unchanged. No request carries a standard. The search is given only prototypes
  whose footprint's longer side is within the longest block; `list_prototypes` (new
  `left_out`), the proposal's notes and its approval lines name those left out, and with none
  left `propose_layouts` stops before anyone is asked. Tests: tests/test_service_standards.py
  (`test_each_standard_is_the_projects_else_the_workspaces_else_the_engines`,
  `test_the_search_and_the_validator_are_given_those_standards`,
  `test_no_tower_is_longer_than_the_firms_longest_block`,
  `test_the_legacy_path_and_the_service_agree_on_a_project_made_through_intake`,
  `test_no_request_can_carry_a_firm_standard`,
  `test_a_longest_block_no_prototype_fits_stops_before_anyone_is_asked`) and
  tests/test_service_client.py `test_the_longest_block_the_project_sets_is_kept_and_honoured`,
  where Suchitra's project now carries its own 56 m.
  Evidence, the service run on the two real sites as tests/test_service_client.py runs them,
  before and after: with no longest block set, Dhulapally (DEBUG) and Suchitra give the same
  three alternatives, figure for figure. With Suchitra's 56 m the kit loses two-core-large-12
  (61.34 m). No alternative used it before either (the longest block proposed was 45.61 m), but
  the full search picks each configuration's blocks from the kit and lays out and judges only
  the best-ranked configurations of each profile (the counts stay 1,152 evaluated, 112 laid
  out, 24 judged, 12 proposed), so a smaller kit changes which layouts are proposed, and two of
  the three alternatives change: MAX_YIELD stays 2 towers at stilt + 7, 98 flats, 117,012 sft;
  BALANCED goes from 2 towers at stilt + 8, 96 flats, 115,232 sft, to 2 towers at stilt + 7,
  84 flats, 100,828 sft; CONVENTIONAL_OPEN_SPACE goes from 1 tower, 64 flats, 76,112 sft, to
  2 towers, 80 flats, 96,736 sft. Every one is still UNVERIFIED with no legal FAIL, and no
  tower is longer than 45.61 m. The search is not monotone in its kit: taking away a prototype
  nothing used can still cost a layout it found before.
- **Every approval the service asks is written down before anything it allows runs**
  (`service/audit.py`, `models.ApprovalRecord`): the title and lines shown and their sha256, the
  decision (APPROVED, REJECTED, UNANSWERED or CHANNEL_FAILURE), the approver's class, the UTC
  time, and for an export the fresh report's UNVERIFIED items as it names them and its digest.
  Every one goes to `out/approvals.jsonl`, refused ones included, and a run's own to its
  `run.json` (`RunRecord.approvals`: the proposal, then each export approval asked on it);
  `validate_candidate` and `export_candidate` return the run's approvals read-only. Nothing in an
  entry comes from the caller. An approval that cannot be written down allows nothing. The
  person channels say which answer came (`decide`); `approve` is unchanged. Behaviour that
  changed: a refused proposal now writes that one line under `out` (before, nothing at all), so
  `test_nothing_runs_or_is_written_without_the_architects_approval` asserts the log is the only
  thing there; an export the person does not approve says which decision it was. Tests in
  tests/test_service.py (`test_the_proposal_is_asked_of_the_person_before_anything_runs`,
  `test_the_export_is_asked_before_anything_is_drawn`,
  `test_the_proposal_approval_is_in_the_run_record_and_the_service_log`,
  `test_an_export_records_the_fresh_reports_items_and_its_digest`,
  `test_nothing_in_an_entry_comes_from_the_caller`,
  `test_every_proposal_asked_is_logged_and_a_refusal_runs_nothing`,
  `test_an_approval_that_cannot_be_written_down_allows_nothing`,
  `test_an_export_the_person_does_not_approve_is_recorded_in_the_run_and_draws_nothing`; a FAIL
  is now also shown to be refused without asking anyone) and tests/test_service_approvers.py.
- **The host boundary** (`service/host.py`, `ToolHost(workspace, out, approver, mode)`): the
  nine operations as tools (name, description, input and output JSON schema; `call` validates
  against the request model and returns JSON), nothing else. Construction refuses any approver
  but the approval page itself (a terminal, any object with an approve method, a subclass) and an
  `out` inside or around the workspace. It imports only `siteplan.service`. No model or
  transport is connected. Tests: tests/test_service_host.py.
- **Test helpers**: `_copy_run` drops a copied run's exports, so a test starts from nothing
  drawn whatever ran before it; the injected-field and banned-word lists also cover the firm's
  standards and the approval; the import ban also covers the command line.

## 2026-10-04: one reading of a compass side; the rule inventory scans every module

No rule value changed and no characterization test changed. On the two real sites nothing moved:
Dhulapally's access side is W and Suchitra's is not known, and every row `tests/search_compare.py`
prints, LEGACY's and the full search's, is the same before and after. Held by normative tests:

- **One reading of a compass side, `geometry.faces`.** The envelope's frontage (legal/frontage.py:
  the access zones a gate may open in, the no-ramp front zone, the frontage strip), the full
  search's setbacks (optimizer/search/land.py) and the validator's front (validator/zones.py) now
  read a side one way, the validator's: a stretch faces a side when its outward normal is within
  45 degrees of the side's bearing, a diagonal label (SW) 22.5 degrees more, the limit included.
  The envelope read a strict 45 degrees for every label, so a diagonal label on a plot set square
  to the compass faced no stretch at all (no access zone, so the full search had nowhere to put a
  gate), on a plot turned off the compass it took one of the two stretches the validator holds to
  the front, and a stretch exactly 45 degrees off a cardinal label was the validator's front and
  not the envelope's. Only those cases change: the envelope's access zones, no-ramp front zone
  and frontage strip now run along every stretch the validator holds to the front, and the search
  may open its gate on any of them. The constants live once (`geometry.FACING_DEG`,
  `geometry.DIAGONAL_SLOP_DEG`); the copies in legal.frontage, optimizer.search.land and
  validator.zones are gone, and `angle_between` moved from validator.zones to geometry. The search
  keeps its own doubt band (`FACING_DOUBT_DEG`): a stretch that would change sides if turned a
  degree keeps the larger setback. tests/test_compass_side.py, for N, NE, E, SE, S, SW, W and NW
  on a plot set square and on plots turned 10 and 45 degrees:
  `test_the_envelopes_frontage_is_the_validators_front`,
  `test_the_envelopes_access_zones_run_along_the_validators_front`,
  `test_the_search_holds_the_validators_front_to_the_building_line`,
  `test_a_diagonal_label_on_a_square_set_plot_takes_both_sides_it_lies_between` and
  `test_a_stretch_within_a_degree_of_the_limit_keeps_the_larger_setback_in_the_search`. Run
  against the code before, the envelope's three fail in exactly those 28 cases and the search's
  two pass: its setbacks already read a side this way.
- **The legacy readings stay as they were.** The legacy entrance (`access._faces`) and the
  road-widening strip (`geometry.strip_along_side`, which places the net plot that the legacy
  runner and the site model both start from) keep a strict 45 degrees for every label: calling
  `faces` would widen both for a diagonal label and move the regression results and the net plot.
- **The inventory's scans cover every module.** `test_inventory.py` looked for a rule marked not
  applied in the top-level modules only, so `legal/`, `optimizer/`, `validator/`, `service/` and
  any new package escaped it. Now every module under src/siteplan is scanned unless it is exempt
  with its reason (rules.py, inventory.py, constraints.py), one added later in any package
  included; every module that imports rules.py is scanned; and every value or clause of rules.py
  that any module names has an entry.
  `test_a_rule_marked_not_applied_is_used_nowhere_but_where_it_is_carried`,
  `test_every_module_is_scanned_or_exempt_with_a_reason`,
  `test_a_module_added_in_any_package_is_scanned_without_being_named`,
  `test_the_scan_sees_every_way_of_importing_the_rules`,
  `test_no_module_that_names_a_rule_escapes_the_inventory`.
- **What the wider scan found, now said in the inventory as the code does it.** An entry may say
  that a rule it marks not applied is still carried as data (`Entry.carried_in`; `siteplan
  inventory` prints "not applied; carried in resolved rules"), and the scan allows the rule's
  names there and nowhere else. The road-widening shortfall of rule 7(a)(iii) was listed as never
  applied, but the resolver applies it: a site that surrenders land and falls short of 2,000 m²
  by no more than 10% of it keeps its plot-size ground unmet but UNVERIFIED, so its high-rise
  eligibility is UNVERIFIED rather than PROHIBITED (unless the road prohibits it); it is now
  INTERPRETED and applied in the resolved rules, and the entry says the validator's own
  plot-size check, the legacy checker, the height search and the floors calculator still hold
  such a site to 2,000 m². Carried and reported, never applied: the electricity-line distances of
  rule 3(c)(i) (ResolvedRules.electrical, which the validator reports UNVERIFIED wherever the
  survey marks a line), the parking-floor clause of rule 7(xvi) (a source of the open stilt
  reading) and the non-high-rise road-widening and TDR setback concessions
  (ResolvedRules.setbacks.concessions, with a note that the engine does not apply them). The
  tally is 24 as written, 14 interpreted, 3 assumed, 26 not modelled (13 interpreted and 27 not
  modelled before).

## 2026-10-04: the production service (siteplan.service)

No characterization test changed, and contracts stay at 1.2. Nothing the legacy path produces
changed. What is new, each held by a normative test (tests/test_service.py on made-up land,
tests/test_service_client.py on the two real sites, skipped on a clean clone):

- **`siteplan.service` is the production surface.** `Service(workspace, out, approver, mode)` is
  built by the host; the workspace is the only folder read (anything else is refused with one
  message, the reason logged), the Approver is asked of the person, and the mode is BLIND
  (blind.py's refusals) or DEBUG (allowed, every output says DEBUG RUN). Nine operations, each one
  frozen request model in (unknown fields refused) and one response model out: `start_project`
  (read-only: what the survey settles and the questions; answers go through `siteplan start`),
  `open_project`, `resolve_rules`, `inspect_envelope`, `list_prototypes`, `propose_layouts`,
  `validate_candidate`, `compare_candidates`, `export_candidate`. The firm's standards come from
  the workspace file only; the readings and the conservative test mode are as the project file
  states them. `test_no_operation_or_request_has_a_parameter_for_what_a_caller_may_not_set`,
  `test_a_request_refuses_every_field_a_caller_may_not_set`,
  `test_a_number_the_brief_never_writes_is_refused_before_anyone_is_asked`,
  `test_only_the_workspace_is_read`,
  `test_a_blind_service_refuses_the_firms_finished_plan_and_a_debug_one_says_so`.
- **The full search and the independent validator, never LEGACY and never optional.**
  `propose_layouts` asks the architect to approve the site facts (the access road's legal width
  and the land given up, each with its status), the readings and the brief, then runs `optimize`
  with `FullSearchStrategy` alone and no validator argument, and judges every alternative again
  with `siteplan.validator.validate` itself before storing it under `out/<run_id>/` with the
  digests of the site model, rules, brief and envelope.
  `test_the_service_runs_the_full_search_and_never_the_legacy_generator`,
  `test_the_service_imports_no_legacy_generator_or_checker`,
  `test_every_stored_candidate_has_a_report_the_service_made_itself`,
  `test_nothing_runs_or_is_written_without_the_architects_approval`.
- **Export judges again and never trusts a stored report.** It parses the stored contracts, holds
  every reference against the files and the recorded digests, and validates afresh; a legal FAIL,
  a blocking discrepancy, a report that could not measure the candidate or a broken reference is
  refused, and UNVERIFIED is exported only when the request names exactly its UNVERIFIED items and
  the architect approves them. Every output then lists them (a SOLVER-NOTES layer in the DXF, a
  SHEET-NOTES note on the A1 sheet, lines under the SVG, a section of the report); the program
  verdict never blocks or grants anything.
  `test_a_candidate_moved_into_the_setback_is_judged_again_and_refused`,
  `test_a_stored_report_turned_into_a_pass_is_not_trusted`,
  `test_a_contract_changed_after_the_run_breaks_its_digest_and_cannot_export`,
  `test_a_report_that_could_not_measure_the_candidate_is_never_exported`,
  `test_unverified_needs_exactly_its_items_and_the_architects_approval`,
  `test_every_output_lists_the_unresolved_items`, `test_every_output_of_a_debug_run_says_debug_run`.
- **The drawings are the candidate's own geometry.** The DXF uses layout_export's BuildNow layer
  names and road labels (imported, not copied); the A1 sheet uses sheet.py's scale, dimensions,
  north arrow, scale bar, border, statement column and title block. Those helpers now take plain
  geometry: `sheet._dimension` takes the footprints and `sheet._border` the rendered area
  statement (it also returns where the statement column and the title block are). The legacy sheet
  is unchanged: written before and after for two options of tests/test_sheet.py's layout under one
  hash seed, the files agree line for line apart from the save timestamps, the random GUIDs and
  ezdxf's version stamp (the order of the DXF CLASSES section follows Python's string hashing, so
  it differs between any two runs that do not fix the seed). tests/test_sheet.py is unchanged.
- **LEGACY marks, docstrings only**: layout, `heights.search_heights`, towers' placement, grounds,
  access's road generators, `runner.run_search`/`run_layout`, checks, access_checks,
  parking_checks, optimizer/legacy.py, and in mcp_server.py's module docstring `propose_layouts`
  and `check_rules` (the tools' own docstrings are what Hermes's model reads, so they are left as
  they were).

Not settled here: no runtime dependency draws a PDF (reportlab is a test dependency, PyMuPDF is
AGPL), so the export says so and the sheet is a DXF to plot; the Approver is a protocol no person
channel is wired to yet; a project file does not name its survey, so the requests that build the
site name it beside the project (`survey_file`).

## 2026-10-04: the number audit covers the new stages

No value, layout or verdict changed, and no characterization test changed. `constraints.py`
classified the prototype's modules only: `tests/test_constraints.py` scanned fifteen named modules,
so the numbers of `legal/`, `optimizer/`, `validator/`, `prototypes/`, `adapters/` and `contracts/`
went unclassified. Now, held by `tests/test_constraints.py` (normative):

- **Every module under `src/siteplan` is audited or exempt with its reason** (`AUDITED_PACKAGES`,
  `AUDITED_MODULES`, `EXEMPT`). A module in an audited package, `service/` included before it
  exists, is audited without being named; a new module anywhere else fails until it is audited
  or exempted. Class-level constants, ranges of numbers and the defaults of every model in an
  audited module (but 0, 1 or -1 on a record) are scanned too; eleven named numbers that are no
  domain number (an ordering, a unit, a bearing, a message length) are set aside by name
  (`NOT_DOMAIN`).
- **154 more numbers are classified**, in 17 new entries and 13 extended ones: 151
  ENGINE_DESIGN_ASSUMPTION (tolerances and slacks, search bounds, the full search's roads and
  reserve, the prototype families, the validator's cross-checks and refusals, the contracts'
  tolerances, the flat importer's figures), 2 FIRM_STANDARD (the area statement's and the
  assistant's copies of the workspace defaults) and 1 UNRESOLVED_INTERPRETATION
  (`quantities.QUARTER_TURN`, the square corner the 6.88 m fire band is derived for). No symbol
  changed basis. `siteplan constraints` and the acceptance report's section 3 list the new
  entries; the note on the road-widening shortfall now says the resolved rules call a near miss
  UNVERIFIED.
- **Three legal figures copied outside `rules.py` now read it**, the same numbers:
  `optimizer/floors.py` `CEILING_M` (Table IV's 120 m), `optimizer/search/network.py`
  `GATE_DEPTH_M` (rule 7(a)(viii)'s 2 m strip) and `MIN_STREET_LENGTH_M` (rule 8(m)'s 9 m road).
- **Inline literals that can change a result are named constants**, the same values:
  `fit.TRIM_WIDE_SHARE` (0.98), `build.ON_POCKET_SHARE` (0.5), `strategy.EVALUATE_SHARE` (0.35),
  `LAY_OUT_SHARE` (0.75) and `PITCH_GAP_M` (10 m) and `search.layout.CLUB_FLOORS` (2) in the full
  search; `fire.GATE_TOUCH_M` (0.5 m), `roads.HEAD_SLACK_M` (0.05 m), `roads.HEAD_CUT_M` (0.1 m),
  `open_space.AGREEMENT_SHARE` (0.005), `shapes.HEAL_M` and `shapes.CENTRE_TOLERANCE_M` (0.05 m)
  in the validator; `legacy_layout.ON_GROUND_SHARE` (0.5) in the adapter.
- **Copies of one number are held to one value** (`COPIES`): an entry that lists the
  validator's or the full search's own copy prints one of them, so the test fails if they part.

## 2026-10-04: C3, blocks below 21 m in the full search

No characterization test changed, and contracts stay at 1.2. LEGACY keeps to the high-rise counts it
always laid out (legacy.py filters them), so its options and notes are as they were. What now
behaves differently, each held by a normative test:

- **A floor count below 21 m stands on its own band's permission** (`optimizer/floors.py`,
  `FloorOption.permission`, read from `HeightRules.band_permission`), as a high-rise count stands on
  the site's eligibility: ALLOWED is offered; UNVERIFIED is offered and labelled UNVERIFIED (its
  reason among `open_items`); PROHIBITED is never offered and is FAIL, but no longer ends the scan,
  which now stops only where a height limit or the high-rise eligibility holds a count back (those
  only grow with the height; a taller band may be permitted where a lower one is not); a band the
  rules give no setback (18-21 m on most plots) is never offered. Such a count was NOT_CHECKED and
  never offered "until C3". test_optimizer_floors.py:
  `test_a_count_below_the_high_rise_height_is_offered_on_its_own_bands_permission` replaces
  `test_a_count_below_the_high_rise_height_is_assessed_but_not_offered_yet`;
  `test_where_a_high_rise_is_prohibited_no_high_rise_count_is_offered_and_lower_ones_stand_alone`
  replaces `test_where_a_high_rise_is_prohibited_no_count_is_offered_and_nothing_lower_either` (a
  prohibited high-rise still permits nothing lower: each lower count stands on its own band);
  `test_a_count_whose_band_is_prohibited_is_never_offered_and_does_not_stop_the_scan`,
  `test_a_count_whose_bands_permission_is_open_is_offered_labelled_unverified` and
  `test_a_band_with_no_setback_is_never_offered` are new; the counts expected by
  `test_every_feasible_count_is_returned_not_only_the_most`,
  `test_without_a_stilt_the_stilt_reading_cannot_matter`, `test_a_small_plots_road_gives_a_lower_limit`
  and `test_an_unsettled_eligibility_offers_high_rise_counts_labelled_unverified` now include the
  Table III counts (1 to 5 floors on a 3 m stilt).
- **The full search places blocks below 21 m wherever their band's land allows**
  (tests/test_search_low_blocks.py). A floor count carries its Table III figures (`FloorClass`: the
  side setback, the Building Line on the access road's frontage, the gap, the 1 m planting strip,
  whether it is a high-rise under any reading). In the columns such a block is one more choice. On
  the ground the ring road leaves (`optimizer/search/fringe.py`) it stands on its own land, the front
  held apart as the validator measures it (`land.setback_land`; which stretches face the access road
  is the engine's reading, classified in constraints.py), off the ring and its turns, out of
  the water buffer and the ground kept for the open space, a gap from every block: rule
  5(f)(xiii)'s taller side setback between two low blocks, the greater gap beside a high-rise (which
  holds under every reading of `mixed_height_spacing`), never less than a high-rise's 6 m lane and
  the room its tender turns in at a corner. It opens onto the ring road or, up to 12 m (physical,
  as the validator measures it), is reached by a 6 m `RoadKind.PATHWAY` branching out of it (rule
  8(l)); a taller block no road reaches is not placed. A fringe block is placed only while the free
  ground stays above what the club house, ramp, open space and facilities are expected to need (the
  search's own estimate, `Run.reserve_target_sqm`, never law). No fire lane or turning room is laid
  round a block that is not a high-rise (rule 15(a)(i) gives no figure: the validator lists it
  NOT_CHECKED), the strip Table III asks is drawn whenever such a block may stand, and the club
  house keeps the gap its own band asks. Any prototype of the kit may stand on the fringe, whatever
  its depth. `test_the_counts_below_21_m_carry_their_table_iii_figures`,
  `test_a_low_blocks_land_keeps_the_building_line_in_front_and_the_side_setback_elsewhere`,
  `test_two_low_blocks_keep_the_taller_ones_side_setback_and_a_high_rise_its_own_gap`,
  `test_low_blocks_on_the_fringe_keep_their_own_setbacks_and_the_front_is_held_apart`,
  `test_a_pathway_branches_out_of_the_ring_road_to_a_block_up_to_12_m`,
  `test_a_block_on_the_fringe_above_12_m_stands_against_a_road`,
  `test_a_low_block_never_stands_in_a_high_rises_fire_lane_or_turning_ground`,
  `test_a_layout_of_blocks_below_21_m_lays_no_fire_lane_and_draws_table_iii_planting`,
  `test_no_layout_with_a_low_block_is_offered_that_the_validator_fails`.
- **Every profile is searched with blocks below 21 m and without**, each kind on its own lay-out
  quota, the configurations without them evaluated first in C2's own order and their reserve
  variants made as before (a high-rise configuration with no room also tries its ends with blocks
  below 21 m, never the other way), so with no time budget cutting the run short the high-rise
  layouts C2 laid out are still laid out; the objective decides between the two kinds when they are
  judged, so the candidates proposed, and their numbering, may differ.
  `test_a_profile_with_counts_on_both_sides_of_21_m_is_searched_with_low_blocks_and_without`.
- **The acceptance criterion (ARCHITECTURE.md section 6, C3): each narrow part of the plot is tried
  for a block below 21 m and the notes say what came of it.** On the made-up L-plot the 24 m arm
  leaves 14 m between Table III's 5 m side setbacks, less than the kit's 24.13 m deep blocks, and
  the note says so with the numbers; with a made-up 13.13 m deep block in the kit a two-floor block
  fits there, some of the layouts proposed stand one there and others do not, and the note counts
  them. `test_the_arm_is_tried_for_a_low_block_and_says_why_none_stands_there`,
  `test_where_a_block_fits_the_arm_the_objective_decides_and_the_layouts_say_which_did`.
- **C2 tests whose meaning moved.** test_search_readings.py: the floor counts a profile leaves open
  now include 1 to 5 floors; test_search_strategy.py: with no floor count open at all the note says
  neither a high-rise nor a block below 21 m may stand, and the helper that finds a tower's deepest
  setback uses `HeightRules.band_for_block` (the bare-height lookup found no setback for a low block).

Not settled by the text, and left as it was read: a block above 12 m on the fringe needs a road and
the search draws no cul-de-sac or branch road to one, so it stands only against the ring; the
fringe's blocks run the columns' way (the other direction is another configuration).

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
