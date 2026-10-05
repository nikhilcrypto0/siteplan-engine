"""Starts the tools host and the sandboxed agent, joined only by the MCP stream, and keeps the
run's record.

    siteplan-agent --workspace <dir> --out <dir> --model-endpoint http://127.0.0.1:8000/v1 \\
        --model-id <id> (--brief <text> | --brief-file <file>) [--config <file>] [--max-... N]
    siteplan-agent --workspace <dir> --out <dir> --agent siteplan.agent.standin --scratch <dir>

The host (siteplan.agent.server, the command `siteplan-agent-tools`) is the trusted process: it
runs as the architect, reads the workspace, writes `out` and opens the approval page in the
architect's browser. The agent, the process that calls the model (siteplan.agent.loop; the
scripted stand-in siteplan.agent.standin proves the transport), runs in the sandbox (sandbox.py)
with a bare environment and a private scratch folder, where the launcher leaves its settings
(settings.HANDOFF). The sandbox is tried before anything starts (sandbox.preflight); if it cannot
be applied nothing starts, and there is no unsandboxed way to run an agent.

The launcher stands between the two and owns every channel out of the sandbox:
- the MCP stream, the agent's stdout to the host's stdin and back, relayed as it comes and
  recorded line by line (mcp.jsonl);
- the agent's events, on a pipe of their own whose number it is given (`--events-fd`), into the
  transcript (transcript.jsonl);
- the agent's stderr, line by line into the transcript and onto the launcher's stderr.
The record lives in `<out>/agent/<run>/` (transcript.py), which the sandbox can neither read nor
write; the architect's terminal shows the model's messages and each tool call (transcript.View).

The children run in sessions of their own, so a Ctrl-C reaches the launcher alone, which stops
the run in order: the first SIGINT or SIGTERM asks the agent to stop (SIGTERM: the loop closes
its MCP session and records why), the host ends with its stream, and a process still running
after its grace is stopped; a second signal kills both at once. The transcript keeps all of it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import BinaryIO, TextIO

from siteplan.agent import sandbox
from siteplan.agent.settings import MEANING, Limits, Settings, load_config
from siteplan.agent.transcript import Record, View

SERVER = "siteplan.agent.server"
LOOP = "siteplan.agent.loop"
HOST_GRACE_S = 30.0  # how long the host has to finish once the agent has gone
STOP_GRACE_S = 5.0  # between asking a process to stop and killing it
POLL_S = 0.2  # how often the launcher looks at its children while it waits
JOIN_S = 5.0  # for the relays and readers to drain once both processes have ended
CHUNK_BYTES = 65_536
MAX_EVENT_BYTES = 64 * 1024 * 1024  # one event line; a longer one is recorded in pieces


@dataclass(frozen=True)
class Launched:
    agent: int  # the agent's exit status
    host: int  # the host's
    record: Path | None = field(default=None, compare=False)  # <out>/agent/<run>
    signal: int | None = None  # the signal that stopped the run, if one did


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(STOP_GRACE_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _send(process: subprocess.Popen, signum: int) -> None:
    with contextlib.suppress(OSError):
        process.send_signal(signum)


class _Stopping:
    """SIGINT and SIGTERM while a run is on (handled in the main thread only, where Python
    delivers them): the first asks the agent to stop, a second kills both processes."""

    def __init__(self, agent: subprocess.Popen, host: subprocess.Popen) -> None:
        self._agent, self._host = agent, host
        self.received: int | None = None
        self.since = 0.0  # time.monotonic() at the first signal
        self.at = 0.0  # time.time() at the first signal, for the record
        self.forced = False
        self._noted: set[str] = set()
        self._previous: dict[int, object] = {}

    def __enter__(self) -> _Stopping:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                self._previous[signum] = signal.signal(signum, self._handle)
        return self

    def __exit__(self, *exc) -> None:
        for signum, handler in self._previous.items():
            signal.signal(signum, handler)

    def _handle(self, signum: int, frame) -> None:
        # A handler only sets flags and signals: the record is written from the waiting loop.
        if self.received is None:
            self.received, self.since, self.at = signum, time.monotonic(), time.time()
            _send(self._agent, signal.SIGTERM)
        else:
            self.forced = True
            for process in (self._agent, self._host):
                _send(process, signal.SIGKILL)

    def note(self, record: Record) -> None:
        """Writes down, once each, the signal and a second one that killed both."""
        if self.received and "signal" not in self._noted:
            self._noted.add("signal")
            record.launcher("signal", signal=signal.Signals(self.received).name,
                            received_at=self.at, action="asked the agent to stop (SIGTERM)")
        if self.forced and "forced" not in self._noted:
            self._noted.add("forced")
            record.launcher("kill", process="agent and host", reason="a second signal")


def _relay(source: BinaryIO, target: BinaryIO, note: Callable[[bytes], None]) -> None:
    """One direction of the MCP stream, copied and noted as it comes, until either end closes;
    then both ends are closed, so each process sees the stream end."""
    try:
        while chunk := source.read(CHUNK_BYTES):
            note(chunk)
            view = memoryview(chunk)
            while view:
                view = view[target.write(view):]
    except (OSError, ValueError):
        pass  # a process has gone
    finally:
        for end in (target, source):
            with contextlib.suppress(OSError, ValueError):
                end.close()


def _events(descriptor: int, record: Record, view: View) -> None:
    with open(descriptor, "rb") as stream:
        while line := stream.readline(MAX_EVENT_BYTES):
            view.show(record.agent(line))


def _stderr(stream: BinaryIO, record: Record) -> None:
    with contextlib.suppress(OSError, ValueError), io.BufferedReader(stream) as lines:
        for line in iter(lines.readline, b""):
            record.stderr(line)
            sys.stderr.write(line.decode("utf-8", errors="replace"))


def _started(target, *args) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


def _wait_agent(agent: subprocess.Popen, timeout: float | None, stopping: _Stopping,
                record: Record) -> int:
    deadline = None if timeout is None else time.monotonic() + timeout
    killed = False
    while True:
        try:
            status = agent.wait(POLL_S)
        except subprocess.TimeoutExpired:
            status = None
        stopping.note(record)
        if status is not None:
            return status
        if stopping.received and not killed and \
                time.monotonic() > stopping.since + STOP_GRACE_S:
            killed = True
            record.launcher("kill", process="agent",
                            reason=f"still running {STOP_GRACE_S:g} s after it was asked to stop")
            agent.kill()
        if deadline is not None and time.monotonic() > deadline:
            raise subprocess.TimeoutExpired(agent.args, timeout)


def _wait_host(host: subprocess.Popen, stopping: _Stopping, record: Record) -> int:
    agent_gone = time.monotonic()
    while True:
        try:
            status = host.wait(POLL_S)
        except subprocess.TimeoutExpired:
            status = None
        stopping.note(record)
        if status is not None:
            return status
        grace = STOP_GRACE_S if stopping.received else HOST_GRACE_S
        if time.monotonic() > max(agent_gone, stopping.since) + grace:
            record.launcher("stop", process="host",
                            reason=f"still running {grace:g} s after the agent had gone "
                                   "(a tool call or an approval was still open)")
            _stop(host)
            return host.wait()


def _run(host_argv: list[str], agent: str, agent_args: list[str], policy: sandbox.Policy,
         env: Mapping[str, str] | None, timeout: float | None, record: Record,
         view: View) -> Launched:
    events_read, events_write = os.pipe()  # the agent's events: its own channel to the record
    agent_argv = sandbox.command(policy, sandbox.agent_argv(
        policy, agent, [*agent_args, "--events-fd", str(events_write)]))
    host = child = None
    try:
        host = subprocess.Popen(host_argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                bufsize=0, env=dict(env) if env is not None else None,
                                start_new_session=True)
        child = subprocess.Popen(agent_argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, bufsize=0, cwd=policy.scratch,
                                 env=sandbox.environment(policy), pass_fds=(events_write,),
                                 start_new_session=True)
    except BaseException as error:
        _stop(host)
        os.close(events_read)
        record.launcher("ended", error=f"{type(error).__name__}: {error}")
        record.close()
        raise
    finally:
        os.close(events_write)  # the agent's alone now: its exit ends the events
    stopping = _Stopping(child, host)
    failure: dict[str, str] = {}
    threads: list[threading.Thread] = []
    try:
        with stopping:  # from here a signal stops the run in order
            threads = [_started(_relay, child.stdout, host.stdin,
                                lambda chunk: record.mcp("agent->host", chunk)),
                       _started(_relay, host.stdout, child.stdin,
                                lambda chunk: record.mcp("host->agent", chunk)),
                       _started(_events, events_read, record, view),
                       _started(_stderr, child.stderr, record)]
            record.launcher("started", host_pid=host.pid, agent_pid=child.pid,
                            host_argv=host_argv, agent_argv=agent_argv)
            agent_status = _wait_agent(child, timeout, stopping, record)
            host_status = _wait_host(host, stopping, record)
        return Launched(agent_status, host_status, record.folder, stopping.received)
    except BaseException as error:  # the launch's own timeout, or something unforeseen
        failure["error"] = f"{type(error).__name__}: {error}"
        _stop(child)
        _stop(host)
        raise
    finally:
        for thread in threads:
            thread.join(JOIN_S)
        record.launcher("ended", agent=child.returncode, host=host.returncode,
                        signal=signal.Signals(stopping.received).name
                        if stopping.received else None, **failure)
        record.close()
        view.say(f"\nThe run's record: {record.folder}")


def launch(workspace: Path, out: Path, agent: str, agent_args: Sequence[str] = (), *,
           debug: bool = False, endpoint: str | None = None, scratch: Path | None = None,
           env: Mapping[str, str] | None = None, timeout: float | None = None,
           settings: Settings | None = None, view: TextIO | None = None) -> Launched:
    """Run `agent` (a module) in the sandbox against the host on `workspace` and `out`. A scratch
    folder made here is removed afterwards; one given is kept. `settings` are handed to the agent
    in the scratch folder (the model loop needs them). `env` is the host's environment (by
    default this process's); the agent's is the sandbox's own. `view` is where the architect
    sees the run (None: nowhere). Raises SandboxUnavailable, having started nothing, when the
    sandbox cannot be applied."""
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError(f"The workspace {workspace} is not a folder.")
    target = Path(out).resolve()
    if target.is_relative_to(workspace) or workspace.is_relative_to(target):
        raise ValueError(f"out ({target}) must lie neither inside the workspace ({workspace}) "
                         "nor around it: the run's record and the host's runs are written there.")
    made = scratch is None
    if made:
        scratch = Path(tempfile.mkdtemp(prefix="siteplan-agent-"))
    else:
        scratch = Path(scratch)
        scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        policy = sandbox.Policy.for_agent(workspace, target, scratch, endpoint)
        sandbox.preflight(policy)
        if settings is not None:
            settings.write(policy.scratch)
        record = Record.create(target)
        record.launcher("launch", workspace=str(workspace), out=str(target), agent=agent,
                        debug=debug, endpoint_given=endpoint,
                        endpoint=policy.endpoint.url if policy.endpoint else None,
                        settings=settings.to_json() if settings else None,
                        scratch=str(policy.scratch))
        shown = View(view)
        shown.say(f"Agent run {record.folder.name}"
                  + (f": {settings.model_id} at {policy.endpoint.url}"
                     if settings and policy.endpoint else "")
                  + ". Ctrl-C stops it.")
        host_argv = [sys.executable, "-I", "-m", SERVER, "--workspace", str(workspace),
                     "--out", str(target), *(["--debug"] if debug else [])]
        return _run(host_argv, agent, list(agent_args), policy, env, timeout, record, shown)
    finally:
        if made:
            shutil.rmtree(scratch, ignore_errors=True)


LIMITS = {f.name: (float if f.type == "float" else int) for f in fields(Limits)}


def _settings(args: argparse.Namespace) -> tuple[str | None, Settings | None]:
    """The endpoint and, for the model loop, its settings: from the arguments, then the
    configuration file, then the defaults. ValueError or OSError says what is wrong."""
    config = load_config(Path(args.config)) if args.config else {}
    endpoint = args.model_endpoint or config.get("model_endpoint")
    if args.agent != LOOP:
        return endpoint, None
    if not endpoint:
        raise ValueError("The model loop needs --model-endpoint (or model_endpoint in --config).")
    brief = Path(args.brief_file).read_text(encoding="utf-8") if args.brief_file else args.brief
    given = {name: getattr(args, name) for name in LIMITS if getattr(args, name) is not None}
    return endpoint, Settings.build(config, brief or "", model_id=args.model_id, limits=given)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="siteplan-agent", description="Starts the tools host and the sandboxed agent, joined "
                                           "only by the MCP stream, and keeps the run's record.")
    parser.add_argument("--workspace", required=True, help="The folder the tools read")
    parser.add_argument("--out", required=True,
                        help="The folder runs, exports and the agent's record are written to")
    parser.add_argument("--agent", default=LOOP,
                        help=f"The agent's module, run in the sandbox (default {LOOP}, the model "
                             "loop; siteplan.agent.standin is the scripted stand-in)")
    parser.add_argument("--debug", action="store_true",
                        help="The host allows the firm's finished plans (DEBUG RUN)")
    parser.add_argument("--model-endpoint",
                        help="The model server's OpenAI-compatible URL on this machine, e.g. "
                             "http://127.0.0.1:8000/v1 (a server elsewhere is reached through an "
                             "SSH tunnel to a local port); without one the agent has no network")
    parser.add_argument("--model-id", help="The model's name on that server")
    brief = parser.add_mutually_exclusive_group()
    brief.add_argument("--brief", help="The architect's brief, naming the survey and project "
                                       "files in the workspace")
    brief.add_argument("--brief-file", help="A file holding the brief")
    parser.add_argument("--config", help="A JSON file with model_endpoint, model_id, "
                                         "request_options and limits; arguments win over it")
    for name, kind in LIMITS.items():
        parser.add_argument("--" + name.replace("_", "-"), dest=name, type=kind,
                            help=f"Limit: {MEANING[name]} (default {getattr(Limits(), name)})")
    parser.add_argument("--scratch", help="The agent's scratch folder, kept afterwards")
    parser.add_argument("agent_args", nargs=argparse.REMAINDER,
                        help="Arguments for the agent, after --")
    args = parser.parse_args(argv)
    extra = args.agent_args[1:] if args.agent_args[:1] == ["--"] else args.agent_args
    try:
        endpoint, settings = _settings(args)
    except (OSError, ValueError) as error:
        print(f"Not started: {error}", file=sys.stderr)
        return 2
    try:
        done = launch(Path(args.workspace), Path(args.out), args.agent, extra, debug=args.debug,
                      endpoint=endpoint, scratch=Path(args.scratch) if args.scratch else None,
                      settings=settings, view=sys.stdout)
    except (sandbox.SandboxUnavailable, ValueError) as error:
        print(f"Not started: {error}", file=sys.stderr)
        return 2
    if done.signal:
        return 128 + done.signal
    return done.agent or done.host


if __name__ == "__main__":
    sys.exit(main())
