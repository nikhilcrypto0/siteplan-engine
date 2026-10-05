"""The model process's sandbox: the MCP stream to the host, and nothing else.

    policy = Policy.for_agent(workspace, out, scratch, endpoint=None)
    preflight(policy)  # runs the interpreter in the sandbox once; refuses unless it holds here
    argv = command(policy, agent_argv(policy, "siteplan.agent.standin"))

The policy, on every platform:
- writes: no file anywhere but the private scratch folder;
- reads: the interpreter, the virtual environment, and of siteplan only its marker and this
  package. Never the workspace or `out`: client data reaches the model only in tool results. Never
  the engine either, so neither the `siteplan` command line nor the legacy MCP server can be
  loaded, even in-process. A path is looked up (stat) only on the way to what may be read or
  written (`lookups`), so the process cannot even tell what exists anywhere else;
- exec: the agent's own interpreter only, so no shell, no `siteplan`, no `siteplan-mcp`;
- network: the model's endpoint on this machine when one is configured, else none.

macOS applies it with sandbox-exec and a Seatbelt profile written for the run (on top of Apple's
own `system.sb` baseline; the process may not fork at all). Linux applies it with bubblewrap,
which mounts only what may be read, so the workspace, `out`, the engine and every shell are not
there to reach (no seccomp filter is applied). Any other platform, a missing tool, or a policy
the platform's tool cannot express is refused with SandboxUnavailable, and a sandbox that starts
but does not hold when tried with SandboxLeak: the model process never runs unsandboxed.

Seatbelt reads a rule on one operation (file-read-data, file-read-metadata) before a rule on the
wildcard (file-read*), and a rule with a filter before one without, whatever their order. So
nothing the model may read is allowed to overlap the workspace or `out` (Policy.for_agent refuses
it), and the closing deny names the operations themselves as well as the wildcards.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
PACKAGE = Path(__file__).resolve().parent.parent  # siteplan: its marker and `agent` are readable
PREFLIGHT_TIMEOUT_S = 60.0  # starting an interpreter in the sandbox, once
# The system's libraries the interpreter loads on Linux: library folders only, never a bin folder.
LINUX_LIBRARIES = ("/usr/lib", "/usr/lib64", "/lib", "/lib64", "/etc/ld.so.cache")
LOOPBACK_NAME = "localhost"  # name lookups fail inside the sandbox, so the agent gets 127.0.0.1
MAX_LINKS = 40  # links followed on the way to the interpreter, as the kernel's own limit


class SandboxUnavailable(RuntimeError):
    """The sandbox cannot be applied here, so the model process is not started."""


class SandboxLeak(SandboxUnavailable):
    """The sandbox started but did not hold: a fault in the policy, not a missing tool."""


@dataclass(frozen=True)
class Endpoint:
    """The model's server, on this machine: the URL the agent is given and the one port opened."""

    url: str
    port: int


@dataclass(frozen=True)
class Policy:
    interpreter: Path  # the agent's interpreter as invoked (the venv's), so the venv is found
    runtime: tuple[Path, ...]  # read-only: the interpreter's installation, the virtual env
    package: Path  # siteplan: only its marker and the agent package are readable
    scratch: Path  # the one folder the agent writes
    hidden: tuple[Path, ...]  # never read nor written: the workspace and out
    endpoint: Endpoint | None = None  # the one port opened, or no network at all

    @classmethod
    def for_agent(cls, workspace: Path, out: Path, scratch: Path,
                  endpoint: str | None = None) -> Policy:
        runtime = tuple(dict.fromkeys(Path(p).resolve() for p in (sys.base_prefix, sys.prefix)))
        policy = cls(interpreter=Path(sys.executable), runtime=runtime, package=PACKAGE,
                     scratch=Path(scratch).resolve(),
                     hidden=(Path(workspace).resolve(), Path(out).resolve()),
                     endpoint=_endpoint(endpoint))
        policy._keep_apart()
        return policy

    def _keep_apart(self) -> None:
        reached = (*self.runtime, self.package, self.scratch)
        for hidden in self.hidden:
            for path in reached:
                if hidden == path or hidden.is_relative_to(path) or path.is_relative_to(hidden):
                    raise SandboxUnavailable(
                        f"{hidden} and {path} overlap: the workspace and out must lie apart from "
                        "the interpreter, the virtual environment, the siteplan package and the "
                        "scratch folder, everything the model process may read or write.")


