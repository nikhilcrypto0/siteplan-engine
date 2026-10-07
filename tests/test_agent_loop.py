"""The agent loop (siteplan.agent.loop) driven through the real launcher against a scripted,
OpenAI-compatible model server on 127.0.0.1 (tests/fake_model.py): the loop in the sandbox, the
real host on made-up land (test_service.make_workspace), the architect played out of band on the
approval page (test_agent_transport.OutOfBandBrowser). No real model is contacted.

Each run is judged from what does not rest on the loop's own word: what the fake server received
and sent, the MCP stream as the launcher relayed it (mcp.jsonl), the host's approval audit and,
on macOS, what the kernel says the running loop process may do. The live runs skip, saying why,
where the sandbox cannot open a model's port (anywhere but macOS today); the configuration and
client checks run everywhere.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import anyio
import pytest
from fake_model import FakeModel, act, call, late, raw, respond, results, say, status
from test_agent_transport import (
    FILES,
    PROJECT,
    PROPOSE,
    SURVEY,
    OutOfBandBrowser,
    _copy_run,
    _quiet_page,
    _tower_into_the_setback,
    hashes,
    token,
)
from test_service import BRIEF, OPERATIONS, make_workspace

from siteplan.agent import launch as launcher
from siteplan.agent import loop, sandbox
from siteplan.agent.launch import LOOP, Launched, launch
from siteplan.agent.model import Chat
from siteplan.agent.settings import Limits, Settings, load_config
from siteplan.service import Asked, Decision, ToolHost, audit

TEST_CLASS = "normative"

MODEL_ID = "fake-model"
LAUNCH_TIMEOUT_S = 600.0
LONG_S = 60.0  # a reply later than any limit a test sets; the server stops waiting at the end
WAIT_S = 60.0  # for a run in another process to reach a step
POLL_S = 0.05
AGENT_COMMAND = Path(sys.executable).parent / "siteplan-agent"
MAC = sys.platform == "darwin"
ASK = f"The survey is {SURVEY} and the project file is {PROJECT}. {BRIEF}"
NO_SUCH = ("read_file", "run_shell", "list_files", "read_survey_drawing", "siteplan")
SANDBOX_FILTER_PATH, SANDBOX_CHECK_NO_REPORT = 1, 0x40000000


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _record(out: Path) -> list[dict]:
    """The transcript of the one run under `out`, as far as it is written."""
    found = sorted(out.glob("agent/*/transcript.jsonl"))
    events = []
    for line in found[0].read_text().splitlines() if found else []:
        try:
            events.append(json.loads(line))
        except ValueError:
            break  # the line being written
    return events


def _launcher_event(events: list[dict], kind: str) -> dict | None:
    return next((e for e in events if e["source"] == "launcher" and e["event"] == kind), None)


def _until(predicate: Callable[[], object], timeout: float = WAIT_S):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := predicate():
            return found
        time.sleep(POLL_S)
    raise AssertionError(f"not reached within {timeout:g} s")


def _unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def here(tmp_path_factory) -> None:
    """Skips the live runs, saying why, where the sandbox cannot be applied with a model's port
    open (bubblewrap refuses one); a sandbox that applies and does not hold fails them."""
    folders = [tmp_path_factory.mktemp(name) for name in ("here-ws", "here-out", "here-scratch")]
    try:
        sandbox.preflight(sandbox.Policy.for_agent(*folders, endpoint="http://127.0.0.1:9/v1"))
    except sandbox.SandboxLeak:
        raise
    except sandbox.SandboxUnavailable as error:
        pytest.skip(f"the sandbox cannot open a model's port on this machine: {error}")


@pytest.fixture(scope="module")
def ws(here, tmp_path_factory) -> Path:
    return make_workspace(tmp_path_factory.mktemp("loop-ws"))


@dataclass
class Ran:
    launched: Launched
    model: FakeModel
    browser: OutOfBandBrowser
    out: Path
    view: str  # what the architect's terminal showed

    @cached_property
    def transcript(self) -> list[dict]:
        return _lines(self.launched.record / "transcript.jsonl")

    @cached_property
    def mcp(self) -> list[dict]:
        return _lines(self.launched.record / "mcp.jsonl")

    def events(self, kind: str, source: str = "agent") -> list[dict]:
        return [e for e in self.transcript if e["source"] == source and e["event"] == kind]

    @property
    def stop(self) -> dict:
        (stop,) = self.events("stop")
        return stop

    def sent(self) -> list[tuple[str, dict]]:
        """Every tool call that reached the host, read off the MCP stream the launcher relayed."""
        return [(m["message"]["params"]["name"], m["message"]["params"].get("arguments"))
                for m in self.mcp if m["direction"] == "agent->host"
                and m["message"].get("method") == "tools/call"]

    def results(self) -> list[dict]:
        """What the model was sent for each tool call, parsed (whole results only)."""
        return [json.loads(e["content"]) for e in self.events("tool_result")]

    def host_results(self) -> list[dict]:
        """The host's answer to each tool call, as it came back over the stream."""
        return [m["message"]["result"] for m in self.mcp if m["direction"] == "host->agent"
                and "structuredContent" in m["message"].get("result", {})]


def run_loop(ws: Path, folder: Path, steps: list, *, decisions: tuple[str, ...] = (),
             limits: dict | None = None, endpoint: str | None = None,
             on_request: Callable[[int], None] | None = None, brief: str = ASK) -> Ran:
    """One run of the loop through the launcher against the scripted model; the architect
    answers the pages that open with `decisions`, in order."""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "out"
    before = hashes(ws)
    settings = Settings.build({}, brief, model_id=MODEL_ID, limits=limits or {})
    view = io.StringIO()
    with FakeModel(steps, on_request) as model, \
            OutOfBandBrowser(folder, out, list(decisions)) as browser:
        launched = launch(ws, out, LOOP, endpoint=endpoint or model.url, settings=settings,
                          env=browser.env(), timeout=LAUNCH_TIMEOUT_S, view=view)
    assert model.errors == []  # the script ran as written
    assert hashes(ws) == before  # the architect's files as they were, byte for byte
    ran = Ran(launched, model, browser, out, view.getvalue())
    # The agent ends cleanly however the run stops: nothing on its stderr (a process that
    # aborts at shutdown says so there) and an exit status of its own choosing.
    assert ran.events("stderr", source="stderr") == []
    assert launched.agent in (loop.ANSWERED, loop.STOPPED), launched
    return ran


