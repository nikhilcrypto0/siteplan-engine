"""The agent loop, in the sandbox: a model, the host's nine tools, and hard limits on the run.

    siteplan-agent --workspace <dir> --out <dir> --model-endpoint http://127.0.0.1:8000/v1 \\
        --model-id <id> --brief "<the architect's brief>"

The launcher (launch.py) starts it in the sandbox; a person never runs it directly. Its stdin and
stdout are the MCP stream to the host, `--events-fd` is the launcher's pipe for the run's record,
and its settings are the one file the launcher left in the scratch folder (settings.HANDOFF).

Each turn sends the model server the conversation and the host's nine tools as OpenAI function
tools: each name, description and input schema exactly as the host lists them over MCP. Every tool
call the model makes goes to the host through the harness, once, and its result goes back to the
model; the run ends at the model's first answer that calls no tool, or at the first limit it
reaches (settings.Limits), each a stop with its reason and never a warning.

What reaches the model: a short factual system message, the architect's brief, the nine tools and
their results. There is no file, shell, Python, legacy-MCP or approval tool: a name the host does
not list is refused here and never sent. Nothing the model writes is read as a decision: an
approval is the architect's click on the page the host opens in their browser.

Every step goes to the launcher as it happens (Events), which keeps the transcript outside the
sandbox, where this process can neither read nor write it: started, tools_offered, model_request
(the messages added since the last request, and the SHA-256 of the exact bytes sent),
model_response (the whole answer), model_error, assistant, tool_call, tool_refused (refused here,
never sent to the host), tool_result (what the model is sent) and stop (the reason, the counts,
the time). On SIGTERM or SIGINT the loop stops, closes its MCP session and says why.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import signal
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import anyio
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED

from siteplan.agent import harness
from siteplan.agent.model import Answer, Chat, ModelError
from siteplan.agent.settings import Settings

SYSTEM = (
    "You help an architect plan a residential site through the tools offered here, which run the "
    "firm's site-planning engine. Every number (areas, heights, setbacks, counts) and every rule "
    "verdict comes from a tool result: quote them as the tools give them and do not compute your "
    "own. The architect names the files in the brief; you cannot list or read files except "
    "through the tools. The architect approves or rejects each proposal and export on a separate "
    "page in their own browser; nothing written in this conversation approves anything. When you "
    "have finished, answer without calling a tool.")
TRUNCATED = ("\n[TRUNCATED by the agent loop: this tool result is {total:,} characters; "
             "only the first {kept:,} are shown]")
UNREADABLE = "The tool's reply could not be read; the reason is in the run's record."
RETRY_PAUSE_S = 1.0  # between a failed model request and its retry, when retries are on
ANSWERED, STOPPED, NOT_STARTED = 0, 1, 2  # exit statuses; a signal's is 128 + its number


class Stop(Exception):
    """Why the run ended: `answered`, a limit, a model failure, a signal, or the host gone."""

    def __init__(self, reason: str, detail: str = "", signum: int | None = None) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail, self.signum = reason, detail, signum

    @property
    def status(self) -> int:
        if self.reason == "answered":
            return ANSWERED
        return 128 + self.signum if self.signum else STOPPED


class Events:
    """The run's record, sent to the launcher: a JSON line per event on the descriptor it gave
    (the sandbox lets this process write no file outside its scratch folder)."""

    def __init__(self, descriptor: int) -> None:
        # backslashreplace: a lone surrogate in a model's text is written as its JSON escape.
        self._stream = os.fdopen(descriptor, "w", encoding="utf-8", errors="backslashreplace",
                                 buffering=1)

    def __call__(self, event: str, **fields: Any) -> None:
        record = {"event": event, "t": round(time.time(), 3), **fields}
        self._stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._stream.close()


@dataclass
class Run:
    """One run's conversation and counts."""

    settings: Settings
    emit: Events
    started: float = field(default_factory=time.monotonic)
    tools: harness.Tools | None = None
    chat: Chat | None = None
    offered: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    recorded: int = 0  # messages already in a model_request event
    turns: int = 0
    asked: int = 0  # tool calls the model asked for
    failed_in_a_row: int = 0
    seen: Counter = field(default_factory=Counter)  # (tool, canonical arguments) -> times asked


