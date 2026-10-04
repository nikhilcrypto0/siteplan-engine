"""The production service (siteplan.service) on made-up land: what a caller may send, what it
gets back, and the gates nothing gets past.

A synthetic survey is written as a DXF, the test acts as the architect through the human intake
flow (`siteplan start --answers`), and the service then runs the whole pipeline: the site, the
rules, the envelope, the prototype kit, the full search, the independent validator, and the
drawings and report. The search runs once for the module; the tests that tamper with a run copy
it first. Nothing here comes from a client drawing.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import shutil
import sys
import typing
import uuid
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import ezdxf
import pytest
from pydantic import ValidationError
from shapely.errors import GEOSException

import siteplan.validator
from siteplan.cli import main as cli
from siteplan.contracts import CandidateLayout, ValidationReport, digest
from siteplan.contracts.design_brief import ParetoPoint
from siteplan.contracts.validation import LegalVerdict
from siteplan.optimizer import LegacyStrategy
from siteplan.optimizer.search import FullSearchStrategy
from siteplan.service import (
    Asked,
    CompareCandidates,
    Decision,
    ExportCandidate,
    ExportStatus,
    HeightChoice,
    InspectEnvelope,
    Intent,
    ListPrototypes,
    Mode,
    OpenProject,
    ProposeLayouts,
    ProposeStatus,
    ResolveRules,
    Service,
    ServiceError,
    StartProject,
    TerminalApprover,
    ValidateCandidate,
    audit,
    store,
)
from siteplan.service import service as service_module
from siteplan.service.models import REQUESTS
from siteplan.validator import refusals

TEST_CLASS = "normative"

EXAMPLES = Path(__file__).parent.parent / "examples"
SERVICE = Path(siteplan.validator.__file__).parent.parent / "service"
ANSWERS = {"main_road": "W", "road_row": "60 ft", "road_row_source": "2", "surrender": "no",
           "authority": "HMDA", "inside_cure": "no", "name": "Service test",
           "mix": "70% 2BHK, 30% 3BHK", "floors": "max"}
BRIEF = "The most floors the rules allow, 70% 2BHK and the rest 3BHK, balanced massing"
INTENT = Intent(height=HeightChoice.MOST_THE_RULES_ALLOW,
                unit_mix_percent={"2BHK": 70, "3BHK": 30}, massing=ParetoPoint.BALANCED)
OPERATIONS = ("start_project", "open_project", "resolve_rules", "inspect_envelope",
              "list_prototypes", "propose_layouts", "validate_candidate", "compare_candidates",
              "export_candidate")


class Approver:
    """The person, as a test plays them: answers every request the same way and remembers it
    (and, given a list, when it was asked)."""

    def __init__(self, answer: bool = True, events: list | None = None):
        self.answer, self.asked, self.events = answer, [], events

    def approve(self, title: str, lines: list[str]) -> bool:
        self.asked.append((title, list(lines)))
        if self.events is not None:
            self.events.append(("asked", title))
        return self.answer


def make_workspace(folder: Path, finished: tuple[str, ...] = (),
                   standards: dict | None = None) -> Path:
    """A survey, the firm's (made-up) libraries and workspace file (with any standards the firm
    sets), and the project file the architect's answers make through `siteplan start`."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.modelspace().add_lwpolyline([(0, 0), (150, 0), (150, 120), (0, 120)], close=True,
                                    dxfattribs={"layer": "SITE-BOUNDARY"})
    doc.modelspace().add_text("AREA: 18000 SQ.MTS", height=2).set_placement((10, -10))
    doc.saveas(folder / "survey.dxf")
    shutil.copy(EXAMPLES / "flat_library.example.json", folder / "flats.json")
    shutil.copy(EXAMPLES / "amenities.hyderabad.json", folder / "amenities.json")
    (folder / "siteplan.workspace.json").write_text(json.dumps(
        {"flat_library": "flats.json", "amenities": "amenities.json",
         "finished_plans": list(finished), **(standards or {})}))
    answers = folder / "answers.json"
    answers.write_text(json.dumps(ANSWERS))
    assert cli(["start", str(folder / "survey.dxf"), "--answers", str(answers)]) == 0
    return folder


@dataclass
class Ran:
    ws: Path
    service: Service
    approver: Approver
    proposed: object
    validated: list  # (calling module, digest of the candidate judged)
    optimized: list  # (args, kwargs) of every optimize call
    events: list  # ("asked", title) and ("optimize", "") in the order they happened


def _propose(service: Service, **intent) -> object:
    return service.propose_layouts(ProposeLayouts(
        project_file="service-test.project.json", survey_file="survey.dxf", brief=BRIEF,
        intent=Intent(**intent) if intent else INTENT))