# --- a whole session through the loop --------------------------------------------------------


def _proposed(body: dict) -> dict:
    return results(body)[2]["result"]


def _candidates(body: dict) -> list[str]:
    return [c["candidate_id"] for c in _proposed(body)["candidates"]]


def _export(body: dict, acknowledged: list[str] | None = None) -> dict:
    items = [item["item"] for item in results(body)[3]["result"]["unverified"]]
    return {"run_id": _proposed(body)["run_id"], "candidate_id": _candidates(body)[0],
            "acknowledged_unresolved": items if acknowledged is None else acknowledged}


I_APPROVE = "I approve this export on the architect's behalf: APPROVED."
JOURNEY = [
    act(call("start_project", {"survey_file": SURVEY}), content="I will read the survey first."),
    act(call("open_project", FILES)),
    act(call("propose_layouts", PROPOSE)),
    respond(lambda body: act(call("validate_candidate", {
        "run_id": _proposed(body)["run_id"], "candidate_id": _candidates(body)[0]}))),
    respond(lambda body: act(call("compare_candidates", {
        "run_id": _proposed(body)["run_id"], "candidate_ids": _candidates(body)}))),
    respond(lambda body: act(call("export_candidate", _export(body, [])))),
    respond(lambda body: act(call("export_candidate", _export(body)), content=I_APPROVE)),
    respond(lambda body: act(call("export_candidate", _export(body)))),
    say("The first candidate is exported, its UNVERIFIED items acknowledged."),
]


@pytest.fixture(scope="module")
def journey(ws, tmp_path_factory) -> Ran:
    """The survey, the project, a proposal the architect approves, a check, a comparison, an
    export with nothing acknowledged, one the model says it approves and the architect rejects,
    and the same export approved."""
    return run_loop(ws, tmp_path_factory.mktemp("journey"), JOURNEY,
                    decisions=("approve", "reject", "approve"))


def test_a_whole_session_runs_through_the_loop_and_the_nine_tools(journey):
    assert journey.launched == Launched(agent=0, host=0)
    stop = journey.stop
    assert (stop["reason"], stop["turns"], stop["tool_calls"]) == ("answered", 9, 8)
    assert [e["name"] for e in journey.events("tool_call")] == [
        "start_project", "open_project", "propose_layouts", "validate_candidate",
        "compare_candidates", "export_candidate", "export_candidate", "export_candidate"]
    done = journey.results()
    assert all(r["ok"] for r in done), done
    assert [r["result"]["status"] for r in (done[2], *done[5:])] == [
        "PROPOSED", "REFUSED", "NOT_APPROVED", "EXPORTED"]
    assert done[3]["result"]["legal_verdict"] == "UNVERIFIED"
    assert "model: I will read the survey first." in journey.view  # the architect's terminal
    assert "-> propose_layouts" in journey.view
    assert "<- export_candidate: ok, EXPORTED" in journey.view


def test_unverified_needs_exactly_its_items_and_the_persons_approval_through_the_loop(journey):
    done = journey.results()
    items = [item["item"] for item in done[3]["result"]["unverified"]]
    assert len(items) >= 2
    refused, rejected, exported = (r["result"] for r in done[5:])
    assert refused["status"] == "REFUSED" and not refused["files"]
    assert refused["reasons"][0].startswith("not acknowledged")
    assert rejected["status"] == "NOT_APPROVED" and not rejected["files"]
    assert exported["status"] == "EXPORTED" and exported["unverified"] == items
    assert all(Path(f).is_file() and Path(f).is_relative_to(journey.out.resolve())
               for f in exported["files"])
    assert len(journey.browser.opened) == 3  # the proposal and the two exports with items
    assert journey.browser.runs_when_opened[0] == []  # asked before anything ran
    entries = audit.read(journey.out)
    assert [(e.asked, e.decision, e.channel) for e in entries] == [
        (Asked.PROPOSAL, Decision.APPROVED, "PageApprover"),
        (Asked.EXPORT, Decision.REJECTED, "PageApprover"),
        (Asked.EXPORT, Decision.APPROVED, "PageApprover")]
    assert all(list(e.acknowledged) == items for e in entries[1:])


def test_the_models_own_approval_changes_nothing(journey):
    """The model wrote that it approves the export; the architect rejected it on the page, and
    the rejection stood. No tool approves, and the page's link never reached the model."""
    assert [e["content"] for e in journey.events("assistant") if e["turn"] == 7] == [I_APPROVE]
    assert journey.results()[6]["result"]["status"] == "NOT_APPROVED"
    assert audit.read(journey.out)[1].decision is Decision.REJECTED
    offered = [t["function"]["name"] for t in journey.model.bodies()[0]["tools"]]
    assert not [n for n in offered for word in ("approv", "decid", "confirm") if word in n]
    seen = b"".join(journey.model.requests).decode()  # everything the model was ever sent
    for url in journey.browser.opened:
        assert token(url) not in seen and url not in seen


