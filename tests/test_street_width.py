"""The width a street of the full search declares (2026-10-12): a street paved wider than the rule's
road, a corridor two columns share, declares the width it is paved at, where it used to declare
the rule's 9 m and under-report itself; a street no wider declares the rule's width as before, and
the validator still measures the pavement and takes the lesser. Made-up roads."""

from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString

from siteplan.contracts.candidate import RoadKind
from siteplan.optimizer.search.build import _declared_m
from siteplan.optimizer.search.road_graph import Road

TEST_CLASS = "normative"

Q = SimpleNamespace(road_m=9.0, legal_road_m=9.0, pathway_m=6.0)
LAID = SimpleNamespace(clipped_rings=set(), entrance=SimpleNamespace(width_m=9.0))
LINE = LineString([(0, 0), (0, 60)])


def test_a_street_paved_wider_than_the_rule_declares_its_own_width():
    assert _declared_m(Road("street-1", RoadKind.INTERNAL, LINE, 10.0), LAID, Q) == 10.0


def test_a_street_no_wider_than_the_rule_declares_the_rules_width():
    assert _declared_m(Road("street-1", RoadKind.INTERNAL, LINE, 9.0), LAID, Q) == 9.0
    assert _declared_m(Road("street-1", RoadKind.INTERNAL, LINE, 8.0), LAID, Q) == 9.0


def test_a_pathway_and_the_approach_declare_as_before():
    assert _declared_m(Road("pathway-1", RoadKind.PATHWAY, LINE, 6.0), LAID, Q) == 6.0
    assert _declared_m(Road("approach", RoadKind.APPROACH, LINE, 12.0), LAID, Q) == 9.0
