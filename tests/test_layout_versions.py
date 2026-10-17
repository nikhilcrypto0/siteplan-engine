"""Stage B of the architect's roadmap (2026-10-16): any layout of a run opened in FreeCAD with
what it is said on the sheet, and a layout kept as a version of its own in the run's folder.

A version is written once, records its parent and the parent's digest, is judged by the
independent validator when saved and again whenever it is used, and is refused when anything it
rests on changed. The model is never offered saving one. In FreeCAD (stood in for in memory) a
layout is drawn vertex for vertex, judged again, labelled DEBUG or STUDY where they apply, with
its verdict and PRELIMINARY for floor plates, and a layout shown after another leaves nothing of
the first. A run is made here from the contract fixtures' made-up land, no search."""

from pathlib import Path

import pytest
from shapely.geometry import Polygon
from test_cad import Drawing
from validator_helpers import fixture

from siteplan.cad import scene
from siteplan.cad.bridge import from_cad
from siteplan.cad.live import Session
from siteplan.cad.server import build
from siteplan.contracts import digest
from siteplan.prototypes.plates import PLATE_SOURCE
from siteplan.service import Service, ServiceError, ValidateCandidate, judge, store, versions
from siteplan.service.host import OPERATIONS, TOOLS
from siteplan.service.models import Mode
from siteplan.service.store import RunRecord, StoredCandidate, StoreError
from siteplan.validator import validate

TEST_CLASS = "normative"
RUN = "0123456789ab"


def _run(out: Path, *, mode: Mode = Mode.BLIND, study: bool = False, plate: bool = False,
         run_id: str = RUN) -> tuple[RunRecord, object]:
    """A run on disk holding one layout shown, the contract fixtures' rectangle."""
    inputs = fixture("rectangle")
    if study:
        inputs = inputs.with_brief(lambda b: setattr(b.objectives, "study", True))
    if plate:
        def as_plate(c):
            first = c.prototypes_used[0]
            c.prototypes_used[0] = first.model_copy(update={"source": PLATE_SOURCE})
        inputs = inputs.edited(as_plate)
    candidate = inputs.candidate
    report = validate(inputs.site, inputs.rules, inputs.brief, candidate, inputs.envelope)
    record = RunRecord(run_id=run_id, mode=mode, project_name="made-up", project_file="p.json",
                       candidates=[StoredCandidate(candidate_id=candidate.candidate_id,
                                                   digest=digest(candidate))])
    record = store.write_run(out / run_id, record, store.Inputs(
        inputs.site, inputs.rules, inputs.brief, inputs.envelope), [(candidate, report)])
    return record, inputs


def _moved(candidate, east_m: float):
    """The layout with its first tower moved east, footprint and all."""
    towers = list(candidate.towers)
    t = towers[0]
    towers[0] = t.model_copy(update={"x": t.x + east_m})
    return candidate.model_copy(update={"towers": towers})


# --- versions in the run's folder ----------------------------------------------------------------


def test_a_layout_kept_is_a_version_with_its_parents_digest(tmp_path):
    record, inputs = _run(tmp_path)
    version, candidate, report = versions.make_version(tmp_path, record, "rectangle-1",
                                                       note="the one to work on")
    assert version.version_id == candidate.candidate_id == "rectangle-1-v1"
    assert version.parent_id == "rectangle-1"
    assert version.parent_digest == digest(inputs.candidate)
    assert version.digest == digest(candidate) and version.report_digest == digest(report)
    stored = tmp_path / RUN / "versions" / "rectangle-1-v1"
    assert sorted(p.name for p in stored.iterdir()) == ["candidate.json", "report.json",
                                                        "version.json"]
    judged = judge.judge_again(tmp_path, record, "rectangle-1-v1")
    assert judged.references == ()
    assert judged.report.verdict == validate(inputs.site, inputs.rules, inputs.brief, candidate,
                                             inputs.envelope).verdict


def test_saving_again_makes_another_version_and_never_changes_the_first(tmp_path):
    record, _ = _run(tmp_path)
    first, _, _ = versions.make_version(tmp_path, record, "rectangle-1")
    before = (tmp_path / RUN / "versions" / "rectangle-1-v1" / "candidate.json").read_bytes()
    second, _, _ = versions.make_version(tmp_path, record, "rectangle-1")
    third, _, _ = versions.make_version(tmp_path, record, "rectangle-1-v2")  # of a version
    assert (first.version_id, second.version_id, third.version_id) == (
        "rectangle-1-v1", "rectangle-1-v2", "rectangle-1-v3")
    assert third.parent_id == "rectangle-1-v2" and third.parent_digest == second.digest
    assert (tmp_path / RUN / "versions" / "rectangle-1-v1" / "candidate.json").read_bytes() == (
        before)