@pytest.fixture(scope="module")
def ran(tmp_path_factory) -> Ran:
    ws = make_workspace(tmp_path_factory.mktemp("service"))
    events = []
    approver = Approver(events=events)
    service = Service(ws, ws / "out", approver)
    validated, optimized = [], []
    real_validate, real_optimize = siteplan.validator.validate, service_module.optimize

    def watch_validate(site, rules, brief, candidate, envelope=None):
        validated.append((sys._getframe(1).f_globals.get("__name__", ""), digest(candidate)))
        return real_validate(site, rules, brief, candidate, envelope)

    def watch_optimize(*args, **kwargs):
        optimized.append((args, kwargs))
        events.append(("optimize", ""))
        return real_optimize(*args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(siteplan.validator, "validate", watch_validate)
        patch.setattr(service_module, "optimize", watch_optimize)
        proposed = _propose(service)
    return Ran(ws, service, approver, proposed, validated, optimized, events)


def _first(ran: Ran):
    return ran.proposed.candidates[0]


def _items(ran: Ran) -> list[str]:
    """The UNVERIFIED items of the first candidate, as validate_candidate names them now."""
    checked = ran.service.validate_candidate(ValidateCandidate(
        run_id=ran.proposed.run_id, candidate_id=_first(ran).candidate_id))
    return [item.item for item in checked.unverified]


@pytest.fixture(scope="module")
def exported(ran: Ran):
    items = _items(ran)
    return items, ran.service.export_candidate(ExportCandidate(
        run_id=ran.proposed.run_id, candidate_id=_first(ran).candidate_id,
        acknowledged_unresolved=items))


def _copy_run(ran: Ran, mode: Mode | None = None) -> str:
    """A copy of the module's run under a new id, with nothing exported yet, so a test may
    tamper with it."""
    out, new = ran.ws / "out", uuid.uuid4().hex[:12]
    shutil.copytree(out / ran.proposed.run_id, out / new)
    shutil.rmtree(out / new / "exports", ignore_errors=True)
    record = json.loads((out / new / "run.json").read_text())
    record["run_id"] = new
    if mode is not None:
        record["mode"] = mode.value
    (out / new / "run.json").write_text(json.dumps(record))
    return new


def _texts(dxf: str) -> str:
    msp = ezdxf.readfile(dxf).modelspace()
    return "\n".join([e.dxf.text for e in msp.query("TEXT")]
                     + [e.plain_text() for e in msp.query("MTEXT")])


# --- 1. The full search, never LEGACY --------------------------------------------------------


def test_the_service_runs_the_full_search_and_never_the_legacy_generator(ran):
    assert ran.proposed.status is ProposeStatus.PROPOSED, ran.proposed.notes
    assert ran.optimized, "optimize was never called"
    for args, kwargs in ran.optimized:
        strategies = args[3]
        assert strategies and all(isinstance(s, FullSearchStrategy) for s in strategies)
        assert not any(isinstance(s, LegacyStrategy) for s in strategies)
        assert "validator" not in kwargs  # the core then judges with siteplan.validator
    assert all(c.strategy == "FULL" for c in ran.proposed.candidates)
    for path in (ran.ws / "out" / ran.proposed.run_id / "candidates").glob("*.json"):
        assert CandidateLayout.model_validate_json(path.read_text()).strategy == "FULL"
    balanced = [c for c in ran.proposed.candidates if c.pareto_point == "BALANCED"]
    if balanced:  # the massing the brief prefers comes first, and says so
        assert ran.proposed.candidates[0] is balanced[0] and balanced[0].preferred_massing


LEGACY = {"layout", "heights", "towers", "grounds", "access", "runner", "checks", "access_checks",
          "parking_checks", "parking", "acceptance", "cases", "mcp_server", "assistant"}
# Nor the command line: it drives the service from outside (siteplan propose), never the reverse.
BANNED = LEGACY | {"cli"}
LEGACY_DEEP = ("siteplan.optimizer.legacy", "siteplan.prototypes.legacy")
LEGACY_NAMES = {"LegacyStrategy", "LegacyRun", "legacy", "legacy_tower"}


def _imports(source: str) -> list[tuple[str, tuple[str, ...]]]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(alias.name, ()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", tuple(alias.name for alias in node.names)))
    return found


def _legacy(module: str, names: tuple[str, ...]) -> list[str]:
    parts = module.split(".")
    wrong = []
    if parts[0] == "siteplan" and len(parts) > 1 and parts[1] in BANNED:
        wrong.append(module)
    if module == "siteplan":
        wrong += [f"siteplan.{n}" for n in names if n in BANNED]
    if any(module == deep or module.startswith(deep + ".") for deep in LEGACY_DEEP):
        wrong.append(module)
    if module.startswith("siteplan") and set(names) & LEGACY_NAMES:
        wrong += [f"{module}.{n}" for n in set(names) & LEGACY_NAMES]
    return wrong


def test_the_scanner_sees_every_way_of_importing_the_legacy_path():
    for source in ("import siteplan.layout", "from siteplan.towers import place",
                   "from siteplan import grounds", "def f():\n    from siteplan.runner import x",
                   "from siteplan.optimizer import LegacyStrategy",
                   "from siteplan.optimizer.legacy import LegacyRun",
                   "from siteplan.cli import main", "from siteplan import cli",
                   "import siteplan.mcp_server"):
        assert [w for m, n in _imports(source) for w in _legacy(m, n)], source


def test_the_service_imports_no_legacy_generator_or_checker():
    files = sorted(SERVICE.glob("*.py"))
    assert {f.name for f in files} >= {"service.py", "judge.py", "render.py", "store.py",
                                       "host.py", "audit.py", "standards.py"}
    offenders = {path.name: wrong for path in files
                 if (wrong := [w for m, n in _imports(path.read_text()) for w in _legacy(m, n)])}
    assert not offenders, offenders


# --- 2. Every candidate is judged again by the service itself --------------------------------


def test_every_stored_candidate_has_a_report_the_service_made_itself(ran):
    by_service = {d for caller, d in ran.validated if caller.startswith("siteplan.service")}
    folder = ran.ws / "out" / ran.proposed.run_id
    record = json.loads((folder / "run.json").read_text())
    assert record["candidates"]
    for entry in record["candidates"]:
        assert entry["digest"] in by_service, entry["candidate_id"]
        stored = json.loads((folder / "reports" / f"{entry['candidate_id']}.json").read_text())
        assert stored["candidate_ref"] == entry["digest"]
        assert stored["verdict"]["legal"] != LegalVerdict.FAIL.value
    assert {c.candidate_id for c in ran.proposed.candidates} == {
        e["candidate_id"] for e in record["candidates"]}


def test_validate_candidate_judges_the_stored_contracts_again(ran, monkeypatch):
    calls = []
    real = siteplan.validator.validate

    def watch(site, rules, brief, candidate, envelope=None):
        calls.append(digest(candidate))
        return real(site, rules, brief, candidate, envelope)

    monkeypatch.setattr(siteplan.validator, "validate", watch)
    checked = ran.service.validate_candidate(ValidateCandidate(
        run_id=ran.proposed.run_id, candidate_id=_first(ran).candidate_id))
    assert len(calls) == 1 and checked.refusals == []
    assert checked.legal_verdict is _first(ran).legal_verdict
    assert {f.family for f in checked.checks_by_family}  # every check, by family


# --- 3. A FAIL cannot be exported ------------------------------------------------------------


def _tower_into_the_setback(ran: Ran, run_id: str, candidate_id: str) -> None:
    folder = ran.ws / "out" / run_id
    site = json.loads((folder / "site.json").read_text())
    west = min(x for x, _ in site["net_plot"]["value"]["outer"])
    path = folder / "candidates" / f"{candidate_id}.json"
    candidate = json.loads(path.read_text())
    tower = candidate["towers"][0]
    dx = west + 0.5 - min(x for x, _ in tower["footprint"]["outer"])
    tower["x"] += dx
    tower["footprint"]["outer"] = [[x + dx, y] for x, y in tower["footprint"]["outer"]]
    path.write_text(json.dumps(candidate))


def _report_into_a_pass(ran: Ran, run_id: str, candidate_id: str) -> None:
    path = ran.ws / "out" / run_id / "reports" / f"{candidate_id}.json"
    report = json.loads(path.read_text())
    report["legal"] = [c for c in report["legal"] if c["finding"]["status"] == "PASS"]
    report["cross_checks"] = []
    report["verdict"] = {**report["verdict"], "legal": "PASS", "reasons": []}
    path.write_text(json.dumps(report))


def test_a_candidate_moved_into_the_setback_is_judged_again_and_refused(ran):
    items = _items(ran)
    run_id, candidate_id = _copy_run(ran), _first(ran).candidate_id
    _tower_into_the_setback(ran, run_id, candidate_id)
    _report_into_a_pass(ran, run_id, candidate_id)  # what was stored says nothing either way
    asked = len(ran.approver.asked)
    recorded = len(store.read_record(ran.ws / "out", run_id).approvals)
    result = ran.service.export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=candidate_id, acknowledged_unresolved=items))
    assert result.status is ExportStatus.REFUSED and result.legal_verdict is LegalVerdict.FAIL
    assert any(r.startswith("FAIL All-round setback") for r in result.reasons), result.reasons
    assert any("stored candidate changed since the run" in r for r in result.reasons)
    assert not (ran.ws / "out" / run_id / "exports").exists()
    assert len(ran.approver.asked) == asked  # a FAIL is never put to the person: it never ships
    assert len(result.approvals) == recorded  # so nothing was asked, and nothing recorded


