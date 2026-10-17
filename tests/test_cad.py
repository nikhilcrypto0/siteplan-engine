"""The live CAD link on made-up land: the engine's step 4 shapes reach CAD exactly, a redraw
updates in place, test towers are placed, moved, read back and removed with the engine's checks,
and the MCP tools and the FreeCAD macro offer no way to run code. FreeCAD itself is stood in for
by an in-memory drawing; `python -m siteplan.cad.acceptance` runs the same against a live one."""

TEST_CLASS = "normative"

import asyncio  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from test_steps import HIGH_RISE, _project, _survey, _workspace  # noqa: E402

from siteplan.cad import scene  # noqa: E402
from siteplan.cad.bridge import MM_PER_M, Bridge, NoBridge, from_cad, to_cad  # noqa: E402
from siteplan.cad.live import Session  # noqa: E402
from siteplan.cad.server import build  # noqa: E402

MACRO = Path(__file__).resolve().parents[1] / "cad" / "siteplan_live.FCMacro"


class Drawing:
    """FreeCAD's end, in memory: the same calls, the same answers."""

    def __init__(self):
        self.docs: dict[str, dict[str, dict]] = {}
        self.active = None

    def document(self, name):
        self.docs.setdefault(name, {})
        self.active = name
        return name

    def upsert(self, items, styles):
        doc, out = self.docs[self.active], []
        for item in items:
            made = item["id"] not in doc
            doc[item["id"]] = dict(item)
            out.append({"id": item["id"], "name": item["id"], "created": made})
        return out

    def remove(self, ids):
        doc = self.docs[self.active]
        return sum(1 for i in ids if doc.pop(i, None) is not None)

    def listing(self):
        return [{"id": k, "kind": v["kind"], "layer": v["layer"]}
                for k, v in self.docs[self.active].items()]

    def read(self, ident):
        item = self.docs[self.active].get(ident)
        if item is None:
            return None
        out = {"id": ident, "kind": item["kind"], "rings": item.get("rings", [])}
        if item["kind"] in ("outline", "area"):
            rings = item["rings"] if item["kind"] == "area" else item["rings"][:1]
            out["area"] = Polygon(rings[0], rings[1:]).area
        if item["kind"] == "dimension":
            (ax, ay), (bx, by) = item["start"], item["end"]
            out["measured"] = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        return out

    def move(self, ident, east_m, north_m):
        dx, dy = to_cad((east_m, north_m))
        item = self.docs[self.active][ident]
        item["rings"] = [[[x + dx, y + dy] for x, y in r] for r in item["rings"]]
        return ident

    def view(self, fit=True):
        return True


@pytest.fixture
def made_up(tmp_path):
    survey = _survey(tmp_path / "survey.dxf")
    sites = {"plot": {"survey": str(survey), "workspace": str(_workspace(tmp_path / "firm")),
                      "project": str(_project(tmp_path / "p.json", **HIGH_RISE)),
                      "mode": "blind"},
             "asks": {"survey": str(survey), "workspace": str(tmp_path / "firm"), "mode": "blind",
                      "project": str(_project(tmp_path / "asks.json", gross_area_sqm=10_800,
                                              net_area_sqm=10_200, road_strip_side="S"))}}
    drawing = Drawing()
    return Session(sites, drawing), drawing


def test_every_step_4_shape_reaches_cad_vertex_for_vertex_in_millimetres(made_up):
    session, _ = made_up
    s = session.site("plot").setbacks
    items = {i["id"]: i for i in scene.step4_items(s)}
    assert [from_cad(p) for p in items["survey-boundary"]["rings"][0]] == \
        list(s.copy.plot.exterior.coords)[:-1]
    assert [from_cad(p) for p in items["buildable"]["rings"][0]] == \
        list(s.left.exterior.coords)[:-1]
    assert items["setback-zone"]["kind"] == "area" and len(items["setback-zone"]["rings"]) == 2
    assert {i["layer"] for i in items.values()} <= set(scene.LAYERS)
    dims = [i for i in items.values() if i["kind"] == "dimension"]
    assert len(dims) == 4  # the 120 x 90 plot's four sides, 10 m each at Stilt + 10
    for d in dims:
        (ax, ay), (bx, by) = d["start"], d["end"]
        assert ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 == pytest.approx(10 * MM_PER_M)


