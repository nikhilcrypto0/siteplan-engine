"""Roads and fire access: the geometry, against answers worked by hand."""

import math

import pytest
from shapely.geometry import Point, Polygon, box

from siteplan.access import (
    FIRE_BAND_M,
    RoadPiece,
    along_boundary,
    around_block,
    blocked,
    entrance,
    fire_bands,
    green_strip_width,
    inner_plot,
    loop_road,
    through_roads,
    tower_inset,
)
from siteplan.findings import narrower_than


def test_the_fire_band_is_what_a_9_m_turn_round_a_square_corner_needs():
    # A 6 m lane turning on a 9 m outer radius has a 3 m inner radius; going round a square
    # corner it swings 3/sqrt(2) m wider than it runs along the faces.
    assert pytest.approx(9 - 3 / math.sqrt(2)) == FIRE_BAND_M
    assert 6.87 < FIRE_BAND_M < 6.89


def test_each_corner_of_a_block_gets_a_sector_that_touches_it_and_stays_in_the_band():
    block = box(0, 0, 10, 10)
    sectors = around_block(block)
    assert len(sectors) == 4
    band = block.buffer(FIRE_BAND_M + 0.01, join_style="mitre")
    for sector in sectors:
        assert not sector.intersects(block.buffer(-0.01))  # the lane never cuts the block
        assert band.contains(sector)
    corner = next(s for s in sectors if s.distance(Point(10, 0)) < 0.05)
    assert corner.bounds[2] == pytest.approx(10 + FIRE_BAND_M, abs=0.05)
    assert corner.bounds[1] == pytest.approx(-FIRE_BAND_M, abs=0.05)


def test_the_loop_turns_inside_a_square_corner_of_the_site():
    inner = box(0, 0, 100, 80)
    sectors = along_boundary(inner)
    assert len(sectors) == 4
    for sector in sectors:
        assert inner.buffer(0.01).contains(sector)
        assert not sector.intersects(inner.buffer(-9.01))  # it stays within the 9 m loop


def test_a_step_in_the_boundary_is_turned_round_like_a_block():
    l_shape = Polygon([(0, 0), (100, 0), (100, 50), (50, 50), (50, 100), (0, 100)])
    sectors = along_boundary(l_shape)
    assert len(sectors) == 6
    step = next(s for s in sectors if s.distance(Point(50, 50)) < 0.05)
    assert l_shape.buffer(0.01).contains(step)  # it stays on the site
    assert Point(50, 50).distance(step) < 0.05  # the step's corner touches the lane's edge


def test_a_turn_with_something_in_its_way_is_found():
    block = box(0, 0, 10, 10)
    free = box(-20, -20, 30, 30).difference(block)
    turns = around_block(block)
    assert blocked(turns, free) == []
    cramped = free.difference(box(15, -20, 30, 30))  # a wall 5 m off the east face
    assert len(blocked(turns, cramped)) == 2  # both corners on that side


def test_the_loop_is_9_m_wide_between_the_towers_land_and_the_green_strip():
    assert green_strip_width(10.0) == 2.0 and green_strip_width(8.0) == 0.0
    assert tower_inset(10.0) == 11.0  # 2 m strip and 9 m of road need more than the setback
    assert tower_inset(8.0) == 9.0
    assert tower_inset(12.0) == 12.0
    plot = box(0, 0, 150, 120)
    envelope = plot.buffer(-11.0, join_style="mitre")
    loop = loop_road(envelope, inner_plot(plot, 2.0))
    assert loop.area == pytest.approx(146 * 116 - 128 * 98, rel=1e-3)
    assert not narrower_than(loop, 8.98)


def test_the_entrance_goes_on_the_side_the_access_road_runs():
    plot = box(0, 0, 150, 120)
    gate = entrance(plot, "W", 11.0)
    minx, _, maxx, _ = gate.approach.bounds
    assert minx == pytest.approx(0.0) and maxx == pytest.approx(11.0)
    assert gate.width_m == 9.0 and "W side" in gate.note
    assert "ASSUMED" in entrance(plot, None, 11.0).note


def test_fire_bands_ring_each_block():
    bands = fire_bands([box(0, 0, 10, 10)])
    assert bands.area == pytest.approx((10 + 2 * FIRE_BAND_M) ** 2 - 100, rel=1e-6)


def test_a_road_that_meets_the_loop_once_is_a_dead_end():
    loop = box(0, 0, 100, 100).difference(box(9, 9, 91, 91))
    through = RoadPiece("internal", box(40, 9, 49, 91), 9.0)
    stub = RoadPiece("internal", box(60, 9, 69, 50), 9.0)
    ok, dead = through_roads([through, stub], loop)
    assert ok == [through] and dead == [stub]


JAGGED_NE = {  # an access side traced through survey points, as Suchitra's outline is
    "one piece long enough": [(100, 50), (97, 54), (93, 57), (88, 62), (84, 65), (79, 70),
                              (75, 74), (70, 79), (66, 82), (60, 85)],
    "every piece shorter than the road": [(100, 50), (97, 55), (94, 56), (91, 61), (87, 63),
                                          (84, 68), (80, 70), (77, 75), (73, 77), (70, 82),
                                          (66, 84), (62, 85)],
}


@pytest.mark.parametrize("side", JAGGED_NE.values(), ids=JAGGED_NE.keys())
def test_a_jagged_access_side_still_gets_a_full_width_approach_road(side):
    """On Suchitra every candidate failed 'main approach': the 9 m road was anchored on a
    piece of boundary shorter than itself, hung past its ends and was cut to a sliver."""
    from pathlib import Path

    from siteplan.findings import narrower_than
    from siteplan.layout import LayoutRequest, SiteFacts, search
    from siteplan.library import FlatLibrary

    library = FlatLibrary.model_validate_json(
        (Path(__file__).parent.parent / "examples" / "flat_library.example.json").read_text())
    plot = Polygon([(0, 0), (100, 0), *side, (0, 85)])
    facts = SiteFacts(abutting_road_m=12.38, authority="HMDA", inside_cure=False,
                      access_side="NE")
    result = search(plot, library, LayoutRequest(floors=7, unit_mix={"2BHK": 1.0}), facts)
    assert result.options, [r.reasons for r in result.rejected]
    approach = next(r for r in result.options[0].roads if r.kind == "main approach")
    assert not narrower_than(approach.shape, 8.98)


def test_a_main_approach_narrower_than_the_rule_says_so_rather_than_its_drawn_width():
    from siteplan.access import Entrance, RoadPiece
    from siteplan.access_checks import road_findings
    from siteplan.checks import Site

    sliver = Polygon([(0, 0), (9, 0), (1, 6)])  # drawn as a 9 m road, 9 m wide nowhere
    site = Site(gross_area_sqm=8_000, net_plot=box(0, 0, 100, 80),
                roads=(RoadPiece("main approach", sliver, 9.0),),
                entrance=Entrance(sliver, sliver, 9.0, "test"))
    finding = next(f for f in road_findings(site) if f.rule == "Internal roads: main approach")
    assert finding.status.value == "FAIL" and finding.measured.startswith("narrower than 9 m")