def test_a_stored_report_turned_into_a_pass_is_not_trusted(ran):
    run_id, candidate_id = _copy_run(ran), _first(ran).candidate_id
    _report_into_a_pass(ran, run_id, candidate_id)
    compared = ran.service.compare_candidates(CompareCandidates(
        run_id=run_id, candidate_ids=[candidate_id]))
    assert compared.rows[0].legal_verdict is LegalVerdict.PASS  # what was stored
    result = ran.service.export_candidate(ExportCandidate(run_id=run_id,
                                                          candidate_id=candidate_id))
    assert result.status is ExportStatus.REFUSED
    assert result.legal_verdict is LegalVerdict.UNVERIFIED  # what the validator finds now
    assert result.reasons[0].startswith("not acknowledged")


def test_a_contract_changed_after_the_run_breaks_its_digest_and_cannot_export(ran):
    items = _items(ran)
    run_id, candidate_id = _copy_run(ran), _first(ran).candidate_id
    path = ran.ws / "out" / run_id / "rules.json"
    rules = json.loads(path.read_text())
    rules["orders"][0]["note"] += " (edited)"
    path.write_text(json.dumps(rules))
    result = ran.service.export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=candidate_id, acknowledged_unresolved=items))
    assert result.status is ExportStatus.REFUSED
    assert any("rules.json changed since the run" in r for r in result.reasons)
    assert any(r.startswith("candidate.rules_ref") for r in result.reasons)