def test_a_version_whose_file_changed_is_refused(tmp_path):
    record, inputs = _run(tmp_path)
    versions.make_version(tmp_path, record, "rectangle-1")
    path = tmp_path / RUN / "versions" / "rectangle-1-v1" / "candidate.json"
    path.write_text(_moved(inputs.candidate, 1.0).model_copy(
        update={"candidate_id": "rectangle-1-v1"}).model_dump_json())
    judged = judge.judge_again(tmp_path, record, "rectangle-1-v1")
    assert any("changed since the run was made" in r for r in judge.refusals(judged))


def test_a_version_whose_parent_changed_is_refused_down_the_line(tmp_path):
    record, inputs = _run(tmp_path)
    versions.make_version(tmp_path, record, "rectangle-1")
    versions.make_version(tmp_path, record, "rectangle-1-v1")
    shown = tmp_path / RUN / "candidates" / "rectangle-1.json"
    shown.write_text(_moved(inputs.candidate, 1.0).model_dump_json())
    for version_id in ("rectangle-1-v1", "rectangle-1-v2"):
        references = judge.judge_again(tmp_path, record, version_id).references
        assert any("rectangle-1" in r and "changed" in r for r in references), version_id


def test_a_line_of_parents_that_runs_in_a_circle_is_refused(tmp_path):
    record, _ = _run(tmp_path)
    versions.make_version(tmp_path, record, "rectangle-1")
    versions.make_version(tmp_path, record, "rectangle-1-v1")
    path = tmp_path / RUN / "versions" / "rectangle-1-v1" / "version.json"
    stored = versions.LayoutVersion.model_validate_json(path.read_text())
    path.write_text(stored.model_copy(update={"parent_id": "rectangle-1-v2"}).model_dump_json())
    references = judge.judge_again(tmp_path, record, "rectangle-1-v2").references
    assert any("circle" in r for r in references)


def test_a_layout_made_for_other_inputs_is_not_saved(tmp_path):
    record, inputs = _run(tmp_path)
    stranger = inputs.candidate.model_copy(update={"brief_ref": "0" * 16})
    with pytest.raises(StoreError, match="not made for this run's inputs"):
        versions.make_version(tmp_path, record, "rectangle-1", stranger)
    assert not (tmp_path / RUN / "versions").exists()


def test_an_edit_is_judged_by_the_validator_and_names_what_broke(tmp_path):
    """The first tower moved 400 m east stands off the 200 x 120 m plot: saved as a version,
    the validator fails it and an export is refused, naming the rule."""
    record, inputs = _run(tmp_path)
    version, _, report = versions.make_version(tmp_path, record, "rectangle-1",
                                               _moved(inputs.candidate, 400.0),
                                               ["T1 moved 400 m east"])
    assert version.edits == ["T1 moved 400 m east"]
    assert report.verdict.legal.value == "FAIL"
    refusals = judge.refusals(judge.judge_again(tmp_path, record, version.version_id))
    assert any(r.startswith("FAIL ") for r in refusals)


def test_the_service_judges_a_version_as_it_judges_any_layout_of_the_run(tmp_path):
    """validate_candidate, one of the nine operations, reaches a version saved in the run: judged
    again, and refused once its file changed."""
    record, inputs = _run(tmp_path / "out")
    versions.make_version(tmp_path / "out", record, "rectangle-1")
    service = Service(tmp_path, tmp_path / "out", approver=None)
    checked = service.validate_candidate(ValidateCandidate(run_id=RUN,
                                                           candidate_id="rectangle-1-v1"))
    assert checked.refusals == [] or not any("changed" in r for r in checked.refusals)
    path = tmp_path / "out" / RUN / "versions" / "rectangle-1-v1" / "candidate.json"
    path.write_text(_moved(inputs.candidate, 1.0).model_copy(
        update={"candidate_id": "rectangle-1-v1"}).model_dump_json())
    checked = service.validate_candidate(ValidateCandidate(run_id=RUN,
                                                           candidate_id="rectangle-1-v1"))
    assert any("changed since the run was made" in r for r in checked.refusals)
    with pytest.raises(ServiceError):
        service.validate_candidate(ValidateCandidate(run_id=RUN, candidate_id="no-such"))


