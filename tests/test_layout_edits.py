"""Stage C of the architect's roadmap (2026-10-16): a block locked, moved or turned, the club
house or a tot-lot piece moved, each saved as a version of its own and judged by the independent
validator; roads, fire lanes and parking kept as drawn, and what the edit broke named.

The made-up layout is the contract fixtures' rectangle: T1 is 72 x 24.13 m, standing in a hole
of its fire hardstanding, so moving it 1 m east puts 1 x 24.13 m of it on that hardstanding.
Every other expectation is worked out by hand from the geometry the test makes."""

import asyncio

import pytest
from shapely import affinity
from test_layout_versions import RUN, _run, _session

from siteplan.cad.bridge import to_cad
from siteplan.cad.server import build
from siteplan.service import edits, judge, store, versions
from siteplan.service.edits import EDITED_CAVEAT, EditRefused

TEST_CLASS = "normative"
DEPTH_M = 24.13  # the fixture's T1, across


def _t(candidate, name):
    return next(t for t in candidate.towers if t.name == name)


def test_a_block_moved_is_saved_as_a_version_and_judged(tmp_path):
    record, inputs = _run(tmp_path)
    done = edits.edit(tmp_path, record, "rectangle-1",
                      lambda c: edits.moved_block(c, "T2", -1.0, 0.0), ["T2 moved 1 m west"],
                      moves=["T2"])
    assert done.version.version_id == "rectangle-1-v1" and done.version.edits == [
        "T2 moved 1 m west"]
    moved, before = _t(done.candidate, "T2"), _t(inputs.candidate, "T2")
    assert (moved.x, moved.y) == pytest.approx((before.x - 1.0, before.y))
    assert moved.footprint.to_shapely().equals(done.candidate.placed_footprint(moved))
    assert done.candidate.partition is None and done.candidate.generator_claims == []
    assert EDITED_CAVEAT in done.candidate.caveats
    # 1 m west, T2 stands 1 m into the 9 m loop road along its 24.13 m side: the road's clear
    # width breaks, and that is named; nothing stale of the generator's is left to block a pass
    t2 = done.candidate.placed_footprint(moved)
    loop = next(r for r in done.candidate.circulation.roads if r.id == "road-1")
    assert sum(s.to_shapely().intersection(t2).area for s in loop.shapes) == pytest.approx(
        1.0 * DEPTH_M)
    blocking = {d.item for d in done.report.cross_checks if d.blocks_pass}
    assert blocking == {"road width road-1"}
    assert all(any(b.startswith(item) for b in done.broke) for item in blocking)
    again = judge.judge_again(tmp_path, record, "rectangle-1-v1")
    assert again.references == () and again.report.verdict == done.report.verdict


def test_what_an_edit_broke_is_named_and_the_roads_stay_as_drawn(tmp_path):
    record, inputs = _run(tmp_path)
    done = edits.edit(tmp_path, record, "rectangle-1",
                      lambda c: edits.moved_block(c, "T1", 1.0, 0.0), ["T1 moved 1 m east"],
                      moves=["T1"])
    t1 = done.candidate.placed_footprint(_t(done.candidate, "T1"))
    lane = inputs.candidate.circulation.fire_hardstanding[1].to_shapely()
    assert t1.intersection(lane).area == pytest.approx(1.0 * DEPTH_M, abs=1e-6)
    assert done.candidate.circulation == inputs.candidate.circulation  # kept as drawn
    assert done.candidate.program.cellars == inputs.candidate.program.cellars
    said = " | ".join(done.broke)
    assert "Fire access: nothing parked or built on it: PASS -> FAIL" in said
    assert done.version.broke == list(done.broke)
    assert any(r.startswith("FAIL ") for r in done.refusals)


def test_what_broke_names_only_what_got_worse(tmp_path):
    record, inputs = _run(tmp_path)
    out = edits.edit(tmp_path, record, "rectangle-1",
                     lambda c: edits.moved_block(c, "T1", 1.0, 0.0), ["T1 moved 1 m east"],
                     moves=["T1"])
    back = edits.edit(tmp_path, record, out.version.version_id,
                      lambda c: edits.moved_block(c, "T1", -1.0, 0.0), ["T1 moved 1 m west"],
                      moves=["T1"])
    assert back.broke == ()  # moving it back mends what moving it broke
    assert _t(back.candidate, "T1").x == pytest.approx(_t(inputs.candidate, "T1").x)