def test_a_report_that_could_not_measure_the_candidate_is_never_exported(ran, monkeypatch):
    def unmeasured(site, rules, brief, candidate, envelope=None):
        return refusals.unmeasurable(site, rules, brief, candidate, envelope,
                                     refusals.library_check(GEOSException("planted")))

    monkeypatch.setattr(siteplan.validator, "validate", unmeasured)
    asked = len(ran.approver.asked)
    items = _items(ran)
    assert items == ["Shapes the geometry library can measure"]  # UNVERIFIED, not FAIL
    result = ran.service.export_candidate(ExportCandidate(
        run_id=ran.proposed.run_id, candidate_id=_first(ran).candidate_id,
        acknowledged_unresolved=items))
    assert result.status is ExportStatus.REFUSED
    assert "the validator could not measure the candidate's towers" in result.reasons
    assert len(ran.approver.asked) == asked  # nothing to approve: it is refused outright


# --- 4. UNVERIFIED stays visibly unresolved --------------------------------------------------


def test_unverified_needs_exactly_its_items_and_the_architects_approval(ran):
    items = _items(ran)
    assert items and _first(ran).legal_verdict is LegalVerdict.UNVERIFIED
    run_id, candidate_id = ran.proposed.run_id, _first(ran).candidate_id
    for given in ([], items[:-1], [*items, "Something nobody found"]):
        result = ran.service.export_candidate(ExportCandidate(
            run_id=run_id, candidate_id=candidate_id, acknowledged_unresolved=given))
        assert result.status is ExportStatus.REFUSED, given
        assert result.unverified == items and not result.files
    no = Approver(False)
    refused = Service(ran.ws, ran.ws / "out", no).export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=candidate_id, acknowledged_unresolved=items))
    assert refused.status is ExportStatus.NOT_APPROVED and not refused.files
    title, lines = no.asked[-1]
    assert str(len(items)) in title
    assert all(any(item in line for line in lines) for item in items)


def test_every_output_lists_the_unresolved_items(ran, exported):
    items, result = exported
    assert result.status is ExportStatus.EXPORTED, result.reasons
    assert result.unverified == items and not result.debug_run
    title, lines = ran.approver.asked[-1]
    assert all(any(item in line for line in lines) for item in items)
    files = {Path(f).name.split(".", 1)[1]: f for f in result.files}
    plain = ezdxf.readfile(files["dxf"]).modelspace()
    noted = " ".join(e.dxf.text for e in plain.query("TEXT[layer=='SOLVER-NOTES']"))
    sheet = " ".join(e.plain_text() for e in ezdxf.readfile(files["sheet.dxf"]).modelspace()
                     .query("MTEXT[layer=='SHEET-NOTES']"))
    svg = " ".join(t.text or "" for t in ElementTree.parse(files["svg"]).iter()
                   if t.tag.endswith("text"))
    report = Path(files["report.txt"]).read_text()
    section = report.split("3. UNRESOLVED")[1].split("4. NOT CHECKED")[0]
    for item in items:
        assert item in noted and item in section
        for wrapped in (sheet, svg):  # the sheet and the SVG wrap long lines
            assert " ".join(item.split()) in " ".join(wrapped.split()), item
    assert "DEBUG RUN" not in report