def test_the_transcript_is_complete_and_kept_outside_the_sandbox(journey):
    record = journey.launched.record
    assert record.parent == journey.out.resolve() / "agent"
    started = journey.events("started", source="launcher")[0]
    if MAC:  # the profile the loop ran under closes by hiding out, where the record is
        assert started["agent_argv"][:2] == [sandbox.SANDBOX_EXEC, "-p"]
        closing = started["agent_argv"][2].strip().splitlines()[-1]
        assert closing.startswith("(deny file-read* file-read-data file-read-metadata")
        assert f'(subpath "{journey.out.resolve()}")' in closing
    requests = journey.events("model_request")
    assert [r["sha256"] for r in requests] == [hashlib.sha256(data).hexdigest()
                                               for data in journey.model.requests]
    rebuilt: list[dict] = []  # each request's conversation, rebuilt from the record alone
    for event, body in zip(requests, journey.model.bodies(), strict=True):
        assert event["first"] == len(rebuilt)
        rebuilt += event["messages"]
        assert rebuilt == body["messages"] and event["count"] == len(rebuilt)
    offered = journey.events("tools_offered")[0]["tools"]
    assert all(body["tools"] == offered for body in journey.model.bodies())
    responses = journey.events("model_response")
    assert [r["body"] for r in responses] == [json.loads(r.data) for r in journey.model.replies]
    calls, answers = journey.events("tool_call"), journey.events("tool_result")
    assert [c["id"] for c in calls] == [a["id"] for a in answers]
    assert all(e["elapsed_s"] >= 0 for e in (*responses, *answers))
    agent = [e for e in journey.transcript if e["source"] == "agent"]
    assert agent[0]["event"] == "started" and agent[-1]["event"] == "stop"
    assert all(isinstance(e["t"], float) for e in agent)
    ended = journey.transcript[-1]
    assert (ended["source"], ended["event"], ended["agent"], ended["host"]) == (
        "launcher", "ended", 0, 0)
    order = sorted(e["seq"] for e in (*journey.transcript, *journey.mcp))
    assert order == list(range(1, len(order) + 1))  # one count across both files: none lost


def test_no_tool_call_is_ever_retried(journey):
    asked = [(c["name"], json.loads(c["arguments"])) for c in journey.events("tool_call")]
    assert journey.sent() == asked  # each reached the host once, in the order asked
    ids = [m["message"]["id"] for m in journey.mcp if m["direction"] == "agent->host"
           and m["message"].get("method") == "tools/call"]
    answered = [m["message"]["id"] for m in journey.mcp if m["direction"] == "host->agent"
                and m["message"].get("id") in ids]
    assert len(set(ids)) == len(ids) == len(answered) == 8
    assert [r["attempt"] for r in journey.events("model_request")] == [1] * 9


# --- what the model asks for that it cannot have ---------------------------------------------


