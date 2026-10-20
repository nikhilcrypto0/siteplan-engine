"""Every tower's way in from the gate (2026-10-19, the architect): its entrance, its driveway from
the road and the shortest route a car can drive, measured by the validator and judged as the
client's requirement, never law. Made-up land (tests/contract_fixtures)."""

import math
from unittest.mock import patch

import ezdxf
import search_support
from shapely import affinity
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from validator_helpers import fixture

from siteplan import validator as independent
from siteplan.cad import scene
from siteplan.contracts.candidate import RoadKind, RoadPiece
from siteplan.contracts.common import Shape, Status
from siteplan.contracts.validation import Family
from siteplan.optimizer.guard import inputs_of, unreached, why_refused
from siteplan.optimizer.search import fringe
from siteplan.optimizer.search.layout import make_run
from siteplan.service.render import plan_of, write_dxf, write_sheet, write_svg
from siteplan.sheet import SheetInfo
from siteplan.validator import routes

TEST_CLASS = "normative"
DRIVEWAY_M = 4.5


def _route_checks(report):
    return [c for c in report.program if c.finding.rule.startswith("Route: ")]


def test_every_tower_has_an_entrance_on_its_outline_and_a_route_from_the_gate():
    inputs = fixture("rectangle")
    c = inputs.candidate
    found = routes.ways(c, DRIVEWAY_M)
    assert [w.tower for w in found] == [t.name for t in c.towers]
    gate = c.circulation.gates[0].shape.to_shapely()
    for way, tower in zip(found, c.towers, strict=True):
        assert way.found, way.why
        assert c.placed_footprint(tower).exterior.distance(way.entrance) < 1e-6
        assert routes.drivable(c).distance(way.road_point) < 1e-6
        # never shorter than the straight line, and it starts in a gate
        start, end = Point(way.route.coords[0]), Point(way.route.coords[-1])
        assert way.route_m + 1e-6 >= start.distance(end)
        assert gate.buffer(routes.CAR_CLEAR_M + 0.5).contains(Point(way.route.coords[0]))
        gap = way.entrance.distance(way.road_point)  # within half a metre it stands on the road
        assert math.isclose(way.driveway_m, gap if gap > routes.ON_ROAD_M else 0.0, abs_tol=1e-6)


def test_the_route_bends_round_the_roads_and_stays_on_them():
    c = fixture("rectangle").candidate
    ground = routes.drivable(c)
    for way in routes.ways(c, DRIVEWAY_M):
        assert ground.buffer(1e-3).covers(way.route)
        assert math.isclose(way.route.length, way.route_m, abs_tol=routes.CAR_CLEAR_M + 1e-6)


def test_a_tower_with_no_gate_has_no_way_and_says_why():
    inputs = fixture("rectangle").edited(lambda c: c.circulation.gates.clear())
    assert {w.why for w in routes.ways(inputs.candidate, DRIVEWAY_M)} == {"no gate is drawn"}


def test_a_driveway_that_would_cross_another_block_is_refused():
    c = fixture("rectangle").candidate
    way = routes.ways(c, DRIVEWAY_M)[0]
    drive = LineString([way.entrance, way.road_point])
    if drive.length:  # a block planted on its driveway: the way in moves or is refused
        blocker = drive.buffer(1.0)
        found = routes._way(c.towers[0], c.placed_footprint(c.towers[0]),
                            routes._cores(c, c.towers[0]), routes.drivable(c),
                            routes._Graph(routes.drivable(c),
                                          [g.shape.to_shapely() for g in c.circulation.gates]),
                            blocker, DRIVEWAY_M)
        assert not found.found or found.entrance != way.entrance


def test_the_report_lists_each_towers_route_as_a_check_of_the_program_never_law():
    inputs = fixture("rectangle")
    report = inputs.report()
    checks = _route_checks(report)
    assert [c.finding.rule for c in checks] == [f"Route: {t.name}"
                                          for t in inputs.candidate.towers]
    assert [c.subject for c in checks] == [t.name for t in inputs.candidate.towers]
    assert all(c.family is Family.PROGRAM and c.finding.status is Status.PASS for c in checks)
    assert all(" m from the gate" in c.finding.measured for c in checks)
    assert not any(c.finding.rule.startswith("Route: ") for c in report.legal)


