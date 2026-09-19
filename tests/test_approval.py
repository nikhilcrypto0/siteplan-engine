"""The approval page: only a click on Approve approves, and only with the one-time link."""

from urllib.error import HTTPError

import pytest
from browser_stub import answer, clicker, read_page

from siteplan.approval import ApprovalDesk

TITLE = "Generate layout options for Test site"
LINES = ["Floors above the stilt: 8 (height 27 m)", "CHECK: the brief never states floors"]


@pytest.fixture
def desk():
    made = []

    def build(open_page=lambda url: None):
        made.append(ApprovalDesk(open_page=open_page))
        return made[-1]

    yield build
    for one in made:
        one.close()


def test_a_click_on_approve_is_a_yes(desk):
    seen: list[str] = []
    assert desk(clicker("approve", seen=seen)).ask(TITLE, LINES, 10) is True
    assert len(seen) == 1 and seen[0].startswith("http://127.0.0.1:")  # local only


def test_the_page_shows_the_values_and_escapes_them(desk):
    shown: list[str] = []
    one = desk(lambda url: shown.append(read_page(url)))
    assert one.ask(TITLE, [*LINES, "<script>alert(1)</script>"], 0.4) is False  # nobody clicked
    assert "Floors above the stilt: 8" in shown[0] and TITLE in shown[0]
    assert "&lt;script&gt;" in shown[0] and "<script>alert(1)</script>" not in shown[0]


@pytest.mark.parametrize("decision", ["reject", "anything-else"])
def test_only_the_word_approve_counts(desk, decision):
    assert desk(clicker(decision)).ask(TITLE, LINES, 10) is False


def test_no_answer_is_a_no(desk):
    assert desk().ask(TITLE, LINES, 0.3) is False


def test_a_wrong_token_cannot_answer(desk):
    replies: list[int] = []

    def open_page(url: str) -> None:
        replies.append(answer(url, "approve", token="not-the-token"))

    assert desk(open_page).ask(TITLE, LINES, 0.3) is False
    assert replies == [404]


def test_the_link_stops_working_once_answered(desk):
    seen: list[str] = []
    assert desk(clicker("approve", seen=seen)).ask(TITLE, LINES, 10) is True
    with pytest.raises(HTTPError) as err:
        read_page(seen[0])
    assert err.value.code == 404


def test_a_machine_with_no_browser_still_refuses_rather_than_crashing(desk):
    def open_page(url: str) -> None:
        raise OSError("no browser here")

    assert desk(open_page).ask(TITLE, LINES, 0.3) is False
