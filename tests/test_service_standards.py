"""The firm's standards in the production service (service/standards.py): the approved project
file's, else the workspace's, else the engine's default; recorded in the DesignBrief with where
each came from, as the firm's (FIRM_STANDARD) when the project or the workspace set it and as the
engine's own (ENGINE_DEFAULT, ENGINE_DESIGN_ASSUMPTION) when neither did; given to the search and
to the validator; never a caller's to set.

Made-up land (test_service.make_workspace). The architect's project, made through the intake flow
while the workspace set no standard, then states the firm's longest block (45 m) and the
common-area loading (25%). The firm's workspace file then sets a longest block of 60 m and a
loading of 23% (both overridden by the project) and a cellar storey of 3.2 m, which the project
had recorded as the engine's default (so the workspace's own takes its place). The rest are the
engine's. One search runs for the module.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon
from test_service import BRIEF, INTENT, VALID, Approver, make_workspace

import siteplan.validator
from siteplan.basis import Basis
from siteplan.contracts import CandidateLayout, DesignBrief, ValidationReport, digest
from siteplan.contracts.common import Provenance, SourceKind
from siteplan.intake import WORKSPACE_FILE, load_defaults
from siteplan.project import Project
from siteplan.service import (
    ListPrototypes,
    OpenProject,
    ProposeLayouts,
    ProposeStatus,
    Service,
    ValidateCandidate,
    audit,
    standards,
)
from siteplan.service import service as service_module
from siteplan.service.models import REQUESTS
from siteplan.validator.shapes import sides_of

TEST_CLASS = "normative"

PROJECT, SURVEY = "service-test.project.json", "survey.dxf"
LONGEST_M = 45.0  # of the example library's blocks (31, 41, 58.5 and 82 m long) two fit
ARCHITECT = {"max_tower_length_m": LONGEST_M, "common_area_pct": 25.0}
FIRM = {"max_tower_length_m": 60.0, "common_area_pct": 23.0, "cellar_floor_height_m": 3.2}
IN_THE_PROJECT = "the project file service-test.project.json"
IN_THE_WORKSPACE = f"the workspace's {WORKSPACE_FILE}"
THE_ENGINES = "the engine's default"
# Each standard: where the DesignBrief holds it, the value it should hold there, its status and
# where it came from.
EXPECTED = {
    "max_tower_length_m": (("firm_standards", "max_tower_length_m"), LONGEST_M,
                           Provenance.USER_CONFIRMED, IN_THE_PROJECT),
    "common_area_pct": (("firm_standards", "common_area_loading_pct"), 25.0,
                        Provenance.USER_CONFIRMED, IN_THE_PROJECT),
    "cellar_floor_height_m": (("firm_standards", "cellar_floor_height_m"), 3.2,
                              Provenance.USER_CONFIRMED, IN_THE_WORKSPACE),
    "stilt_height_m": (("firm_standards", "stilt_height_m"), 3.0, Provenance.ASSUMED_FOR_TEST,
                       THE_ENGINES),
    "floor_height_m": (("firm_standards", "floor_to_floor_m"), 3.0, Provenance.ASSUMED_FOR_TEST,
                       THE_ENGINES),
    "cellar_utilities_pct": (("firm_standards", "cellar_utilities_share"), 0.1,
                             Provenance.ASSUMED_FOR_TEST, THE_ENGINES),
    "max_cellars": (("program", "parking", "max_cellars"), 3, Provenance.ASSUMED_FOR_TEST,
                    THE_ENGINES),
    "flat_library": (("program", "flat_library"), "flats.json", Provenance.USER_CONFIRMED,
                     IN_THE_WORKSPACE),
    "amenities": (("program", "amenity_library"), "amenities.json", Provenance.USER_CONFIRMED,
                  IN_THE_WORKSPACE),
}


def _set_by_the_architect(ws: Path, name: str, values: dict) -> None:
    project = json.loads((ws / name).read_text())
    for key, value in values.items():
        project["layout"][key] = value
        project["sources"][key] = f"architect: {key} for this site"
        project["status"][key] = Provenance.USER_CONFIRMED.value
    (ws / name).write_text(json.dumps(project))


def _set_by_the_firm(ws: Path, values: dict) -> None:
    workspace = json.loads((ws / WORKSPACE_FILE).read_text())
    (ws / WORKSPACE_FILE).write_text(json.dumps({**workspace, **values}))


@dataclass
class Run:
    ws: Path
    service: Service
    approver: Approver
    proposed: object
    optimized: list  # (the brief, the prototypes) optimize was given
    judged: list  # the digest of every brief the validator judged against
    stored: DesignBrief


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> Run:
    ws = make_workspace(tmp_path_factory.mktemp("standards"))
    _set_by_the_architect(ws, PROJECT, ARCHITECT)
    _set_by_the_firm(ws, FIRM)
    approver = Approver()
    service = Service(ws, ws / "out", approver)
    optimized, judged = [], []
    real_optimize, real_validate = service_module.optimize, siteplan.validator.validate

    def watch_optimize(site, rules, brief, strategies, **kwargs):
        optimized.append((brief, tuple(kwargs.get("prototypes", ()))))
        return real_optimize(site, rules, brief, strategies, **kwargs)

    def watch_validate(site, rules, brief, candidate, envelope=None):
        judged.append(digest(brief))
        return real_validate(site, rules, brief, candidate, envelope)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service_module, "optimize", watch_optimize)
        patch.setattr(siteplan.validator, "validate", watch_validate)
        proposed = service.propose_layouts(ProposeLayouts(
            project_file=PROJECT, survey_file=SURVEY, brief=BRIEF, intent=INTENT))
        for candidate in proposed.candidates:  # judged again from the stored contracts
            service.validate_candidate(ValidateCandidate(
                run_id=proposed.run_id, candidate_id=candidate.candidate_id))
    stored = DesignBrief.model_validate_json(
        (ws / "out" / proposed.run_id / "brief.json").read_text())
    return Run(ws, service, approver, proposed, optimized, judged, stored)


def _kind(origin: str) -> tuple[SourceKind, Basis]:
    """What a value's origin makes it: the firm's when the project or the workspace set it, the
    engine's own when the engine filled it in."""
    return ((SourceKind.ENGINE_DEFAULT, Basis.ENGINE_DESIGN_ASSUMPTION) if origin == THE_ENGINES
            else (SourceKind.FIRM_STANDARD, Basis.FIRM_STANDARD))


