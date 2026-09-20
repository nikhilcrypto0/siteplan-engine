"""The MCP server, driven by an in-memory MCP client standing in for the agent harness.

`Architect` plays the person answering the approval prompt. Its default answer mirrors
Hermes Agent, which accepts with an empty form.
"""

import json
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import anyio
import pytest
from browser_stub import clicker, read_page
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ElicitResult
from shapely.geometry import Polygon

from siteplan.approval import ApprovalDesk
from siteplan.dxf_export import write_survey_dxf
from siteplan.mcp_server import build_server
from siteplan.survey import Survey

EXAMPLES = Path(__file__).parent.parent / "examples"
BRIEF = "Stilt plus 8 floors, 70% 2BHK and the rest 3BHK."
LAYOUT_ARGS = {
    "project_file": "example.project.json",
    "library_file": "flat_library.example.json",
    "brief": BRIEF,
    "floors_above_stilt": 8,
    "unit_mix_percent": {"2BHK": 70, "3BHK": 30},
}
READ_TOOLS = {"list_files", "read_survey_drawing", "check_rules", "area_statement"}


class Architect:
    def __init__(self, action="accept", content=None, fail=False):
        self.action, self.content, self.fail = action, content or {}, fail
        self.asked: list[str] = []

    async def __call__(self, context, params):
        self.asked.append(params.message)
        if self.fail:
            raise RuntimeError("approval surface crashed")
        return ElicitResult(action=self.action,
                            content=self.content if self.action == "accept" else None)


@pytest.fixture
def ws(tmp_path):
    shutil.copytree(EXAMPLES, tmp_path / "ws")
    return tmp_path / "ws"


def call(ws, tool, args=None, architect=None, approval="elicit", desk=None, wait=5.0,
         opened=None):
    async def go():  # opened=None: no browser window is ever opened during tests
        server = build_server(ws, ws / "out", approval, desk, wait,
                              open_result=None if opened is None else opened.append)
        async with create_connected_server_and_client_session(
            server, elicitation_callback=architect
        ) as client:
            if tool is None:
                return await client.list_tools()
            return await client.call_tool(tool, args or {})

    return anyio.run(go)


def ok(result):
    assert not result.isError, result.content
    return result.structuredContent


def nothing_drawn(ws):
    out = ws / "out"
    return not out.exists() or not any(out.rglob("*.dxf"))


def test_tools_carry_honest_annotations(ws):
    tools = {t.name: t for t in call(ws, None).tools}
    assert set(tools) == READ_TOOLS | {"propose_layouts"}
    assert all(tools[name].annotations.readOnlyHint for name in READ_TOOLS)
    assert tools["propose_layouts"].annotations.readOnlyHint is False


def test_list_files_classifies_the_workspace(ws):
    found = ok(call(ws, "list_files"))
    assert found["projects"] == ["example.project.json"]
    assert found["flat_libraries"] == ["flat_library.example.json"]
    assert "assistant.config.json" not in json.dumps(found)


def test_survey_summary_is_computed(ws):
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    write_survey_dxf(Survey("synthetic", square, 10000, None, (), ()), ws / "site.dxf")
    summary = ok(call(ws, "read_survey_drawing", {"survey_file": "site.dxf"}))
    assert summary["boundary"]["area_sqm"] == pytest.approx(10000)


def test_rules_and_area_statement(ws):
    findings = ok(call(ws, "check_rules", {"project_file": "example.project.json"}))["result"]
    assert findings and all(f["clause"] and f["status"] for f in findings)
    statement = call(ws, "area_statement", {"project_file": "example.project.json"})
    assert "BLOCK - A, B" in statement.content[0].text


@pytest.mark.parametrize("name", ["../secret.project.json", "/etc/hosts", "missing.json"])
def test_files_outside_the_workspace_are_refused_without_saying_why(ws, name):
    shutil.copy(ws / "example.project.json", ws.parent / "secret.project.json")
    result = call(ws, "check_rules", {"project_file": name})
    assert result.isError
    assert "is not a readable file in the workspace" in result.content[0].text
    assert "outside" not in result.content[0].text


def test_approved_request_is_solved_and_compared_in_code(ws):
    architect = Architect()  # Hermes-style: accept with an empty form
    reply = ok(call(ws, "propose_layouts", LAYOUT_ARGS, architect))
    assert reply["solved"] is True
    assert len(architect.asked) == 1
    assert "Floors above the stilt: 8" in architect.asked[0]
    assert "2BHK 70%" in architect.asked[0]
    best = max(reply["options"], key=lambda o: o["saleable_sqft"])
    assert reply["comparison"].startswith(f"Option {best['option']} sells the most")
    assert all(Path(o["dxf"]).is_file() and Path(o["preview_svg"]).is_file()
               for o in reply["options"])
    record = json.loads((Path(reply["folder"]) / "run.json").read_text())
    assert record["approved_request"]["floors"] == 8


