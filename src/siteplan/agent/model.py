"""The model's server, as the loop reaches it: an OpenAI-compatible chat-completions client.

    async with Chat(endpoint, model_id, request_options, timeout_s, max_bytes) as chat:
        payload = chat.payload(messages, tools)  # the exact bytes sent, for the record
        answer = await chat.complete(payload)    # Answer, or ModelError

One POST to `{endpoint}/chat/completions` per call, with `model`, `messages` and `tools` and any
extra request options the configuration gives (SGLang, vLLM and the OpenAI API all take this
shape). httpx with `trust_env=False`: no proxy, `.netrc` or certificate setting is taken from the
environment, which inside the sandbox is bare anyway, and redirects are not followed. The endpoint
is the one port the sandbox opens on this machine.

A request has `timeout_s` from the first byte sent to the last byte read, whatever the server
does in between; a body over `max_bytes` is not read further, and the run cannot use it. Nothing is
retried here: the loop decides, and only a model request is ever retried, never a tool call.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import anyio
import httpx

CONNECT_TIMEOUT_S = 10.0  # a server on this machine answers a connection at once, or never
CHUNK_BYTES = 65_536
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
CUT = "\n[CUT by the agent loop: the response was longer than {limit:,} bytes]"


class ModelError(Exception):
    """A request that brought no usable answer: `kind` is connection, timeout, http_status,
    too_large, malformed or transport. `body` is what was read of the response, whole (it is
    never longer than the limit), with a marker where it was cut."""

    def __init__(self, kind: str, detail: str, *, status: int | None = None, body: str = "",
                 elapsed_s: float = 0.0) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail, self.status = kind, detail, status
        self.body, self.elapsed_s = body, elapsed_s


@dataclass(frozen=True)
class Answer:
    body: dict[str, Any]  # the server's whole answer, parsed
    message: dict[str, Any]  # its first choice's message
    finish_reason: str | None
    status: int
    size: int  # bytes read
    sha256: str  # of the bytes read
    elapsed_s: float


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def parse(data: bytes, status: int, elapsed_s: float) -> Answer:
    """The answer in a 200 response's body; ModelError when it is not a chat completion."""
    try:
        body = json.loads(data)
    except ValueError:
        raise ModelError("malformed", "the response is not JSON", status=status,
                         body=_text(data), elapsed_s=elapsed_s) from None
    choices = body.get("choices") if isinstance(body, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        raise ModelError("malformed", "the response has no choices[0].message", status=status,
                         body=_text(data), elapsed_s=elapsed_s)
    reason = first.get("finish_reason")
    return Answer(body, message, reason if isinstance(reason, str) else None, status, len(data),
                  hashlib.sha256(data).hexdigest(), elapsed_s)


class Chat:
    def __init__(self, endpoint: str, model_id: str, request_options: dict[str, Any],
                 timeout_s: float, max_bytes: int) -> None:
        self.url = endpoint.rstrip("/") + "/chat/completions"
        self._model, self._options = model_id, dict(request_options)
        self._timeout_s, self._max_bytes = timeout_s, max_bytes
        self._http = httpx.AsyncClient(
            trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(timeout_s, connect=min(CONNECT_TIMEOUT_S, timeout_s)))

    async def __aenter__(self) -> Chat:
        return self

    async def __aexit__(self, *exc) -> None:
        with anyio.CancelScope(shield=True):
            await self._http.aclose()

    def payload(self, messages: list[dict], tools: list[dict]) -> bytes:
        """The request's body, exactly as it is sent. A lone surrogate a model once sent (as
        "\\ud83d") goes back as the same JSON escape, never as an encoding error."""
        body = {**self._options, "model": self._model, "messages": messages, "tools": tools}
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        return text.encode("utf-8", errors="backslashreplace")

    async def complete(self, payload: bytes) -> Answer:
        started = time.monotonic()
        try:
            with anyio.fail_after(self._timeout_s):
                async with self._http.stream("POST", self.url, content=payload,
                                             headers=HEADERS) as response:
                    data = await self._read(response, started)
        except TimeoutError:
            raise ModelError("timeout", f"no whole answer within {self._timeout_s:g} s",
                             elapsed_s=time.monotonic() - started) from None
        except httpx.TimeoutException as error:
            raise ModelError("timeout", f"{type(error).__name__}: {error}",
                             elapsed_s=time.monotonic() - started) from None
        except httpx.ConnectError as error:
            raise ModelError("connection", f"{error}",
                             elapsed_s=time.monotonic() - started) from None
        except httpx.HTTPError as error:
            raise ModelError("transport", f"{type(error).__name__}: {error}",
                             elapsed_s=time.monotonic() - started) from None
        elapsed = time.monotonic() - started
        if response.status_code != 200:
            raise ModelError("http_status", f"HTTP {response.status_code}",
                             status=response.status_code, body=_text(data), elapsed_s=elapsed)
        return parse(data, response.status_code, elapsed)

    async def _read(self, response: httpx.Response, started: float) -> bytes:
        chunks, size = [], 0
        async for chunk in response.aiter_bytes(CHUNK_BYTES):
            size += len(chunk)
            chunks.append(chunk)
            if size > self._max_bytes:
                kept = b"".join(chunks)[:self._max_bytes]
                raise ModelError("too_large", f"the response passed {self._max_bytes:,} bytes "
                                              "and was not read further",
                                 status=response.status_code,
                                 body=_text(kept) + CUT.format(limit=self._max_bytes),
                                 elapsed_s=time.monotonic() - started)
        return b"".join(chunks)