# --- 5. Nothing legal, site, provenance, reading, profile, validator or strategy gets in ---------


VALID = {"StartProject": {"survey_file": "survey.dxf"},
         "OpenProject": {"project_file": "p.json"}, "ResolveRules": {"project_file": "p.json"},
         "InspectEnvelope": {"project_file": "p.json"},
         "ListPrototypes": {"project_file": "p.json"},
         "ProposeLayouts": {"project_file": "p.json", "brief": BRIEF},
         "ValidateCandidate": {"run_id": "0123456789ab", "candidate_id": "full-ALL-ALL-1"},
         "CompareCandidates": {"run_id": "0123456789ab", "candidate_ids": ["full-ALL-ALL-1"]},
         "ExportCandidate": {"run_id": "0123456789ab", "candidate_id": "full-ALL-ALL-1"},
         "Intent": {}}
INJECTED = {"setback_m": 10.0, "front_setback_m": 3.0, "abutting_road_m": 18.29,
            "abutting_road_ft": 60, "legal_row_m": 24.0, "net_plot_m": [[0, 0], [1, 0], [1, 1]],
            "net_area_sqm": 18000, "site_coordinates": [17.5, 78.4],
            "_status": {"abutting_road": "VERIFIED"}, "_source": {"road_row": "certified"},
            "_source_kind": {"net_plot_m": "ARCHITECT"}, "status": "VERIFIED",
            "selections": {"stilt_in_rule_height": "not_counted"},
            "stilt_in_rule_height": False, "circulation_in_setback": True,
            "when_open": "CONSERVATIVE", "conservative_parking": True,
            "readings": {"stilt_in_rule_height": "not_counted"},
            "profile": {"name": "x", "purpose": "y"}, "debug_fixture": True,
            "validator": "none", "strategies": ["LEGACY"], "stilt_height_m": 2.0,
            "floor_height_m": 2.5, "mode": "DEBUG",
            # the firm's standards: the project file's, else the workspace's, never a caller's
            "max_tower_length_m": 200.0, "common_area_pct": 10.0, "cellar_floor_height_m": 2.0,
            "cellar_utilities_pct": 0.0, "max_cellars": 6, "flat_library": "elsewhere.json",
            "amenities": "elsewhere.json", "design_margins": {"setback_extra_m": 0},
            # the approval: asked of the person by the host's channel, never answered here
            "approved": True, "approve": True, "approval": "APPROVED", "decision": "APPROVED",
            "approver": "terminal", "approvals": [], "channel": "page",
            "workspace": "/", "out": "/tmp"}


