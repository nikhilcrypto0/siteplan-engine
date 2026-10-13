"""The production service gives the search floor plates sized to the land (2026-10-13), beside
the firm's families and competing with them everywhere: on made-up land where no family fits, and
on land where they do. Each plate is PRELIMINARY and said so on the approval page, in the
prototypes listed and in every report of a layout that uses one; none makes a layout pass the law.
Made-up land and the example flat library only."""

TEST_CLASS = "normative"

import json  # noqa: E402
import shutil  # noqa: E402
from functools import cache  # noqa: E402
from pathlib import Path  # noqa: E402

import ezdxf  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from test_service import ANSWERS, BRIEF, EXAMPLES, INTENT, Approver  # noqa: E402

from siteplan.cli import main as cli  # noqa: E402
from siteplan.prototypes import compose_library  # noqa: E402
from siteplan.service import Service  # noqa: E402
from siteplan.service import service as service_module  # noqa: E402
from siteplan.service.models import ListPrototypes, ProposeLayouts  # noqa: E402
from siteplan.service.service import NO_PLATES_YET  # noqa: E402

PLATE = "ENGINE-COMPOSED floor plate, PRELIMINARY"
LANDS = {
    "l arm": [(0, 0), (140, 0), (140, 34), (34, 34), (34, 150), (0, 150)],  # a 34 m arm
    "narrow slant": [(0, 0), (230, 0), (200, 40), (0, 40)],  # 40 m wide, a slanted end
}


def _workspace(folder: Path, outline) -> Path:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.modelspace().add_lwpolyline(outline, close=True, dxfattribs={"layer": "SITE-BOUNDARY"})
    area = Polygon(outline).area
    doc.modelspace().add_text(f"AREA: {area:.0f} SQ.MTS", height=2).set_placement((10, -10))
    doc.saveas(folder / "survey.dxf")
    shutil.copy(EXAMPLES / "flat_library.example.json", folder / "flats.json")
    shutil.copy(EXAMPLES / "amenities.hyderabad.json", folder / "amenities.json")
    (folder / "siteplan.workspace.json").write_text(json.dumps(
        {"flat_library": "flats.json", "amenities": "amenities.json", "finished_plans": []}))
    (folder / "answers.json").write_text(json.dumps(ANSWERS))
    assert cli(["start", str(folder / "survey.dxf"), "--answers",
                str(folder / "answers.json")]) == 0
    return folder


def _families_only(library, unit_mix, env, *, loading_pct, source_kind, **_):
    return compose_library(library, unit_mix, source_kind=source_kind), []


@cache
def _run(name: str, plates: bool, root: Path):
    folder = root / f"{name.replace(' ', '-')}-{'plates' if plates else 'families'}"
    folder.mkdir()
    ws = _workspace(folder, LANDS[name])
    approver = Approver()
    service = Service(ws, ws / "out", approver)
    with pytest.MonkeyPatch.context() as patch:
        if not plates:
            patch.setattr(service_module, "kit_for", _families_only)
        result = service.propose_layouts(ProposeLayouts(
            project_file="service-test.project.json", survey_file="survey.dxf", brief=BRIEF,
            intent=INTENT))
    return ws, service, approver, result


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("plates")


def _proposed(ws: Path, result) -> list[dict]:
    folder = ws / "out" / result.run_id / "proposed" / "candidates"
    return [json.loads(f.read_text()) for f in sorted(folder.glob("*.json"))]


def _plates_in(candidate: dict) -> set[str]:
    plates = {p["id"] for p in candidate["prototypes_used"] if p["source"].startswith(PLATE)}
    return {t["prototype_id"] for t in candidate["towers"]} & plates


def test_where_no_family_fits_the_plates_lay_layouts_that_the_law_does_not_refuse(root):
    _, _, _, families = _run("l arm", False, root)
    assert not families.candidates  # the 34 m arm and its 34 m stem take no family
    ws, _, approver, result = _run("l arm", True, root)
    assert result.candidates
    for c in result.candidates:
        assert c.legal_verdict.value != "FAIL", c.candidate_id
    for candidate in _proposed(ws, result):
        assert _plates_in(candidate), candidate["candidate_id"]
    [(_, lines)] = approver.asked
    said = [line for line in lines if line.startswith("Floor plate ")]
    assert said and all("PRELIMINARY" in line for line in said)


def test_every_report_of_a_layout_with_a_plate_says_it_is_preliminary(root):
    ws, _, _, result = _run("l arm", True, root)
    for c in result.candidates:
        report = json.loads((ws / "out" / result.run_id / "reports" /
                             f"{c.candidate_id}.json").read_text())
        rules = [f["finding"]["rule"] for f in report["program"]]
        assert "Floor plate: PRELIMINARY" in rules, c.candidate_id


def test_where_the_families_fit_plates_still_compete_and_take_nothing_from_them(root):
    ws_f, _, _, families = _run("narrow slant", False, root)
    ws_p, _, _, plates = _run("narrow slant", True, root)
    assert families.candidates
    proposed = _proposed(ws_p, plates)
    assert any(_plates_in(c) for c in proposed)  # selected even where the families fit
    best = max(c["metrics"]["total_flats"] for c in _proposed(ws_f, families))
    assert max(c["metrics"]["total_flats"] for c in proposed) >= best


def test_the_prototypes_listed_name_the_plates_once_the_net_plot_is_known(root):
    ws, service, _, _ = _run("l arm", True, root)
    without = service.list_prototypes(ListPrototypes(project_file="service-test.project.json"))
    assert without.plates == [NO_PLATES_YET]
    assert not any(p.preliminary for p in without.prototypes)
    listed = service.list_prototypes(ListPrototypes(project_file="service-test.project.json",
                                                    survey_file="survey.dxf"))
    plates = [p for p in listed.prototypes if p.preliminary]
    assert plates and len(listed.plates) == len(plates)
    assert all(p.note.startswith(PLATE) and "effective loading" in p.note for p in plates)
