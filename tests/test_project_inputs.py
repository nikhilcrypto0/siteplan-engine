"""A project file's own inputs reach production, and none of them becomes law (2026-10-13, the
regulatory audit's phase 2).

- Readings a project selects for its studies, each with its source (who, when, whether the
  architect confirmed it or it is a study assumption), go from the project file through the
  service to the rules, the search's profiles, the validator and the stored report. The rules
  keep their legal sources beside the architect's words, and every reading is still judged.
- The application's status and date are site inputs. Where the application was received before
  G.O.Ms.No.95 of 2026, or nobody says when, a block of 18 to 21 m (a high-rise on the 2012 line
  and not on G.O.95's) is CONDITIONAL; a scheme not yet filed is judged on 21 m alone. Every
  report names the rule set it applied.
- A client requirement (the unit mix, the club house's size) stays in the brief: it never moves
  the rules.

Made-up land throughout. Every expected value is written out by hand.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from test_service import Approver, make_workspace
from validator_helpers import check, fixture
from validator_low_helpers import floors_of

from siteplan.contracts import ValidationReport
from siteplan.contracts.common import Provenance, SourceKind, Status
from siteplan.contracts.resolved_rules import CIRCULATION_IN_SETBACK, STILT_IN_RULE_HEIGHT
from siteplan.contracts.site_model import ApplicationStatus
from siteplan.contracts.validation import DependsOn
from siteplan.legal.readings import BACHUPALLY_PERMIT
from siteplan.legal.resolve import resolve
from siteplan.optimizer.search.verdicts import rests_on
from siteplan.service import ProposeLayouts, ResolveRules, Service
from siteplan.service.models import HeightChoice, Intent

TEST_CLASS = "normative"
PROJECT, SURVEY = "service-test.project.json", "survey.dxf"
ARCHITECT = "the architect, 2026-10-13"
SELECTED = {
    "nbc_fire_height": {"reading": "nbc_line", "source": ARCHITECT, "status": "USER_CONFIRMED"},
    "stilt_in_rule_height": {"reading": "not_counted", "source": "the architect, 2026-10-11",
                             "status": "USER_CONFIRMED"},
    "circulation_in_setback": {"reading": "allowed", "source": "a feasibility study, 2026-10-13"},
}
LINE = "High-rise line for this application"


def _edit_project(ws: Path, edit) -> None:
    path = ws / PROJECT
    project = json.loads(path.read_text())
    edit(project)
    path.write_text(json.dumps(project))


def _select(project: dict) -> None:
    project["layout"]["readings"] = SELECTED
    project["site"].update(application_status="FILED", application_date="2026-01-10")


@pytest.fixture(scope="module")
def ws(tmp_path_factory) -> Path:
    folder = make_workspace(tmp_path_factory.mktemp("inputs"))
    _edit_project(folder, _select)
    return folder


def _rules(ws: Path):
    return Service(ws, ws / "out", Approver()).resolve_rules(
        ResolveRules(project_file=PROJECT, survey_file=SURVEY))


# --- the readings, from the project file to the rules ------------------------------------------


def test_the_architects_selection_is_recorded_beside_the_law_and_every_reading_still_judged(ws):
    found = {i.id: i for i in _rules(ws).interpretations}
    nbc, stilt, roads = (found["nbc_fire_height"], found["stilt_in_rule_height"],
                         found["circulation_in_setback"])
    assert (nbc.selected, nbc.status) == ("nbc_line", Provenance.USER_CONFIRMED)
    assert ARCHITECT in nbc.sources
    assert any("NBC" in s for s in nbc.sources if s != ARCHITECT)  # the law's own, kept
    assert sorted(nbc.readings_evaluated) == ["nbc_line", "state_line"]  # both, still
    assert (stilt.selected, stilt.status) == ("not_counted", Provenance.USER_CONFIRMED)
    assert sorted(stilt.readings_evaluated) == ["counted", "not_counted"]
    assert (roads.selected, roads.status) == ("allowed", Provenance.ASSUMED_FOR_TEST)
    assert "a feasibility study, 2026-10-13 (a study assumption)" in roads.sources


def test_the_bachupally_permit_supports_the_stilt_reading_and_settles_nothing(ws):
    """2026-10-18: HMDA's Bachupally permit (Stilt + 12 at 35.4 m = 12 x 2.95 m) is supporting
    evidence for the stilt left out, beside the architect's selection; the reading stays open and
    both are still judged, so a result resting on it stays CONDITIONAL."""
    stilt = next(i for i in _rules(ws).interpretations if i.id == "stilt_in_rule_height")
    assert BACHUPALLY_PERMIT in stilt.sources
    assert "004812/BP/HMDA/1054/MED/2024" in BACHUPALLY_PERMIT and "35.4 m" in BACHUPALLY_PERMIT
    assert stilt.status is Provenance.USER_CONFIRMED  # the architect's selection, still open
    assert sorted(stilt.readings_evaluated) == ["counted", "not_counted"]
    unselected = resolve(fixture("rectangle").site).interpretation("stilt_in_rule_height")
    assert BACHUPALLY_PERMIT in unselected.sources and unselected.selected == "ALL"
    assert not unselected.settled


def test_a_reading_said_twice_two_ways_is_refused(tmp_path):
    folder = make_workspace(tmp_path)

    def twice(project):
        project["layout"]["stilt_in_rule_height"] = True  # counted, by the old switch
        project["layout"]["readings"] = {"stilt_in_rule_height": SELECTED["stilt_in_rule_height"]}
    _edit_project(folder, twice)
    with pytest.raises(Exception, match="say it once"):
        _rules(folder)


@pytest.fixture(scope="module")
def proposed(ws):
    service = Service(ws, ws / "out", Approver())
    result = service.propose_layouts(ProposeLayouts(
        project_file=PROJECT, survey_file=SURVEY, brief="The most floors the rules allow",
        intent=Intent(height=HeightChoice.MOST_THE_RULES_ALLOW)))
    return ws / "out" / result.run_id, result


def test_the_selection_reaches_the_search_the_validator_and_the_stored_reports(proposed):
    run, result = proposed
    assert result.candidates, "the made-up land takes a layout"
    rules = json.loads((run / "rules.json").read_text())
    nbc = next(i for i in rules["interpretations"] if i["id"] == "nbc_fire_height")
    assert nbc["selected"] == "nbc_line" and ARCHITECT in nbc["sources"]
    for shown in result.candidates:
        candidate = json.loads((run / "candidates" / f"{shown.candidate_id}.json").read_text())
        # the search builds for the stilt left out, as selected: never the counted reading
        assert candidate["interpretation_basis"]["stilt_in_rule_height"] in (
            "not_counted", "ALL")
        report = json.loads((run / "reports" / f"{shown.candidate_id}.json").read_text())
        assert report["schema_version"] == "1.4" and "study" in report["verdict"]
        for c in report["legal"]:
            for d in c.get("rests_on", []):
                if d["kind"] == "READING" and d["id"] in SELECTED:
                    assert d["selected"] == SELECTED[d["id"]]["reading"], (c, d)
        named = next(c for c in report["legal"] if c["finding"]["rule"] == "Rule set applied")
        assert "G.O.Ms.No.95 of 2026" in named["finding"]["measured"]
        assert "the application filed, received 10-01-2026" in named["finding"]["note"]


def test_with_readings_selected_the_search_lays_out_for_them_alone(proposed):
    """2026-10-18: a project file that selects readings is searched for those readings alone, no
    layout built for every reading nor for another one (what makes Dhulapally's run fast), and
    every verdict shown still names each open reading it rests on: the validator judges every
    reading of a question the law leaves open whatever the study selected."""
    run, result = proposed
    record = json.loads((run / "run.json").read_text())
    laid_for = {(c["basis"]["stilt_in_rule_height"], c["basis"]["circulation_in_setback"])
                for c in record["proposed_candidates"]}
    assert laid_for == {("not_counted", "allowed")}
    named = 0
    for shown in result.candidates:
        report = ValidationReport.model_validate_json(
            (run / "reports" / f"{shown.candidate_id}.json").read_text())
        rests = rests_on(report).readings
        assert not rests_on(report).holds_under_every_reading
        for reading in rests:
            assert reading in shown.verdict, (shown.candidate_id, reading, shown.verdict)
        named += STILT_IN_RULE_HEIGHT in rests or CIRCULATION_IN_SETBACK in rests
    assert named, "a layout built for the selections rests on them, and says so"


def test_a_client_requirement_stays_in_the_brief_and_never_moves_the_rules(ws, tmp_path):
    before = _rules(ws)
    other = make_workspace(tmp_path)

    def wants_more(project):
        _select(project)
        project["layout"]["club_house_sqm"] = 2500.0  # the client's 3%, say
        project["layout"]["unit_mix"] = {"2BHK": 0.5, "3BHK": 0.5}
    _edit_project(other, wants_more)
    after = _rules(other)
    assert after.model_dump(exclude={"project_name"}) == before.model_dump(
        exclude={"project_name"})


# --- the application's date, and the high-rise line in force -----------------------------------


def _dated(application: dict):
    """An edit giving the site's application as stated (nothing: nobody says)."""
    def edit(site):
        stated = site.jurisdiction.model_dump()
        for key, value in application.items():
            stated[key] = {"value": value, "status": Provenance.USER_CONFIRMED,
                           "source": ARCHITECT, "source_kind": SourceKind.ARCHITECT}
        site.jurisdiction = type(site.jurisdiction).model_validate(stated)
    return edit


def _line_rules(**application):
    """The made-up rectangle's rules from the resolver, for a site whose application stands as
    given (an empty call: nobody says)."""
    site = fixture("rectangle").with_site(_dated(application)).site
    site = type(site).model_validate(site.model_dump())
    return resolve(site).height.earlier_high_rise_m


def _with_line(line, **application):
    """The made-up rectangle with T3 at 6 floors on its 3 m stilt: 21 m with the stilt, 18 m
    without (rule 5(c)), so under the not_counted reading it stands between the 2012 line and
    G.O.95's; judged with the given 2012 line carried (or none), on the same application."""
    return floors_of(fixture("rectangle"), T3=6).with_site(_dated(application)).with_rules(
        lambda r: setattr(r.height, "earlier_high_rise_m", line))


def test_an_application_received_before_g_o_95_leaves_an_18_to_21_m_block_conditional():
    filed = {"application_status": ApplicationStatus.FILED,
             "application_date": date(2026, 1, 10)}
    line = _line_rules(**filed)
    assert line is not None and line.value == 18.0
    c = check(_with_line(line, **filed).report(), LINE)
    assert c.finding.status is Status.CONDITIONAL
    assert c.finding.measured == "T3: 18.00 m"
    (dep,) = c.rests_on
    assert dep.kind is DependsOn.RULE_GAP  # the order names no commencement date
    assert "10-01-2026" in c.finding.note


def test_an_application_nobody_dates_leaves_it_conditional_on_that_fact():
    line = _line_rules()
    assert line is not None
    c = check(_with_line(line).report(), LINE)
    assert c.finding.status is Status.CONDITIONAL
    assert [(d.kind, d.id) for d in c.rests_on] == [
        (DependsOn.SITE_FACT, "the application's status and the date it was received")]


@pytest.mark.parametrize("application", [
    {"application_status": ApplicationStatus.NOT_FILED},
    {"application_status": ApplicationStatus.FILED, "application_date": date(2026, 3, 21)},
    {"application_status": ApplicationStatus.SANCTIONED, "application_date": date(2026, 6, 1)}])
def test_a_new_scheme_or_one_received_on_or_after_g_o_95_is_judged_on_21_m_alone(application):
    assert _line_rules(**application) is None
    report = _with_line(None, **application).report()
    assert LINE not in {c.finding.rule for c in report.legal}


def test_a_block_outside_18_to_21_m_is_not_named():
    line = _line_rules()
    report = fixture("rectangle").with_rules(
        lambda r: setattr(r.height, "earlier_high_rise_m", line)).report()
    assert LINE not in {c.finding.rule for c in report.legal}  # its blocks are 24 m and more


def test_every_report_names_the_rule_set_it_applied():
    c = check(fixture("rectangle").report(), "Rule set applied")
    assert c.finding.status is Status.INFO
    assert "G.O.Ms.No.168 of 2012" in c.finding.measured
    assert "G.O.Ms.No.95 of 2026" in c.finding.measured
    assert "not read: G.O.Ms.No.245 of 2012" in c.finding.measured