@pytest.mark.parametrize(
    ("architect", "reason"),
    [
        (Architect("decline"), "did not approve"),
        (Architect("cancel"), "did not approve"),
        (Architect("accept", {"approve": False}), "did not approve"),
        (Architect(fail=True), "could not show the architect the approval prompt"),
        (None, "could not show the architect the approval prompt"),
    ],
    ids=["decline", "cancel", "unticked", "approval-crashed", "client-cannot-ask"],
)
def test_anything_but_an_approval_draws_nothing(ws, architect, reason):
    reply = ok(call(ws, "propose_layouts", LAYOUT_ARGS, architect))
    assert reply["solved"] is False
    assert reason in reply["next"]
    assert nothing_drawn(ws)


def test_the_drawings_open_by_themselves_when_the_run_finishes(ws):
    opened: list[str] = []
    reply = ok(call(ws, "propose_layouts", LAYOUT_ARGS, Architect(), opened=opened))
    page = Path(reply["results_page"])
    assert opened == [page.as_uri()] and page.is_file()
    html = page.read_text()
    assert html.count("<img src=") == len(reply["options"])
    assert 'src="option_1.svg"' in html and 'href="option_1.dxf"' in html
    assert reply["comparison"].splitlines()[0] in html
    assert "No rule failures" in html and "placeholder" not in html.lower()


def test_the_project_settings_apply_and_the_brief_still_wins(ws):
    project = json.loads((ws / "example.project.json").read_text())
    project["layout"] = {"floors": 5, "unit_mix": {"2BHK": 1.0}, "max_tower_length_m": 40}
    (ws / "example.project.json").write_text(json.dumps(project))
    reply = ok(call(ws, "propose_layouts", LAYOUT_ARGS, Architect()))
    record = json.loads((Path(reply["folder"]) / "run.json").read_text())
    assert record["approved_request"]["max_tower_length_m"] == 40   # from the project file
    assert record["approved_request"]["floors"] == 8                # from the brief


def test_missing_values_come_back_without_asking(ws):
    architect = Architect()
    args = LAYOUT_ARGS | {"unit_mix_percent": None}
    reply = ok(call(ws, "propose_layouts", args, architect))
    assert reply["solved"] is False and reply["missing"] == ["unit mix"]
    assert architect.asked == [] and nothing_drawn(ws)


def test_a_value_the_brief_never_stated_is_flagged_to_the_architect(ws):
    architect = Architect("decline")
    call(ws, "propose_layouts", LAYOUT_ARGS | {"floors_above_stilt": 9}, architect)
    assert "CHECK: the brief never states floors" in architect.asked[0]


@pytest.mark.parametrize(
    ("decision", "solved"), [("approve", True), ("reject", False)], ids=["approve", "reject"]
)
def test_the_approval_page_decides_and_its_link_never_reaches_the_model(ws, decision, solved):
    seen: list[str] = []
    desk = ApprovalDesk(open_page=clicker(decision, seen=seen))
    try:
        reply = ok(call(ws, "propose_layouts", LAYOUT_ARGS, approval="page", desk=desk))
    finally:
        desk.close()
    assert reply["solved"] is solved
    assert nothing_drawn(ws) is not solved
    assert len(seen) == 1
    token = parse_qs(urlparse(seen[0]).query)["t"][0]
    assert token not in json.dumps(reply) and "127.0.0.1" not in json.dumps(reply)


def test_the_approval_page_shows_what_the_brief_never_stated(ws):
    shown: list[str] = []
    desk = ApprovalDesk(open_page=lambda url: shown.append(read_page(url)))
    try:
        call(ws, "propose_layouts", LAYOUT_ARGS | {"floors_above_stilt": 9},
             approval="page", desk=desk, wait=0.5)  # nobody clicks: the page still showed
    finally:
        desk.close()
    assert "CHECK: the brief never states floors" in shown[0]
    assert "Floors above the stilt: 9" in shown[0]


def test_unknown_flat_category_is_refused(ws):
    result = call(ws, "propose_layouts", LAYOUT_ARGS | {"unit_mix_percent": {"4BHK": 100}},
                  Architect())
    assert result.isError and "4BHK" in result.content[0].text
    assert nothing_drawn(ws)