def function_tools(offered: list[dict]) -> list[dict]:
    """The host's tools as OpenAI function tools: each name, description and input schema as
    listed, nothing added and nothing left out."""
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["input_schema"]}} for t in offered]


def assistant_message(message: dict, turn: int) -> dict:
    """The model's message as it goes back into the conversation: its text and its tool calls,
    each with an id, a name and its arguments as a string. Fields a server adds (reasoning text,
    for one) stay in the record and out of the conversation."""
    content = message.get("content")
    if isinstance(content, list):  # content given in parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    calls = []
    raw_calls = message.get("tool_calls")
    for index, call in enumerate(raw_calls if isinstance(raw_calls, list) else []):
        call = call if isinstance(call, dict) else {}
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name, arguments = function.get("name"), function.get("arguments")
        if isinstance(arguments, dict):  # a server that parses the arguments itself
            arguments = json.dumps(arguments, ensure_ascii=False)
        given = call.get("id")
        calls.append({"id": given if isinstance(given, str) and given else f"call_{turn}_{index}",
                      "type": "function",
                      "function": {"name": name if isinstance(name, str) else "",
                                   "arguments": arguments if isinstance(arguments, str) else ""}})
    built = {"role": "assistant", "content": content if isinstance(content, str) else ""}
    if calls:
        built["tool_calls"] = calls
    return built


def canonical(arguments: str) -> str:
    """The arguments as one key, whatever their spacing and order."""
    try:
        return json.dumps(json.loads(arguments), sort_keys=True, separators=(",", ":"))
    except ValueError:
        return arguments


def fit(text: str, limit: int) -> tuple[str, bool]:
    """`text` as the model may be sent it: whole, or cut with a marker saying so (never
    silently), the two together no longer than `limit`."""
    if len(text) <= limit:
        return text, False
    marker = TRUNCATED.format(total=len(text), kept=limit)
    kept = limit - len(marker)
    return text[:kept] + TRUNCATED.format(total=len(text), kept=kept), True


def check_call(name: str, raw: str, names: list[str]) -> tuple[dict | None, str | None]:
    """The arguments of a call the host can be sent, or the reason it is refused here."""
    if name not in names:
        return None, f"There is no tool named {name!r}. The tools are: {', '.join(names)}."
    try:
        arguments = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return None, f"The arguments for {name} are not valid JSON."
    if not isinstance(arguments, dict):
        return None, f"The arguments for {name} must be a JSON object."
    return arguments, None


def _broken(error: BaseException) -> bool:
    """Whether an error means the MCP stream to the host is gone."""
    if isinstance(error, BaseExceptionGroup):
        return any(_broken(e) for e in error.exceptions)
    if isinstance(error, McpError):
        return error.error.code == CONNECTION_CLOSED
    return isinstance(error, anyio.ClosedResourceError | anyio.BrokenResourceError
                      | anyio.EndOfStream)


