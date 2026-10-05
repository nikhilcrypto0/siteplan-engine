"""Starts the tools host and the sandboxed model process, joined only by the MCP stream.

    python -m siteplan.agent.launch --workspace <dir> --out <dir> --agent <module> [--debug]
        [--model-endpoint http://127.0.0.1:8000/v1] [--scratch <dir>] [-- <agent arguments>]

The host (siteplan.agent.server, the command `siteplan-agent-tools`) is the trusted process: it
runs as the architect, reads the workspace, writes `out` and opens the approval page in the
architect's browser. The agent, the process that calls the model, runs in the sandbox
(sandbox.py) with a bare environment and a private scratch folder: its stdin is the host's stdout
and its stdout the host's stdin, so the MCP stream is its one way to the engine. The sandbox is
tried before the host starts (sandbox.preflight); if it cannot be applied nothing starts, and
there is no unsandboxed way to run an agent.

The only agent today is siteplan.agent.standin, the scripted stand-in; no model is connected.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from siteplan.agent import sandbox

SERVER = "siteplan.agent.server"
HOST_GRACE_S = 30.0  # how long the host has to finish once the agent has gone
STOP_GRACE_S = 5.0  # between asking a process to stop and killing it


@dataclass(frozen=True)
class Launched:
    agent: int  # the agent's exit status
    host: int  # the host's


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(STOP_GRACE_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def launch(workspace: Path, out: Path, agent: str, agent_args: Sequence[str] = (), *,
           debug: bool = False, endpoint: str | None = None, scratch: Path | None = None,
           env: Mapping[str, str] | None = None, timeout: float | None = None) -> Launched:
    """Run `agent` (a module) in the sandbox against the host on `workspace` and `out`. A scratch
    folder made here is removed afterwards; one given is kept. `env` is the host's environment
    (by default this process's); the agent's is the sandbox's own. Raises SandboxUnavailable,
    having started nothing, when the sandbox cannot be applied."""
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError(f"The workspace {workspace} is not a folder.")
    made = scratch is None
    if made:
        scratch = Path(tempfile.mkdtemp(prefix="siteplan-agent-"))
    else:
        scratch = Path(scratch)
        scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        policy = sandbox.Policy.for_agent(workspace, Path(out), scratch, endpoint)
        sandbox.preflight(policy)
        argv = sandbox.command(policy, sandbox.agent_argv(policy, agent, list(agent_args)))
        host_argv = [sys.executable, "-I", "-m", SERVER, "--workspace", str(workspace),
                     "--out", str(Path(out).resolve()), *(["--debug"] if debug else [])]
        return _run(host_argv, argv, policy, env, timeout)
    finally:
        if made:
            shutil.rmtree(scratch, ignore_errors=True)


def _run(host_argv: list[str], agent_argv: list[str], policy: sandbox.Policy,
         env: Mapping[str, str] | None, timeout: float | None) -> Launched:
    to_host, to_agent = os.pipe(), os.pipe()  # (read end, write end) each
    host = agent = None
    try:
        host = subprocess.Popen(host_argv, stdin=to_host[0], stdout=to_agent[1],
                                env=dict(env) if env is not None else None)
        agent = subprocess.Popen(agent_argv, stdin=to_agent[0], stdout=to_host[1],
                                 env=sandbox.environment(policy), cwd=policy.scratch)
    except BaseException:
        _stop(host)
        raise
    finally:  # each end now belongs to one child only, so either one's exit ends the stream
        for fd in (*to_host, *to_agent):
            os.close(fd)
    try:
        agent_status = agent.wait(timeout)
    except BaseException:  # a timeout, or the person pressing Ctrl-C
        _stop(agent)
        _stop(host)
        raise
    try:
        host_status = host.wait(HOST_GRACE_S)
    except subprocess.TimeoutExpired:
        _stop(host)
        host_status = host.wait()
    return Launched(agent_status, host_status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m siteplan.agent.launch",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True, help="The folder the tools read")
    parser.add_argument("--out", required=True, help="The folder runs are written to")
    parser.add_argument("--agent", required=True,
                        help="The agent's module, run in the sandbox (siteplan.agent.standin)")
    parser.add_argument("--debug", action="store_true",
                        help="The host allows the firm's finished plans (DEBUG RUN)")
    parser.add_argument("--model-endpoint",
                        help="The model server's URL on this machine; without one the agent has "
                             "no network")
    parser.add_argument("--scratch", help="The agent's scratch folder, kept afterwards")
    parser.add_argument("agent_args", nargs=argparse.REMAINDER,
                        help="Arguments for the agent, after --")
    args = parser.parse_args(argv)
    extra = args.agent_args[1:] if args.agent_args[:1] == ["--"] else args.agent_args
    try:
        done = launch(Path(args.workspace), Path(args.out), args.agent, extra, debug=args.debug,
                      endpoint=args.model_endpoint,
                      scratch=Path(args.scratch) if args.scratch else None)
    except sandbox.SandboxUnavailable as error:
        print(f"Not started: {error}", file=sys.stderr)
        return 2
    return done.agent or done.host


if __name__ == "__main__":
    sys.exit(main())