def seatbelt_applies(pid: int) -> bool:
    check = ctypes.CDLL("/usr/lib/libSystem.B.dylib").sandbox_check
    check.restype, check.argtypes = ctypes.c_int, [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    return check(pid, None, 0) == 1


def seatbelt_denies(pid: int, operation: str, path: Path | None = None) -> bool:
    """Whether Seatbelt denies `operation` (on `path`) to the running process `pid`, asked of
    the kernel from outside (libsystem's sandbox_check)."""
    check = ctypes.CDLL("/usr/lib/libSystem.B.dylib").sandbox_check
    check.restype, check.argtypes = ctypes.c_int, [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    if path is None:
        answer = check(pid, operation.encode(), SANDBOX_CHECK_NO_REPORT)
    else:
        answer = check(pid, operation.encode(), SANDBOX_FILTER_PATH | SANDBOX_CHECK_NO_REPORT,
                       ctypes.c_char_p(str(path).encode()))
    assert answer in (0, 1), (operation, path, answer)
    return answer == 1


def _probe(out: Path, ws: Path, found: dict) -> Callable[[int], None]:
    """At the model's first request, while the loop waits for its answer: what Seatbelt lets the
    running loop process do, asked of the kernel from outside."""
    def started() -> list[dict] | None:
        events = _record(out)
        return events if _launcher_event(events, "started") else None

    def probe(index: int) -> None:
        if index or not MAC:
            return
        events = _until(started)
        pid = _launcher_event(events, "started")["agent_pid"]
        scratch = Path(_launcher_event(events, "launch")["scratch"])
        record, package = next(out.glob("agent/*/transcript.jsonl")), sandbox.PACKAGE
        found["sandboxed"] = seatbelt_applies(pid)
        found["denied"] = {
            "read the project file": seatbelt_denies(pid, "file-read-data", ws / PROJECT),
            "look the project file up": seatbelt_denies(pid, "file-read-metadata", ws / PROJECT),
            "list the workspace": seatbelt_denies(pid, "file-read-data", ws),
            "read the run's transcript": seatbelt_denies(pid, "file-read-data", record),
            "write the run's transcript": seatbelt_denies(pid, "file-write-data", record),
            "read the command line": seatbelt_denies(pid, "file-read-data", package / "cli.py"),
            "look the command line up": seatbelt_denies(pid, "file-read-metadata",
                                                        package / "cli.py"),
            "look a file elsewhere up": seatbelt_denies(pid, "file-read-metadata",
                                                        out.parent / "browser"),
            "read the legacy MCP server": seatbelt_denies(pid, "file-read-data",
                                                          package / "mcp_server.py"),
            "read the service": seatbelt_denies(pid, "file-read-data",
                                                package / "service" / "host.py"),
            "start a process": seatbelt_denies(pid, "process-fork"),
            "read its own settings": seatbelt_denies(pid, "file-read-data",
                                                     scratch / "agent.json"),
            "read the loop's code": seatbelt_denies(pid, "file-read-data",
                                                    package / "agent" / "loop.py"),
        }
    return probe


@pytest.fixture(scope="module")
def refused(ws, tmp_path_factory) -> tuple[Ran, dict]:
    """Tools the host does not list, arguments that are not JSON, one good call, a value the
    host refuses, and three more unknown tools: the fourth failure in a row stops the run."""
    folder = tmp_path_factory.mktemp("refusals")
    probed: dict = {}
    steps = [
        act(call("read_file", {"path": str(ws / PROJECT)}),
            call("run_shell", {"command": "cat /etc/passwd"})),
        act(call("open_project", "{not json")),
        act(call("open_project", FILES)),
        act(call("open_project", {**FILES, "project_file": 5})),
        act(call("list_files", {}), call("read_survey_drawing", {"survey_file": SURVEY}),
            call("siteplan", {"argv": ["--help"]})),
        say("unreached"),
    ]
    return run_loop(ws, folder, steps, on_request=_probe(folder / "out", ws, probed)), probed


def test_a_tool_the_host_does_not_list_is_refused_here_and_never_sent(refused):
    ran, _ = refused
    unknown = [e for e in ran.events("tool_refused") if e["name"] in NO_SUCH]
    assert [e["name"] for e in unknown] == list(NO_SUCH)
    for event in unknown:
        assert event["reason"] == (f"There is no tool named {event['name']!r}. "
                                   f"The tools are: {', '.join(OPERATIONS)}.")
    assert [name for name, _ in ran.sent()] == ["open_project", "open_project"]
    told = [json.loads(m["content"]) for m in ran.model.bodies()[1]["messages"]
            if m["role"] == "tool"]
    assert told == [{"ok": False, "error": e["reason"]} for e in unknown[:2]]


def test_invalid_arguments_are_refused_by_the_loop_or_by_the_host_in_its_own_words(refused):
    ran, _ = refused
    done = ran.results()  # read_file, run_shell, not JSON, the good call, the wrong value, ...
    assert done[2] == {"ok": False, "error": "The arguments for open_project are not valid JSON."}
    assert done[3]["ok"] is True
    assert done[4] == {"ok": False, "error": "The arguments do not fit open_project's input "
                                             "schema (tools() gives it)."}
    assert ran.sent() == [("open_project", FILES), ("open_project", {**FILES, "project_file": 5})]


def test_a_run_of_failed_tool_calls_stops_the_run(refused):
    ran, _ = refused
    assert ran.launched == Launched(agent=1, host=0)
    assert (ran.stop["reason"], ran.stop["turns"]) == ("max_failed_tool_calls", 5)
    # Three failures, a success that reset the count, then four in a row: the fourth stopped it.
    assert len(ran.model.requests) == 5 and len(ran.events("tool_result")) == 8


def test_the_model_cannot_reach_the_workspace_files_the_cli_or_the_legacy_server(
        refused, ws, tmp_path):
    ran, probed = refused
    listed = ToolHost(ws, tmp_path / "out", _quiet_page()).tools()
    for body in ran.model.bodies():  # the nine as the host lists them, nothing else
        assert [t["type"] for t in body["tools"]] == ["function"] * len(OPERATIONS)
        assert [t["function"]["name"] for t in body["tools"]] == list(OPERATIONS)
        assert [t["function"]["description"] for t in body["tools"]] == [
            t["description"] for t in listed]
        assert [t["function"]["parameters"] for t in body["tools"]] == [
            loop.written_out(t["input_schema"]) for t in listed]
        assert "$ref" not in json.dumps(body["tools"])
    if not MAC:
        pytest.skip("asking the kernel what a running process may do is macOS's sandbox_check")
    assert probed["sandboxed"] is True
    allowed = {"read its own settings", "read the loop's code"}  # the probe can tell
    assert {label for label, denied in probed["denied"].items() if not denied} == allowed


# --- one step at a time ----------------------------------------------------------------------


def test_a_plain_answer_needs_no_tool(ws, tmp_path):
    ran = run_loop(ws, tmp_path, [say("Which drawing should I read first?")])
    assert ran.launched == Launched(agent=0, host=0)
    assert (ran.stop["reason"], ran.stop["turns"], ran.stop["tool_calls"]) == ("answered", 1, 0)
    (body,) = ran.model.bodies()
    assert body["model"] == MODEL_ID
    assert body["messages"] == [{"role": "system", "content": loop.SYSTEM},
                                {"role": "user", "content": ASK}]
    assert ran.sent() == []
    assert "model: Which drawing should I read first?" in ran.view
    assert "Stopped (answered)" in ran.view


def test_one_tool_call_runs_once_and_its_whole_result_reaches_the_model(ws, tmp_path):
    asked = {"project_file": PROJECT}
    ran = run_loop(ws, tmp_path, [act(call("list_prototypes", asked)),
                                  say("Those are the prototypes.")])
    assert ran.stop["reason"] == "answered" and ran.sent() == [("list_prototypes", asked)]
    (host,) = ran.host_results()
    (tool,) = [m for m in ran.model.bodies()[1]["messages"] if m["role"] == "tool"]
    assert tool["tool_call_id"] == ran.events("tool_call")[0]["id"]
    told = json.loads(tool["content"])
    assert told == {"ok": True, "result": host["structuredContent"],
                    "counts": loop.counts(host["structuredContent"])}
    assert told["counts"]["prototypes"] == len(host["structuredContent"]["prototypes"]) > 1


def test_every_list_in_a_result_comes_with_its_count_so_the_model_never_counts():
    """D2 (KNOWN_QWEN_DEFECTS.md): the model miscounted lists in its prose ("six" standards for
    seven, "15 bands" for 16). Each result now carries how many items each of its lists holds."""
    result = {"questions": ["a", "b", "c"], "one": ["x"], "none": [],
              "candidates": [{"candidate_id": "full-1", "unverified": ["p", "q"]},
                             {"candidate_id": "full-2", "unverified": ["p"]}]}
    assert loop.counts(result) == {"questions": 3, "candidates": 2,
                                   "candidates[full-1].unverified": 2}
    assert loop._counted({"a": 1}) == {"ok": True, "result": {"a": 1}}
    many = {f"list{i}": [1, 2] for i in range(loop.MOST_COUNTS + 5)}
    shown = loop._counted(many)["counts"]
    assert len(shown) == loop.MOST_COUNTS + 1 and shown["(lists not counted here)"] == 5


def test_an_identifier_no_result_or_brief_gave_is_refused_with_the_ones_that_were():
    """D1 (KNOWN_QWEN_DEFECTS.md): the model copied run_id 303161fb656e as 303161656e, was
    refused three times, and searched again "to get a clean run id". The loop now refuses a run_id
    or candidate_id that no tool result and not the brief has given, naming the ones that were."""
    given = {"run_id": {"303161fb656e"}, "candidate_id": {"full-ALL-ALL-1", "full-ALL-ALL-5"}}
    brief = set(loop.TOKEN.findall("The brief says: validate full-x-9 from run 9cca0ec05912."))
    wrong = loop.unknown_identifier({"run_id": "303161656e", "candidate_id": "full-ALL-ALL-1"},
                                    given, brief)
    assert wrong == ("run_id '303161656e' is not one a tool result or the brief has given. The "
                     "run_ids given so far: 303161fb656e. Copy one exactly; do not call "
                     "propose_layouts again only to get a new one.")
    assert loop.unknown_identifier({"run_id": "303161fb656e", "candidate_id": "full-ALL-ALL-1"},
                                   given, brief) is None
    assert loop.unknown_identifier({"run_id": "9cca0ec05912", "candidate_id": "full-x-9"},
                                   given, brief) is None  # named in the brief
    assert "candidate_ids 'full-ALL-ALL-2'" in loop.unknown_identifier(
        {"run_id": "303161fb656e", "candidate_ids": ["full-ALL-ALL-1", "full-ALL-ALL-2"]},
        given, brief)
    assert "given so far: none yet" in loop.unknown_identifier(
        {"run_id": "abcdef012345", "candidate_id": "c"}, {"run_id": set(), "candidate_id": set()},
        set())
    assert loop.unknown_identifier({"project_file": "x"}, given, brief) is None
    found = {"run_id": set(), "candidate_id": set()}
    loop.ids_given({"run_id": "r1", "candidates": [{"candidate_id": "c1"}, {"candidate_id": "c2"}],
                    "notes": ["run_id r9 is not a field"]}, found)
    assert found == {"run_id": {"r1"}, "candidate_id": {"c1", "c2"}}


def test_the_system_message_names_the_two_approval_points_and_the_identifier_rules():
    """D3 (KNOWN_QWEN_DEFECTS.md): the model invented browser steps ("the architect picks a
    candidate in the browser"). The system message names the only two approval pages, says that
    choosing happens in the conversation, and states D1's and D2's rules."""
    for words in ("exactly two places", "before a search runs (propose_layouts)",
                  "before each export (export_candidate", "not in a browser",
                  "character for character", "never call propose_layouts again",
                  "name every run_id you were given", "Never count the items of a list"):
        assert words in loop.SYSTEM, words


def test_a_wrong_identifier_is_refused_by_the_loop_and_never_sent(ws, tmp_path):
    ran = run_loop(ws, tmp_path, [
        act(call("validate_candidate", {"run_id": "303161656e00", "candidate_id": "full-1"})),
        say("I need the exact run id.")])
    (refused,) = ran.events("tool_refused")
    assert refused["name"] == "validate_candidate" and "given so far: none yet" in (
        refused["reason"])
    assert ran.sent() == [] and ran.stop["reason"] == "answered"


def test_a_model_message_that_is_not_valid_unicode_neither_stops_the_run_nor_the_record(
        ws, tmp_path):
    """Half an emoji, as a model may emit it ("\\ud83d"): Python reads it, but it cannot be
    written as UTF-8. It goes back to the model and into the record as the same escape."""
    half = "Half an emoji: \ud83d"
    ran = run_loop(ws, tmp_path, [act(call("list_prototypes", {"project_file": PROJECT}),
                                      content=half), say("Done.")])
    assert ran.stop["reason"] == "answered" and ran.launched == Launched(agent=0, host=0)
    assert [e["content"] for e in ran.events("assistant")] == [half, "Done."]
    assert ran.model.bodies()[1]["messages"][2]["content"] == half


def test_an_oversized_tool_result_is_cut_with_a_visible_marker(ws, tmp_path):
    ran = run_loop(ws, tmp_path, [act(call("open_project", FILES)), say("Read.")],
                   limits={"max_tool_result_chars": 1000})
    (event,) = ran.events("tool_result")
    (host,) = ran.host_results()
    whole = json.dumps(loop._counted(host["structuredContent"]), ensure_ascii=False,
                       separators=(",", ":"))
    (tool,) = [m for m in ran.model.bodies()[1]["messages"] if m["role"] == "tool"]
    sent = tool["content"]
    assert event["truncated"] is True and event["chars"] == len(whole) > 1000
    assert sent == event["content"] and len(sent) <= 1000
    marker = re.search(r"\n\[TRUNCATED by the agent loop: this tool result is ([\d,]+) "
                       r"characters; only the first ([\d,]+) are shown\]$", sent)
    assert marker and int(marker[1].replace(",", "")) == len(whole)
    kept = int(marker[2].replace(",", ""))
    assert sent[:kept] == whole[:kept] and sent[kept:] == marker[0]
    assert "<- open_project: ok (cut for the model)" in ran.view


def test_repeated_identical_tool_calls_stop_the_run(ws, tmp_path):
    same = json.dumps({"survey_file": SURVEY, "project_file": PROJECT}, indent=2)
    ran = run_loop(ws, tmp_path, [
        act(call("open_project", FILES)), act(call("resolve_rules", FILES)),
        act(call("open_project", same)),  # the same call, whatever its spacing and order
        act(call("resolve_rules", FILES)), act(call("open_project", FILES)), say("unreached")])
    assert (ran.stop["reason"], ran.stop["turns"]) == ("repeated_tool_call", 5)
    assert "open_project was asked for 3 times" in ran.stop["detail"]
    assert [name for name, _ in ran.sent()] == ["open_project", "resolve_rules",
                                                "open_project", "resolve_rules"]
    assert len(ran.events("tool_call")) == 5 and len(ran.events("tool_result")) == 4


def test_the_turn_and_tool_call_limits_stop_the_run(ws, tmp_path):
    turns = run_loop(ws, tmp_path / "turns", [act(call("open_project", FILES)),
                                              act(call("resolve_rules", FILES)),
                                              say("unreached")], limits={"max_turns": 2})
    assert (turns.stop["reason"], turns.stop["turns"]) == ("max_turns", 2)
    assert [name for name, _ in turns.sent()] == ["open_project"]  # the last turn's: never run
    calls = run_loop(ws, tmp_path / "calls", [
        act(call("open_project", FILES), call("resolve_rules", FILES),
            call("inspect_envelope", FILES)), say("unreached")], limits={"max_tool_calls": 2})
    assert calls.stop["reason"] == "max_tool_calls"
    assert [name for name, _ in calls.sent()] == ["open_project", "resolve_rules"]
    assert turns.launched == calls.launched == Launched(agent=1, host=0)


def test_a_model_request_past_its_timeout_stops_the_run(ws, tmp_path):
    began = time.monotonic()
    ran = run_loop(ws, tmp_path, [late(LONG_S, say("too late"))],
                   limits={"request_timeout_s": 1.0})
    assert time.monotonic() - began < LONG_S / 2
    assert ran.stop["reason"] == "request_timeout" and ran.launched.agent == 1
    (error,) = ran.events("model_error")
    assert error["kind"] == "timeout" and 1.0 <= error["elapsed_s"] < LONG_S / 2


def test_the_whole_run_has_a_time_limit(ws, tmp_path):
    began = time.monotonic()
    ran = run_loop(ws, tmp_path, [act(call("open_project", FILES)),
                                  late(LONG_S, say("too late"))],
                   limits={"run_timeout_s": 3.0, "request_timeout_s": LONG_S * 2})
    assert time.monotonic() - began < LONG_S / 2
    assert ran.stop["reason"] == "run_timeout" and 3.0 <= ran.stop["elapsed_s"] < LONG_S / 2
    assert ran.sent() == [("open_project", FILES)] and ran.launched.agent == 1


@pytest.mark.parametrize("case", ["HTTP 503", "connection refused", "not JSON", "no choices"])
def test_a_failing_model_endpoint_stops_the_run(ws, tmp_path, case):
    steps = {"HTTP 503": [status(503, b"overloaded")], "connection refused": [],
             "not JSON": [raw(b"{not json")], "no choices": [raw(b'{"id": "x", "choices": []}')]}
    endpoint = f"http://127.0.0.1:{_unused_port()}/v1" if case == "connection refused" else None
    ran = run_loop(ws, tmp_path, steps[case], endpoint=endpoint)
    assert ran.stop["reason"] == "model_error" and ran.launched == Launched(agent=1, host=0)
    (error,) = ran.events("model_error")  # tried once: retries are off unless configured
    assert error["kind"] == {"HTTP 503": "http_status", "connection refused": "connection",
                             "not JSON": "malformed", "no choices": "malformed"}[case]
    assert len(ran.model.requests) == (0 if case == "connection refused" else 1)
    if case == "HTTP 503":
        assert (error["status"], error["body"]) == (503, "overloaded")
    if case == "not JSON":
        assert error["body"] == "{not json"
    assert ran.sent() == [] and "model request failed" in ran.view


def test_retries_repeat_a_failed_model_request_and_never_a_tool_call(ws, tmp_path):
    ran = run_loop(ws, tmp_path, [act(call("open_project", FILES)), status(503), status(502),
                                  say("Done.")], limits={"model_retries": 2})
    assert ran.stop["reason"] == "answered" and ran.launched == Launched(agent=0, host=0)
    assert [(r["turn"], r["attempt"]) for r in ran.events("model_request")] == [
        (1, 1), (2, 1), (2, 2), (2, 3)]
    assert len(set(ran.model.requests[1:])) == 1  # the same request, byte for byte
    assert ran.sent() == [("open_project", FILES)]  # the tool ran once


def test_a_proposal_the_person_rejects_runs_nothing_and_the_record_says_so(ws, tmp_path):
    ran = run_loop(ws, tmp_path, [act(call("propose_layouts", PROPOSE)),
                                  say("The architect rejected the proposal.")],
                   decisions=("reject",))
    (result,) = ran.results()
    assert result["result"]["status"] == "NOT_APPROVED" and result["result"]["run_id"] is None
    assert len(ran.browser.opened) == 1 and not list(ran.out.glob("*/run.json"))
    (entry,) = audit.read(ran.out)
    assert (entry.asked, entry.decision, entry.channel, entry.run_id) == (
        Asked.PROPOSAL, Decision.REJECTED, "PageApprover", None)
    assert "<- propose_layouts: ok, NOT_APPROVED" in ran.view
    assert ran.stop["reason"] == "answered"


def test_a_fail_candidate_cannot_be_exported_through_the_loop(journey, ws, tmp_path):
    proposed, checked = (r["result"] for r in journey.results()[2:4])
    candidate_id = proposed["candidates"][0]["candidate_id"]
    run_id = _copy_run(journey.out, proposed["run_id"], tmp_path / "out")
    _tower_into_the_setback(tmp_path / "out", run_id, candidate_id)
    export = {"run_id": run_id, "candidate_id": candidate_id,
              "acknowledged_unresolved": [item["item"] for item in checked["unverified"]]}
    # a new session: the architect names the run and the candidate in the brief
    ran = run_loop(ws, tmp_path, [act(call("export_candidate", export)),
                                  say("The export was refused.")], decisions=("approve",),
                   brief=f"{ASK} Export {candidate_id} from run {run_id}.")
    result = ran.results()[0]["result"]
    assert result["status"] == "REFUSED" and result["legal_verdict"] == "FAIL"
    assert any(r.startswith("FAIL All-round setback") for r in result["reasons"]), result
    assert not (ran.out / run_id / "exports").exists() and not result["files"]
    assert ran.browser.opened == [] and audit.read(ran.out) == []  # never put to the person


# --- stopping a run --------------------------------------------------------------------------


def _launcher(ws: Path, out: Path, url: str, browser: OutOfBandBrowser) -> subprocess.Popen:
    """The launcher as the architect starts it, in a process of its own."""
    return subprocess.Popen([str(AGENT_COMMAND), "--workspace", str(ws), "--out", str(out),
                             "--model-endpoint", url, "--model-id", MODEL_ID, "--brief", ASK],
                            env=browser.env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_ctrl_c_stops_the_run_in_order_and_keeps_the_transcript(ws, tmp_path):
    out = tmp_path / "out"
    with FakeModel([late(LONG_S, say("too late"))]) as model, \
            OutOfBandBrowser(tmp_path, out, []) as browser:
        running = _launcher(ws, out, model.url, browser)
        _until(lambda: any(e["event"] == "model_request" for e in _record(out)))
        asked = time.monotonic()
        running.send_signal(signal.SIGINT)
        stdout, stderr = running.communicate(timeout=WAIT_S)
        took = time.monotonic() - asked
    assert running.returncode == 128 + signal.SIGINT, stderr
    assert took < launcher.STOP_GRACE_S  # the agent stopped when asked: nothing was killed
    events = _record(out)
    assert _launcher_event(events, "signal")["signal"] == "SIGINT"
    (stop,) = [e for e in events if e["source"] == "agent" and e["event"] == "stop"]
    assert stop["reason"] == "signal" and "SIGTERM" in stop["detail"]
    ended = events[-1]
    assert (ended["event"], ended["agent"], ended["host"], ended["signal"]) == (
        "ended", 128 + signal.SIGTERM, 0, "SIGINT")  # the host ended with its stream
    assert not [e for e in events if e["source"] == "launcher" and e["event"] in ("kill", "stop")]
    started = _launcher_event(events, "started")
    assert _gone(started["agent_pid"]) and _gone(started["host_pid"])
    assert "Stopped (signal)" in stdout


def test_sigterm_while_the_architect_is_asked_stops_the_run_and_runs_nothing(ws, tmp_path):
    out = tmp_path / "out"
    with FakeModel([act(call("propose_layouts", PROPOSE)), say("unreached")]) as model, \
            OutOfBandBrowser(tmp_path, out, []) as browser:  # nobody answers the page
        running = _launcher(ws, out, model.url, browser)
        _until(lambda: browser.opened)
        running.send_signal(signal.SIGTERM)
        stdout, stderr = running.communicate(timeout=WAIT_S)
    assert running.returncode == 128 + signal.SIGTERM, stderr
    events = _record(out)
    (stop,) = [e for e in events if e["source"] == "agent" and e["event"] == "stop"]
    assert stop["reason"] == "signal"
    assert _launcher_event(events, "stop")["process"] == "host"  # still on the page: stopped
    ended = events[-1]
    assert (ended["agent"], ended["host"], ended["signal"]) == (
        128 + signal.SIGTERM, -signal.SIGTERM, "SIGTERM")
    assert not list(out.glob("*/run.json")) and audit.read(out) == []  # nothing ran or approved
    mcp = _lines(next(out.glob("agent/*/mcp.jsonl")))
    assert [m["message"]["params"]["name"] for m in mcp if m["direction"] == "agent->host"
            and m["message"].get("method") == "tools/call"] == ["propose_layouts"]
    started = _launcher_event(events, "started")
    assert _gone(started["agent_pid"]) and _gone(started["host_pid"])


# --- the configuration, everywhere -----------------------------------------------------------


def test_the_configuration_comes_from_the_arguments_then_the_file_then_the_defaults(tmp_path):
    path = tmp_path / "agent.config.json"
    path.write_text(json.dumps({"model_endpoint": "http://127.0.0.1:8000/v1",
                                "model_id": "qwen3.8-27b-sglang",
                                "request_options": {"temperature": 0.6, "max_tokens": 4096},
                                "limits": {"max_turns": 12, "request_timeout_s": 900}}))
    config = load_config(path)
    settings = Settings.build(config, "A brief.", limits={"max_turns": 20})
    assert settings.model_id == "qwen3.8-27b-sglang"
    assert (settings.limits.max_turns, settings.limits.request_timeout_s) == (20, 900.0)
    assert settings.limits.max_tool_calls == Limits().max_tool_calls
    assert settings.request_options == {"temperature": 0.6, "max_tokens": 4096}
    other = Settings.build(config, "A brief.", model_id="GLM-5.3-Flash")  # A/B: one argument
    assert other.model_id == "GLM-5.3-Flash"
    settings.write(tmp_path)
    assert Settings.read(tmp_path) == settings
    assert (tmp_path / "agent.json").stat().st_mode & 0o777 == 0o600


def test_the_endpoint_model_and_limits_can_come_from_a_configuration_file(ws, tmp_path, capsys):
    out, config = tmp_path / "out", tmp_path / "agent.config.json"
    with FakeModel([say("Configured.")]) as model:
        config.write_text(json.dumps({"model_endpoint": model.url, "model_id": "from-the-file",
                                      "request_options": {"temperature": 0.25},
                                      "limits": {"max_turns": 5}}))
        status = launcher.main(["--workspace", str(ws), "--out", str(out), "--config",
                                str(config), "--brief", ASK])
    assert status == 0, capsys.readouterr().err
    (body,) = model.bodies()
    assert (body["model"], body["temperature"]) == ("from-the-file", 0.25)
    launched = _launcher_event(_record(out), "launch")
    assert launched["endpoint"] == model.url and launched["settings"]["limits"]["max_turns"] == 5
    assert "model: Configured." in capsys.readouterr().out  # the architect's terminal


URL = "http://127.0.0.1:8000/v1"
FULL = ["--model-endpoint", URL, "--model-id", MODEL_ID, "--brief", ASK]
BAD = {
    "no endpoint": (["--model-id", MODEL_ID, "--brief", ASK], {}, "needs --model-endpoint"),
    "no model": (["--model-endpoint", URL, "--brief", ASK], {}, "model id is missing"),
    "no brief": (["--model-endpoint", URL, "--model-id", MODEL_ID], {}, "brief is missing"),
    "no turns": ([*FULL, "--max-turns", "0"], {}, "max_turns must be at least 1"),
    "one repeat": ([*FULL, "--max-identical-calls", "1"], {}, "must be at least 2"),
    "no time": ([*FULL, "--run-timeout-s", "0"], {}, "must be more than 0"),
    "a remote endpoint": (["--model-endpoint", "http://10.0.0.5:8888/v1", "--model-id",
                           MODEL_ID, "--brief", ASK], {}, "is not on this machine"),
    "a misspelt key": (FULL, {"modle_id": "x"}, "Unknown key 'modle_id'"),
    "a misspelt limit": (FULL, {"limits": {"max_turn": 3}}, "Unknown limit 'max_turn'"),
    "a reserved option": (FULL, {"request_options": {"tools": []}}, "may not set 'tools'"),
}


@pytest.mark.parametrize("case", BAD)
def test_the_launcher_refuses_a_configuration_it_cannot_use_and_starts_nothing(
        tmp_path, case, capsys):
    argv, config, why = BAD[case]
    ws, out = tmp_path / "ws", tmp_path / "out"
    ws.mkdir()
    if config:
        (tmp_path / "config.json").write_text(json.dumps(config))
        argv = [*argv, "--config", str(tmp_path / "config.json")]
    assert launcher.main(["--workspace", str(ws), "--out", str(out), *argv]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Not started:") and why in err, err
    assert not out.exists()


def test_the_model_client_takes_no_proxy_from_the_environment(monkeypatch):
    """httpx with trust_env=False: a proxy named in the environment is not used (inside the
    sandbox the environment is bare anyway). Nothing listens where the proxy is said to be, so
    a client that used it would fail."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                 "all_proxy"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{_unused_port()}")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)

    async def ask(url: str):
        async with Chat(url, MODEL_ID, {}, 10.0, 65_536) as chat:
            return await chat.complete(chat.payload([{"role": "user", "content": "Hello"}], []))

    with FakeModel([say("Straight through.")]) as model:
        answer = anyio.run(ask, model.url)
    assert answer.message["content"] == "Straight through." and len(model.requests) == 1


def test_a_long_tool_result_is_cut_and_marked_and_a_short_one_is_whole():
    assert loop.fit("short", 300) == ("short", False)
    cut, was_cut = loop.fit("x" * 5000, 300)
    assert was_cut and len(cut) <= 300 and cut.startswith("x" * 100)
    assert "this tool result is 5,000 characters" in cut


def test_the_models_message_goes_back_as_its_text_and_tool_calls_only():
    message = {"role": "assistant", "content": None, "reasoning_content": "thinking",
               "tool_calls": [{"type": "function", "function": {
                   "name": "open_project", "arguments": {"project_file": "p"}}}]}
    assert loop.assistant_message(message, 3) == {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "call_3_0", "type": "function", "function": {
            "name": "open_project", "arguments": '{"project_file": "p"}'}}]}
    parts = {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    assert loop.assistant_message(parts, 1) == {"role": "assistant", "content": "ab"}


def test_every_parameter_the_model_is_offered_carries_its_own_type(ws, tmp_path):
    # The first real run: SGLang's qwen3_coder parser types a parameter by its own schema and
    # follows no $ref, so `intent`, offered as {"$ref": "#/$defs/Intent"}, reached the host as
    # text, and the host refused every proposal that carried one.
    listed = ToolHost(ws, tmp_path / "out", _quiet_page()).tools()
    for tool in listed:
        offered = loop.written_out(tool["input_schema"])
        assert "$ref" not in json.dumps(offered) and "$defs" not in offered
        for name, parameter in offered["properties"].items():
            kinds = [parameter, *parameter.get("anyOf", [])]
            assert any("type" in kind for kind in kinds), (tool["name"], name)
    (propose,) = [t["input_schema"] for t in listed if t["name"] == "propose_layouts"]
    intent = loop.written_out(propose)["properties"]["intent"]
    assert (intent["type"], intent["additionalProperties"]) == ("object", False)
    assert set(intent["properties"]) == {"height", "floors_above_stilt", "unit_mix_percent",
                                         "massing"}
    assert intent["default"] == propose["properties"]["intent"]["default"]
    assert intent["properties"]["massing"]["anyOf"][0]["enum"] == [
        "MAX_YIELD", "BALANCED", "CONVENTIONAL_OPEN_SPACE"]
    assert "$defs" in propose  # the host's own schema is left as it is


def test_a_reference_that_cannot_be_written_out_leaves_the_schema_as_listed():
    node = {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}
    looped = {"$defs": {"Node": node}, "type": "object",
              "properties": {"head": {"$ref": "#/$defs/Node"}}}
    remote = {"type": "object", "properties": {"a": {"$ref": "https://example.com/a.json"}}}
    missing = {"type": "object", "properties": {"a": {"$ref": "#/$defs/Absent"}}}
    for schema in (looped, remote, missing):
        assert loop.written_out(schema) is schema
    kind = {"enum": ["X", "Y"], "type": "string"}
    nested = {"$defs": {"Kind": kind, "Box": {"type": "object",
                                              "properties": {"kind": {"$ref": "#/$defs/Kind"}}}},
              "type": "object",
              "properties": {"box": {"$ref": "#/$defs/Box", "default": {}, "title": "the box"}}}
    assert loop.written_out(nested) == {
        "type": "object", "properties": {"box": {
            "type": "object", "properties": {"kind": kind}, "default": {}, "title": "the box"}}}