def _held(brief: DesignBrief, path: tuple[str, ...]):
    found = brief
    for name in path:
        found = getattr(found, name)
    return found


def test_each_standard_is_the_projects_else_the_workspaces_else_the_engines(run):
    assert run.proposed.status is ProposeStatus.PROPOSED, run.proposed.notes
    for key, (path, value, status, origin) in EXPECTED.items():
        held = _held(run.stored, path)
        assert held is not None, key
        assert held.value == (pytest.approx(value) if isinstance(value, float) else value), key
        assert held.status is status, (key, held.status)
        assert held.source_kind is _kind(origin)[0], key  # the firm's or the engine's, never law
        assert held.source.startswith(origin), (key, held.source)


def test_an_engine_fallback_is_never_labelled_the_firms(run):
    """Strict provenance: a value the project file or the workspace set is the firm's; one the
    engine filled in is the engine's design assumption, whatever its status says."""
    assert {origin for *_, origin in EXPECTED.values()} == {IN_THE_PROJECT, IN_THE_WORKSPACE,
                                                           THE_ENGINES}  # all three are met
    for key, (path, _, _, origin) in EXPECTED.items():
        kind = _held(run.stored, path).source_kind
        if origin == THE_ENGINES:
            assert kind is SourceKind.ENGINE_DEFAULT and kind is not SourceKind.FIRM_STANDARD, key
        else:
            assert kind is SourceKind.FIRM_STANDARD, key


def test_the_search_and_the_validator_are_given_those_standards(run):
    [(brief, _)] = run.optimized
    assert digest(brief) == digest(run.stored)  # the brief the search planned with is stored
    assert run.judged and set(run.judged) == {digest(run.stored)}  # and every verdict used it
    assert brief.firm_standards.max_tower_length_m.value == LONGEST_M


def test_no_tower_is_longer_than_the_firms_longest_block(run):
    [(_, kit)] = run.optimized
    assert {p.id for p in kit} == {"single-core-small-4", "single-core-6"}
    assert all(max(p.length_m, p.depth_m) <= LONGEST_M for p in kit)
    folder = run.ws / "out" / run.proposed.run_id
    assert run.proposed.candidates
    for summary in run.proposed.candidates:
        candidate = CandidateLayout.model_validate_json(
            (folder / "candidates" / f"{summary.candidate_id}.json").read_text())
        assert candidate.towers
        for tower in candidate.towers:
            longest, _ = sides_of(Polygon(tower.footprint.outer))
            assert longest <= LONGEST_M + 1e-6, (summary.candidate_id, tower.name, longest)
        report = ValidationReport.model_validate_json(
            (folder / "reports" / f"{summary.candidate_id}.json").read_text())
        firm = next(c for c in report.program
                    if c.finding.rule == "Firm standards and parking preferences")
        assert "longest block" not in firm.finding.measured
    left_out = [n for n in run.proposed.notes if n.startswith("Prototype ")]
    assert len(left_out) == 2 and all(IN_THE_PROJECT in n for n in left_out)