def _endpoint(url: str | None) -> Endpoint | None:
    if url is None:
        return None
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise SandboxUnavailable(f"The model endpoint {url!r} is not a URL.") from None
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host:
        raise SandboxUnavailable(f"The model endpoint {url!r} is not an http(s) URL.")
    try:
        loopback = host == LOOPBACK_NAME or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise SandboxUnavailable(
            f"The model endpoint {url!r} is not on this machine. The sandbox can open one port on "
            "localhost but cannot name another host: forward the model server's port to "
            "127.0.0.1 first (an SSH tunnel) and give that.")
    if host == LOOPBACK_NAME:  # by address: names are not looked up inside the sandbox
        userinfo, at, _ = parts.netloc.rpartition("@")
        address = "127.0.0.1" + (f":{parts.port}" if parts.port else "")
        url = parts._replace(netloc=f"{userinfo}{at}{address}").geturl()
    return Endpoint(url, port)


def agent_argv(policy: Policy, module: str, args: tuple[str, ...] | list[str] = ()) -> list[str]:
    """The agent's command, before the sandbox: its interpreter, isolated from the environment's
    Python settings and writing no bytecode, running `module`."""
    return [str(policy.interpreter), "-I", "-B", "-m", module, *args]


def environment(policy: Policy) -> dict[str, str]:
    """The agent's whole environment: nothing of the person's (no keys, no tokens)."""
    env = {"HOME": str(policy.scratch), "TMPDIR": str(policy.scratch), "PATH": "/usr/bin:/bin",
           "SITEPLAN_SCRATCH": str(policy.scratch)}
    if policy.endpoint is not None:
        env["SITEPLAN_MODEL_ENDPOINT"] = policy.endpoint.url
    return env


def command(policy: Policy, argv: list[str], platform: str | None = None) -> list[str]:
    """`argv` run inside the sandbox; SandboxUnavailable when this platform has none to apply."""
    platform = platform or sys.platform
    if platform == "darwin":
        if not os.access(SANDBOX_EXEC, os.X_OK):
            raise SandboxUnavailable(f"{SANDBOX_EXEC} is not on this Mac, so the model process "
                                     "cannot be sandboxed.")
        return [SANDBOX_EXEC, "-p", seatbelt_profile(policy), *argv]
    if platform.startswith("linux"):
        bwrap = shutil.which("bwrap")
        if bwrap is None:
            raise SandboxUnavailable("bubblewrap (bwrap) is not installed, so the model process "
                                     "cannot be sandboxed.")
        return [*bwrap_args(policy, bwrap), *argv]
    raise SandboxUnavailable(f"There is no sandbox for this platform ({platform}), so the model "
                             "process is not started.")


def _quoted(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _filters(kind: str, paths) -> str:
    return " ".join(f"({kind} {_quoted(p)})" for p in paths)


def lookups(policy: Policy) -> str:
    """Where the agent may look a path up without reading it: each folder on the way to what it
    may read or write (a lookup stats every one, and Python resolves its own paths), and each
    link on the way to its interpreter (the venv's is a chain of them). Nothing else: not the
    person's home or another project, not the engine's own files. Inside what it may read,
    `file-read*` already allows the lookups."""
    links = [link for link, _ in _links(policy.interpreter)]
    ways = dict.fromkeys([*policy.runtime, policy.package, policy.scratch, *links,
                          Path(os.path.realpath(policy.interpreter))])
    filters = [_filters("path-ancestors", ways), *([_filters("literal", links)] if links else [])]
    return f"(allow file-read-metadata {' '.join(filters)})"


def seatbelt_profile(policy: Policy) -> str:
    package, executables = policy.package, dict.fromkeys(
        [str(policy.interpreter), os.path.realpath(policy.interpreter)])
    rules = [
        "(version 1)",
        "(deny default)",
        # Apple's baseline for any process: dyld and the shared cache, the system's libraries
        # and frameworks, the standard devices, a few system services.
        '(import "system.sb")',
        # Looking a path up stats each folder on the way to it: only those folders, and the
        # links to the interpreter (lookups). The workspace and out are taken back at the end.
        lookups(policy),
        f"(allow process-exec {_filters('literal', executables)})",
        f"(allow file-read* file-map-executable {_filters('subpath', policy.runtime)})",
        # Of siteplan, its marker and this package only, wherever it is installed.
        f"(deny file-read* {_filters('subpath', [package])})",
        f"(allow file-read* {_filters('literal', [package.parent, package])} "
        f"{_filters('literal', [package / '__init__.py'])} "
        f"{_filters('subpath', [package / 'agent'])})",
        f"(allow file-read* file-write* {_filters('subpath', [policy.scratch])})",
        # system.sb lets a process create core files and write to syslog: not this one.
        '(deny file-write-create (subpath "/cores"))',
        '(deny network-outbound (literal "/private/var/run/syslog"))',
    ]
    if policy.endpoint is not None:
        rules.append(f'(allow network-outbound (remote tcp "localhost:{policy.endpoint.port}"))')
    rules.append("(deny file-read* file-read-data file-read-metadata file-read-xattr "
                 "file-test-existence file-write* file-write-data file-write-create "
                 f"file-write-unlink {_filters('subpath', policy.hidden)})")
    return "\n".join(rules) + "\n"


def bwrap_args(policy: Policy, bwrap: str) -> list[str]:
    """bubblewrap's arguments: a new root holding only what the agent may read, the scratch
    folder writable, no network. It cannot open one port and keep the rest closed, so an
    endpoint is refused rather than the whole network shared."""
    if policy.endpoint is not None:
        raise SandboxUnavailable(
            "bubblewrap cannot open the network to the model's port alone: the model process "
            "would reach every port on this machine. Until a forwarder into the sandbox is "
            "built, only an agent with no network runs on Linux.")
    real = Path(os.path.realpath(policy.interpreter))
    args = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
            "--proc", "/proc", "--dev", "/dev"]
    for library in LINUX_LIBRARIES:
        args += ["--ro-bind-try", library, library]
    for path in policy.runtime:  # libraries and the venv's marker; no bin folder, no scripts
        for part in ("lib", "pyvenv.cfg"):
            args += ["--ro-bind-try", str(path / part), str(path / part)]
    for link, target in _links(policy.interpreter):  # the venv finds its home through these
        args += ["--symlink", target, str(link)]
    args += ["--ro-bind", str(real), str(real)]  # the one program there is to run
    package = policy.package
    args += ["--tmpfs", str(package),
             "--ro-bind", str(package / "__init__.py"), str(package / "__init__.py"),
             "--ro-bind", str(package / "agent"), str(package / "agent"),
             "--bind", str(policy.scratch), str(policy.scratch), "--chdir", str(policy.scratch)]
    return args