@pytest.mark.parametrize("model", REQUESTS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("key", sorted(INJECTED))
def test_a_request_refuses_every_field_a_caller_may_not_set(model, key):
    model.model_validate(VALID[model.__name__])  # the request itself is valid
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate({**VALID[model.__name__], key: INJECTED[key]})


def test_an_intent_nested_in_a_request_refuses_them_too_and_requests_are_frozen():
    for key in ("setback_m", "_status", "selections", "validator", "strategies"):
        with pytest.raises(ValidationError):
            ProposeLayouts.model_validate({**VALID["ProposeLayouts"],
                                           "intent": {key: INJECTED[key]}})
    request = ProposeLayouts.model_validate(VALID["ProposeLayouts"])
    with pytest.raises(ValidationError):
        request.project_file = "elsewhere.json"
    with pytest.raises(ValidationError):  # a height named with no floors is asked, not guessed
        Intent(height=HeightChoice.FLOORS_ABOVE_STILT)


ALLOWED_FIELDS = {"survey_file", "project_file", "brief", "intent", "run_id", "candidate_id",
                  "candidate_ids", "acknowledged_unresolved", "height", "floors_above_stilt",
                  "unit_mix_percent", "massing"}
BANNED_WORDS = ("validator", "strateg", "selection", "profile", "when_open", "conservative",
                "status", "source", "provenance", "setback", "coordinate", "reading", "width",
                "legal", "mode", "debug", "approv", "decision", "channel", "standard", "library",
                "amenit", "loading", "cellar", "length", "margin", "workspace")


def test_no_operation_or_request_has_a_parameter_for_what_a_caller_may_not_set():
    public = sorted(name for name, _ in inspect.getmembers(Service, inspect.isfunction)
                    if not name.startswith("_"))
    assert public == sorted(OPERATIONS)
    for name in OPERATIONS:
        method = getattr(Service, name)
        assert list(inspect.signature(method).parameters) == ["self", "request"], name
        hints = typing.get_type_hints(method)
        assert hints["request"] in REQUESTS, name
    assert list(inspect.signature(Service.__init__).parameters) == [
        "self", "workspace", "out", "approver", "mode"]
    fields = {field for model in REQUESTS for field in model.model_fields}
    assert fields <= ALLOWED_FIELDS, fields - ALLOWED_FIELDS
    assert not [f for f in fields for word in BANNED_WORDS if word in f]


def test_a_number_the_brief_never_writes_is_refused_before_anyone_is_asked(ran):
    asked = len(ran.approver.asked)
    with pytest.raises(ServiceError, match="floors above the stilt 9"):
        _propose(ran.service, height=HeightChoice.FLOORS_ABOVE_STILT, floors_above_stilt=9)
    with pytest.raises(ServiceError, match="unit mix 2BHK 60"):
        _propose(ran.service, unit_mix_percent={"2BHK": 60, "3BHK": 40})
    with pytest.raises(ServiceError, match="no \\['4BHK'\\]"):
        _propose(ran.service, unit_mix_percent={"4BHK": 70, "3BHK": 30})
    assert len(ran.approver.asked) == asked


def test_nothing_runs_or_is_written_without_the_architects_approval(ran):
    no = Approver(False)
    out = ran.ws / "out-refused"
    result = _propose(Service(ran.ws, out, no))
    assert result.status is ProposeStatus.NOT_APPROVED and result.run_id is None
    title, lines = no.asked[0]
    assert title.startswith("Generate layout options")
    shown = "\n".join(lines)
    for words in ("access road: legal right of way: 18.29 m [USER_CONFIRMED", "net plot outline",
                  "Height (the brief): the most the rules allow", "2BHK 70%", BRIEF):
        assert words in shown, words
    # No run: the only thing written is the refusal itself, in the approvals log.
    assert sorted(p.name for p in out.iterdir()) == [audit.LOG]
    (entry,) = audit.read(out)
    assert entry.decision is Decision.REJECTED and entry.run_id is None


def test_only_the_workspace_is_read(ran):
    outside = ran.ws.parent / "elsewhere.dxf"
    shutil.copy(ran.ws / "survey.dxf", outside)
    link = ran.ws / "linked.dxf"
    link.symlink_to(outside)
    for name in ("../elsewhere.dxf", str(outside), "linked.dxf", "missing.dxf",
                 "flats.json"):
        with pytest.raises(ServiceError, match="is not a readable file in the workspace"):
            ran.service.start_project(StartProject(survey_file=name))


# --- 6. Raw survey to drawings on made-up land -----------------------------------------------


def test_from_a_raw_survey_through_intake_to_drawings_that_open(ran, exported):
    started = ran.service.start_project(StartProject(survey_file="survey.dxf"))
    assert {"road_row", "dead_end", "surrender", "mix", "floors"} <= {
        q.key for q in started.questions}
    assert started.settled[0].value == 18000.0 and "siteplan start" in started.next
    files = {"project_file": "service-test.project.json", "survey_file": "survey.dxf"}
    opened = ran.service.open_project(OpenProject(**files))
    assert opened.run_kind is Mode.BLIND and opened.net_plot_placed and not opened.stop
    assert opened.readings_stated == {} and not opened.conservative_parking
    rules = ran.service.resolve_rules(ResolveRules(**files))
    assert rules.group_development and rules.high_rise_eligibility.value == "ALLOWED"
    assert any("airport" in item for item in rules.unverified)
    land = ran.service.inspect_envelope(InspectEnvelope(**files))
    assert land.net_plot_sqm == 18000.0 and any(b.buildable_sqm > 0 for b in land.bands)
    kit = ran.service.list_prototypes(ListPrototypes(project_file=files["project_file"]))
    assert len(kit.prototypes) >= 2 and kit.unit_mix == {"2BHK": 0.7, "3BHK": 0.3}
    compared = ran.service.compare_candidates(CompareCandidates(
        run_id=ran.proposed.run_id, candidate_ids=[c.candidate_id for c in
                                                   ran.proposed.candidates]))
    assert len(compared.rows) == len(ran.proposed.candidates) and compared.findings
    _, result = exported
    assert result.status is ExportStatus.EXPORTED and result.not_produced  # no PDF yet
    for name in result.files:
        assert Path(name).is_file(), name
        if name.endswith(".dxf"):
            ezdxf.readfile(name)
    sheet = next(f for f in result.files if f.endswith(".sheet.dxf"))
    layers = {e.dxf.layer for e in ezdxf.readfile(sheet).modelspace()}
    assert {"Plot", "Building Plan", "Dwelling Unit", "SHEET-BORDER", "SHEET-NOTES"} <= layers
    assert "AREA STATEMENT" in _texts(sheet)
    ElementTree.parse(next(f for f in result.files if f.endswith(".svg")))
    report = Path(next(f for f in result.files if f.endswith(".report.txt"))).read_text()
    for heading in ("1. LEGAL VERDICT: UNVERIFIED", "2. CHECKS BY FAMILY", "SETBACK",
                    "5. DESIGN TARGETS", "6. PROGRAM", "8. AREA STATEMENT", "TOTAL SITE AREA"):
        assert heading in report, heading


# --- Blind and debug -------------------------------------------------------------------------


def test_a_blind_service_refuses_the_firms_finished_plan_and_a_debug_one_says_so(tmp_path):
    ws = make_workspace(tmp_path, finished=("survey.dxf",))
    asked = Approver()
    blind = Service(ws, ws / "out", asked)
    files = {"project_file": "service-test.project.json", "survey_file": "survey.dxf"}
    with pytest.raises(ServiceError, match="finished plan"):
        blind.start_project(StartProject(survey_file="survey.dxf"))
    with pytest.raises(ServiceError, match="finished plan"):
        blind.open_project(OpenProject(**files))
    with pytest.raises(ServiceError, match="finished plan"):
        blind.propose_layouts(ProposeLayouts(**files, brief=BRIEF, intent=INTENT))
    assert not asked.asked
    opened = Service(ws, ws / "out", asked, mode=Mode.DEBUG).open_project(OpenProject(**files))
    assert opened.run_kind is Mode.DEBUG
    assert opened.finished_plan_inputs[0] == ("the survey survey.dxf is one of the firm's "
                                              "finished plans")
    assert any(i.startswith("net_plot") for i in opened.finished_plan_inputs)  # its outline


def test_every_output_of_a_debug_run_says_debug_run(ran):
    run_id = _copy_run(ran, mode=Mode.DEBUG)
    candidate_id = _first(ran).candidate_id
    with pytest.raises(ServiceError, match="blind service"):
        ran.service.validate_candidate(ValidateCandidate(run_id=run_id,
                                                         candidate_id=candidate_id))
    debug = Service(ran.ws, ran.ws / "out", Approver(), mode=Mode.DEBUG)
    items = [i.item for i in debug.validate_candidate(ValidateCandidate(
        run_id=run_id, candidate_id=candidate_id)).unverified]
    result = debug.export_candidate(ExportCandidate(run_id=run_id, candidate_id=candidate_id,
                                                    acknowledged_unresolved=items))
    assert result.status is ExportStatus.EXPORTED and result.debug_run
    for name in result.files:
        text = _texts(name) if name.endswith(".dxf") else Path(name).read_text()
        if name.endswith(".validation.json"):
            continue  # the validator's own report, unchanged
        assert "DEBUG RUN" in text, name
    report = next(f for f in result.files if f.endswith(".report.txt"))
    assert Path(report).read_text().startswith("DEBUG RUN")


# --- The person's approval, asked before anything runs and written down -----------------------


def _export_items(ran: Ran) -> tuple[str, str, list[str]]:
    """A fresh copy of the module's run, its first candidate and that candidate's items."""
    return _copy_run(ran), _first(ran).candidate_id, _items(ran)


def test_the_proposal_is_asked_of_the_person_before_anything_runs(ran):
    title = f"Generate layout options for {ANSWERS['name']}"
    assert ran.events[:2] == [("asked", title), ("optimize", "")]


def test_the_export_is_asked_before_anything_is_drawn(ran):
    run_id, candidate_id, items = _export_items(ran)
    folder = ran.ws / "out" / run_id / "exports"
    drawn_when_asked = []

    class Watching(Approver):
        def approve(self, title: str, lines: list[str]) -> bool:
            drawn_when_asked.append(folder.exists())
            return super().approve(title, lines)

    result = Service(ran.ws, ran.ws / "out", Watching()).export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=candidate_id, acknowledged_unresolved=items))
    assert drawn_when_asked == [False]
    assert result.status is ExportStatus.EXPORTED and all(Path(f).is_file() for f in result.files)


