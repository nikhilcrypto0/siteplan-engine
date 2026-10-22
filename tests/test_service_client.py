"""The service on the firm's two real sites (client data; skipped on a clean clone).

Dhulapally runs in DEBUG mode: its net outline is the firm's own, fitted onto the survey and
tagged FIRM_FINISHED_PLAN (the regression load, built as tests/search_compare.py builds it), so a
blind service refuses it and every output of the debug run says DEBUG RUN. Suchitra runs BLIND
from its survey and the project file the architect's answers make through the intake flow, with
its entrance pinned on R1 where the surveyor drew the gate, ASSUMED_FOR_TEST: its access road R2
touches the plot at a corner only, where no entrance fits (2026-10-21), and the architect has not
placed it; the stretch is worked out from the survey here, never written into a file. The files
are copied into a workspace under pytest's temporary folder, which is never committed.
What is asserted is what the service promises, never a number: FULL alternatives, no legal FAIL
among them when the service judges each again, DEBUG RUN on Dhulapally's drawings and report,
and Suchitra's own longest block (56 m, as the architect's project file sets it) kept: no tower
of any alternative is longer.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import ezdxf
import pytest
from client_baseline import ANSWERS, SURVEY, WORKSPACE, profile_path
from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge

from siteplan import rules
from siteplan.contracts import CandidateLayout, DesignBrief
from siteplan.contracts.common import SourceKind
from siteplan.contracts.design_brief import ParetoPoint
from siteplan.contracts.validation import LegalVerdict
from siteplan.intake import WORKSPACE_FILE, build_project, extract, load_defaults, save
from siteplan.legal.envelope import envelope
from siteplan.legal.site import resolve_project, site_from_project
from siteplan.optimizer.pareto import same_idea
from siteplan.optimizer.search import network
from siteplan.optimizer.search.land import plot_of
from siteplan.profiles import apply_profile, load_profile
from siteplan.project import Project
from siteplan.provenance import Provenance
from siteplan.runner import read_survey
from siteplan.service import (
    ExportCandidate,
    ExportStatus,
    HeightChoice,
    Intent,
    Mode,
    OpenProject,
    ProposeLayouts,
    ProposeStatus,
    Service,
    ServiceError,
    ValidateCandidate,
)
from siteplan.service.brief import SHOWN_LAYOUTS
from siteplan.steps.gate import around
from siteplan.steps.survey_copy import meets
from siteplan.validator.shapes import sides_of

TEST_CLASS = "normative"

SUCHITRA_SURVEY = WORKSPACE / "suchitra_survey.pdf"
SUCHITRA_PROJECT = WORKSPACE / "suchitra.project.json"  # the architect's own: its longest block
SUCHITRA_LONGEST_M = 56.0
# Suchitra has no answers file in fixtures; these are test_envelope_client.py's: the road it
# takes access from is the one drawn to the north-east, its width as drawn, the nala cyan.
SUCHITRA_ANSWERS = {
    "main_road": "2", "road_row": "as drawn", "dead_end": "unknown", "street_join": "unknown",
    "surrender": "no", "water": "#00FFFF nala over 10 m", "authority": "HMDA",
    "inside_cure": "no", "name": "Suchitra (survey only)", "mix": "70% 2BHK, 30% 3BHK",
    "floors": "max", "club_house": "yes"}
NEEDED = {"dhulapally": (SURVEY, ANSWERS, profile_path("counted"), WORKSPACE / WORKSPACE_FILE),
          "suchitra": (SUCHITRA_SURVEY, SUCHITRA_PROJECT, WORKSPACE / WORKSPACE_FILE)}
BRIEF = "The most floors the rules allow, 70% 2BHK and the rest 3BHK"
INTENT = Intent(height=HeightChoice.MOST_THE_RULES_ALLOW,
                unit_mix_percent={"2BHK": 70, "3BHK": 30})


class Yes:
    def approve(self, title: str, lines: list[str]) -> bool:
        return True


def _workspace(folder: Path) -> Path:
    """The firm's workspace file and the libraries it names, copied: the service reads nothing
    outside its workspace."""
    defaults = load_defaults(WORKSPACE)
    shutil.copy(WORKSPACE / WORKSPACE_FILE, folder / WORKSPACE_FILE)
    for name in filter(None, (defaults.flat_library, defaults.amenities)):
        shutil.copy(WORKSPACE / name, folder / name)
    return folder


def _dhulapally(folder: Path) -> tuple[str, str]:
    """The pinned debug run's project: the architect's answers, the conservative test mode, and
    the debug profile that puts the firm's net outline in as the net plot."""
    built = build_project(extract(SURVEY), json.loads(ANSWERS.read_text()),
                          load_defaults(WORKSPACE))
    built["layout"]["conservative_parking"] = True
    built["sources"]["conservative_parking"] = "run in the conservative test mode"
    built["status"]["conservative_parking"] = Provenance.ASSUMED_FOR_TEST
    built = apply_profile(built, load_profile(profile_path("counted")))
    save(built, folder / "dhulapally.debug.project.json")
    shutil.copy(SURVEY, folder / SURVEY.name)
    return "dhulapally.debug.project.json", SURVEY.name