def test_the_architect_is_shown_each_standard_and_where_it_came_from(run):
    _, lines = run.approver.asked[0]
    shown = "\n".join(lines)
    assert (f"Standard max_tower_length_m: 45 [USER_CONFIRMED, FIRM_STANDARD], from "
            f"{IN_THE_PROJECT}") in shown
    assert (f"Standard cellar_floor_height_m: 3.2 [USER_CONFIRMED, FIRM_STANDARD], from "
            f"{IN_THE_WORKSPACE}") in shown
    assert (f"Standard max_cellars: 3 [ASSUMED_FOR_TEST, ENGINE_DESIGN_ASSUMPTION], from "
            f"{THE_ENGINES}") in shown
    assert "Prototype two-core-large-12 left out" in shown


def test_open_project_and_list_prototypes_say_the_same(run):
    opened = run.service.open_project(OpenProject(project_file=PROJECT, survey_file=SURVEY))
    facts = {f.name.removeprefix("standard: "): f for f in opened.firm_standards}
    assert set(facts) == set(standards.KEYS)
    for key, (_, value, status, origin) in EXPECTED.items():
        fact = facts[key]
        shown = value * 100 if key == "cellar_utilities_pct" else value  # a share in the brief
        assert fact.value == pytest.approx(shown), key
        assert (fact.status, fact.source_kind, fact.basis) == (status, *_kind(origin)), key
        assert fact.source.startswith(origin), key
    kit = run.service.list_prototypes(ListPrototypes(project_file=PROJECT))
    assert {p.id for p in kit.prototypes} == {"single-core-small-4", "single-core-6"}
    assert [n.split()[1] for n in kit.left_out] == ["two-core-medium-8", "two-core-large-12"]


def test_the_legacy_path_and_the_service_agree_on_a_project_made_through_intake(tmp_path):
    ws = make_workspace(tmp_path, standards={"floor_height_m": 3.1, "max_tower_length_m": 50.0,
                                             "cellar_utilities_pct": 5.0})
    legacy = Project.model_validate_json((ws / PROJECT).read_text()).layout  # what it lays out
    defaults = load_defaults(ws)  # where `siteplan layout` finds the libraries
    opened = Service(ws, tmp_path / "out", Approver()).open_project(OpenProject(
        project_file=PROJECT, survey_file=SURVEY))
    service = {f.name.removeprefix("standard: "): f.value for f in opened.firm_standards}
    assert {key: service[key] for key in standards.LAYOUT} == {
        key: getattr(legacy, key) for key in standards.LAYOUT}
    assert (service["flat_library"], service["amenities"]) == (defaults.flat_library,
                                                               defaults.amenities)
    assert (service["floor_height_m"], service["max_tower_length_m"]) == (3.1, 50.0)


@pytest.mark.parametrize("model", REQUESTS, ids=lambda m: m.__name__)
def test_no_request_can_carry_a_firm_standard(model):
    for key in (*standards.KEYS, "design_margins"):
        assert key not in model.model_fields
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            model.model_validate({**VALID[model.__name__], key: 1})
        if model is ProposeLayouts:  # nor the intent nested in it
            with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
                model.model_validate({**VALID["ProposeLayouts"], "intent": {key: 1}})


def test_a_longest_block_no_prototype_fits_stops_before_anyone_is_asked(run, tmp_path):
    shutil.copy(run.ws / PROJECT, run.ws / "tiny.project.json")
    _set_by_the_architect(run.ws, "tiny.project.json", {"max_tower_length_m": 20.0})
    approver, out = Approver(), tmp_path / "out"
    result = Service(run.ws, out, approver).propose_layouts(ProposeLayouts(
        project_file="tiny.project.json", survey_file=SURVEY, brief=BRIEF, intent=INTENT))
    assert result.status is ProposeStatus.STOPPED and result.run_id is None
    assert len(result.notes) == 4 and "longest block" in result.next
    assert approver.asked == [] and audit.read(out) == []