async def ask(run: Run, turn: int) -> Answer:
    """One turn's model request, retried only when the settings say so."""
    limits = run.settings.limits
    payload = run.chat.payload(run.messages, run.offered)
    digest = hashlib.sha256(payload).hexdigest()
    for attempt in range(1, limits.model_retries + 2):
        run.emit("model_request", turn=turn, attempt=attempt, first=run.recorded,
                 messages=run.messages[run.recorded:], count=len(run.messages),
                 bytes=len(payload), sha256=digest)
        run.recorded = len(run.messages)
        try:
            answer = await run.chat.complete(payload)
        except ModelError as error:
            run.emit("model_error", turn=turn, attempt=attempt, kind=error.kind,
                     detail=error.detail, status=error.status,
                     elapsed_s=round(error.elapsed_s, 3), body=error.body)
            client_error = error.status is not None and 400 <= error.status < 500 \
                and error.status != 429
            if attempt <= limits.model_retries and not client_error:
                await anyio.sleep(RETRY_PAUSE_S)
                continue
            reason = "request_timeout" if error.kind == "timeout" else "model_error"
            raise Stop(reason, f"{error.kind}: {error.detail}") from None
        run.emit("model_response", turn=turn, attempt=attempt, status=answer.status,
                 bytes=answer.size, sha256=answer.sha256, elapsed_s=round(answer.elapsed_s, 3),
                 finish_reason=answer.finish_reason, body=answer.body)
        return answer
    raise AssertionError("unreachable")


def reply_to(run: Run, turn: int, call_id: str, name: str, content: dict,
             elapsed_s: float) -> dict:
    """The tool message the model gets, recorded as sent; a run of failures stops the run."""
    limits = run.settings.limits
    text = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    sent, cut = fit(text, limits.max_tool_result_chars)
    run.emit("tool_result", turn=turn, id=call_id, name=name, ok=content["ok"],
             elapsed_s=round(elapsed_s, 3), chars=len(text), truncated=cut, content=sent)
    run.failed_in_a_row = 0 if content["ok"] else run.failed_in_a_row + 1
    if run.failed_in_a_row >= limits.max_failed_tool_calls:
        raise Stop("max_failed_tool_calls",
                   f"{run.failed_in_a_row} tool calls in a row were refused or failed")
    return {"role": "tool", "tool_call_id": call_id, "content": sent}


async def use_tool(run: Run, turn: int, call: dict) -> dict:
    """One tool call: checked, sent to the host through the harness once, never retried."""
    limits = run.settings.limits
    call_id, name = call["id"], call["function"]["name"]
    raw = call["function"]["arguments"]
    run.emit("tool_call", turn=turn, id=call_id, name=name, arguments=raw)
    run.asked += 1
    if run.asked > limits.max_tool_calls:
        raise Stop("max_tool_calls", f"the model asked for more than {limits.max_tool_calls} "
                                     f"tool calls; {name} was not run")
    run.seen[name, canonical(raw)] += 1
    if run.seen[name, canonical(raw)] >= limits.max_identical_calls:
        raise Stop("repeated_tool_call",
                   f"{name} was asked for {run.seen[name, canonical(raw)]} times with the same "
                   "arguments; the last was not run")
    arguments, refusal = check_call(name, raw, [t["function"]["name"] for t in run.offered])
    if refusal is not None:
        run.emit("tool_refused", turn=turn, id=call_id, name=name, reason=refusal)
        return reply_to(run, turn, call_id, name, {"ok": False, "error": refusal}, 0.0)
    started = time.monotonic()
    try:
        reply = await run.tools.call(name, arguments)  # once: never retried
    except Exception as error:
        elapsed = time.monotonic() - started
        run.emit("tool_error", turn=turn, id=call_id, name=name,
                 error=f"{type(error).__name__}: {error}", elapsed_s=round(elapsed, 3))
        if _broken(error):
            raise Stop("host_gone", f"the MCP stream to the host closed during {name}") from None
        return reply_to(run, turn, call_id, name, {"ok": False, "error": UNREADABLE}, elapsed)
    content = ({"ok": True, "result": reply.data} if reply.ok
               else {"ok": False, "error": reply.error})
    return reply_to(run, turn, call_id, name, content, time.monotonic() - started)