def test_the_model_is_never_offered_saving_a_version():
    """The architect's answer (2026-10-16): the language-model agent gets no editing tools. The
    service and the host the model reaches have their nine operations and no other; a version is
    saved through FreeCAD (the CAD session) alone."""
    assert len(OPERATIONS) == 9 and set(TOOLS) == set(OPERATIONS)
    assert not any("version" in name for name in dir(Service) if not name.startswith("_"))


# --- a layout of a run in FreeCAD ----------------------------------------------------------------


def _session(out: Path, mode: str = "blind") -> tuple[Session, Drawing]:
    drawing = Drawing()
    return Session({"plot": {"runs": str(out), "mode": mode}}, drawing), drawing


def test_a_layout_of_a_run_reaches_cad_vertex_for_vertex(tmp_path):
    _, inputs = _run(tmp_path)
    session, drawing = _session(tmp_path)
    shown = session.show_layout("plot", RUN, "rectangle-1")
    doc = drawing.docs["Siteplan_plot"]
    candidate = inputs.candidate
    for tower in candidate.towers:
        drawn = Polygon([from_cad(p) for p in doc[f"layout-{tower.name.lower()}"]["rings"][0]])
        placed = candidate.placed_footprint(tower)
        assert drawn.symmetric_difference(placed).area < 1e-6, tower.name
    assert shown["verdict"] == inputs.report(envelope=True).verdict.legal.value
    assert doc["layout-sheet-label"]["layer"] == scene.NOTES


def test_the_sheet_says_its_verdict_and_nothing_it_is_not(tmp_path):
    _run(tmp_path)
    session, drawing = _session(tmp_path)
    lines = session.show_layout("plot", RUN, "rectangle-1")["labels"]
    text = drawing.docs["Siteplan_plot"]["layout-sheet-label"]["text"]
    assert " ".join(text.split()) == " ".join(" ".join(lines).split())  # wrapped, same words
    assert lines[0].startswith(f"rectangle-1 (run {RUN}")
    assert any(line.startswith(("PASS", "CONDITIONAL", "FAIL")) for line in lines)
    assert not any(word in text for word in ("DEBUG", "STUDY", "PRELIMINARY"))


def _verdict_with_many_items(tmp_path):
    """A layout whose verdict names many things: T1 moved 400 m off the plot fails rule after
    rule, so its verdict in full runs far wider than the plot."""
    record, inputs = _run(tmp_path)
    towers = list(inputs.candidate.towers)
    towers[0] = towers[0].model_copy(update={"x": towers[0].x + 400.0})
    versions.make_version(tmp_path, record, "rectangle-1",
                          inputs.candidate.model_copy(update={"towers": towers}), ["T1 off"])
    return inputs


def test_the_sheet_label_is_short_and_no_wider_than_the_plot(tmp_path):
    """Found in a real FreeCAD (2026-10-17): the verdict, every reading and fact it rests on, was
    one line hundreds of metres wide, so fitting the view zoomed out until nothing was readable.
    The sheet says the verdict in a few words, each line within the plot's width."""
    inputs = _verdict_with_many_items(tmp_path)
    session, drawing = _session(tmp_path)
    session.show_layout("plot", RUN, "rectangle-1-v1")
    label = drawing.docs["Siteplan_plot"]["layout-sheet-label"]["text"].split("\n")
    x0, _, x1, _ = inputs.site.net_plot.value.to_shapely().bounds
    size_m = drawing.docs["Siteplan_plot"]["layout-sheet-label"]["size"] / 1000
    assert size_m > scene.TEXT_SIZE_M  # larger than the drawing's other labels, to be read
    widest_m = max(len(line) for line in label) * size_m * scene.CHAR_WIDTH
    assert widest_m <= x1 - x0
    assert any(line.startswith("FAIL: ") and "rules" in line for line in label)
    assert "(listed in the note below the plot)" in " ".join(label)


