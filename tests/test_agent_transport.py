"""The model-facing transport (siteplan.agent.server, `siteplan-agent-tools`): the ToolHost's
nine operations over MCP on stdio, and nothing else.

The host runs as its own process, as the launcher starts it, and the test drives it through the
model's harness (siteplan.agent.harness) over the process's stdin and stdout. The architect's
browser is played out of band: the host opens the approval page with Python's webbrowser, which
runs the command BROWSER names, here a script that only writes the URL to an inbox file; a thread
of the test reads it, opens the real page and clicks. The link and its token go host -> browser,
never through the MCP stream. Made-up land only (test_service.make_workspace).
"""

from __future__ import annotations

import ast
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from test_service import BRIEF, LEGACY, OPERATIONS, _imports, _legacy, make_workspace

import siteplan.agent
from siteplan.agent import harness, standin
from siteplan.approval import ApprovalDesk
from siteplan.service import Asked, Decision, PageApprover, ToolHost, audit

TEST_CLASS = "normative"

TOOLS_COMMAND = Path(sys.executable).parent / "siteplan-agent-tools"
PROJECT, SURVEY = "service-test.project.json", "survey.dxf"
FILES = {"project_file": PROJECT, "survey_file": SURVEY}
INTENT = {"height": "MOST_THE_RULES_ALLOW", "unit_mix_percent": {"2BHK": 70, "3BHK": 30}}
PROPOSE = {**FILES, "brief": BRIEF, "intent": INTENT}
PLAN = {"project_file": PROJECT, "survey_file": SURVEY, "brief": BRIEF, "intent": INTENT}
NO_SUCH_TOOL = "There is no such tool; tools() lists the nine there are."
HOST_WAIT_S = 30.0
POLL_S = 0.05


def hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def token(url: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["t"][0]


class OutOfBandBrowser:
    """The architect's browser, played out of band. The host's webbrowser.open runs BROWSER, a
    script that writes the URL to an inbox; a thread here notes which runs `out` held when the
    page opened, reads the page and clicks the next decision (none left: no click)."""

    def __init__(self, folder: Path, out: Path, decisions: list[str]) -> None:
        self.inbox, self.command = folder / "inbox.txt", folder / "browser"
        self.command.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$1\" >> '{self.inbox}'\n")
        self.command.chmod(0o700)
        self.out, self.decisions = out, list(decisions)
        self.opened: list[str] = []
        self.pages: list[str] = []
        self.runs_when_opened: list[list[str]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def env(self, **extra: str) -> dict[str, str]:
        return {**os.environ, "BROWSER": str(self.command), **extra}

    def __enter__(self) -> OutOfBandBrowser:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(HOST_WAIT_S)

    def _watch(self) -> None:
        seen = 0
        while not self._stop.is_set():
            text = self.inbox.read_text() if self.inbox.exists() else ""
            for url in text.split("\n")[:-1][seen:]:  # whole lines only
                seen += 1
                self._open(url)
            self._stop.wait(POLL_S)

    def _open(self, url: str) -> None:
        self.opened.append(url)
        self.runs_when_opened.append(sorted(p.parent.name for p in self.out.glob("*/run.json")))
        self.pages.append(urllib.request.urlopen(url, timeout=5).read().decode())
        if self.decisions:
            parsed = urllib.parse.urlparse(url)
            form = urllib.parse.urlencode({"t": token(url),
                                           "decision": self.decisions.pop(0)}).encode()
            action = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            urllib.request.urlopen(urllib.request.Request(action, data=form), timeout=5).read()


def run_session(ws: Path, out: Path, env: dict[str, str], script, *flags: str):
    """The host started as the launcher starts it, the model's harness on its stdin and stdout,
    `script(tools)` run; its result, every line the host sent, and the host's exit status."""
    host = subprocess.Popen([str(TOOLS_COMMAND), "--workspace", str(ws), "--out", str(out),
                             *flags], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)

    async def main():
        async with harness.connect(host.stdout, host.stdin) as tools:
            return await script(tools), list(tools.received)

    try:
        result, received = anyio.run(main)
    finally:
        try:
            host.wait(HOST_WAIT_S)
        except subprocess.TimeoutExpired:
            host.kill()
            host.wait()
    return result, received, host.returncode


# --- one session through the transport: the nine operations, and what must be refused --------


@dataclass
class Walked:
    ws: Path
    out: Path
    before: dict[str, str]
    browser: OutOfBandBrowser
    offered: list[dict]
    calls: dict[str, harness.Reply]
    refused: list[tuple[str, str, dict, harness.Reply]]  # kind, tool, arguments, reply
    received: list[str]
    status: int


async def _walk(tools: harness.Tools):
    calls = {"start_project": await tools.call("start_project", {"survey_file": SURVEY})}
    for name in ("open_project", "resolve_rules", "inspect_envelope"):
        calls[name] = await tools.call(name, FILES)
    calls["list_prototypes"] = await tools.call("list_prototypes", {"project_file": PROJECT})
    calls["propose_layouts"] = proposed = await tools.call("propose_layouts", PROPOSE)
    run_id = proposed.data["run_id"]
    ids = [c["candidate_id"] for c in proposed.data["candidates"]]
    calls["validate_candidate"] = checked = await tools.call(
        "validate_candidate", {"run_id": run_id, "candidate_id": ids[0]})
    calls["compare_candidates"] = await tools.call(
        "compare_candidates", {"run_id": run_id, "candidate_ids": ids})
    items = [item["item"] for item in checked.data["unverified"]]
    export = {"run_id": run_id, "candidate_id": ids[0]}
    for label, given in (("none acknowledged", []), ("one left out", items[:-1]),
                         ("rejected", items), ("export_candidate", items)):
        calls[label] = await tools.call("export_candidate",
                                        {**export, "acknowledged_unresolved": given})
    refused = []
    for name in standin.UNKNOWN_TOOLS:
        refused.append(("unknown tool", name, {}, await tools.call(name, {})))
    for key, value in standin.INJECTED.items():
        arguments = {**FILES, key: value}
        refused.append(("injected field", "open_project", arguments,
                        await tools.call("open_project", arguments)))
    for key in standin.INJECTED_INTENT:
        arguments = {**PROPOSE, "intent": {**INTENT, key: standin.INJECTED[key]}}
        refused.append(("injected field", "propose_layouts", arguments,
                        await tools.call("propose_layouts", arguments)))
    for name, arguments in standin.invalid(PLAN):
        refused.append(("invalid value", name, arguments, await tools.call(name, arguments)))
    return tools.offered, calls, refused


@pytest.fixture(scope="module")
def walked(tmp_path_factory) -> Walked:
    ws = make_workspace(tmp_path_factory.mktemp("transport-ws"))
    out = tmp_path_factory.mktemp("transport-out")
    before = hashes(ws)
    # The proposal approved, the first export with its items rejected, the second approved.
    browser = OutOfBandBrowser(tmp_path_factory.mktemp("transport-browser"), out,
                               ["approve", "reject", "approve"])
    with browser:
        (offered, calls, refused), received, status = run_session(ws, out, browser.env(), _walk)
    return Walked(ws, out, before, browser, offered, calls, refused, received, status)


def test_all_nine_operations_are_reachable_through_the_transport(walked):
    for name in OPERATIONS:
        reply = walked.calls[name]
        assert reply.ok and reply.data, (name, reply.error)
    assert walked.calls["propose_layouts"].data["status"] == "PROPOSED"
    assert walked.calls["validate_candidate"].data["refusals"] == []
    assert walked.calls["export_candidate"].data["status"] == "EXPORTED"
    assert walked.calls["start_project"].data["settled"][0]["value"] == 18000.0
    assert walked.status == 0  # the host ended its session when the stream closed


def _quiet_page() -> PageApprover:
    return PageApprover(ApprovalDesk(open_page=lambda url: None), timeout_s=0.1)


def test_the_tools_listed_are_exactly_the_hosts_nine(walked, tmp_path):
    listed = ToolHost(walked.ws, tmp_path / "out", _quiet_page()).tools()
    assert walked.offered == listed  # names, descriptions, input and output schemas, as is
    assert [t["name"] for t in walked.offered] == list(OPERATIONS)


def test_any_other_tool_is_refused_in_the_hosts_words(walked):
    unknown = [(name, reply) for kind, name, _, reply in walked.refused if kind == "unknown tool"]
    assert [name for name, _ in unknown] == list(standin.UNKNOWN_TOOLS)
    for name, reply in unknown:
        assert (reply.ok, reply.data, reply.error) == (False, None, NO_SUCH_TOOL), name


def test_the_host_offers_tools_and_nothing_else(walked, tmp_path):
    """No prompts, no resources, no logging: an MCP client gets the nine tools or nothing."""
    params = StdioServerParameters(command=str(TOOLS_COMMAND), args=[
        "--workspace", str(walked.ws), "--out", str(tmp_path / "out")])

    async def main():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            started = await session.initialize()
            refused = []
            for ask in (session.list_prompts, session.list_resources,
                        session.list_resource_templates,
                        lambda: session.set_logging_level("debug")):
                try:
                    await ask()
                except McpError as error:
                    refused.append(error.error.message)
            return started, refused

    started, refused = anyio.run(main)
    capabilities = started.capabilities
    assert capabilities.tools is not None
    assert (capabilities.prompts, capabilities.resources, capabilities.logging,
            capabilities.completions) == (None, None, None, None)
    assert refused == ["Method not found"] * 4


def test_extra_and_invalid_fields_are_refused_and_the_reason_stays_in_the_log(walked):
    fields = [(kind, name, arguments, reply) for kind, name, arguments, reply in walked.refused
              if kind != "unknown tool"]
    assert len(fields) == (len(standin.INJECTED) + len(standin.INJECTED_INTENT)
                           + len(standin.invalid(PLAN)))
    for kind, name, arguments, reply in fields:
        assert not reply.ok and reply.data is None, (kind, name, arguments)
        assert reply.error == (f"The arguments do not fit {name}'s input schema "
                               "(tools() gives it)."), (kind, name, arguments)
    log = (walked.out / "logs" / "agent-tools.log").read_text()
    for key in standin.INJECTED:  # the reason is logged, never sent back
        assert f"{key}\n  Extra inputs are not permitted" in log, key


# --- the person's approval: never the model's ------------------------------------------------


def test_there_is_no_approve_tool_and_the_approval_token_never_reaches_the_model(walked):
    names = [t["name"] for t in walked.offered]
    assert not [n for n in names for word in ("approv", "decid", "confirm") if word in n]
    assert len(walked.browser.opened) == 3  # the proposal and the two exports with items open
    sent = "".join(walked.received)
    assert walked.received and json.loads(walked.received[0])["result"]
    for url in walked.browser.opened:
        assert token(url) not in sent and url not in sent
        assert urllib.parse.urlparse(url).path not in sent  # nor the page's own address


def test_a_proposal_runs_only_after_the_person_clicks_approve(walked):
    proposed = walked.calls["propose_layouts"].data
    assert walked.browser.runs_when_opened[0] == []  # asked before anything ran
    assert "Generate layout options for Service test" in walked.browser.pages[0]
    assert sorted(p.parent.name for p in walked.out.glob("*/run.json")) == [proposed["run_id"]]
    proposal = audit.read(walked.out)[0]
    assert (proposal.asked, proposal.decision, proposal.channel, proposal.run_id) == (
        Asked.PROPOSAL, Decision.APPROVED, "PageApprover", proposed["run_id"])


def test_a_proposal_the_person_rejects_runs_nothing(tmp_path, walked):
    out = tmp_path / "out"
    with OutOfBandBrowser(tmp_path, out, ["reject"]) as browser:
        async def propose(tools):
            return await tools.call("propose_layouts", PROPOSE)
        reply, received, status = run_session(walked.ws, out, browser.env(), propose)
    assert reply.ok and reply.data["status"] == "NOT_APPROVED" and reply.data["run_id"] is None
    assert len(browser.opened) == 1 and not list(out.glob("*/run.json"))
    (entry,) = audit.read(out)
    assert (entry.asked, entry.decision, entry.channel, entry.run_id) == (
        Asked.PROPOSAL, Decision.REJECTED, "PageApprover", None)
    assert token(browser.opened[0]) not in "".join(received) and status == 0


# --- what export still refuses, through the transport ----------------------------------------


def _copy_run(out: Path, run_id: str, into: Path) -> str:
    """The run copied into another `out` under a new id with nothing exported, as test_service
    copies one to tamper with."""
    new = uuid.uuid4().hex[:12]
    shutil.copytree(out / run_id, into / new)
    shutil.rmtree(into / new / "exports", ignore_errors=True)
    record = json.loads((into / new / "run.json").read_text())
    record["run_id"] = new
    (into / new / "run.json").write_text(json.dumps(record))
    return new


def _tower_into_the_setback(out: Path, run_id: str, candidate_id: str) -> None:
    """The stored candidate's first tower moved to 0.5 m from the plot's west edge."""
    folder = out / run_id
    site = json.loads((folder / "site.json").read_text())
    west = min(x for x, _ in site["net_plot"]["value"]["outer"])
    path = folder / "candidates" / f"{candidate_id}.json"
    candidate = json.loads(path.read_text())
    tower = candidate["towers"][0]
    dx = west + 0.5 - min(x for x, _ in tower["footprint"]["outer"])
    tower["x"] += dx
    tower["footprint"]["outer"] = [[x + dx, y] for x, y in tower["footprint"]["outer"]]
    path.write_text(json.dumps(candidate))


def test_a_candidate_tampered_into_the_setback_cannot_be_exported_through_the_transport(
        walked, tmp_path):
    proposed = walked.calls["propose_layouts"].data
    candidate_id = proposed["candidates"][0]["candidate_id"]
    out = tmp_path / "out"
    run_id = _copy_run(walked.out, proposed["run_id"], out)
    _tower_into_the_setback(out, run_id, candidate_id)
    items = [i["item"] for i in walked.calls["validate_candidate"].data["unverified"]]
    with OutOfBandBrowser(tmp_path, out, ["approve"]) as browser:
        async def export(tools):
            return await tools.call("export_candidate", {
                "run_id": run_id, "candidate_id": candidate_id,
                "acknowledged_unresolved": items})
        reply, _, _ = run_session(walked.ws, out, browser.env(), export)
    result = reply.data
    assert result["status"] == "REFUSED" and result["legal_verdict"] == "FAIL"
    assert any(r.startswith("FAIL All-round setback") for r in result["reasons"]), result
    assert any("stored candidate changed since the run" in r for r in result["reasons"])
    assert not (out / run_id / "exports").exists() and not result["files"]
    assert browser.opened == []  # a FAIL is never put to the person: it never ships
    assert audit.read(out) == []  # so nothing was asked, and nothing recorded


def test_unverified_needs_exactly_its_items_and_the_persons_approval_through_the_transport(
        walked):
    items = [i["item"] for i in walked.calls["validate_candidate"].data["unverified"]]
    assert len(items) >= 2 and walked.calls["validate_candidate"].data[
        "legal_verdict"] == "UNVERIFIED"
    for label in ("none acknowledged", "one left out"):
        result = walked.calls[label].data
        assert result["status"] == "REFUSED" and not result["files"], label
        assert result["reasons"][0].startswith("not acknowledged"), label
    rejected = walked.calls["rejected"].data
    assert rejected["status"] == "NOT_APPROVED" and not rejected["files"]
    exported = walked.calls["export_candidate"].data
    assert exported["status"] == "EXPORTED" and exported["unverified"] == items
    assert all(Path(f).is_file() and Path(f).is_relative_to(walked.out)
               for f in exported["files"])
    for page in walked.browser.pages[1:]:  # what the person was shown names every item
        assert all(html.escape(item) in page for item in items)
    proposal, refused, approved = audit.read(walked.out)[:3]
    assert [(e.asked, e.decision, e.channel) for e in (proposal, refused, approved)] == [
        (Asked.PROPOSAL, Decision.APPROVED, "PageApprover"),
        (Asked.EXPORT, Decision.REJECTED, "PageApprover"),
        (Asked.EXPORT, Decision.APPROVED, "PageApprover")]
    run_id = walked.calls["propose_layouts"].data["run_id"]
    for entry in (refused, approved):
        assert list(entry.acknowledged) == items and entry.run_id == run_id
        assert entry.candidate_id == exported["candidate_id"]
    assert exported["approvals"] == [e.model_dump(mode="json")
                                     for e in (proposal, refused, approved)]


def test_a_session_leaves_the_workspace_as_it_was(walked):
    assert hashes(walked.ws) == walked.before


def _finished_workspace(tmp_path: Path) -> Path:
    """A workspace whose survey the firm lists among its finished plans."""
    (tmp_path / "ws").mkdir()
    return make_workspace(tmp_path / "ws", finished=(SURVEY,))


def test_the_host_is_blind_unless_the_person_starts_it_with_debug(tmp_path):
    ws = _finished_workspace(tmp_path)

    async def open_project(tools):
        return await tools.call("open_project", FILES)

    blind, _, _ = run_session(ws, tmp_path / "blind", dict(os.environ), open_project)
    debug, _, _ = run_session(ws, tmp_path / "debug", dict(os.environ), open_project, "--debug")
    assert not blind.ok and "may not use the firm's finished plan" in blind.error
    assert debug.ok and debug.data["run_kind"] == "DEBUG"


def test_the_host_refuses_to_start_with_out_in_the_workspace_and_writes_nothing_there(tmp_path):
    ws = _finished_workspace(tmp_path)
    before = hashes(ws)
    for out in (ws / "out", ws):
        done = subprocess.run([str(TOOLS_COMMAND), "--workspace", str(ws), "--out", str(out)],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=HOST_WAIT_S)
        assert done.returncode == 2 and "neither inside the workspace" in done.stderr
        assert done.stdout == ""  # nothing on the stream
    assert hashes(ws) == before and not (ws / "out").exists() and not (ws / "logs").exists()


# --- the agent package reaches the engine only through the service ---------------------------


AGENT = Path(siteplan.agent.__file__).parent
# Never from the model's side: the legacy generator and checker, the command line, the legacy MCP
# server, the assistant, and the optimizer and validator the service runs behind its gates.
AGENT_BANNED = LEGACY | {"cli", "mcp_server", "assistant", "runner", "optimizer", "validator"}
# The SDK, the async library it runs on, and the HTTP client it brings (the loop's, to the model).
THIRD_PARTY = {"mcp", "anyio", "httpx"}


def _agent_offences(module: str, names: tuple[str, ...], file: str) -> list[str]:
    parts = module.split(".")
    if not parts[0]:  # `from . import x` names no module the scan could check
        return [f"a relative import of {names}"]
    if parts[0] != "siteplan":
        known = parts[0] in sys.stdlib_module_names or parts[0] in THIRD_PARTY
        return [] if known else [module]
    wrong = list(_legacy(module, names))
    reached = {parts[1]} if len(parts) > 1 else set(names)
    wrong += [f"{module}: {r}" for r in reached & AGENT_BANNED]
    if reached - {"agent", "service"}:
        wrong.append(f"{module}: {sorted(reached - {'agent', 'service'})}")
    if "service" in reached and file != "server.py":  # only the host side reaches the service
        wrong.append(f"{module} outside server.py")
    return wrong


def test_the_scanner_sees_every_way_into_the_engine_from_the_agent_package():
    for source in ("import siteplan.validator", "from siteplan import optimizer",
                   "from siteplan.optimizer.core import optimize", "import siteplan.cli",
                   "from siteplan.mcp_server import build_server", "from siteplan import assistant",
                   "from siteplan.runner import run_layout", "from siteplan.layout import x",
                   "from siteplan.validator.refusals import x", "import siteplan.rules",
                   "def f():\n    from siteplan import checks", "import requests",
                   "from .. import cli"):
        assert [w for m, n in _imports(source) for w in _agent_offences(m, n, "x.py")], source
    assert _agent_offences("siteplan.service", ("ToolHost",), "harness.py")
    assert not _agent_offences("siteplan.service", ("ToolHost",), "server.py")
    assert not _agent_offences("siteplan.agent", ("harness",), "standin.py")


def test_the_agent_package_imports_only_the_service_the_sdk_and_the_standard_library():
    files = sorted(AGENT.glob("*.py"))
    assert {f.name for f in files} >= {"server.py", "harness.py", "launch.py", "sandbox.py",
                                       "standin.py"}
    offences = {path.name: wrong for path in files if (wrong := [
        w for m, n in _imports(path.read_text()) for w in _agent_offences(m, n, path.name)])}
    assert not offences, offences
    imported = {m for m, _ in _imports((AGENT / "server.py").read_text())}
    assert "siteplan.service" in imported  # the host side reaches the engine through it alone


def test_the_harness_offers_the_model_the_hosts_tools_and_nothing_of_its_own():
    tree = ast.parse((AGENT / "harness.py").read_text())
    tools = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Tools")
    methods = [n.name for n in tools.body if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)]
    assert methods == ["__init__", "call"]
    imported = {m.split(".")[0] for m, _ in _imports((AGENT / "harness.py").read_text())}
    assert not imported & {"subprocess", "shutil", "socket", "pathlib", "urllib", "http"}
