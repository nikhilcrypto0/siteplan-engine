"""The model-facing transport: the ToolHost's nine operations as an MCP server on stdio.

    siteplan-agent-tools --workspace <dir> --out <dir> [--debug] [--log-file <file>]

MCP is the protocol agent harnesses speak, the project already depends on its SDK, and stdio
opens no network listener: the one way in is this process's stdin, which the launcher joins to
the sandboxed model process (launch.py). The SDK's low-level server is used so that the tools
listed are exactly `ToolHost.tools()` (each name, description, input and output schema) and a
call goes to `ToolHost.call` with its arguments as sent. The host's frozen request models are the
only check, so a refusal comes back as a tool error in the host's own safe words (the reason
stays in the log), never in the SDK's.

The server offers tools and nothing else: no prompts, no resources, and it never asks the client
anything (no elicitation, no sampling). An approval is asked on the page the host opens in the
architect's browser (PageApprover, the only channel ToolHost takes), never in this stream.

Calls run one at a time and off the event loop: an operation may wait minutes for the architect.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from io import TextIOWrapper
from pathlib import Path
from typing import BinaryIO

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from siteplan.service import Mode, PageApprover, ServiceError, ToolHost

log = logging.getLogger("siteplan.agent")

NAME = "siteplan-agent-tools"
FAILED = "The tool failed; the reason is in the host's log."


def _refused(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)],
                                isError=True)


def build_server(host: ToolHost) -> Server:
    """The MCP server: list_tools gives the host's tools, call_tool goes to the host."""
    tools = [types.Tool(name=t["name"], description=t["description"],
                        inputSchema=t["input_schema"], outputSchema=t["output_schema"])
             for t in host.tools()]
    server = Server(NAME)
    one_at_a_time = anyio.Lock()

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return tools

    # The host checks the arguments, so its words, not the SDK's, say what it refused.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> dict | types.CallToolResult:
        async with one_at_a_time:
            try:
                return await anyio.to_thread.run_sync(host.call, name, arguments)
            except ServiceError as error:  # its message is safe to show the caller
                return _refused(str(error))
            except Exception:
                log.exception("the call to %r failed outside the host", name)
                return _refused(FAILED)

    return server


async def _serve(server: Server, stream: BinaryIO) -> None:
    stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace"))
    stdout = anyio.wrap_file(TextIOWrapper(stream, encoding="utf-8"))
    async with stdio_server(stdin, stdout) as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=NAME, description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True,
                        help="The folder the tools read: the survey, the project files and the "
                             "firm's libraries")
    parser.add_argument("--out", required=True,
                        help="The folder runs and exports are written to, apart from the "
                             "workspace")
    parser.add_argument("--debug", action="store_true",
                        help="Allow the firm's finished plans; every output then says DEBUG RUN")
    parser.add_argument("--log-file",
                        help="Where refusals and failures are logged (default "
                             "<out>/logs/agent-tools.log); stdout carries the protocol")
    args = parser.parse_args(argv)
    approver = PageApprover()
    try:
        host = ToolHost(Path(args.workspace), Path(args.out), approver,
                        mode=Mode.DEBUG if args.debug else Mode.BLIND)
    except (TypeError, ValueError) as error:
        print(f"{NAME}: {error}", file=sys.stderr)
        return 2
    log_file = Path(args.log_file or Path(args.out) / "logs" / "agent-tools.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_file, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # The protocol keeps the real stdout. Anything else written there (a stray print, a child
    # process such as the browser) goes to stderr instead, never into the MCP stream.
    stream = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        anyio.run(_serve, build_server(host), stream)
    finally:
        approver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
