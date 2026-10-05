"""The model process's isolation (siteplan.agent.sandbox, siteplan.agent.launch): it gets the
MCP stream to the host and nothing else.

The launcher starts the host and the scripted stand-in model (siteplan.agent.standin) in the
sandbox, joined only by the stream; the stand-in calls the nine tools and tries everything that
must fail. These live runs need the sandbox to apply on this machine (sandbox-exec on macOS,
bubblewrap on Linux); where it cannot, they skip and say why, never pass. The refusals (no
sandbox for the platform, its tool missing, a sandbox that cannot be applied or does not hold, a
policy it cannot express) are tested everywhere. The architect's browser is played out of band
as in tests/test_agent_transport.py. Made-up land only.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_agent_transport import PLAN, OutOfBandBrowser, hashes, token
from test_service import OPERATIONS, make_workspace

from siteplan.agent import launch as launcher
from siteplan.agent import sandbox, standin
from siteplan.agent.launch import Launched, launch
from siteplan.agent.sandbox import Policy, SandboxLeak, SandboxUnavailable
from siteplan.service import Decision, audit

TEST_CLASS = "normative"

LAUNCH_TIMEOUT_S = 600.0
SECRET = "SITEPLAN_TEST_SECRET"  # set in the launcher's environment, never the agent's
# Python's own locale coercion and macOS add these two to a bare environment.
ADDED_BY_THE_PLATFORM = {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"}
MAC = sys.platform == "darwin"


def _folders(root: Path) -> tuple[Path, Path, Path]:
    folders = tuple(root / name for name in ("ws", "out", "scratch"))
    for folder in folders:
        folder.mkdir(exist_ok=True)
    return folders


@pytest.fixture(scope="module")
def here(tmp_path_factory) -> None:
    """Skips the live runs, saying why, when the sandbox cannot be applied on this machine. A
    sandbox that applies and does not hold is a fault, and fails them instead."""
    try:
        sandbox.preflight(Policy.for_agent(*_folders(tmp_path_factory.mktemp("here"))))
    except SandboxLeak:
        raise
    except SandboxUnavailable as error:
        pytest.skip(f"the sandbox cannot be applied on this machine: {error}")


# --- the stand-in's tour through the launcher ------------------------------------------------


@dataclass
class Toured:
    ws: Path
    out: Path
    elsewhere: Path
    before: dict[str, str]
    browser: OutOfBandBrowser
    launched: Launched
    report: dict

    def probes(self, *starts: str) -> list[dict]:
        found = [p for p in self.report["probes"] if p["probe"].startswith(starts)]
        assert found, starts
        return found


@pytest.fixture(scope="module")
def toured(here, tmp_path_factory) -> Toured:
    ws = make_workspace(tmp_path_factory.mktemp("sandbox-ws"))
    out = tmp_path_factory.mktemp("sandbox-out")
    scratch = tmp_path_factory.mktemp("sandbox-scratch")
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "secret.txt"
    elsewhere.write_text("not for the model")
    listener = socket.create_server(("127.0.0.1", 0))  # it would accept, were it reachable
    plan = {**PLAN, "workspace": str(ws), "out": str(out), "elsewhere": str(elsewhere),
            "connect": [listener.getsockname()[1]]}
    (scratch / standin.PLAN).write_text(json.dumps(plan))
    before = hashes(ws)
    browser = OutOfBandBrowser(tmp_path_factory.mktemp("sandbox-browser"), out,
                               ["approve", "approve"])
    try:
        with browser:
            launched = launch(ws, out, "siteplan.agent.standin", scratch=scratch,
                              env=browser.env(**{SECRET: "a key the model must not see"}),
                              timeout=LAUNCH_TIMEOUT_S)
    finally:
        listener.close()
    report = json.loads((scratch / standin.REPORT).read_text())
    return Toured(ws, out, elsewhere, before, browser, launched, report)


def _held(probes: list[dict]) -> None:
    """Every attempt failed; on macOS, refused by the sandbox itself."""
    for probe in probes:
        assert probe["outcome"] != "allowed", probe
        if MAC:
            assert probe["outcome"] == "denied" and "PermissionError" in probe["detail"], probe


def test_the_sandboxed_stand_in_reaches_the_nine_tools_through_the_launcher(toured):
    report = toured.report
    assert toured.launched == Launched(agent=0, host=0)
    assert report["finished"] and "session_error" not in report
    assert [t["name"] for t in report["offered"]] == list(OPERATIONS)
    operations = {c["tool"]: c for c in report["calls"] if c["kind"] == "operation"}
    assert list(operations) == list(OPERATIONS)
    for name, call in operations.items():
        assert call["ok"] and call["data"], (name, call["error"])
    assert operations["propose_layouts"]["data"]["status"] == "PROPOSED"
    assert operations["export_candidate"]["data"]["status"] == "EXPORTED"
    assert [(e.asked.value, e.decision, e.channel) for e in audit.read(toured.out)] == [
        ("PROPOSAL", Decision.APPROVED, "PageApprover"),
        ("EXPORT", Decision.APPROVED, "PageApprover")]


def test_the_host_refuses_what_the_sandboxed_stand_in_must_not_do(toured):
    refused = [c for c in toured.report["calls"] if c["kind"] != "operation"]
    assert len(refused) == (len(standin.UNKNOWN_TOOLS) + len(standin.INJECTED)
                            + len(standin.INJECTED_INTENT) + len(standin.invalid(PLAN)))
    for call in refused:
        assert not call["ok"] and not call.get("broken"), call
        assert call["error"].startswith(("There is no such tool", "The arguments do not fit"))


def test_the_model_process_cannot_write_the_workspace_or_out(toured):
    _held(toured.probes("create a file in", "open the project file for writing",
                        "delete a file in the workspace", "make a folder in out"))
    assert hashes(toured.ws) == toured.before  # byte for byte
    leftovers = [p for folder in (toured.ws, toured.out, toured.elsewhere.parent)
                 for p in folder.rglob(f"{standin.WAS_HERE}*")]
    assert leftovers == []


def test_the_model_process_cannot_read_the_workspace_out_or_anything_else(toured):
    _held(toured.probes("read the project file", "list the workspace", "look up the project",
                        "list out", "read a file elsewhere", "read the approvals log",
                        "read run "))
    assert len(toured.probes("read run ")) == 1  # the run the host wrote was tried too


def test_the_model_process_cannot_load_or_start_the_engine_the_legacy_server_or_a_shell(
        toured):
    programs = standin.programs()
    assert [Path(p).name for p in programs] == ["siteplan", "siteplan-mcp", "sh"]
    _held(toured.probes(*(f"start {p}" for p in programs)))
    _held(toured.probes(*(f"become {p}" for p in programs)))
    _held(toured.probes("load siteplan.cli", "load siteplan.mcp_server", "load siteplan.service",
                        "load siteplan.validator"))
    if MAC:  # Seatbelt also forbids any child process: not even another interpreter
        _held(toured.probes("start another interpreter"))
    assert toured.report["finished"]  # no exec replaced the process along the way


def test_the_model_process_has_no_network_without_a_model_endpoint(toured):
    _held(toured.probes("connect to 127.0.0.1:"))


def test_the_model_process_gets_a_bare_environment(toured):
    seen = set(toured.report["environment"])
    assert SECRET not in seen and "BROWSER" not in seen
    assert seen - ADDED_BY_THE_PLATFORM == {"HOME", "TMPDIR", "PATH", "SITEPLAN_SCRATCH"}


def test_the_approval_token_never_reaches_the_sandboxed_model(toured):
    assert len(toured.browser.opened) == 2  # the proposal, then the export's UNVERIFIED items
    assert toured.browser.runs_when_opened[0] == []  # nothing ran before the click
    sent = "".join(toured.report["received"])
    assert len(toured.report["received"]) == 2 + len(toured.report["calls"])  # every answer
    for url in toured.browser.opened:
        assert token(url) not in sent and url not in sent


def test_a_model_endpoint_opens_its_port_and_no_other(here, tmp_path):
    if not MAC:
        pytest.skip("only Seatbelt opens a single port; bubblewrap refuses an endpoint "
                    "(test_linux_refuses_a_model_endpoint_rather_than_open_the_network)")
    model, other = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
    try:
        port, closed = model.getsockname()[1], other.getsockname()[1]
        policy = Policy.for_agent(*_folders(tmp_path), endpoint=f"http://localhost:{port}/v1")
        code = ("import socket, sys\n"
                "for port in sys.argv[1:]:\n"
                "    try:\n"
                "        socket.create_connection(('127.0.0.1', int(port)), timeout=5).close()\n"
                "        print(port, 'open')\n"
                "    except OSError as error:\n"
                "        print(port, type(error).__name__)\n")
        done = subprocess.run(sandbox.command(policy, [str(policy.interpreter), "-I", "-B",
                                                       "-c", code, str(port), str(closed)]),
                              env=sandbox.environment(policy), cwd=policy.scratch,
                              capture_output=True, text=True, timeout=60)
    finally:
        model.close()
        other.close()
    assert done.stdout.split("\n")[:2] == [f"{port} open", f"{closed} PermissionError"], done
    assert sandbox.environment(policy)["SITEPLAN_MODEL_ENDPOINT"] == (
        f"http://127.0.0.1:{port}/v1")  # by address: names are not looked up inside


# --- refused everywhere ----------------------------------------------------------------------


def test_a_platform_without_a_sandbox_is_refused(tmp_path, monkeypatch):
    policy = Policy.for_agent(*_folders(tmp_path))
    with pytest.raises(SandboxUnavailable, match="no sandbox for this platform"):
        sandbox.command(policy, ["agent"], platform="win32")
    monkeypatch.setattr(sandbox, "SANDBOX_EXEC", str(tmp_path / "no-sandbox-exec"))
    with pytest.raises(SandboxUnavailable, match="not on this Mac"):
        sandbox.command(policy, ["agent"], platform="darwin")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with pytest.raises(SandboxUnavailable, match="bubblewrap"):
        sandbox.command(policy, ["agent"], platform="linux")


def test_linux_refuses_a_model_endpoint_rather_than_open_the_network(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/bwrap")
    policy = Policy.for_agent(*_folders(tmp_path), endpoint="http://127.0.0.1:8000/v1")
    with pytest.raises(SandboxUnavailable, match="every port on this machine"):
        sandbox.command(policy, ["agent"], platform="linux")


@pytest.mark.parametrize("url", ["http://10.0.0.5:8000/v1", "http://office-server:8000/v1",
                                 "https://api.example.com/v1", "ftp://127.0.0.1/model",
                                 "127.0.0.1:8000", "http://127.0.0.1:99999/v1"])
def test_a_model_endpoint_off_this_machine_or_not_a_url_is_refused(tmp_path, url):
    with pytest.raises(SandboxUnavailable):
        Policy.for_agent(*_folders(tmp_path), endpoint=url)


def test_a_model_endpoint_on_this_machine_is_one_port_by_address(tmp_path):
    for url, port, given in (("http://localhost:11434/v1", 11434, "http://127.0.0.1:11434/v1"),
                             ("http://127.0.0.1:8000/v1", 8000, "http://127.0.0.1:8000/v1"),
                             ("http://[::1]/v1", 80, "http://[::1]/v1")):
        endpoint = Policy.for_agent(*_folders(tmp_path), endpoint=url).endpoint
        assert (endpoint.port, endpoint.url) == (port, given), url


def test_what_the_model_may_touch_stays_apart_from_the_workspace_and_out(tmp_path):
    ws, out, scratch = _folders(tmp_path)
    venv = Path(sys.prefix)
    for workspace, out_, scratch_ in ((ws, out, ws / "scratch"), (ws, out, out),
                                      (ws, out, tmp_path), (venv / "ws", out, scratch),
                                      (ws, sandbox.PACKAGE / "agent" / "out", scratch),
                                      (sandbox.PACKAGE.parent, out, scratch)):
        with pytest.raises(SandboxUnavailable, match="overlap"):
            Policy.for_agent(workspace, out_, scratch_)
    Policy.for_agent(ws, out, scratch)  # side by side is where they belong


class _Started(list):
    def __call__(self, *args, **kwargs):
        self.append(args)
        raise AssertionError("a process was started")


def _failing(policy, argv, platform=None):
    return [sys.executable, "-I", "-c",
            "import sys; sys.exit('sandbox-exec: sandbox_apply: Operation not permitted')"]


@pytest.mark.parametrize("case", ["no sandbox for the platform", "no sandbox tool",
                                  "cannot be applied", "does not hold"])
def test_the_launcher_starts_nothing_when_the_sandbox_cannot_be_applied(tmp_path, monkeypatch,
                                                                        case):
    ws, out, scratch = _folders(tmp_path)
    started = _Started()
    monkeypatch.setattr(launcher, "_run", started)
    if case == "no sandbox for the platform":
        monkeypatch.setattr(sys, "platform", "sunos5")
    elif case == "no sandbox tool":
        monkeypatch.setattr(sandbox, "SANDBOX_EXEC", str(tmp_path / "no-sandbox-exec"))
        monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    elif case == "cannot be applied":
        monkeypatch.setattr(sandbox, "command", _failing)
    else:  # the sandbox's tool runs the agent but confines nothing: the preflight finds out
        monkeypatch.setattr(sandbox, "command", lambda policy, argv, platform=None: argv)
    with pytest.raises(SandboxUnavailable) as refused:
        launch(ws, out, "siteplan.agent.standin", scratch=scratch)
    assert started == []  # neither the host nor the agent
    expected = {"no sandbox for the platform": "no sandbox for this platform",
                "no sandbox tool": "cannot be sandboxed", "cannot be applied": "sandbox_apply",
                "does not hold": "could read"}[case]
    assert expected in str(refused.value)
    assert isinstance(refused.value, SandboxLeak) == (case == "does not hold")
    assert sorted(p.name for p in scratch.iterdir()) == []


def test_the_command_line_says_why_it_did_not_start(tmp_path, monkeypatch, capsys):
    ws, out, _ = _folders(tmp_path)
    monkeypatch.setattr(sys, "platform", "sunos5")
    assert launcher.main(["--workspace", str(ws), "--out", str(out),
                          "--agent", "siteplan.agent.standin"]) == 2
    assert capsys.readouterr().err.startswith("Not started: There is no sandbox")


# --- what the policy says, platform by platform ---------------------------------------------


def test_the_agent_runs_isolated_with_nothing_of_the_persons_environment(tmp_path):
    policy = Policy.for_agent(*_folders(tmp_path))
    assert sandbox.agent_argv(policy, "siteplan.agent.standin", ["--x"]) == [
        sys.executable, "-I", "-B", "-m", "siteplan.agent.standin", "--x"]
    assert sandbox.environment(policy) == {
        "HOME": str(policy.scratch), "TMPDIR": str(policy.scratch), "PATH": "/usr/bin:/bin",
        "SITEPLAN_SCRATCH": str(policy.scratch)}


def test_the_seatbelt_profile_is_the_policy(tmp_path):
    policy = Policy.for_agent(*_folders(tmp_path))
    rules = sandbox.seatbelt_profile(policy).strip().split("\n")
    assert rules[:3] == ["(version 1)", "(deny default)", '(import "system.sb")']
    interpreters = dict.fromkeys([sys.executable, os.path.realpath(sys.executable)])
    assert [r for r in rules if "process-exec" in r] == [
        "(allow process-exec " + " ".join(f'(literal "{p}")' for p in interpreters) + ")"]
    assert not [r for r in rules if "process-fork" in r]  # denied by default: no child at all
    writes = [r for r in rules if r.startswith("(allow") and "file-write" in r]
    assert writes == [f'(allow file-read* file-write* (subpath "{policy.scratch}"))']
    assert not [r for r in rules if r.startswith("(allow network")]
    ws, out = policy.hidden
    assert rules[-1].startswith("(deny file-read* file-read-data file-read-metadata")
    assert rules[-1].endswith(f'(subpath "{ws}") (subpath "{out}"))')
    endpoint = Policy.for_agent(*_folders(tmp_path), endpoint="http://127.0.0.1:8000/v1")
    opened = [r for r in sandbox.seatbelt_profile(endpoint).split("\n")
              if r.startswith("(allow network")]
    assert opened == ['(allow network-outbound (remote tcp "localhost:8000"))']


def test_the_bubblewrap_root_holds_only_what_the_model_may_read(tmp_path):
    policy = Policy.for_agent(*_folders(tmp_path))
    args = sandbox.bwrap_args(policy, "/usr/bin/bwrap")
    assert args[:4] == ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
    assert "--share-net" not in args
    text = " ".join(args)
    assert all(str(hidden) not in text for hidden in policy.hidden)
    pairs = list(zip(args, args[1:], strict=False))
    assert [b for a, b in pairs if a == "--bind"] == [str(policy.scratch)]  # the one writable
    sources = {b for a, b in pairs if a in ("--ro-bind", "--ro-bind-try", "--bind")}
    assert not sources & {"/", "/usr", "/bin", "/usr/bin", "/sbin", "/usr/sbin",
                          *map(str, policy.runtime), *(str(p / "bin") for p in policy.runtime)}
    assert os.path.realpath(sys.executable) in sources  # the interpreter, the one program
    assert [b for a, b in pairs if a == "--tmpfs"] == [str(policy.package)]
    assert {str(policy.package / "__init__.py"), str(policy.package / "agent")} <= sources
    links = {args[i + 2]: args[i + 1] for i, arg in enumerate(args) if arg == "--symlink"}
    if policy.interpreter.is_symlink():  # the venv's way to its interpreter, link by link
        assert str(policy.interpreter) in links


def test_the_links_to_the_interpreter_are_recreated_in_order(tmp_path):
    real = tmp_path / "python-3.11.15" / "bin"
    real.mkdir(parents=True)
    (real / "python3.11").write_text("")
    (tmp_path / "python-3.11").symlink_to(tmp_path / "python-3.11.15")  # uv's minor-version link
    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(tmp_path / "python-3.11" / "bin" / "python3.11")
    (venv / "python3").symlink_to("python")
    links = sandbox._links(venv / "python3")
    assert links == [(venv / "python3", "python"),
                     (venv / "python", str(tmp_path / "python-3.11" / "bin" / "python3.11")),
                     (tmp_path / "python-3.11", str(tmp_path / "python-3.11.15"))]