def test_a_tower_no_car_reaches_fails_its_route_check():
    checks = _route_checks(fixture("rectangle").edited(
        lambda c: c.circulation.gates.clear()).report())
    assert checks and all(c.finding.status is Status.FAIL for c in checks)
    assert all("no gate is drawn" in c.finding.measured for c in checks)


# --- The drawings ---------------------------------------------------------------------------


def test_every_drawing_shows_each_towers_way_in_every_roads_width_and_north(tmp_path):
    inputs = fixture("rectangle")
    plan = plan_of(inputs.site, inputs.candidate)
    towers = [t.name for t in inputs.candidate.towers]
    assert [w.tower for w in plan.ways] == towers and all(w.found for w in plan.ways)
    road_parts = sum(len(getattr(p, "geoms", [p])) for _, pieces in plan.roads for p in pieces)
    for path in (write_dxf(plan, tmp_path / "plan.dxf", []),
                 write_sheet(plan, tmp_path / "sheet.dxf", SheetInfo(project="made-up"), "", [])):
        msp = ezdxf.readfile(path).modelspace()
        texts = [e.dxf.text for e in msp.query("TEXT")]
        assert sum("ROAD" in t and t.endswith(" M") for t in texts) >= road_parts, path.name
        for name in towers:
            assert any(t.startswith(f"{name}: ") and "FROM THE GATE" in t for t in texts)
        assert len(msp.query('CIRCLE[layer=="SOLVER-TOWER-ENTRANCE"]')) == len(towers)
        assert len(msp.query('LWPOLYLINE[layer=="SOLVER-ROUTES"]')) == len(towers)
        assert msp.query('LWPOLYLINE[layer=="SOLVER-DRIVEWAYS"]')  # T1 and T3 stand back
        assert msp.query('TEXT[layer=="SHEET-NORTH"]'), "no north arrow"
    svg = write_svg(plan, tmp_path / "plan.svg", "t", "s", []).read_text()
    assert svg.count(" m from the gate") == len(towers) and ">N</text>" in svg
    assert svg.count("Road 9 M") >= road_parts
    items = [i for _, group in scene.candidate_layers(plan, None, "") for i in group]
    ways = [i for i in items if i["layer"] == scene.ROUTES]
    assert {i["label"] for i in ways if i["kind"] == "point"} == {f"{n} entrance" for n in towers}
    assert {i["label"] for i in ways if i["kind"] == "line"} == {
        f"{n} route from the gate" for n in towers}
    assert [i["text"] for i in items if i["layer"] == scene.NORTH and i["kind"] == "text"] == ["N"]


def test_a_tower_with_no_way_in_says_so_on_every_drawing(tmp_path):
    inputs = fixture("rectangle").edited(lambda c: c.circulation.gates.clear())
    plan = plan_of(inputs.site, inputs.candidate)
    towers = len(inputs.candidate.towers)
    svg = write_svg(plan, tmp_path / "plan.svg", "t", "s", []).read_text()
    assert svg.count("no drivable route") == towers
    texts = [e.dxf.text for e in ezdxf.readfile(write_dxf(plan, tmp_path / "p.dxf", []))
             .modelspace().query("TEXT")]
    assert sum("NO DRIVABLE ROUTE" in t for t in texts) == towers
    items = [i for _, group in scene.candidate_layers(plan, None, "") for i in group]
    assert sum("no drivable route" in i.get("text", "") for i in items) == towers


# --- Along the roads' centre lines (2026-10-19: a straight line between points looked as if it
# crossed a park or a block) ---------------------------------------------------------------


