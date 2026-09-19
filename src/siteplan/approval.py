"""Approval outside the chat: a page on this machine that only a person can answer.

MCP clients differ in whether they can put a question in front of the architect. Hermes
0.21's chat screen declines every form elicitation without showing it (its approval panel
is registered on another thread), and a harness whose model has a shell could answer a
prompt the model itself can reach.

So the decision is taken on a page served on 127.0.0.1, opened in the architect's browser,
behind a one-time token that never appears in the tool's reply. The model cannot see the
link or click the button. Anything other than a click on Approve, including a timeout, is
a no.
"""

from __future__ import annotations

import logging
import secrets
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("siteplan.approval")

MAX_FORM_BYTES = 4096
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Approve this layout request</title><style>
:root {{ color-scheme: light dark; }}
body {{ font: 16px/1.5 -apple-system, Helvetica, Arial, sans-serif; margin: 0;
  padding: 32px 16px; background: #fbfbf8; color: #1a1a1a; }}
main {{ max-width: 640px; margin: 0 auto; background: #fff; border: 1px solid #e3e3dd;
  border-radius: 10px; padding: 28px; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }}
p.who {{ color: #666; margin: 0 0 20px; font-size: 14px; }}
ul {{ list-style: none; padding: 0; margin: 0 0 24px; }}
li {{ padding: 8px 0; border-bottom: 1px solid #f0f0ea; }}
li.check {{ color: #a3410b; font-weight: 600; }}
button {{ font: inherit; font-weight: 600; padding: 12px 22px; border-radius: 8px;
  border: 1px solid transparent; cursor: pointer; }}
button.yes {{ background: #1f6f43; color: #fff; }}
button.no {{ background: #fff; color: #444; border-color: #ccc; margin-left: 10px; }}
</style></head><body><main>
<h1>{title}</h1>
<p class="who">Asked by the site-plan tools. Nothing is drawn unless you approve.</p>
<ul>{items}</ul>
<form method="post" action="{action}">
<input type="hidden" name="t" value="{token}">
<button class="yes" name="decision" value="approve" type="submit">Approve</button>
<button class="no" name="decision" value="reject" type="submit">Reject</button>
</form></main></body></html>"""
DONE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{word}</title><style>body {{ font: 16px/1.5 -apple-system, Helvetica, Arial, sans-serif;
margin: 0; padding: 64px 16px; text-align: center; background: #fbfbf8; color: #1a1a1a; }}
strong {{ font-size: 22px; }}</style></head><body>
<p><strong>{word}</strong></p><p>You can go back to the assistant.</p></body></html>"""


@dataclass
class Pending:
    title: str
    lines: list[str]
    token: str
    answered: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class ApprovalDesk:
    """Serves one approval page per request on 127.0.0.1, and waits for the click."""

    def __init__(self, open_page: Callable[[str], object] = webbrowser.open) -> None:
        self._open_page = open_page
        self._pending: dict[str, Pending] = {}
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    @property
    def port(self) -> int:
        return self._start().server_address[1]

    def _start(self) -> ThreadingHTTPServer:
        with self._lock:
            if self._server is None:
                self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
                threading.Thread(target=self._server.serve_forever, daemon=True).start()
                log.info("approval page listening on 127.0.0.1:%d", self._server.server_address[1])
            return self._server

    def close(self) -> None:
        with self._lock:
            if self._server is not None:
                self._server.shutdown()
                self._server = None

    def ask(self, title: str, lines: list[str], timeout: float) -> bool:
        """Open the page and block until someone clicks. A timeout is a no."""
        self._start()
        request_id, token = secrets.token_urlsafe(9), secrets.token_urlsafe(24)
        pending = Pending(title=title, lines=list(lines), token=token)
        self._pending[request_id] = pending
        url = f"http://127.0.0.1:{self.port}/a/{request_id}?t={token}"
        try:
            self._open_page(url)  # the link never goes back to the model
        except Exception as exc:  # a machine with no browser
            log.warning("could not open the approval page: %s", exc)
        log.info("waiting for the architect's decision on the approval page")
        answered = pending.answered.wait(timeout)
        self._pending.pop(request_id, None)
        if not answered:
            log.info("approval page timed out after %.0f s", timeout)
        return answered and pending.approved

    def _lookup(self, path: str, token: str | None) -> Pending | None:
        pending = self._pending.get(path.rsplit("/", 1)[-1])
        if pending is None or not token or not secrets.compare_digest(token, pending.token):
            return None
        return pending


def _handler(desk: ApprovalDesk) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # keep the server's stdout clean
            pass

        def _send(self, status: int, body: str) -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            token = parse_qs(url.query).get("t", [None])[0]
            pending = desk._lookup(url.path, token)
            if pending is None:
                return self._send(404, DONE.format(word="This request is no longer open."))
            items = "".join(
                f'<li class="{"check" if line.startswith("CHECK") else ""}">{escape(line)}</li>'
                for line in pending.lines
            )
            self._send(200, PAGE.format(title=escape(pending.title), items=items,
                                        action=escape(url.path), token=escape(pending.token)))

        def do_POST(self) -> None:
            length = min(int(self.headers.get("Content-Length") or 0), MAX_FORM_BYTES)
            form = parse_qs(self.rfile.read(length).decode(errors="replace"))
            pending = desk._lookup(urlparse(self.path).path, form.get("t", [None])[0])
            if pending is None:
                return self._send(404, DONE.format(word="This request is no longer open."))
            pending.approved = form.get("decision", [""])[0] == "approve"
            pending.answered.set()
            log.info("approval page answer: %s", "approve" if pending.approved else "reject")
            self._send(200, DONE.format(word="Approved." if pending.approved else "Rejected."))

    return Handler
