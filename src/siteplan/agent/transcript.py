"""The run's record and the architect's view, kept by the launcher outside the sandbox.

    record = Record.create(out)          # <out>/agent/<run>/
    record.launcher("started", ...)      # what the launcher did
    record.agent(event)                  # an event the agent sent on its pipe
    record.mcp("agent->host", chunk)     # the MCP stream, as the launcher relayed it
    View(sys.stdout).show(event)         # the architect's terminal

`transcript.jsonl` holds, a JSON object per line, what the launcher did (source `launcher`),
every event the agent reported on its pipe (source `agent`: each model request and response,
tool call, tool result, refusal, the stop and its reason, with times) and the agent's own error
output (source `stderr`). `mcp.jsonl` holds every line of the MCP stream, each way, as the launcher
relayed it: the trusted side's own record of what the agent asked of the host and what came back,
which the agent cannot alter. Each line carries `seq` (one count across both files, so they merge
in order) and `at` (the launcher's clock, UTC). Both live in `out`, which the sandbox hides: the
agent can neither read nor write them. Each line is written and flushed as it arrives, so a run
that is stopped or killed keeps everything up to that moment.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

FOLDER = "agent"  # under out
TRANSCRIPT, MCP = "transcript.jsonl", "mcp.jsonl"
SHOWN_CHARS = 240  # how much of a tool call's arguments or an error the terminal shows
ASKS_THE_ARCHITECT = ("propose_layouts", "export_candidate")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _parsed(line: bytes) -> Any:
    text = line.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return {"unparsed": text}


class Record:
    """The run's folder and its two files; safe to write from several threads."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._lock = threading.Lock()
        self._seq = 0
        # backslashreplace: a lone surrogate in what a model wrote is kept as its JSON escape,
        # never an encoding error that would stop the record.
        self._files = {name: open(folder / name, "a", encoding="utf-8",  # noqa: SIM115
                                  errors="backslashreplace") for name in (TRANSCRIPT, MCP)}
        self._partial: dict[str, bytes] = {}  # per direction: a line not yet ended

    @classmethod
    def create(cls, out: Path) -> Record:
        run = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
        folder = Path(out) / FOLDER / run
        folder.mkdir(parents=True)
        return cls(folder)

    @property
    def transcript(self) -> Path:
        return self.folder / TRANSCRIPT

    def _write(self, name: str, head: dict, fields: dict) -> None:
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, "at": _now(), **head}
            entry.update((key, value) for key, value in fields.items() if key not in entry)
            handle = self._files[name]
            if not handle.closed:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
                handle.flush()

    def launcher(self, event: str, **fields: Any) -> None:
        self._write(TRANSCRIPT, {"source": "launcher", "event": event}, fields)

    def agent(self, line: bytes) -> dict:
        """One line from the agent's pipe, recorded as sent (an unreadable one as text)."""
        event = _parsed(line)
        event = event if isinstance(event, dict) else {"unparsed": event}
        self._write(TRANSCRIPT, {"source": "agent"}, event)
        return event

    def stderr(self, line: bytes) -> None:
        text = line.decode("utf-8", errors="replace").rstrip("\n")
        self._write(TRANSCRIPT, {"source": "stderr", "event": "stderr"}, {"text": text})

    def mcp(self, direction: str, chunk: bytes) -> None:
        """Bytes relayed one way; each line they complete is recorded."""
        with self._lock:
            *lines, rest = (self._partial.get(direction, b"") + chunk).split(b"\n")
            self._partial[direction] = rest
        for line in lines:
            self._write(MCP, {"direction": direction}, {"message": _parsed(line)})

    def close(self) -> None:
        for direction, rest in list(self._partial.items()):
            if rest:  # a line the stream ended in the middle of
                self._write(MCP, {"direction": direction},
                            {"message": _parsed(rest), "incomplete": True})
        with self._lock:
            for handle in self._files.values():
                handle.close()


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= SHOWN_CHARS else text[:SHOWN_CHARS] + " ..."


def _outcome(event: dict) -> str:
    """A tool result in a few words: ok and the result's status, or the error."""
    try:
        content = json.loads(event.get("content", ""))
    except ValueError:
        content = None
    if not isinstance(content, dict):  # cut for the model, so no longer whole JSON
        return "ok" if event.get("ok") else "refused"
    if not content.get("ok"):
        return f"refused: {_short(content.get('error', ''))}"
    result = content.get("result")
    status = result.get("status") if isinstance(result, dict) else None
    return f"ok, {status}" if isinstance(status, str) else "ok"


class View:
    """The architect's view of a run on the launcher's terminal: the model's messages, each tool
    call and what came of it, and why the run stopped. The detail stays in the record."""

    def __init__(self, stream: TextIO | None) -> None:
        self._stream = stream

    def say(self, text: str) -> None:
        if self._stream is not None:
            print(text, file=self._stream, flush=True)

    def show(self, event: dict) -> None:
        kind, name = event.get("event"), event.get("name", "")
        if kind == "assistant" and str(event.get("content") or "").strip():
            self.say(f"\nmodel: {str(event['content']).strip()}\n")
        elif kind == "tool_call":
            note = " (the approval page may open in your browser)" \
                if name in ASKS_THE_ARCHITECT else ""
            self.say(f"  -> {name} {_short(event.get('arguments', ''))}{note}")
        elif kind == "tool_refused":
            self.say(f"  <- {name}: refused by the loop: {_short(event.get('reason', ''))}")
        elif kind == "tool_result":
            cut = " (cut for the model)" if event.get("truncated") else ""
            self.say(f"  <- {name}: {_outcome(event)}{cut}")
        elif kind == "tool_error":
            self.say(f"  <- {name}: failed: {_short(event.get('error', ''))}")
        elif kind == "model_error":
            self.say(f"  model request failed ({event.get('kind')}): "
                     f"{_short(event.get('detail', ''))}")
        elif kind == "stop":
            self.say(f"\nStopped ({event.get('reason')}): {_short(event.get('detail', ''))}. "
                     f"{event.get('turns', 0)} turns, {event.get('tool_calls', 0)} tool calls, "
                     f"{float(event.get('elapsed_s') or 0):.0f} s.")