def test_the_proposal_approval_is_in_the_run_record_and_the_service_log(ran):
    checked = ran.service.validate_candidate(ValidateCandidate(
        run_id=ran.proposed.run_id, candidate_id=_first(ran).candidate_id))
    proposal = checked.approvals[0]
    title, lines = ran.approver.asked[0]
    assert proposal.asked is Asked.PROPOSAL and proposal.decision is Decision.APPROVED
    assert (proposal.title, list(proposal.lines)) == (title, lines)  # exactly what was shown
    shown = json.dumps({"title": title, "lines": lines}, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    assert proposal.asked_digest == hashlib.sha256(shown.encode()).hexdigest()
    assert proposal.channel == "Approver" and proposal.run_id == ran.proposed.run_id
    assert datetime.fromisoformat(proposal.at).utcoffset() == timedelta(0)
    assert proposal in audit.read(ran.ws / "out")
    with pytest.raises(ValidationError):  # read-only: what a caller gets back cannot be changed
        proposal.decision = Decision.REJECTED


def test_an_export_records_the_fresh_reports_items_and_its_digest(ran, exported):
    items, result = exported
    entry = result.approvals[-1]
    assert entry.asked is Asked.EXPORT and entry.decision is Decision.APPROVED
    assert (entry.run_id, entry.candidate_id) == (ran.proposed.run_id, _first(ran).candidate_id)
    assert list(entry.acknowledged) == items
    fresh = next(f for f in result.files if f.endswith(".validation.json"))
    assert entry.report_digest == digest(ValidationReport.model_validate_json(
        Path(fresh).read_text()))
    record = store.read_record(ran.ws / "out", ran.proposed.run_id)
    assert entry in record.approvals and record.approvals[0].asked is Asked.PROPOSAL
    assert entry in audit.read(ran.ws / "out")


def test_nothing_in_an_entry_comes_from_the_caller(ran):
    run_id, candidate_id, items = _export_items(ran)
    given = [*reversed(items), items[0]]  # the same items in another order, one given twice
    recorded = len(store.read_record(ran.ws / "out", run_id).approvals)
    result = ran.service.export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=candidate_id, acknowledged_unresolved=given))
    assert result.status is ExportStatus.EXPORTED
    (entry,) = result.approvals[recorded:]
    assert list(entry.acknowledged) == items  # as the fresh report names them, each once
    assert (entry.run_id, entry.candidate_id) == (run_id, candidate_id)  # the stored run's
    assert entry.channel == type(ran.approver).__name__  # the host's channel, never a field