def test_a_route_follows_the_centre_lines_of_the_roads_it_takes():
    """The full search's layouts carry each road's centre line; every bend of a route lies on
    one, and only its last step leaves it, across to where the driveway starts."""
    c = search_support.proposal_on_the_rectangle().candidates[0]
    lines = routes.centre_lines(c)
    assert len(lines) == len(c.circulation.roads)
    net = unary_union(lines)
    for way in routes.ways(c, DRIVEWAY_M):
        assert way.found, way.why
        assert all(net.distance(Point(xy)) < 1e-6 for xy in way.route.coords), way.tower
        assert math.isclose(way.route.length + way.route.boundary.geoms[-1].distance(
            way.road_point), way.route_m, abs_tol=1e-6)


def test_without_centre_lines_a_route_still_runs_inside_the_pavement():
    c = search_support.proposal_on_the_rectangle().candidates[0]
    bare = c.model_copy(update={"circulation": c.circulation.model_copy(update={"roads": [
        r.model_copy(update={"centre_line": None}) for r in c.circulation.roads]})})
    assert routes.centre_lines(bare) == []
    assert "centre_line" not in bare.circulation.roads[0].model_dump()  # stored as before
    ground = routes.drivable(bare).buffer(1e-3)
    for way in routes.ways(bare, DRIVEWAY_M):
        assert way.found and ground.covers(way.route)


def test_a_centre_line_off_the_pavement_is_not_followed():
    c = search_support.proposal_on_the_rectangle().candidates[0]
    stray = c.model_copy(deep=True)
    road = stray.circulation.roads[0]
    road.centre_line = road.centre_line.model_copy(update={"points": [
        (x + 50.0, y) for x, y in road.centre_line.points]})
    assert routes.centre_lines(stray) == []


# --- Never a tower the roads do not reach (2026-10-19: two layouts placed blocks that only
# touched the ring road at a corner, with no way in) -------------------------------------------


def test_a_block_that_only_touches_the_road_at_a_corner_is_not_on_it():
    made = search_support.rectangle()  # any made-up site: the rules give the pathway's 6 m
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, [])
    ring = box(0, 0, 100, 9)
    along = box(10, 9, 40, 23)  # faces the road along 30 m
    corner = affinity.rotate(box(50, 9, 80, 23), 30, origin=(50, 9))  # touches it at a point
    assert fringe.fronts_road(along, ring, run.q)
    assert along.distance(ring) < 1e-9 and corner.distance(ring) < 1e-6
    assert not fringe.fronts_road(corner, ring, run.q)


def test_a_pathway_is_a_way_in():
    c = fixture("rectangle").candidate
    path = box(-50, -50, -44, -40)  # a 6 m pathway, somewhere on its own
    edited = c.model_copy(deep=True)
    edited.circulation.roads.append(RoadPiece(id="pathway-9", kind=RoadKind.PATHWAY,
                                              shapes=[Shape.from_shapely(path)],
                                              declared_width_m=6.0))
    assert routes.drivable(edited).covers(path)


def test_a_layout_with_a_tower_no_road_reaches_is_refused_by_the_guard():
    inputs = fixture("rectangle").edited(lambda c: c.circulation.gates.clear())
    report = inputs.report()
    why = why_refused(inputs.candidate, report, inputs_of(inputs.site, inputs.rules,
                                                          inputs.brief))
    stranded = unreached(report)
    assert stranded and all("no gate is drawn" in s for s in stranded)
    assert set(stranded) <= set(why)
    assert not unreached(fixture("rectangle").report())


def test_the_search_never_proposes_a_layout_with_a_tower_it_cannot_reach():
    """A tower the route check says no road reaches: the search drops its layout and says so in
    its notes; every layout it proposes reaches every tower."""
    made = search_support.rectangle()
    real = routes.ways

    def stranding(candidate, driveway_m):  # the first tower of every other layout stranded
        found = real(candidate, driveway_m)
        if sum(ord(ch) for ch in candidate.candidate_id) % 2:
            found[0] = routes.Way(found[0].tower, why="made up for the test")
        return found

    with patch.object(routes, "ways", stranding):
        proposal = search_support.strategy().propose(made.context())
        for c in proposal.candidates:
            report = independent.validate(made.site, made.rules, made.brief, c, made.envelope)
            assert not unreached(report), c.candidate_id
    assert any("dropped because a tower has no road or pathway" in n for n in proposal.notes)
