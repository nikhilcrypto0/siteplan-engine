"""The service on the firm's two real sites (client data; skipped on a clean clone).

Dhulapally runs in DEBUG mode: its net outline is the firm's own, fitted onto the survey and
tagged FIRM_FINISHED_PLAN (the regression load, built as tests/search_compare.py builds it), so a
blind service refuses it and every output of the debug run says DEBUG RUN. Suchitra runs BLIND
from its survey and the project file the architect's answers make through the intake flow. The
files are copied into a workspace under pytest's temporary folder, which is never committed.
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
from shapely.geometry import Polygon

from siteplan.contracts import CandidateLayout, DesignBrief
from siteplan.contracts.common import SourceKind
from siteplan.contracts.validation import LegalVerdict
from siteplan.intake import WORKSPACE_FILE, build_project, extract, load_defaults, save
from siteplan.profiles import apply_profile, load_profile
from siteplan.provenance import Provenance
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


def _suchitra(folder: Path) -> tuple[str, str]:
    """Suchitra's project as `siteplan start` writes it from the architect's answers, with the
    longest block the architect's own project file sets (the workspace sets none)."""
    built = build_project(extract(SUCHITRA_SURVEY), SUCHITRA_ANSWERS, load_defaults(WORKSPACE))
    longest = json.loads(SUCHITRA_PROJECT.read_text())["layout"]["max_tower_length_m"]
    assert longest == SUCHITRA_LONGEST_M, "Suchitra's project file changed its longest block"
    built["layout"]["max_tower_length_m"] = longest
    built["sources"]["max_tower_length_m"] = f"architect: {SUCHITRA_PROJECT.name}"
    built["status"]["max_tower_length_m"] = Provenance.USER_CONFIRMED
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
    name, _, service, proposed, _ = site
    assert proposed.status is ProposeStatus.PROPOSED, (name, proposed.notes)
    assert 1 <= len(proposed.candidates) <= 3, name
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
