"""Table V row 4 (residential parking) outside GHMC and CURE: which edition is in force is open
(2026-10-13, the regulatory audit's D3).

The 2012 text gives 20 % outside GHMC; G.O.Ms.No.143 and No.144 of 24.09.2024 print the row as
30 | 30 | 30 | 25 | 25 | 25 (read on G.O.144's page image, p.2) while their operative words only
add row 5. The resolver plans the stricter (30 %), the validator judges both editions: a layout
between them is CONDITIONAL on the reading, and inside GHMC or CURE nothing changes (30 % either
way).

The made-up rectangle (outside GHMC and CURE) has 36,817 m² of built-up area: 20 % is 7,363 m²,
30 % is 11,045 m². As drawn it lays out 13,700 m² (above both); with its cellar outline shrunk
to 8,000 m² it lays out 9,380 m² (measured on 2026-10-13), about 2,000 m² above the one and 1,665
m² below the other.
"""

import math

import pytest
from shapely.affinity import scale
from validator_helpers import fixture, shape

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import TableVColumn
from siteplan.contracts.validation import DependsOn
from siteplan.legal.resolve import resolve

TEST_CLASS = "normative"
ROW = "table_v_row_4"
TABLE_V = "Parking (Table V)"


def _under_the_resolver(inputs):
    """The made-up inputs judged under the resolver's own rules, which carry the reading."""
    rules = resolve(inputs.site)
    assert rules.jurisdiction.table_v_column is TableVColumn.ELSEWHERE
    return type(inputs)(inputs.site, rules, inputs.brief, inputs.candidate, None)


def _cellar_shrunk(candidate):
    outline = candidate.program.cellars.outline[0].to_shapely()
    f = math.sqrt(8_000 / outline.area)
    candidate.program.cellars.outline = [shape(scale(outline, f, f, origin=outline.centroid))]


def _table_v(report):
    return next(c for c in report.legal if c.finding.rule == TABLE_V)


def test_a_layout_above_both_editions_passes_under_both():
    c = _table_v(_under_the_resolver(fixture("rectangle")).report())
    assert c.finding.status is Status.PASS
    assert c.by_reading[ROW] == {"edition_2012": Status.PASS, "edition_2024": Status.PASS}


def test_a_layout_between_the_editions_is_conditional_on_the_reading():
    c = _table_v(_under_the_resolver(fixture("rectangle").edited(_cellar_shrunk)).report())
    assert c.by_reading[ROW] == {"edition_2012": Status.PASS, "edition_2024": Status.FAIL}
    assert c.finding.status is Status.CONDITIONAL
    assert any(d.kind is DependsOn.READING and d.id == ROW for d in c.rests_on)


def test_the_need_is_recorded_under_each_edition():
    q = _under_the_resolver(fixture("rectangle")).report().recomputed.quantities
    assert q["parking_required_sqm[ELSEWHERE]"] == pytest.approx(0.20 * q["built_up_sqm"])
    assert q["parking_required_sqm[ELSEWHERE, edition_2024]"] == pytest.approx(
        0.30 * q["built_up_sqm"])


def test_inside_ghmc_or_cure_the_reading_never_comes_in():
    def in_cure(site):
        stated = site.jurisdiction.model_dump()
        stated["inside_cure"] = {**stated["inside_cure"], "value": True}
        site.jurisdiction = type(site.jurisdiction).model_validate(stated)
    inputs = fixture("rectangle").with_site(in_cure)
    rules = resolve(inputs.site)
    assert rules.jurisdiction.table_v_column is TableVColumn.GHMC_OR_CURE
    report = type(inputs)(inputs.site, rules, inputs.brief, inputs.candidate, None).report()
    assert ROW not in _table_v(report).by_reading