class Broken:
    def approve(self, title: str, lines: list[str]) -> bool:
        raise OSError("the channel went away")


@pytest.mark.parametrize(("approver", "decision"), [
    (Approver(False), Decision.REJECTED),
    (TerminalApprover(interactive=lambda: False), Decision.UNANSWERED),
    (Broken(), Decision.CHANNEL_FAILURE)], ids=["rejected", "unanswered", "broken"])
def test_every_proposal_asked_is_logged_and_a_refusal_runs_nothing(ran, tmp_path, approver,
                                                                    decision):
    out = tmp_path / "out"
    result = _propose(Service(ran.ws, out, approver))
    assert result.status is ProposeStatus.NOT_APPROVED and not list(out.glob("*/run.json"))
    (entry,) = audit.read(out)
    assert (entry.asked, entry.decision, entry.run_id) == (Asked.PROPOSAL, decision, None)
    assert entry.channel == type(approver).__name__


def test_an_approval_that_cannot_be_written_down_allows_nothing(ran, tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.write_text("a file where the service's folder should be")  # nothing can go under it
    searched = []
    monkeypatch.setattr(service_module, "optimize", lambda *args, **kwargs: searched.append(1))
    with pytest.raises(ServiceError, match="could not be recorded"):
        _propose(Service(ran.ws, out, Approver()))
    assert searched == []


def test_an_export_the_person_does_not_approve_is_recorded_in_the_run_and_draws_nothing(ran):
    run_id, candidate_id, items = _export_items(ran)
    recorded = store.read_record(ran.ws / "out", run_id).approvals
    logged = audit.read(ran.ws / "out")
    unanswered = Service(ran.ws, ran.ws / "out", TerminalApprover(interactive=lambda: False))
    result = unanswered.export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=candidate_id, acknowledged_unresolved=items))
    assert result.status is ExportStatus.NOT_APPROVED and not result.files
    assert "UNANSWERED" in result.reasons[0]
    assert result.approvals[:len(recorded)] == recorded  # appended: nothing before it changed
    (entry,) = result.approvals[len(recorded):]
    assert (entry.asked, entry.decision, entry.channel) == (
        Asked.EXPORT, Decision.UNANSWERED, "TerminalApprover")
    assert store.read_record(ran.ws / "out", run_id).approvals == (*recorded, entry)
    assert audit.read(ran.ws / "out") == [*logged, entry]
    assert not (ran.ws / "out" / run_id / "exports").exists()
