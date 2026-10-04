"""The person channels the service asks the architect on (service/approvers.py), and the two
commands that drive the service by hand (`siteplan propose`, `siteplan export-candidate`).

Only the person's own yes is a yes. A rejection, an unanswered page, a terminal no one types into
and a channel that breaks are all a no, and one channel never falls back to the other. Made-up
land only; the browser is played by a test that opens the real approval page and clicks."""

from __future__ import annotations

import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from test_service import BRIEF, make_workspace

from siteplan.approval import ApprovalDesk
from siteplan.cli import main as cli
from siteplan.service import (
    Intent,
    PageApprover,
    ProposeLayouts,
    ProposeStatus,
    Service,
    TerminalApprover,
    approver_for,
)
from siteplan.service.approvers import QUESTION

TEST_CLASS = "normative"

TITLE = "Generate layout options for a made-up site"
LINES = ["Access road: 18.29 m legal width (USER_CONFIRMED)", "CHECK: the brief never states X"]
PROJECT, SURVEY = "service-test.project.json", "survey.dxf"
REQUEST = ["--brief", BRIEF, "--most", "--mix", "2BHK=70,3BHK=30", "--massing", "BALANCED"]


class Browser:
    """The architect's browser as a test plays it: opens the page, reads it, clicks one button
    (or none, when `decision` is None)."""

    def __init__(self, decision: str | None) -> None:
        self.decision, self.opened, self.pages = decision, [], []

    def __call__(self, url: str) -> None:
        self.opened.append(url)
        if self.decision is not None:
            threading.Thread(target=self._click, args=(url,), daemon=True).start()

    def _click(self, url: str) -> None:
        self.pages.append(urllib.request.urlopen(url, timeout=5).read().decode())
        parsed = urllib.parse.urlparse(url)
        token = urllib.parse.parse_qs(parsed.query)["t"][0]
        form = urllib.parse.urlencode({"t": token, "decision": self.decision}).encode()
        action = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        urllib.request.urlopen(urllib.request.Request(action, data=form), timeout=5).read()


def _page(decision: str | None, timeout_s: float = 10.0) -> tuple[PageApprover, Browser]:
    browser = Browser(decision)
    return PageApprover(ApprovalDesk(open_page=browser), timeout_s=timeout_s), browser


# --- the approval page ---------------------------------------------------------------------


def test_the_page_says_yes_only_when_the_architect_clicks_approve():
    approver, browser = _page("approve")
    try:
        assert approver.approve(TITLE, LINES) is True
    finally:
        approver.close()
    (url,) = browser.opened
    assert url.startswith("http://127.0.0.1:") and "?t=" in url  # this machine, behind a token
    (page,) = browser.pages
    assert TITLE in page and all(line in page for line in LINES)  # the person sees everything


@pytest.mark.parametrize(("decision", "timeout_s"), [("reject", 10.0), (None, 0.3)])
def test_a_rejection_or_an_unanswered_page_is_a_no(decision, timeout_s):
    approver, _ = _page(decision, timeout_s)
    try:
        assert approver.approve(TITLE, LINES) is False
    finally:
        approver.close()


def test_the_link_goes_to_the_browser_and_never_back_to_the_caller():
    approver, browser = _page("approve")
    try:
        answer = approver.approve(TITLE, LINES)
    finally:
        approver.close()
    token = urllib.parse.parse_qs(urllib.parse.urlparse(browser.opened[0]).query)["t"][0]
    assert answer is True  # a bare yes or no, nothing a caller could follow
    assert not [k for k, v in vars(approver).items() if token in repr(v)]


# --- the terminal --------------------------------------------------------------------------


def _terminal(answer: str | None, interactive: bool = True):
    shown, asked = [], []

    def ask(question: str) -> str:
        asked.append(question)
        if answer is None:
            raise EOFError
        return answer
    return TerminalApprover(ask=ask, show=shown.append, interactive=lambda: interactive), \
        shown, asked


