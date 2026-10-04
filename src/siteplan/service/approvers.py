"""The person channels a host gives the service to ask the architect (`service.Approver`).

The service asks before it runs a search and before it exports a candidate that rests on
something unresolved. The answer must come from the architect, never from whoever called the
operation, so the host picks one channel when it starts and the service never falls back to
another; a channel that cannot ask is a no (as the MCP server's two channels never fall back to
each other).

- `PageApprover`: the approval page (`approval.ApprovalDesk`) on 127.0.0.1, opened in the
  architect's browser behind a one-time token that never reaches the caller. Only a click on
  Approve is a yes; a rejection or a timeout is a no. The channel for any host a model drives,
  and the only one `host.ToolHost` takes.
- `TerminalApprover`: the question on the terminal the architect typed the command in. Only
  "y" or "yes" is a yes, and a terminal whose input is not interactive (piped in, a script, a
  job) is a no without asking. For the architect running `siteplan` by hand, never for a host
  whose terminal a model can type into.

Each says what came back (`decide`): APPROVED, REJECTED, or UNANSWERED when no person answered
(the page timed out, the terminal could not ask). The service writes that down in its approval
audit; `approve` is the same question answered yes or no, and only APPROVED is a yes.

No approver here says yes by itself; the tests play the person with their own.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from siteplan.approval import ApprovalDesk
from siteplan.service.models import Decision

log = logging.getLogger("siteplan.service")

PAGE_TIMEOUT_S = 300.0  # how long the architect has to answer the page: the MCP server's five
CHANNELS = ("page", "terminal")
YES = frozenset({"y", "yes"})
QUESTION = "Approve? Type yes to approve; anything else is a no: "


class PageApprover:
    """Asks on the approval page and waits for the architect's click."""

    def __init__(self, desk: ApprovalDesk | None = None,
                 timeout_s: float = PAGE_TIMEOUT_S) -> None:
        self._desk = desk or ApprovalDesk()
        self._timeout_s = timeout_s

    def decide(self, title: str, lines: list[str]) -> Decision:
        answer = self._desk.answer(title, list(lines), self._timeout_s)
        if answer is None:
            return Decision.UNANSWERED
        return Decision.APPROVED if answer is True else Decision.REJECTED

    def approve(self, title: str, lines: list[str]) -> bool:
        return self.decide(title, lines) is Decision.APPROVED

    def close(self) -> None:
        self._desk.close()


class TerminalApprover:
    """Asks on the architect's own terminal."""

    def __init__(self, ask: Callable[[str], str] | None = None,
                 show: Callable[[str], object] | None = None,
                 interactive: Callable[[], bool] | None = None) -> None:
        # The terminal is looked up when the question is put, not when the host starts.
        self._ask, self._show, self._interactive = ask, show, interactive

    def decide(self, title: str, lines: list[str]) -> Decision:
        if not (self._interactive or sys.stdin.isatty)():
            log.info("not asked: the terminal's input is not interactive, so no person answers")
            return Decision.UNANSWERED
        show = self._show or print
        show(f"\n{title}")
        for line in lines:
            show(f"  - {line}")
        try:
            answer = (self._ask or input)(QUESTION)
        except EOFError:
            return Decision.UNANSWERED
        return Decision.APPROVED if answer.strip().lower() in YES else Decision.REJECTED

    def approve(self, title: str, lines: list[str]) -> bool:
        return self.decide(title, lines) is Decision.APPROVED

    def close(self) -> None:
        pass


def approver_for(channel: str) -> PageApprover | TerminalApprover:
    """The one channel the host chose. There is no default and no fallback."""
    if channel == "page":
        return PageApprover()
    if channel == "terminal":
        return TerminalApprover()
    raise ValueError(f"unknown approval channel '{channel}': {' or '.join(CHANNELS)}")