def _links(path: Path) -> list[tuple[Path, str]]:
    """Each symbolic link met on the way to the file `path` names, its folders' included, with
    its target, so that a new root can recreate the way there."""
    links: list[tuple[Path, str]] = []
    pending = Path(os.path.abspath(path))
    for _ in range(MAX_LINKS):
        here = Path(pending.anchor)
        for index, part in enumerate(pending.parts[1:], start=1):
            here = here / part
            if here.is_symlink():
                target = os.readlink(here)
                links.append((here, target))
                pending = Path(os.path.normpath(here.parent / target)).joinpath(
                    *pending.parts[index + 1:])
                break
        else:
            return links
    raise SandboxUnavailable(f"Too many links on the way to {path}.")


LEAKED = 3  # the preflight's exit status when the sandbox started but did not hold
PREFLIGHT = f"""
import os, sys
import siteplan.agent
canary, scratch, *hidden = sys.argv[1:]
def leaked(what):
    print("the model process could " + what, file=sys.stderr)
    sys.exit({LEAKED})
for path in hidden:
    try:
        os.listdir(path)
    except (PermissionError, FileNotFoundError):
        continue
    leaked("read " + path)
try:
    open(os.path.join(canary, "written"), "x").close()
except (PermissionError, FileNotFoundError):
    pass
else:
    leaked("write outside its scratch folder")
probe = os.path.join(scratch, ".preflight")
open(probe, "w").close()
os.remove(probe)
"""


def preflight(policy: Policy, platform: str | None = None) -> None:
    """Start the interpreter in the sandbox once and check that the sandbox holds: the package is
    readable and the scratch writable, the workspace and out are not readable, and a folder
    outside the scratch is not writable. A sandbox that cannot start is SandboxUnavailable; one
    that starts and does not hold is SandboxLeak."""
    with tempfile.TemporaryDirectory(prefix="siteplan-canary-") as canary:
        argv = command(policy, [str(policy.interpreter), "-I", "-B", "-c", PREFLIGHT, canary,
                                str(policy.scratch), *map(str, policy.hidden)], platform)
        try:
            done = subprocess.run(argv, env=environment(policy), cwd=policy.scratch,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=PREFLIGHT_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SandboxUnavailable(f"The sandbox could not be started: {error}") from None
    if done.returncode == 0:
        return
    reason = (done.stderr.strip().splitlines() or [f"exit status {done.returncode}"])[-1]
    if done.returncode == LEAKED:
        raise SandboxLeak(f"The sandbox did not hold, so the model process is not started: "
                          f"{reason}")
    raise SandboxUnavailable(f"The sandbox could not be applied, so the model process is not "
                             f"started: {reason}")
