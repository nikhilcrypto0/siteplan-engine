"""A scripted OpenAI-compatible chat-completions server on 127.0.0.1, for the agent loop's tests.

    with FakeModel([act(call("open_project", {...})), say("Done.")]) as model:
        launch(..., endpoint=model.url, ...)

Each POST to /v1/chat/completions gets the next step of the script. A step is a function of the
request's body that returns the reply: a chat completion whose message says something (`say`) or
calls tools (`act`), an HTTP error (`status`), raw bytes (`raw`), or any of them late (`late`);
`respond` builds the step from the request, as a model reading its tool results would. The server
keeps every request's exact bytes and every reply it sent; a request past the end of the script is
answered 500, so a script that runs short fails loudly. No real model is contacted.
"""

from __future__ import annotations

import itertools
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PATH = "/v1/chat/completions"
SCRIPT_ENDED = b'{"error": "the script has no more steps"}'
_ids = itertools.count(1)


@dataclass(frozen=True)
class Reply:
    status: int
    data: bytes
    delay_s: float = 0.0


Step = Callable[[dict], Reply]


def completion(message: dict, finish_reason: str) -> bytes:
    return json.dumps({"id": "chatcmpl-fake", "object": "chat.completion", "created": 0,
                       "model": "fake-model",
                       "choices": [{"index": 0, "message": message,
                                    "finish_reason": finish_reason}],
                       "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                                 "total_tokens": 0}}).encode()


def call(name: str, arguments: dict | str) -> dict:
    """A tool call as a model server sends it: the arguments as a JSON string."""
    return {"id": f"call-{next(_ids)}", "type": "function",
            "function": {"name": name, "arguments": arguments if isinstance(arguments, str)
                         else json.dumps(arguments)}}


def say(text: str) -> Step:
    return lambda body: Reply(200, completion({"role": "assistant", "content": text}, "stop"))


def act(*calls: dict, content: str | None = None) -> Step:
    message = {"role": "assistant", "content": content, "tool_calls": list(calls)}
    return lambda body: Reply(200, completion(message, "tool_calls"))


def respond(build: Callable[[dict], Step]) -> Step:
    return lambda body: build(body)(body)


def status(code: int, text: bytes = b"") -> Step:
    return lambda body: Reply(code, text)


def raw(data: bytes) -> Step:
    return lambda body: Reply(200, data)


def late(seconds: float, step: Step) -> Step:
    return lambda body: replace(step(body), delay_s=seconds)


def results(body: dict) -> list[dict]:
    """The tool results in the conversation so far, as the model was sent them, parsed."""
    return [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]


class FakeModel:
    def __init__(self, steps: list[Step],
                 on_request: Callable[[int], None] | None = None) -> None:
        self.steps = list(steps)
        self.requests: list[bytes] = []  # each request's body, exactly as received
        self.replies: list[Reply] = []
        self.errors: list[str] = []  # a step that raised: the test's own mistake
        self.release = threading.Event()  # set at the end: a late reply stops waiting
        self._on_request = on_request
        self._lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self.server.daemon_threads = True

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def bodies(self) -> list[dict]:
        return [json.loads(data) for data in self.requests]

    def __enter__(self) -> FakeModel:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()

    def answer(self, path: str, data: bytes) -> Reply:
        with self._lock:
            index = len(self.requests)
            self.requests.append(data)
        if self._on_request is not None:
            try:
                self._on_request(index)
            except Exception as error:
                self.errors.append(f"hook {index}: {type(error).__name__}: {error}")
        if path != PATH:
            reply = Reply(404, b"not found")
        elif index >= len(self.steps):
            reply = Reply(500, SCRIPT_ENDED)
        else:
            try:
                reply = self.steps[index](json.loads(data))
            except Exception as error:
                self.errors.append(f"step {index}: {type(error).__name__}: {error}")
                reply = Reply(500, b"the step failed")
        with self._lock:
            self.replies.append(reply)
        return reply


def _handler(model: FakeModel) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:
            pass

        def do_POST(self) -> None:
            data = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            reply = model.answer(self.path, data)
            if reply.delay_s:
                model.release.wait(reply.delay_s)
            try:
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply.data)))
                self.end_headers()
                self.wfile.write(reply.data)
            except OSError:
                pass  # the client stopped waiting

    return Handler
