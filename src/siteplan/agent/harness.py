"""The model's side of the transport: an MCP client on the agent process's own stdin and stdout.

    async with connect() as tools:
        tools.offered  # the host's tools, exactly as it lists them
        reply = await tools.call("open_project", {"project_file": "site.project.json"})

This is everything a model is offered: the tools the host lists, as it lists them, and a way to
call them. The harness has no shell, file or network tool of its own, adds no tool, and answers
nothing on the architect's behalf: it declares no elicitation or sampling, and an approval is
asked on the page the host opens in the architect's browser, outside this stream. A call goes to
the host as the model made it; the host decides, and a tool it does not have or arguments its
request models refuse come back as an error in its own words.

Every line the host sends is kept (`received`): the record of what reached the model's side.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO

import anyio
from mcp import ClientSession, types
from mcp.shared.message import SessionMessage


@dataclass(frozen=True)
class Reply:
    ok: bool
    data: dict[str, Any] | None  # the host's answer, when ok
    error: str  # the host's words, when not


class Tools:
    """The host's tools, as offered to a model."""

    def __init__(self, session: ClientSession, listed: list[types.Tool], received: list[str]):
        self._session = session
        self.offered = [{"name": t.name, "description": t.description or "",
                         "input_schema": t.inputSchema, "output_schema": t.outputSchema}
                        for t in listed]
        self.received = received

    async def call(self, name: str, arguments: dict[str, Any]) -> Reply:
        result = await self._session.call_tool(name, arguments)
        text = "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))
        if result.isError:
            return Reply(False, None, text)
        return Reply(True, result.structuredContent, "")


def _own_stdio() -> tuple[BinaryIO, BinaryIO]:
    """This process's stdin and stdout for the stream; anything else printed goes to stderr."""
    writer = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    return sys.stdin.buffer, writer


def _pump(reader: BinaryIO, lines, token) -> None:
    """The host's lines into the session, on a daemon thread: a read still blocked when the
    session ends never holds the process open."""
    try:
        for line in iter(reader.readline, b""):
            anyio.from_thread.run(lines.send, line, token=token)
    except Exception:  # the session is over, or its event loop has gone
        pass
    finally:
        with contextlib.suppress(Exception):
            anyio.from_thread.run_sync(lines.close, token=token)


async def _read(reader: BinaryIO, to_session, received: list[str]) -> None:
    lines_in, lines = anyio.create_memory_object_stream(0)
    threading.Thread(target=_pump, args=(reader, lines_in, anyio.lowlevel.current_token()),
                     daemon=True).start()
    async with to_session, lines:
        async for line in lines:
            text = line.decode("utf-8", errors="replace")
            received.append(text)
            try:
                item = SessionMessage(types.JSONRPCMessage.model_validate_json(text))
            except ValueError as error:
                item = error
            try:
                await to_session.send(item)
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                return  # the session is over


def _send(writer: BinaryIO, data: bytes) -> None:
    writer.write(data)
    writer.flush()


async def _write(writer: BinaryIO, from_session) -> None:
    try:
        async with from_session:
            async for item in from_session:
                data = item.message.model_dump_json(by_alias=True, exclude_none=True) + "\n"
                await anyio.to_thread.run_sync(_send, writer, data.encode())
    except OSError:
        pass  # the host has gone
    finally:
        # The end of the stream, even when cancelled: the host then ends its session.
        with anyio.CancelScope(shield=True), contextlib.suppress(OSError):
            await anyio.to_thread.run_sync(writer.close)


@asynccontextmanager
async def connect(reader: BinaryIO | None = None,
                  writer: BinaryIO | None = None) -> AsyncIterator[Tools]:
    """The session with the host over `reader` and `writer` (by default this process's stdin and
    stdout), initialised and with the host's tools listed."""
    if reader is None or writer is None:
        reader, writer = _own_stdio()
    received: list[str] = []
    to_session, incoming = anyio.create_memory_object_stream(0)
    outgoing, from_session = anyio.create_memory_object_stream(0)
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(_read, reader, to_session, received)
        tasks.start_soon(_write, writer, from_session)
        try:
            async with ClientSession(incoming, outgoing) as session:
                await session.initialize()
                listed = await session.list_tools()
                yield Tools(session, listed.tools, received)
        finally:
            tasks.cancel_scope.cancel()