def test_a_block_turned_keeps_its_middle_and_four_quarter_turns_bring_it_back(tmp_path):
    _, inputs = _run(tmp_path)
    c = inputs.candidate
    middle = c.placed_footprint(_t(c, "T3")).centroid
    turned = edits.turned_block(c, "T3", 90.0)
    t3 = turned.placed_footprint(_t(turned, "T3"))
    assert (t3.centroid.x, t3.centroid.y) == pytest.approx((middle.x, middle.y))
    x0, y0, x1, y1 = t3.bounds
    assert (x1 - x0, y1 - y0) == pytest.approx((DEPTH_M, 41.0))  # 41 x 24.13 m, now upright
    again = c
    for _ in range(4):
        again = edits.turned_block(again, "T3", 90.0)
    back = again.placed_footprint(_t(again, "T3"))
    assert back.symmetric_difference(c.placed_footprint(_t(c, "T3"))).area < 1e-6


def test_a_block_dragged_in_cad_is_read_back_whole_and_a_reshaped_one_refused(tmp_path):
    _, inputs = _run(tmp_path)
    c = inputs.candidate
    placed = c.placed_footprint(_t(c, "T3"))
    dragged = affinity.translate(affinity.rotate(placed, 30.0, origin=placed.centroid), 5.0, -2.0)
    read = edits.block_from_outline(c, "T3", dragged)
    assert read.placed_footprint(_t(read, "T3")).symmetric_difference(dragged).area < 1e-6
    assert _t(read, "T3").rotation_deg == pytest.approx(30.0)
    with pytest.raises(EditRefused, match="keeps its prototype's shape"):
        edits.block_from_outline(c, "T3", affinity.scale(placed, 1.1, 1.0))  # stretched
    with pytest.raises(EditRefused, match="keeps its prototype's shape"):
        edits.block_from_outline(c, "T3", affinity.skew(placed, xs=10.0))  # sheared
    # (a rectangle mirrored is the same outline turned half round, which is taken as turned)


def test_the_club_house_and_a_tot_lot_piece_are_moved_and_judged(tmp_path):
    record, inputs = _run(tmp_path)
    c = inputs.candidate
    club = edits.edit(tmp_path, record, "rectangle-1", lambda x: edits.moved_club(x, 2.0, 0.0),
                      ["club house moved 2 m east"])
    before = c.program.club_house.shape.to_shapely()
    after = club.candidate.program.club_house.shape.to_shapely()
    assert after.symmetric_difference(affinity.translate(before, 2.0, 0.0)).area < 1e-6
    piece = edits.edit(tmp_path, record, "rectangle-1",
                       lambda x: edits.moved_piece(x, 2, 0.0, -3.0), ["tot-lot piece 2 moved"])
    moved = piece.candidate.program.open_space[1].to_shapely()
    assert moved.bounds[1] == pytest.approx(c.program.open_space[1].to_shapely().bounds[1] - 3.0)
    assert piece.candidate.program.open_space[0] == c.program.open_space[0]
    with pytest.raises(EditRefused, match="pieces 1 to 2"):
        edits.moved_piece(c, 3, 1.0, 0.0)


def test_an_edit_claims_only_the_open_space_the_validator_counts(tmp_path):
    """Found on Dhulapally (2026-10-16): the club house moved 5 m north onto open ground kept the
    generator's open-space figure, which the validator then reported as claiming more than
    counts. An edited layout's figure is the validator's own."""
    record, _ = _run(tmp_path)
    done = edits.edit(tmp_path, record, "rectangle-1", lambda x: edits.moved_club(x, 0.0, -9.0),
                      ["club house moved 9 m south, onto the open space"])
    found = done.report.recomputed.quantities
    counting = found.get("open_space_study_counting_sqm", min(
        v for k, v in found.items() if k.startswith("open_space_counting_sqm")))
    assert done.candidate.metrics.open_space_sqm == pytest.approx(counting)
    assert "open space" not in {d.item for d in done.report.cross_checks}


