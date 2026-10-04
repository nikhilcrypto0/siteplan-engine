"""The host boundary a future model-facing transport will hold (siteplan.service.host).

No model and no transport: the tests call the ToolHost as a transport would, with plain JSON
arguments. It offers the nine operations and nothing else, refuses what a request model refuses
and any tool it does not have, asks the architect only on the approval page, and keeps `out`
clear of the workspace. The browser is played as tests/test_service_approvers.py plays it: it
opens the real approval page and clicks. Made-up land only.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_service import (
    ALLOWED_FIELDS,
    BANNED_WORDS,
    BRIEF,
    OPERATIONS,
    SERVICE,
    VALID,
    make_workspace,
)
from test_service_approvers import Browser

from siteplan.approval import ApprovalDesk
from siteplan.service import (
    Asked,
    Decision,
    PageApprover,
    Service,
    ServiceError,
    TerminalApprover,
    ToolHost,
    audit,
)
from siteplan.service.host import TOOLS

TEST_CLASS = "normative"

PROJECT, SURVEY = "service-test.project.json", "survey.dxf"
PROPOSE = {"project_file": PROJECT, "survey_file": SURVEY, "brief": BRIEF,
           "intent": {"height": "MOST_THE_RULES_ALLOW",
                      "unit_mix_percent": {"2BHK": 70, "3BHK": 30}}}


def _quiet_page() -> PageApprover:
    """The approval page with nobody at the browser: never asked in these tests."""
    return PageApprover(ApprovalDesk(open_page=lambda url: None), timeout_s=0.1)


@pytest.fixture(scope="module")
def ws(tmp_path_factory) -> Path:
    return make_workspace(tmp_path_factory.mktemp("host-workspace"))


@pytest.fixture
def host(ws, tmp_path) -> ToolHost:
    return ToolHost(ws, tmp_path / "out", _quiet_page())


# --- what the host offers --------------------------------------------------------------------


def test_the_host_offers_exactly_the_nine_operations(host):
    public = sorted(name for name, _ in inspect.getmembers(Service, inspect.isfunction)
                    if not name.startswith("_"))
    tools = host.tools()
    assert [t["name"] for t in tools] == list(OPERATIONS) and sorted(OPERATIONS) == public
    for tool in tools:
        spec = TOOLS[tool["name"]]
        assert set(tool) == {"name", "description", "input_schema", "output_schema"}
        assert tool["description"] == inspect.getdoc(getattr(Service, tool["name"]))
        assert tool["input_schema"] == spec.request.model_json_schema()
        assert tool["output_schema"] == spec.response.model_json_schema()
    json.dumps(tools)  # plain JSON, ready for a transport
    for name in ("validate_candidate", "export_candidate"):  # the audit, read-only
        schema = next(t["output_schema"] for t in tools if t["name"] == name)
        assert "approvals" in schema["properties"]


def _objects(schema: dict):
    """Every object schema in an input schema, its $defs included."""
    if isinstance(schema, dict):
        if "properties" in schema:
            yield schema
        for value in schema.values():
            yield from _objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _objects(value)


def test_every_input_schema_refuses_extra_fields_and_has_no_banned_field(host):
    for tool in host.tools():
        objects = list(_objects(tool["input_schema"]))
        assert objects, tool["name"]
        for schema in objects:
            assert schema.get("additionalProperties") is False, (tool["name"], schema)
            fields = set(schema["properties"])
            assert fields <= ALLOWED_FIELDS, (tool["name"], fields - ALLOWED_FIELDS)
            assert not [f for f in fields for word in BANNED_WORDS if word in f], tool["name"]


def _valid(name: str) -> dict:
    return dict(VALID[TOOLS[name].request.__name__])


@pytest.mark.parametrize("name", ["optimize", "validate", "Service", "_service", "__init__",
                                  "propose_layouts ", "", "legacy_propose_layouts",
                                  "check_rules", None, 5])
def test_call_refuses_a_tool_it_does_not_have(host, name):
    with pytest.raises(ServiceError, match="no such tool"):
        host.call(name, {})


@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.parametrize("key", ["setback_m", "_status", "_source", "selections", "profile",
                                 "validator", "mode", "approved", "max_tower_length_m",
                                 "out", "workspace"])
def test_call_refuses_a_key_the_request_model_does_not_have(host, name, key):
    with pytest.raises(ServiceError, match="do not fit") as refused:
        host.call(name, {**_valid(name), key: 1})
    # The same words whatever was refused: the reason stays in the log.
    assert str(refused.value) == (f"The arguments do not fit {name}'s input schema "
                                  "(tools() gives it).")


def test_call_refuses_keys_injected_into_the_intent_and_arguments_that_are_not_an_object(host):
    for key in ("_status", "stilt_height_m", "validator", "approve"):
        with pytest.raises(ServiceError, match="do not fit"):
            host.call("propose_layouts", {**PROPOSE, "intent": {key: 1}})
    for arguments in ([], None, "{}", 5):
        with pytest.raises(ServiceError, match="JSON object"):
            host.call("open_project", arguments)


# --- what construction enforces --------------------------------------------------------------


class AlwaysYes:
    def approve(self, title: str, lines: list[str]) -> bool:
        return True


class YesPage(PageApprover):
    def approve(self, title: str, lines: list[str]) -> bool:
        return True


@pytest.mark.parametrize("approver", [TerminalApprover(), AlwaysYes(), YesPage(), None],
                         ids=["terminal", "plain-object", "page-subclass", "none"])
def test_construction_refuses_any_channel_but_the_approval_page(ws, tmp_path, approver):
    with pytest.raises(TypeError, match="approval page only"):
        ToolHost(ws, tmp_path / "out", approver)


def test_construction_keeps_out_clear_of_the_workspace(ws, tmp_path):
    for out in (ws, ws / "out", ws / "deep" / "runs", ws.parent, ws / ".."):
        with pytest.raises(ValueError, match="neither inside the workspace"):
            ToolHost(ws, out, _quiet_page())
    with pytest.raises(ValueError, match="not a folder"):
        ToolHost(ws / PROJECT, tmp_path / "out", _quiet_page())
    ToolHost(ws, tmp_path / "out", _quiet_page())  # beside it is where it belongs


def test_the_host_shows_a_transport_two_methods_and_nothing_more(host):
    assert sorted(n for n in dir(host) if not n.startswith("_")) == ["call", "tools"]
    assert sorted(n for n in vars(ToolHost) if not n.startswith("_")) == ["call", "tools"]
    assert list(inspect.signature(ToolHost.call).parameters) == ["self", "name", "arguments"]


def _siteplan_imports(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return [m for m in found if m == "siteplan" or m.startswith("siteplan.")]


def test_the_host_reaches_the_engine_only_through_the_service():
    imports = _siteplan_imports((SERVICE / "host.py").read_text())
    assert imports and all(m.startswith("siteplan.service.") for m in imports), imports


# --- a proposal through the host, asked on the page -------------------------------------------


def _hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


@dataclass
class Hosted:
    ws: Path
    out: Path
    browser: Browser
    before: dict[str, str]
    proposed: dict
    checked: dict
    exported: dict


@pytest.fixture(scope="module")
def hosted(tmp_path_factory) -> Hosted:
    ws = make_workspace(tmp_path_factory.mktemp("host-run"))
    out = tmp_path_factory.mktemp("host-run-out")
    before = _hashes(ws)
    browser = Browser("approve")
    approver = PageApprover(ApprovalDesk(open_page=browser), timeout_s=10.0)
    host = ToolHost(ws, out, approver)
    try:
        proposed = host.call("propose_layouts", PROPOSE)
        first = proposed["candidates"][0]["candidate_id"]
        checked = host.call("validate_candidate", {"run_id": proposed["run_id"],
                                                   "candidate_id": first})
        exported = host.call("export_candidate", {
            "run_id": proposed["run_id"], "candidate_id": first,
            "acknowledged_unresolved": [item["item"] for item in checked["unverified"]]})
    finally:
        approver.close()
    return Hosted(ws, out, browser, before, proposed, checked, exported)


def test_a_proposal_through_the_host_runs_once_the_architect_clicks_and_is_audited(hosted):
    assert hosted.proposed["status"] == "PROPOSED" and hosted.proposed["candidates"]
    assert hosted.exported["status"] == "EXPORTED", hosted.exported["reasons"]
    assert len(hosted.browser.opened) == 2  # the request, then the UNVERIFIED items
    proposal, export = (audit.read(hosted.out))
    assert (proposal.asked, proposal.decision, proposal.channel) == (
        Asked.PROPOSAL, Decision.APPROVED, "PageApprover")
    assert proposal.run_id == hosted.proposed["run_id"]
    assert (export.asked, export.decision, export.channel) == (
        Asked.EXPORT, Decision.APPROVED, "PageApprover")
    assert hosted.checked["approvals"] == [proposal.model_dump(mode="json")]
    assert hosted.exported["approvals"] == [proposal.model_dump(mode="json"),
                                            export.model_dump(mode="json")]
    assert proposal.title in hosted.browser.pages[0]  # what the architect saw is what is kept


def test_the_pages_token_never_reaches_the_caller_or_the_audit(hosted):
    tokens = [urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["t"][0]
              for url in hosted.browser.opened]
    kept = [json.dumps(hosted.proposed), json.dumps(hosted.checked), json.dumps(hosted.exported),
            (hosted.out / audit.LOG).read_text(),
            (hosted.out / hosted.proposed["run_id"] / "run.json").read_text()]
    assert tokens and not [t for t in tokens for text in kept if t in text]


def test_the_host_writes_only_to_out_and_leaves_the_workspace_as_it_was(hosted):
    assert _hashes(hosted.ws) == hosted.before
    assert all(Path(f).is_relative_to(hosted.out) for f in hosted.exported["files"])


@pytest.mark.parametrize(("click", "timeout_s", "decision"), [
    ("reject", 10.0, Decision.REJECTED), (None, 0.3, Decision.UNANSWERED)],
    ids=["rejected", "unanswered"])
def test_a_page_not_approved_runs_nothing_and_is_audited(ws, tmp_path, click, timeout_s,
                                                         decision):
    browser = Browser(click)
    approver = PageApprover(ApprovalDesk(open_page=browser), timeout_s=timeout_s)
    out = tmp_path / "out"
    try:
        result = ToolHost(ws, out, approver).call("propose_layouts", PROPOSE)
    finally:
        approver.close()
    assert result["status"] == "NOT_APPROVED" and result["run_id"] is None
    assert len(browser.opened) == 1 and not list(out.glob("*/run.json"))
    (entry,) = audit.read(out)
    assert (entry.decision, entry.channel, entry.run_id) == (decision, "PageApprover", None)