R1_ENTRANCE = ("test: the entrance on R1 where the surveyor drew the gate, 9 m round its mouth, "
               "until the architect places it (R2 touches the plot at a corner only)")


def _r1_mouth() -> list[list[float]]:
    """The 9 m stretch round R1's mouth, as the steps' gate places one round a road narrower
    than the main approach road (`steps.gate.gate_line`), from the survey itself."""
    survey = read_survey(SUCHITRA_SURVEY)
    met = meets(extract(SUCHITRA_SURVEY).roads[0], survey.boundary, survey.roads)
    merged = linemerge([g for g in getattr(met, "geoms", [met])
                        if g.geom_type == "LineString" and g.length])
    line = max(getattr(merged, "geoms", [merged]), key=lambda g: g.length)
    edge = LineString(survey.boundary.exterior.coords)
    narrowest, widest = rules.MAIN_APPROACH_ROAD_M
    middle = edge.project(line.interpolate(0.5, normalized=True))
    gate = linemerge(around(edge, middle, min(max(line.length, narrowest), widest) / 2))
    return [list(point) for point in gate.coords]


def _suchitra(folder: Path) -> tuple[str, str]:
    """Suchitra's project as `siteplan start` writes it from the architect's answers, with the
    longest block the architect's own project file sets (the workspace sets none)."""
    built = build_project(extract(SUCHITRA_SURVEY), SUCHITRA_ANSWERS, load_defaults(WORKSPACE))
    architect = json.loads(SUCHITRA_PROJECT.read_text())
    longest = architect["layout"]["max_tower_length_m"]
    assert longest == SUCHITRA_LONGEST_M, "Suchitra's project file changed its longest block"
    built["layout"]["max_tower_length_m"] = longest
    built["sources"]["max_tower_length_m"] = f"architect: {SUCHITRA_PROJECT.name}"
    built["status"]["max_tower_length_m"] = Provenance.USER_CONFIRMED
    # the readings he selects and where the application stands, as his project file gives them
    # (2026-10-18), so the blind run is the one he asked for
    if architect["layout"].get("readings"):
        built["layout"]["readings"] = architect["layout"]["readings"]
    if architect["site"].get("application_status"):
        built["site"]["application_status"] = architect["site"]["application_status"]
        for part in ("sources", "status", "source_kinds"):
            if "application_status" in architect.get(part, {}):
                built.setdefault(part, {})["application_status"] = (
                    architect[part]["application_status"])
    built["site"]["gate_m"] = _r1_mouth()
    built["sources"]["gate_m"] = R1_ENTRANCE
    built["status"]["gate_m"] = Provenance.ASSUMED_FOR_TEST
    save(built, folder / "suchitra.project.json")
    shutil.copy(SUCHITRA_SURVEY, folder / SUCHITRA_SURVEY.name)
    return "suchitra.project.json", SUCHITRA_SURVEY.name


@pytest.fixture(scope="module", params=sorted(NEEDED))
def site(request, tmp_path_factory):
    name = request.param
    if not all(path.exists() for path in NEEDED[name]):
        pytest.skip(f"the {name} fixtures are not present")
    folder = _workspace(tmp_path_factory.mktemp(name))
    project_file, survey_file = (_dhulapally if name == "dhulapally" else _suchitra)(folder)
    mode = Mode.DEBUG if name == "dhulapally" else Mode.BLIND
    service = Service(folder, folder / "out", Yes(), mode=mode)
    proposed = service.propose_layouts(ProposeLayouts(
        project_file=project_file, survey_file=survey_file, brief=BRIEF, intent=INTENT))
    return name, folder, service, proposed, (project_file, survey_file)


