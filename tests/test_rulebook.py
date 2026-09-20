"""Rule answers: exact values from the encoded table, passages quoted from the order."""

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from siteplan.rulebook import RuleBook
from siteplan.rules import height_rules

PAGES = [
    [
        "7. HIGH RISE BUILDINGS",
        "(vii) In every high rise building site, an organized open space shall be",
        "provided over and above the mandatory setbacks. This space shall be at",
        "least 10% of total site area at ground level open to sky and shall be a",
        "minimum width of 3m.",
        "(viii) In addition a minimum of 2m wide green planting strip in the",
        "periphery on all sides within the setbacks shall be developed.",
    ],
    [
        "13. PARKING",
        "(viii) The minimum width of the drive way shall be 4.5m.",
        "(ix) In case where the permissible set back is less than 4.6m the pillars",
        "position in stilt floor shall be so designed that there shall be clear",
        "space of 3.6m for movement of vehicles.",
    ],
    [
        "16. ROAD WIDENING",
        "(a) The land affected in road widening shall be surrendered free of cost",
        "to the sanctioning authority before the building permission is issued.",
        "(b) All internal roads with a width of below 9m existing roads shall be",
        "widened to the width shown in the master plan wherever a wide road is",
        "proposed, and the road width shall be measured at the site.",
    ],
]


@pytest.fixture(scope="module")
def order(tmp_path_factory):
    path = tmp_path_factory.mktemp("rules") / "order.pdf"
    sheet = canvas.Canvas(str(path), pagesize=A4)
    for lines in PAGES:
        y = 780
        for line in lines:
            sheet.drawString(56, y, line)
            y -= 16
        sheet.showPage()
    sheet.save()
    return path


@pytest.fixture(scope="module")
def book(order):
    return RuleBook.load(order)


def test_a_question_finds_the_clause_that_answers_it(book):
    hits = book.search("how wide must the driveway be")
    assert hits and hits[0].page == 2
    assert "4.5m" in hits[0].text


def test_the_answer_carries_its_page_so_it_can_be_checked(book):
    hits = book.search("organized open space 10% of site area")
    assert hits[0].page == 1
    assert "10%" in hits[0].text and hits[0].as_dict()["page"] == 1


def test_a_question_the_document_does_not_answer_comes_back_empty(book):
    assert book.search("lift machine room headroom") == []


def test_the_text_is_extracted_once_and_cached_beside_the_document(order, book):
    cache = order.with_suffix(".passages.json")
    assert cache.is_file()
    again = RuleBook.load(order)
    assert again.passages == book.passages


def test_a_stale_cache_is_rebuilt_rather_than_trusted(order, book):
    cache = order.with_suffix(".passages.json")
    cache.write_text('{"stamp": {"version": 0, "size": 1, "mtime": 1}, "passages": []}')
    assert RuleBook.load(order).passages == book.passages


@pytest.mark.parametrize(("height", "road", "setback"), [
    (21.0, 12.0, 7.0),      # the band reads "above 21 up to 24", so 21 is still the first row
    (27.0, 18.0, 9.0),
    (35.0, 24.0, 11.0),
    (55.0, 30.0, 16.0),
])
def test_exact_values_come_from_the_table_not_a_search(height, road, setback):
    answer = height_rules(height)
    assert answer["min_abutting_road_m"] == road
    assert answer["min_all_round_setback_m"] == setback
    assert answer["clause"].startswith("G.O.168")


def test_below_the_high_rise_threshold_it_says_so_instead_of_guessing():
    answer = height_rules(15.0)
    assert answer["class"] == "not high-rise"
    assert "not encoded" in answer["answer"]


@pytest.mark.parametrize(("height", "setback"), [(57.0, 16.5), (60.0, 16.5), (61.0, 17.0)])
def test_above_the_table_the_note_is_applied(height, setback):
    answer = height_rules(height)
    assert answer["min_all_round_setback_m"] == pytest.approx(setback)
    assert "0.5 m" in answer["clause"]