def test_a_redraw_updates_in_place_and_cad_matches_the_engine(made_up):
    session, drawing = made_up
    first = session.show("plot", "setbacks")
    second = session.show("plot", "setbacks")
    assert first["created"] == first["drawn"] and second["created"] == 0
    assert second["updated"] == first["drawn"] == len(drawing.docs["Siteplan_plot"])
    compared = session.compare("plot")
    assert compared["all_agree"] and compared["objects"]["buildable"]["engine_sqm"] == 7000
    assert session.setback_distances("plot")["all_kept"]


def test_a_stopped_step_draws_what_exists_and_says_why(made_up):
    session, drawing = made_up
    shown = session.show("asks", "setbacks")
    assert shown["stopped"].startswith("step 3 stopped")
    assert {i["layer"] for i in drawing.listing()} <= {scene.SURVEY, scene.OUTSIDE_ROADS}


def test_a_tower_is_placed_moved_read_back_and_removed_with_the_engines_checks(made_up):
    session, drawing = made_up
    session.show("plot", "setbacks")
    placed = session.place_tower("plot", "T1", 40.0, 24.13)
    assert placed["checks"]["T1"]["holds"]
    before = session.sites["plot"].towers["T1"].polygon
    moved = session.move_tower("plot", "T1", east_m=3.0)
    after = session.sites["plot"].towers["T1"].polygon
    assert [round(a[0] - b[0], 9) for a, b in zip(after.exterior.coords, before.exterior.coords,
                                                 strict=True)] == [3.0] * 5
    assert moved["checks"]["T1"]["holds"]
    far = session.move_tower("plot", "T1", east_m=40.0)  # over the east setback
    assert not far["checks"]["T1"]["inside_setbacks"] and not far["checks"]["T1"]["holds"]
    session.move_tower("plot", "T1", east_m=-40.0)
    drawing.move("tower-T1", 0.0, -2.0)  # as a person dragging it in FreeCAD
    taken = session.read_back("plot", "T1")
    assert [p[1] for p in taken["towers"]["T1"]] == \
        [round(y - 2.0, 3) for _, y in before.exterior.coords[:-1]]
    close = session.place_tower("plot", "T2", 30.0, 24.13, x=after.centroid.x + 30,
                                y=after.centroid.y)  # 6 m apart, Table IV asks 10
    assert not close["checks"]["T2"]["gaps"]["T1"]["holds"]
    left = close["remaining_sqm"]
    gone = session.delete_tower("plot", "T2")
    assert gone["removed_objects"] == 2 and "tower-T2" not in drawing.docs["Siteplan_plot"]
    assert gone["remaining_sqm"] > left


def test_the_mcp_tools_reach_the_session_and_none_runs_code(made_up):
    session, drawing = made_up
    server = build(session)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"cad_status", "show_site", "site_summary", "place_tower", "move_tower",
                     "delete_tower", "read_tower_from_cad", "validate_towers",
                     "compare_cad_with_engine", "measure_setbacks_in_cad", "save_drawing",
                     "reopen_drawing", "show_layout", "keep_layout"}  # Stage B, 2026-10-16
    asyncio.run(server.call_tool("show_site", {"site": "plot", "what": "setbacks"}))
    asyncio.run(server.call_tool("place_tower", {"site": "plot", "tower": "T1",
                                                 "length_m": 40.0, "depth_m": 24.13}))
    asyncio.run(server.call_tool("move_tower", {"site": "plot", "tower": "T1", "east_m": 3.0}))
    assert "tower-T1" in drawing.docs["Siteplan_plot"]


def test_freecad_s_end_listens_on_this_machine_only_and_never_runs_code_it_is_sent():
    text = MACRO.read_text()
    assert 'HOST = "127.0.0.1"' in text and "0.0.0.0" not in text
    assert not re.search(r"\b(exec|eval|compile)\(", text)
    assert "compare_digest" in text and 'get("Origin")' in text
    calls = re.search(r"CALLS = \{f\.__name__: f for f in \(([^)]*)\)", text).group(1)
    assert {c.strip() for c in calls.split(",")} == {
        "ping", "document", "upsert", "remove", "listing", "read", "move", "save", "reopen",
        "view", "snapshot", "show_layer", "layers"}


def test_the_bridge_needs_freecad_s_token(tmp_path):
    with pytest.raises(NoBridge):
        Bridge(tmp_path)
    assert from_cad(to_cad((12.345678901, -0.5))) == (12.345678901, -0.5)