def test_the_verdict_in_full_is_a_note_below_the_plot_on_its_own_layer(tmp_path):
    inputs = _verdict_with_many_items(tmp_path)
    session, drawing = _session(tmp_path)
    shown = session.show_layout("plot", RUN, "rectangle-1-v1")
    note = drawing.docs["Siteplan_plot"]["layout-sheet-note"]
    _, y0, _, _ = inputs.site.net_plot.value.to_shapely().bounds
    assert note["layer"] == scene.DETAIL and from_cad(note["at"])[1] < y0
    text = " ".join(note["text"].split("\n"))
    failed = [r for r in shown["refusals"] if r.startswith("FAIL ")]
    assert failed and all(" ".join(r.split()) in " ".join(text.split()) for r in failed[:3])


def test_a_screenshot_is_framed_on_the_plot_and_its_label(tmp_path):
    """The note of the verdict in full is hidden for the shot (its own layer), the plot, its
    blocks and the short label are shown, and the note is shown again after."""
    _verdict_with_many_items(tmp_path)
    session, drawing = _session(tmp_path)
    session.show_layout("plot", RUN, "rectangle-1-v1")
    assert session.screenshot("plot", "edited.png") == "edited.png"
    [shot] = drawing.shots
    assert scene.DETAIL not in shot["layers"]
    assert {scene.NOTES, scene.TOWERS, scene.NET} <= shot["layers"]
    assert scene.DETAIL not in drawing.hidden


def test_a_debug_run_is_labelled_so_and_a_blind_site_refuses_it(tmp_path):
    _run(tmp_path, mode=Mode.DEBUG)
    blind, _ = _session(tmp_path, "blind")
    with pytest.raises(ValueError, match="finished plan"):
        blind.show_layout("plot", RUN, "rectangle-1")
    debug, _ = _session(tmp_path, "debug")
    assert any(line.startswith("DEBUG RUN") for line in
               debug.show_layout("plot", RUN, "rectangle-1")["labels"])


def test_a_study_is_labelled_not_a_legal_layout(tmp_path):
    _run(tmp_path, study=True)
    session, _ = _session(tmp_path)
    assert "STUDY, NOT A LEGAL LAYOUT" in session.show_layout("plot", RUN, "rectangle-1")["labels"]


def test_a_floor_plate_is_labelled_preliminary_on_the_sheet_and_on_its_tower(tmp_path):
    _, inputs = _run(tmp_path, plate=True)
    session, drawing = _session(tmp_path)
    lines = session.show_layout("plot", RUN, "rectangle-1")["labels"]
    plate = inputs.candidate.prototypes_used[0].id
    names = [t.name for t in inputs.candidate.towers if t.prototype_id == plate]
    assert names and any(line.startswith("PRELIMINARY") and names[0] in line for line in lines)
    tower_text = drawing.docs["Siteplan_plot"][f"layout-{names[0].lower()}-text"]["text"]
    assert tower_text.endswith("PRELIMINARY floor plate")


def test_a_layout_shown_after_another_leaves_nothing_of_the_first(tmp_path):
    record, inputs = _run(tmp_path)
    fewer = inputs.candidate.model_copy(update={"towers": inputs.candidate.towers[:1]})
    versions.make_version(tmp_path, record, "rectangle-1", fewer, ["T2 and T3 taken out"])
    session, drawing = _session(tmp_path)
    session.show_layout("plot", RUN, "rectangle-1")
    assert "layout-t3" in drawing.docs["Siteplan_plot"]
    shown = session.show_layout("plot", RUN, "rectangle-1-v1")
    doc = drawing.docs["Siteplan_plot"]
    assert shown["removed"] > 0
    assert "a version of rectangle-1: T2 and T3 taken out" in shown["labels"]
    assert "layout-t1" in doc and "layout-t2" not in doc and "layout-t3" not in doc


def test_the_cad_tools_keep_a_layout_as_a_version_and_show_it(tmp_path):
    import asyncio

    _run(tmp_path)
    session, drawing = _session(tmp_path)
    server = build(session)
    asyncio.run(server.call_tool("show_layout", {"site": "plot", "run_id": RUN,
                                                 "layout_id": "rectangle-1"}))
    kept = session.keep_layout("plot", RUN, "rectangle-1", "the architect's pick")
    assert kept["version"] == "rectangle-1-v1" and kept["parent"] == "rectangle-1"
    asyncio.run(server.call_tool("show_layout", {"site": "plot", "run_id": RUN,
                                                 "layout_id": "rectangle-1-v1"}))
    assert drawing.docs["Siteplan_plot"]["layout-sheet-label"]["text"].startswith(
        f"rectangle-1-v1 (run {RUN}")
