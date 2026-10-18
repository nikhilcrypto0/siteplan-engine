"""Stage D of the architect's roadmap (2026-10-17): alternatives round locked blocks. The locked
blocks stay exactly where they stand, to the millimetre and at their own height; the full search
places the rest and lays the roads, the club house, the tot-lot and the parking again; up to N
genuinely different alternatives, each judged by the independent validator and saved as a version
of the chosen layout; a lock that leaves no room says why. Made-up land (the contract fixtures'
rectangle, 200 x 120 m, its net plot 150 x 100 m) and the search's quick limits."""

import asyncio
import json
from functools import cache
from pathlib import Path

import pytest
from contract_fixtures.build import LIBRARY
from search_support import FAST
from test_cad import Drawing
from test_layout_versions import RUN, _run

from siteplan.cad.live import Session
from siteplan.cad.server import build
from siteplan.intake import WORKSPACE_FILE
from siteplan.optimizer.pareto import same_idea
from siteplan.service import around, edits, judge, store, versions
from siteplan.service.edits import EditRefused
from siteplan.service.service import search_kit

TEST_CLASS = "normative"


def _tower(candidate, name):
    return next(t for t in candidate.towers if t.name == name)


def _workspace(root: Path) -> Path:
    """A made-up firm's workspace beside the runs: its settings naming its flat library, the
    contract fixtures' own flats."""
    folder = root / "workspace"
    folder.mkdir(exist_ok=True)
    (folder / "flats.json").write_text(LIBRARY.model_dump_json())
    (folder / WORKSPACE_FILE).write_text(json.dumps({"flat_library": "flats.json"}))
    return folder


def _alternatives(root: Path, layout_id: str, n: int):
    return around.alternatives(root, _workspace(root), store.read_record(root, RUN), layout_id,
                               n, limits=FAST)


def _locked_run(out: Path, change=None, names=("T1",)):
    """A run whose layout, edited first when `change` is given, has these blocks locked."""
    record, inputs = _run(out)
    parent = "rectangle-1"
    if change is not None:
        parent = edits.edit(out, record, parent, change, ["moved for the test"]).version.version_id
    locked = edits.lock(out, record, parent, list(names))
    return record, inputs, locked


@cache
def _around(root: Path):
    record, inputs, locked = _locked_run(root)
    got = _alternatives(root, locked.version.version_id, 4)
    return record, inputs, locked, got


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return _around(tmp_path_factory.mktemp("around"))


def test_a_locked_block_stays_to_the_millimetre_in_every_alternative(made):
    _, inputs, locked, got = made
    assert got.alternatives and got.why_none == ""
    t1 = _tower(locked.candidate, "T1")
    for alt in got.alternatives:
        mine = _tower(alt.candidate, "T1")
        assert (mine.prototype_id, mine.floors_above_stilt) == (t1.prototype_id,
                                                                 t1.floors_above_stilt)
        assert alt.candidate.placed_footprint(mine).hausdorff_distance(
            locked.candidate.placed_footprint(t1)) <= 0.001
        assert (mine.x, mine.y) == pytest.approx((t1.x, t1.y), abs=0.001)


def test_each_alternative_is_a_judged_version_of_the_chosen_layout_laid_again(made):
    root_record, _, locked, got = made
    for alt in got.alternatives:
        v = alt.version
        assert v.parent_id == locked.version.version_id and v.locked == ["T1"]
        assert v.edits[0].startswith("laid again round the locked T1: alternative ")
        assert alt.report.verdict.legal.value != "FAIL"
        c = alt.candidate
        assert c.circulation.roads and c.circulation.gates  # the roads drawn again
        assert c.program.club_house is not None and c.program.open_space  # and the program
        assert c.program.cellars is not None
    names = [alt.version.version_id for alt in got.alternatives]
    assert len(set(names)) == len(names)


def test_the_alternatives_are_genuinely_different(made):
    _, _, _, got = made
    shown = [a.candidate for a in got.alternatives]
    assert not any(same_idea(a, b) for i, a in enumerate(shown) for b in shown[i + 1:])


def test_fewer_than_asked_says_how_many_passed_and_how_many_were_copies(made):
    """Four asked round the locked T1 on the small made-up plot: fewer are found, and the answer
    says how many passed and how many of the rest were the same idea (Stage A's rule)."""
    _, _, _, got = made
    shown = len(got.alternatives)
    assert 0 < shown < 4
    assert got.short.startswith(f"{shown} different layout{'s' if shown != 1 else ''} shown "
                                "of the 4 asked: ")