def test_a_steps_picture_reaches_cad_layer_for_layer_with_its_colours(made_up):
    """Steps 1 and 2 go to CAD from their own pictures: every shape vertex for vertex, every
    label as text, one CAD layer per picture layer in the picture's order, its colour kept."""
    from siteplan.steps import survey_copy_report

    session, _ = made_up
    copy = session.site("plot").setbacks.copy
    picture = survey_copy_report.picture(copy)
    groups, styles = scene.picture_layers(picture, "Step 1")
    names = [name for name, _ in groups]
    drawn = [layer.name for layer in picture.layers
             if any(n == layer.name for n, _ in picture.shapes + [(lb[0], 0) for lb in
                                                                   picture.labels])]
    assert names == [f"Step 1 · {n}" for n in drawn]
    plot = next(items for name, items in groups if name == "Step 1 · PLOT")
    assert [from_cad(p) for p in plot[0]["rings"][0]] == list(copy.plot.exterior.coords)[:-1]
    assert styles["Step 1 · PLOT"]["line"] == scene._rgb("#b0177e")
    texts = sum(1 for _, items in groups for i in items if i["kind"] == "text")
    assert texts == len(picture.labels)
    ids = [i["id"] for _, items in groups for i in items]
    assert len(ids) == len(set(ids))


def test_two_roads_or_amenities_with_one_name_stay_two_objects():
    """Found on Dhulapally (2026-10-12): two roads with the same label shared an id, so the
    second overwrote the first in FreeCAD. Every road and amenity now has its own id."""
    from shapely.geometry import box

    from siteplan.service.render import Plan

    plan = Plan(plot=box(0, 0, 100, 100), towers=(),
                roads=(("INTERNAL ROAD 9 M", (box(0, 0, 9, 50),)),
                       ("INTERNAL ROAD 9 M", (box(50, 0, 59, 50),))),
                fire=(), gates=(), green_strip=(), open_space=(), club=None, club_floors=0,
                amenities=(("Gym", box(70, 70, 80, 80)), ("Gym", box(85, 85, 95, 95))),
                ramps=(), cellars=(), bays=())
    ids = [i["id"] for _, items in scene.candidate_layers(plan, None, "") for i in items]
    assert len(ids) == len(set(ids)) == 5  # the plot, two roads, two amenities


def test_a_hole_a_hair_inside_its_outer_edge_reaches_cad_as_the_c_it_is():
    """Found on Dhulapally (2026-10-12): a fire lane round a block, broken at one place, came as
    a polygon whose hole ran 1e-12 m inside its outer edge: valid in metres, but closer than
    FreeCAD tells apart, so FreeCAD cut it into faces and the read-back saw only one. It is now
    sent as the C it is, its area kept."""
    from shapely.geometry import box

    lane = box(0, 0, 20, 20).difference(box(1e-12, 5, 10, 15))
    assert lane.is_valid and len(lane.interiors) == 1
    pieces = scene.parts(lane)
    assert all(not p.interiors for p in pieces)
    assert sum(p.area for p in pieces) == pytest.approx(lane.area, abs=1e-6)
    whole = box(0, 0, 20, 20).difference(box(5, 5, 15, 15))  # a real hole is kept
    assert [len(p.interiors) for p in scene.parts(whole)] == [1]


def test_a_tower_is_labelled_with_its_height_and_its_flats_a_floor():
    """The architect (2026-10-12): '12' alone read like twelve floors. A tower's label in CAD
    says its height too."""
    from shapely.geometry import box

    from siteplan.service.render import Plan, TowerShape

    tower = TowerShape(name="T1", footprint=box(0, 0, 40, 24), flats=(), cores=(),
                       flats_per_floor=12, floors_above_stilt=9)
    plan = Plan(plot=box(-50, -50, 100, 100), towers=(tower,), roads=(), fire=(), gates=(),
                green_strip=(), open_space=(), club=None, club_floors=0, amenities=(),
                ramps=(), cellars=(), bays=())
    items = [i for _, layer in scene.candidate_layers(plan, None, "") for i in layer]
    text = next(i for i in items if i["kind"] == "text")["text"]
    outline = next(i for i in items if i["id"] == "layout-t1")["label"]
    assert text == "T1\nStilt + 9\n12 flats a floor"
    assert outline == "T1 · Stilt + 9 · 12 flats a floor"