def test_the_service_proposes_full_alternatives_with_no_legal_fail(site):
    name, folder, service, proposed, _ = site
    assert proposed.status is ProposeStatus.PROPOSED, (name, proposed.notes)
    # one a point at most, then (Stage A, 2026-10-16) the next different ideas, up to SHOWN_LAYOUTS
    assert 1 <= len(proposed.candidates) <= SHOWN_LAYOUTS, name
    points = [c.pareto_point for c in proposed.candidates if c.pareto_point]
    assert len(points) == len(set(points)) <= len(ParetoPoint), name
    shown = [CandidateLayout.model_validate_json(
        (folder / "out" / proposed.run_id / "candidates" / f"{c.candidate_id}.json").read_text())
        for c in proposed.candidates]
    assert not any(same_idea(a, b) for i, a in enumerate(shown) for b in shown[i + 1:]), name
    for candidate in proposed.candidates:
        assert candidate.strategy == "FULL", name
        assert candidate.legal_verdict is not LegalVerdict.FAIL, (name, candidate.candidate_id)
        checked = service.validate_candidate(ValidateCandidate(
            run_id=proposed.run_id, candidate_id=candidate.candidate_id))
        assert checked.refusals == [], (name, candidate.candidate_id, checked.refusals)
        assert checked.legal_verdict is not LegalVerdict.FAIL


def test_the_longest_block_the_project_sets_is_kept_and_honoured(site):
    name, folder, _, proposed, _ = site
    run = folder / "out" / proposed.run_id
    longest = DesignBrief.model_validate_json((run / "brief.json").read_text()) \
        .firm_standards.max_tower_length_m
    if name == "dhulapally":  # neither its project nor the workspace sets one
        assert longest is None
        return
    assert longest.value == SUCHITRA_LONGEST_M and longest.source_kind is SourceKind.FIRM_STANDARD
    assert longest.source.startswith("the project file suchitra.project.json")
    for summary in proposed.candidates:
        candidate = CandidateLayout.model_validate_json(
            (run / "candidates" / f"{summary.candidate_id}.json").read_text())
        for tower in candidate.towers:
            long_side, _ = sides_of(Polygon(tower.footprint.outer))
            assert long_side <= SUCHITRA_LONGEST_M + 1e-6, (summary.candidate_id, tower.name)


def test_a_debug_run_says_so_and_a_blind_service_refuses_its_inputs(site):
    name, folder, service, proposed, (project_file, survey_file) = site
    assert proposed.debug_run is (name == "dhulapally")
    if name != "dhulapally":
        return
    with pytest.raises(ServiceError, match="finished plan"):
        Service(folder, folder / "out", Yes()).open_project(OpenProject(
            project_file=project_file, survey_file=survey_file))


def test_the_first_alternative_exports_and_the_debug_run_is_labelled_on_every_output(site):
    name, _, service, proposed, _ = site
    first = proposed.candidates[0].candidate_id
    items = [i.item for i in service.validate_candidate(ValidateCandidate(
        run_id=proposed.run_id, candidate_id=first)).unverified]
    result = service.export_candidate(ExportCandidate(
        run_id=proposed.run_id, candidate_id=first, acknowledged_unresolved=items))
    assert result.status is ExportStatus.EXPORTED, (name, result.reasons)
    for path in result.files:
        if path.endswith(".validation.json"):
            continue
        if path.endswith(".dxf"):
            msp = ezdxf.readfile(path).modelspace()
            text = " ".join([e.dxf.text for e in msp.query("TEXT")]
                            + [e.plain_text() for e in msp.query("MTEXT")])
        else:
            text = Path(path).read_text()
        assert ("DEBUG RUN" in text) is (name == "dhulapally"), (name, path)


def test_suchitra_without_a_pinned_entrance_lays_none_there_and_says_why():
    """Its access road R2 runs past the plot and touches it at a corner only (2026-10-21): the
    search used to open the gate 80 m away on an edge no road touches. Unpinned, the only
    stretch a gate may open on is that touch, shorter than the 9 m approach road, and the search
    says so before anything else."""
    if not all(path.exists() for path in NEEDED["suchitra"]):
        pytest.skip("the suchitra fixtures are not present")
    project = Project.model_validate(build_project(extract(SUCHITRA_SURVEY), SUCHITRA_ANSWERS,
                                                   load_defaults(WORKSPACE)))
    site = site_from_project(project, SUCHITRA_SURVEY)
    assert site.access.gate is None and site.access_road().id == 2
    zones = envelope(site, resolve_project(site, project)).circulation.access_zones
    assert sum(z.length_m for z in zones) < 5  # the corner touch, not the edges facing NE
    why = network.too_short(plot_of(site, envelope(site, resolve_project(site, project))), 9.0)
    assert "the access road meets the plot along 3.5 m" in why