@pytest.mark.parametrize("answer", ["yes", "y", " YES ", "Y"])
def test_the_terminal_says_yes_only_to_yes(answer):
    approver, shown, asked = _terminal(answer)
    assert approver.approve(TITLE, LINES) is True
    assert shown[0].strip() == TITLE and [s.strip() for s in shown[1:]] == [
        f"- {line}" for line in LINES]
    assert asked == [QUESTION]


@pytest.mark.parametrize("answer", ["no", "", "yess", "approve", "ok", None])
def test_anything_else_on_the_terminal_is_a_no(answer):
    approver, _, _ = _terminal(answer)
    assert approver.approve(TITLE, LINES) is False


def test_a_terminal_whose_input_is_not_interactive_is_a_no_without_asking():
    approver, shown, asked = _terminal("yes", interactive=False)
    assert approver.approve(TITLE, LINES) is False
    assert shown == [] and asked == []  # piped "yes" never reaches the question


# --- one channel, chosen at startup --------------------------------------------------------


def test_the_host_chooses_one_channel_and_there_is_no_default():
    page = approver_for("page")
    page.close()
    assert isinstance(page, PageApprover)
    assert isinstance(approver_for("terminal"), TerminalApprover)
    for other in ("", "auto", "yes", "elicit", "none"):
        with pytest.raises(ValueError, match="unknown approval channel"):
            approver_for(other)


def test_the_commands_refuse_to_start_without_a_channel(tmp_path):
    with pytest.raises(SystemExit):
        cli(["propose", PROJECT, *REQUEST, "--workspace", str(tmp_path)])
    with pytest.raises(SystemExit):
        cli(["export-candidate", "run", "candidate", "--workspace", str(tmp_path)])


# --- the service on these channels ---------------------------------------------------------


@pytest.fixture(scope="module")
def ws(tmp_path_factory) -> Path:
    return make_workspace(tmp_path_factory.mktemp("approvers"))


def test_a_rejection_on_the_page_runs_and_writes_nothing(ws):
    approver, browser = _page("reject")
    out = ws / "out-rejected"
    try:
        result = Service(ws, out, approver).propose_layouts(ProposeLayouts(
            project_file=PROJECT, survey_file=SURVEY, brief=BRIEF,
            intent=Intent(height="MOST_THE_RULES_ALLOW",
                          unit_mix_percent={"2BHK": 70, "3BHK": 30})))
    finally:
        approver.close()
    assert result.status is ProposeStatus.NOT_APPROVED and result.run_id is None
    assert len(browser.opened) == 1  # asked once, of the person
    assert not list(out.glob("*/run.json"))


def test_propose_on_a_terminal_no_one_answers_runs_nothing(ws, capsys):
    out = ws / "out-unanswered"  # pytest's own input is not a terminal
    assert cli(["propose", PROJECT, "--survey", SURVEY, *REQUEST, "--workspace", str(ws),
                "--out", str(out), "--approval", "terminal"]) == 1
    assert "NOT_APPROVED" in capsys.readouterr().out
    assert not list(out.glob("*/run.json"))


def test_the_architect_proposes_and_exports_on_the_terminal(ws, capsys, monkeypatch):
    asked = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda question: asked.append(question) or "yes")
    out = ws / "out-approved"
    base = ["--workspace", str(ws), "--out", str(out), "--approval", "terminal"]
    assert cli(["propose", PROJECT, "--survey", SURVEY, *REQUEST, *base]) == 0
    result = capsys.readouterr().out.split("PROPOSED: run ", 1)[1]  # after the question shown
    run_id = result.split()[0]
    candidate = result.split("\n  ", 1)[1].split(":", 1)[0]
    assert len(asked) == 1  # the request, approved before anything ran

    # Without accepting its UNVERIFIED items the candidate stays where it is.
    assert cli(["export-candidate", run_id, candidate, *base]) == 1
    assert "Not exported" in capsys.readouterr().out
    assert cli(["export-candidate", run_id, candidate, "--accept-unresolved", *base]) == 0
    exported = capsys.readouterr().out
    assert "EXPORTED" in exported and ".dxf" in exported
    assert len(asked) == 2  # the UNVERIFIED items, put to the architect before anything drew