def test_a_locked_block_cannot_be_moved_and_stays_locked_down_the_line(tmp_path):
    record, _ = _run(tmp_path)
    locked = edits.lock(tmp_path, record, "rectangle-1", ["T1"])
    assert locked.version.locked == ["T1"] and locked.version.edits == ["T1 locked"]
    with pytest.raises(EditRefused, match="T1 is locked"):
        edits.edit(tmp_path, record, locked.version.version_id,
                   lambda c: edits.moved_block(c, "T1", 1.0, 0.0), ["T1 moved"], moves=["T1"])
    child = edits.edit(tmp_path, record, locked.version.version_id,
                       lambda c: edits.moved_block(c, "T2", -1.0, 0.0), ["T2 moved"],
                       moves=["T2"])
    assert child.version.locked == ["T1"]
    with pytest.raises(EditRefused, match="no block T9"):
        edits.lock(tmp_path, record, "rectangle-1", ["T9"])


# --- through FreeCAD (stood in for in memory) ----------------------------------------------------


def test_each_edit_in_cad_saves_a_version_redraws_it_and_says_what_broke(tmp_path):
    _run(tmp_path)
    session, drawing = _session(tmp_path)
    session.show_layout("plot", RUN, "rectangle-1")
    moved = session.move_block("plot", RUN, "rectangle-1", "T1", 1.0, 0.0)
    assert moved["version"] == "rectangle-1-v1"
    assert any("PASS -> FAIL" in b for b in moved["broke"])
    text = drawing.docs["Siteplan_plot"]["layout-sheet-label"]["text"]
    assert "a version of rectangle-1: T1 moved 1.00 m east, 0.00 m north" in text
    turned = session.turn_block("plot", RUN, moved["version"], "T3", 90.0)
    assert turned["version"] == "rectangle-1-v2"
    club = session.move_club_house("plot", RUN, turned["version"], 0.0, 1.0)
    piece = session.move_tot_lot_piece("plot", RUN, club["version"], 1, 0.0, 1.0)
    locked = session.lock_blocks("plot", RUN, piece["version"], ["T2"])
    with pytest.raises(EditRefused):
        session.move_block("plot", RUN, locked["version"], "T2", 1.0, 0.0)
    line = [v.version_id for v in versions.listed(tmp_path, store.read_record(tmp_path, RUN))]
    assert line == [f"rectangle-1-v{n}" for n in range(1, 6)]


def test_a_layout_dragged_in_cad_is_read_back_as_one_version(tmp_path):
    _, inputs = _run(tmp_path)
    session, drawing = _session(tmp_path)
    session.show_layout("plot", RUN, "rectangle-1")
    drawing.move("layout-t2", -2.0, 0.0)  # T2 dragged 2 m west in FreeCAD
    doc = drawing.docs["Siteplan_plot"]
    club = inputs.candidate.program.club_house.shape.to_shapely()
    doc["layout-club-1"]["rings"] = [[to_cad(p) for p in affinity.translate(
        club, 0.0, -1.0).exterior.coords]]  # the club house redrawn 1 m south
    read = session.read_layout_from_cad("plot", RUN, "rectangle-1")
    assert read["edits"] == ["T2 moved 2.00 m west, 0.00 m north",
                             "club house redrawn in CAD"]
    candidate = versions.load(tmp_path, store.read_record(tmp_path, RUN), read["version"])[1]
    assert _t(candidate, "T2").x == pytest.approx(_t(inputs.candidate, "T2").x - 2.0)
    nothing = session.read_layout_from_cad("plot", RUN, read["version"])
    assert nothing["edits"] == [] and nothing["version"] is None  # nothing moved, nothing saved


def test_the_cad_tools_offer_the_edits_and_none_runs_code(tmp_path):
    _run(tmp_path)
    session, _ = _session(tmp_path)
    names = {t.name for t in asyncio.run(build(session).list_tools())}
    assert {"move_block", "turn_block", "move_club_house", "move_tot_lot_piece", "lock_blocks",
            "read_layout_from_cad"} <= names
    assert not any(word in n for n in names for word in ("exec", "eval", "python", "code"))