def test_a_block_turned_to_an_odd_angle_and_locked_is_kept_exactly(tmp_path):
    record, _, locked = _locked_run(tmp_path, lambda c: edits.turned_block(c, "T3", 33.3),
                                    names=("T3",))
    got = _alternatives(tmp_path, locked.version.version_id, 2)
    t3 = _tower(locked.candidate, "T3")
    for alt in got.alternatives:
        mine = _tower(alt.candidate, "T3")
        assert mine.rotation_deg % 360 == pytest.approx(t3.rotation_deg % 360)
        assert alt.candidate.placed_footprint(mine).hausdorff_distance(
            locked.candidate.placed_footprint(t3)) <= 0.001
    assert got.alternatives  # the turned block is laid round, not only refused


def test_a_lock_off_the_plot_says_why_and_saves_nothing(tmp_path):
    record, _, locked = _locked_run(tmp_path, lambda c: edits.moved_block(c, "T1", 400.0, 0.0))
    before = len(versions.listed(tmp_path, record))
    got = _alternatives(tmp_path, locked.version.version_id, 4)
    assert got.alternatives == () and "T1 stands off the net plot" in got.why_none
    assert len(versions.listed(tmp_path, store.read_record(tmp_path, RUN))) == before


def test_a_lock_that_leaves_no_room_says_why_in_the_searchs_words(tmp_path):
    """T1 pushed 12 m north stands 1.01 m inside the net plot's north edge (its north side at
    86.99 m, the plot's at 100 m): on the plot, but no 9 m ring road can run round it, so no
    layout keeps it, and the reason is the search's own."""
    record, _, locked = _locked_run(tmp_path, lambda c: edits.moved_block(c, "T1", 0.0, 12.0))
    got = _alternatives(tmp_path, locked.version.version_id, 4)
    assert got.alternatives == ()
    assert got.why_none.startswith("no layout can be laid round the locked blocks")
    assert "round the locked blocks" in got.why_none.split(":", 1)[1]


def test_a_layout_with_nothing_locked_is_refused(tmp_path):
    record, _ = _run(tmp_path)
    with pytest.raises(EditRefused, match="no locked block"):
        _alternatives(tmp_path, "rectangle-1", 4)


def test_the_cad_tool_lays_the_alternatives_and_draws_the_first(tmp_path):
    record, _, locked = _locked_run(tmp_path)
    drawing = Drawing()
    session = Session({"plot": {"runs": str(tmp_path), "mode": "blind",
                               "workspace": str(_workspace(tmp_path))}}, drawing)
    names = {t.name for t in asyncio.run(build(session).list_tools())}
    assert "alternatives_around" in names
    session_around = around.alternatives  # the CAD tool runs the same, with the default limits

    def quick(out, workspace, record_, layout_id, n, limits=None, seed=0):
        return session_around(out, workspace, record_, layout_id, n, limits=FAST, seed=seed)

    around.alternatives = quick
    try:
        got = session.alternatives_around("plot", RUN, locked.version.version_id, 3)
    finally:
        around.alternatives = session_around
    assert got["alternatives"] and got["why_none"] == ""
    first = got["alternatives"][0]
    assert first["description"] and first["verdict"] != "FAIL"
    label = " ".join(drawing.docs["Siteplan_plot"]["layout-sheet-label"]["text"].split())
    assert label.startswith(f"{first['version']} (run {RUN}")


def test_the_search_round_the_locks_is_given_every_block_in_the_firms_library(tmp_path,
                                                                                monkeypatch):
    """The architect's decision of 2026-10-18: the alternatives may use every block type the
    firm's flat library in the workspace gives, composed as the run's own search was given them
    (`service.search_kit`), not only the blocks the run's layouts used; the chosen layout's own
    blocks beside them, so the locked one is always there."""
    record, _, locked = _locked_run(tmp_path)
    parent = judge.judge_again(tmp_path, record, locked.version.version_id)
    library, _ = search_kit(LIBRARY, parent.inputs.brief, parent.inputs.envelope)
    used = {p.id for p in parent.candidate.prototypes_used}
    given = []

    class Watched(around.FullSearchStrategy):
        def propose(self, context):
            given.append({p.id for p in context.prototypes})
            return super().propose(context)

    monkeypatch.setattr(around, "FullSearchStrategy", Watched)
    _alternatives(tmp_path, locked.version.version_id, 2)
    assert given == [used | {p.id for p in library}]
    assert given[0] - used, "the library gives blocks the run's layouts never used"


def test_a_workspace_that_names_no_flat_library_is_refused(tmp_path):
    record, _, locked = _locked_run(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(EditRefused, match="names no flat_library"):
        around.alternatives(tmp_path, empty, record, locked.version.version_id, 2, limits=FAST)


def test_the_cad_tool_asks_for_the_sites_workspace(tmp_path):
    _, _, locked = _locked_run(tmp_path)
    session = Session({"plot": {"runs": str(tmp_path), "mode": "blind"}}, Drawing())
    with pytest.raises(ValueError, match="names no 'workspace' for plot"):
        session.alternatives_around("plot", RUN, locked.version.version_id, 2)
