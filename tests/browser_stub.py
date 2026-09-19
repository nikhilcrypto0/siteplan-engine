"""Stands in for the architect's browser: opens the approval link and clicks a button."""

import threading
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


def read_page(url: str) -> str:
    return urlopen(url, timeout=5).read().decode()


def answer(url: str, decision: str, token: str | None = None) -> int:
    """What the browser sends when the architect clicks Approve or Reject."""
    parsed = urlparse(url)
    token = token or parse_qs(parsed.query)["t"][0]
    body = urlencode({"t": token, "decision": decision}).encode()
    request = Request(f"http://{parsed.netloc}{parsed.path}", body)
    try:
        return urlopen(request, timeout=5).status
    except HTTPError as exc:
        return exc.code


def clicker(decision: str, token: str | None = None, seen: list | None = None):
    """An `open_page` that answers in the background, as a person would."""

    def open_page(url: str) -> None:
        if seen is not None:
            seen.append(url)
        threading.Thread(target=answer, args=(url, decision, token), daemon=True).start()

    return open_page