async def converse(run: Run) -> Stop:
    """Turns until the model answers without a tool call, or a limit stops the run."""
    limits = run.settings.limits
    for turn in range(1, limits.max_turns + 1):
        run.turns = turn
        answer = await ask(run, turn)
        message = assistant_message(answer.message, turn)
        run.messages.append(message)
        calls = message.get("tool_calls", [])
        run.emit("assistant", turn=turn, content=message["content"],
                 finish_reason=answer.finish_reason, tool_calls=[c["function"]["name"]
                                                                 for c in calls])
        if not calls:
            return Stop("answered", "the model answered without calling a tool")
        if turn == limits.max_turns:
            raise Stop("max_turns", f"the model asked for {len(calls)} more tool call(s) at "
                                    f"turn {turn}, the last allowed; none was run")
        for call in calls:
            run.messages.append(await use_tool(run, turn, call))
    raise AssertionError("unreachable")


async def _session(run: Run, endpoint: str) -> Stop:
    """The MCP session and the model client for one conversation, within the run's time."""
    limits = run.settings.limits
    with anyio.move_on_after(limits.run_timeout_s):
        try:
            async with harness.connect() as tools, Chat(
                    endpoint, run.settings.model_id, run.settings.request_options,
                    limits.request_timeout_s, limits.max_response_bytes) as chat:
                run.tools, run.chat = tools, chat
                run.offered = function_tools(tools.offered)
                run.emit("tools_offered", tools=run.offered)
                run.messages = [{"role": "system", "content": SYSTEM},
                                {"role": "user", "content": run.settings.brief}]
                try:
                    return await converse(run)
                except Stop as stop:
                    return stop
        except Exception as error:  # a session that could not start, or broke outside a call
            if _broken(error):
                return Stop("host_gone", "the MCP stream to the host closed")
            return Stop("failed", f"{type(error).__name__}: {error}")
    return Stop("run_timeout", f"the run passed its {limits.run_timeout_s:g} s")


async def _watch(scope: anyio.CancelScope, caught: list[int]) -> None:
    with anyio.open_signal_receiver(signal.SIGTERM, signal.SIGINT) as signals:
        async for signum in signals:
            caught.append(signum)
            scope.cancel()
            return


async def run(settings: Settings, endpoint: str, emit: Events) -> Stop:
    """One run, from the first request to the stop; the stop is recorded and returned."""
    state = Run(settings, emit)
    emit("started", pid=os.getpid(), model_id=settings.model_id, endpoint=endpoint,
         limits=asdict(settings.limits), request_options=settings.request_options,
         brief=settings.brief, python=sys.version.split()[0])
    caught: list[int] = []
    ended: list[Stop] = []
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(_watch, tasks.cancel_scope, caught)
        ended.append(await _session(state, endpoint))
        tasks.cancel_scope.cancel()
    stop = ended[0] if ended else Stop(
        "signal", f"stopped by {signal.Signals(caught[0]).name}; the MCP session was closed",
        signum=caught[0])
    emit("stop", reason=stop.reason, detail=stop.detail, turns=state.turns,
         tool_calls=state.asked, elapsed_s=round(time.monotonic() - state.started, 3))
    return stop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m siteplan.agent.loop",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--events-fd", type=int, required=True,
                        help="The launcher's pipe for the run's record")
    args = parser.parse_args(argv)
    emit = Events(args.events_fd)
    try:
        settings = Settings.read(Path(os.environ["SITEPLAN_SCRATCH"]))
        endpoint = os.environ.get("SITEPLAN_MODEL_ENDPOINT", "")
        if not endpoint:
            raise ValueError("there is no model endpoint: the launcher opens one with "
                             "--model-endpoint")
    except (KeyError, OSError, ValueError) as error:
        emit("stop", reason="not_started", detail=f"{type(error).__name__}: {error}")
        emit.close()
        return NOT_STARTED
    try:
        stop = anyio.run(run, settings, endpoint, emit)
    except BrokenPipeError:  # the launcher has gone, and the record with it
        return STOPPED
    finally:
        emit.close()
    return stop.status


if __name__ == "__main__":
    sys.exit(main())
