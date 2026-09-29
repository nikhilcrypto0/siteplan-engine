"""Sanctioned plans as the test of the rules. Made-up geometry here; the firm's own cases live
in gitignored fixtures/cases/ and are checked by the last test when present."""

from pathlib import Path

import pytest

from siteplan.cases import Case, load_cases, render, review
from siteplan.cli import main

CASES = Path(__file__).parent.parent / "fixtures" / "cases"


def _case(setback_m: float, known: dict[str, str] | None = None) -> Case:
    """A 120 x 80 m plot with one stilt + 8 block, 50 x 20 m (27 m tall, so 10 m all round)."""
    x0, y0 = setback_m, 30.0
    return Case(
        name="Example", evidence="sanctioned", sources=["made up for the test"],
        authority="HMDA", net_area_sqm=9600, abutting_road_m=18,
        net_plot=[(0, 0), (120, 0), (120, 80), (0, 80)],
        buildings=[{"name": "A", "floors": 8, "stilt_height_m": 3, "floor_height_m": 3,
                    "outline": [(x0, y0), (x0 + 50, y0), (x0 + 50, y0 + 20), (x0, y0 + 20)]}],
        known_disagreements=known or {},
    )


def test_a_scheme_inside_every_rule_passes():
    result = review(_case(setback_m=12))
    assert result.failures == () and result.settled


def test_a_failure_nobody_has_explained_unsettles_the_case():
    result = review(_case(setback_m=8))
    assert [f.rule for f in result.unexplained] == ["All-round setback: A"]
    assert not result.settled
    assert "NEW: not yet understood" in render([result])


def test_a_failure_already_understood_is_reported_but_does_not_unsettle():
    result = review(_case(setback_m=8, known={"All-round setback: A": "a concession we lack"}))
    assert [f.rule for f in result.failures] == ["All-round setback: A"]
    assert result.settled and "understood: a concession we lack" in render([result])


def test_a_listed_failure_that_now_passes_is_reported_as_a_rule_fixed():
    result = review(_case(setback_m=12, known={"All-round setback: A": "was failing"}))
    assert result.resolved == ("All-round setback: A",) and not result.settled
    assert "NOW PASSES All-round setback: A" in render([result])


def test_the_tally_counts_only_sanctioned_plans():
    drawing = _case(setback_m=8, known={"All-round setback: A": "x"}).model_copy(
        update={"evidence": "firm_drawing"})
    text = render([review(_case(setback_m=12)), review(drawing)])
    assert text.endswith("Sanctioned plans passing every rule: 1 of 1.")


def test_the_command_exits_non_zero_until_every_failure_is_understood(tmp_path, capsys):
    (tmp_path / "a.case.json").write_text(_case(setback_m=8).model_dump_json())
    assert main(["cases", str(tmp_path)]) == 1
    known = _case(setback_m=8, known={"All-round setback: A": "understood"})
    (tmp_path / "a.case.json").write_text(known.model_dump_json())
    assert main(["cases", str(tmp_path)]) == 0
    assert "Example (sanctioned plan)" in capsys.readouterr().out


@pytest.mark.skipif(not CASES.is_dir(), reason="client cases not present")
def test_every_client_case_fails_only_where_we_already_know_why():
    for case in load_cases(CASES):
        result = review(case)
        assert result.unexplained == (), (case.name, [f.rule for f in result.unexplained])
        assert result.resolved == (), (case.name, result.resolved)
