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
        "5. SETBACKS AND HEIGHT",
        "TABLE - IV Height of building, minimum abutting road width, minimum",
        "all round open space. Up to 21m: 12m road and 7m open space.",
        "(f) 'High-Rise Building' means a building with 18m or more in height.",
    ],
    [
        "16. ROAD WIDENING",
        "(a) The land affected in road widening shall be surrendered free of cost",
        "to the sanctioning authority before the building permission is issued.",
        "(b) All internal roads with a width of below 9m existing roads shall be",
        "widened to the width shown in the master plan wherever a wide road is",
        "proposed, and the road width shall be measured at the site.",
    ],
    [
        "15. GENERAL CONDITIONS",
        "(x) In case of Group Housing Buildings where there are 100 units and above,",
        "a minimum 3% of the total built up area shall be planned and developed",
        "for common amenities and facilities like club house and gymnasium.",
        "(e) In case of High Rise Buildings the concessions in setbacks, other than",
        "the front setback would be considered subject to a clear setback of 7m.",
        "(a) In HMDA area where the site for residential projects is 4000sq.m and",
        "above, the developer shall provide 20% of developed land for EWS housing.",
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


def test_the_citation_is_read_off_the_document_not_composed(book):
    hit = book.search("how wide must the driveway be")[0]
    assert hit.section == "13. PARKING" and hit.clause == "(viii)"
    assert hit.citation == "rule 13(viii) (page 2)"
    assert hit.as_dict()["citation"] == hit.citation


def test_the_replaced_table_admits_it_has_been_replaced(book):
    """A live search answered a setback question from the 2012 table, which 2019 replaced."""
    hit = next(h for h in book.search("table IV abutting road width", limit=5) if "TABLE" in h.text)
    assert hit.superseded_by.startswith("G.O.Ms.No.50 of 2019")
    assert "rules_for_height" in hit.superseded_by
    assert hit.as_dict()["still_in_force"] is False


def test_the_old_high_rise_threshold_is_flagged(book):
    hit = next(h for h in book.search("high rise building means 18m", limit=5)
               if "High-Rise Building" in h.text)
    assert "21 m" in hit.superseded_by and "2026" in hit.superseded_by


def test_the_green_strip_clause_carries_its_2016_amendment(book):
    hit = next(h for h in book.search("green planting strip periphery", limit=5)
               if "green planting strip" in h.text)
    assert "G.O.Ms.No.7 of 2016" in hit.superseded_by


@pytest.mark.parametrize(("question", "marker", "note"), [
    ("club house amenities percentage of built up area", "minimum 3%", "50,000 Sft"),
    ("setback concessions for high rise other than the front", "other than",
     "all sides, front included"),
    ("EWS housing developed land", "developed land", "shelter fee"),
])
def test_the_clauses_rewritten_in_2016_say_so(book, question, marker, note):
    """The amenities, road-widening and EWS clauses all changed in 2016; the 2012 text is not
    the rule in force, and a search that quotes it must say so."""
    hit = next(h for h in book.search(question, limit=8) if marker in h.text)
    assert "G.O.Ms.No.7 of 2016" in hit.superseded_by and note in hit.superseded_by


def test_a_clause_still_in_force_is_left_alone(book):
    hit = book.search("how wide must the driveway be")[0]
    assert hit.superseded_by == ""
    assert hit.as_dict()["still_in_force"] is True


def test_a_section_heading_carries_on_to_later_clauses(book):
    hit = book.search("green planting strip in the periphery")[0]
    assert hit.section.startswith("7.")   # the clause sits under the high-rise section
    assert hit.citation.startswith("rule 7(")


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


@pytest.mark.parametrize(("height", "setback"), [(57.0, 17.0), (100.0, 18.0), (150.0, 20.0)])
def test_the_2019_bands_answer_for_tall_buildings(height, setback):
    answer = height_rules(height)
    assert answer["min_all_round_setback_m"] == pytest.approx(setback)
    assert "G.O.Ms.No.50 of 2019" in answer["clause"]


def test_a_long_building_is_told_it_needs_more():
    answer = height_rules(27.0, longest_side_m=56.0)
    assert answer["min_all_round_setback_m"] == pytest.approx(10.6)
    assert "56 m long" in answer["note"]
    assert any("G.O.Ms.No.50" in clause for clause in answer["also"])


def test_the_tdr_band_is_flagged_rather_than_passed():
    answer = height_rules(19.5, plot_sqm=1200)
    assert answer["class"] == "not high-rise"
    assert "TDR" in answer["watch"]
