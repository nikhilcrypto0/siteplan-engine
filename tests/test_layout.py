import itertools
import math

import ezdxf
import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon, box

from siteplan.checks import Status
from siteplan.layout import LayoutRequest, area_statement, free_stretches, solve
from siteplan.layout_export import write_layout_dxf, write_layout_svg
from siteplan.library import FlatLibrary, FlatType
from siteplan.units import sqm_to_sqft

LIBRARY = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 10.0, "depth_m": 11.0, "saleable_sqft": 1190},
        {"name": "3A", "bhk": "3BHK", "width_m": 13.5, "depth_m": 11.0, "saleable_sqft": 1690},
    ],
    core_width_m=7.5,
)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3})  # 27 m: 9 m setbacks
LAYOUT_RULES = ("All-round setback", "Gap between blocks", "Organized open space", "Open-space")
L_PLOT = Polygon([(0, 0), (180, 0), (180, 90), (90, 90), (90, 170), (0, 170)])


def _layout_findings(option):
    return [f for f in option.findings if f.rule.startswith(LAYOUT_RULES)]


@pytest.mark.parametrize("plot", [box(0, 0, 150, 100), L_PLOT], ids=["rectangle", "L-shape"])
def test_every_option_passes_the_layout_rules(plot):
    options = solve(plot, LIBRARY, REQUEST)
    assert 1 <= len(options) <= REQUEST.options
    for option in options:
        findings = _layout_findings(option)
        assert findings, "the checker must have looked at setbacks, gaps and open space"
        assert all(f.status is Status.PASS for f in findings), [
            (f.rule, f.measured) for f in findings if f.status is not Status.PASS
        ]


def test_geometry_is_honest_independently_of_the_checker():
    plot = box(0, 0, 150, 100)
    for option in solve(plot, LIBRARY, REQUEST):
        for tower in option.towers:
            assert plot.exterior.distance(tower.footprint) >= 9.0
            assert plot.contains(tower.footprint)
            assert len(tower.flat_outlines) == 2 * len(tower.flats_per_side)
        for a, b in itertools.combinations(option.towers, 2):
            assert a.footprint.distance(b.footprint) >= 9.0
        assert option.open_space_sqm >= 0.10 * plot.area


def test_unit_mix_is_close_to_the_request_and_best_option_is_first():
    options = solve(box(0, 0, 150, 100), LIBRARY, REQUEST)
    assert options[0].mix_error < 0.05
    assert [o.score for o in options] == sorted((o.score for o in options), reverse=True)


def test_single_category_request_uses_only_that_category():
    only_2bhk = LayoutRequest(floors=8, unit_mix={"2BHK": 1.0})
    for option in solve(box(0, 0, 150, 100), LIBRARY, only_2bhk):
        assert set(option.flats_per_floor) == {"2BHK"}


def test_plot_too_small_for_a_tower_gives_no_options():
    assert solve(box(0, 0, 40, 40), LIBRARY, REQUEST) == []


def test_solver_is_deterministic():
    first = [o.summary() for o in solve(L_PLOT, LIBRARY, REQUEST)]
    assert first == [o.summary() for o in solve(L_PLOT, LIBRARY, REQUEST)]


def test_requests_the_library_or_rules_cannot_serve_are_refused():
    with pytest.raises(ValueError, match="not in the flat library"):
        solve(box(0, 0, 150, 100), LIBRARY, LayoutRequest(floors=8, unit_mix={"4BHK": 1.0}))
    with pytest.raises(ValueError, match="not high-rise"):
        solve(box(0, 0, 150, 100), LIBRARY, LayoutRequest(floors=4, unit_mix={"2BHK": 1.0}))
    with pytest.raises(ValidationError, match="add up to 1"):
        LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.7})
    with pytest.raises(ValidationError, match="same depth"):
        FlatLibrary(
            flats=[
                {"name": "a", "bhk": "2BHK", "width_m": 10, "depth_m": 11, "saleable_sqft": 1},
                {"name": "b", "bhk": "3BHK", "width_m": 12, "depth_m": 12, "saleable_sqft": 1},
            ],
            core_width_m=7.5,
        )


def test_free_stretches_skip_a_notch_in_the_strip():
    notched = box(0, 0, 50, 100).difference(box(20, 40, 50, 60))
    assert free_stretches(notched, 10, 20) == [(0.0, 40.0), (60.0, 100.0)]
    assert free_stretches(notched, 0, 10) == [(0.0, 100.0)]


def test_area_statement_groups_identical_towers_and_loads_common_area():
    option = solve(box(0, 0, 150, 100), LIBRARY, REQUEST)[0]
    statement = area_statement(option, REQUEST)
    built_up = sum(t.footprint.area for t in option.towers) / 0.09290304
    subtotal = sum(g.subtotal_sqft for g in statement.groups)
    assert subtotal == pytest.approx(round(built_up) * 8, rel=1e-3)
    assert statement.total_sqft == sum(math.floor(g.subtotal_sqft * 1.22) for g in statement.groups)


def test_exports_write_buildnow_layers_and_a_preview(tmp_path):
    plot = box(0, 0, 150, 100)
    option = solve(plot, LIBRARY, REQUEST)[0]
    doc = ezdxf.readfile(write_layout_dxf(option, plot, tmp_path / "o.dxf"))
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"Plot", "Building Plan", "Dwelling Unit", "Organized Open Space"} <= layers
    svg = write_layout_svg(option, plot, tmp_path / "o.svg", "Test <site>").read_text()
    assert svg.startswith("<svg") and "Test &lt;site&gt;" in svg


def test_the_flats_are_visible_in_the_preview(tmp_path):
    """Unfilled hairlines vanish on a 300px card and the towers read as empty blocks."""
    plot = box(0, 0, 150, 100)
    option = solve(plot, LIBRARY, REQUEST)[0]
    svg = write_layout_svg(option, plot, tmp_path / "o.svg", "t").read_text()
    drawn = sum(len(t.flat_outlines) for t in option.towers)
    assert drawn > 0
    assert svg.count('fill="#f7f4ea"') == drawn  # every flat is filled, not just outlined


def test_the_summary_prints_built_up_as_well_as_saleable():
    """A firm's area statement is built-up, so a scheme can only be compared on that."""
    plot = box(0, 0, 120, 90)
    library = FlatLibrary(
        flats=[FlatType(name="2BHK", bhk="2BHK", width_m=7.0, depth_m=11.0, saleable_sqft=1000)],
        core_width_m=7.5,
    )
    option = solve(plot, library, LayoutRequest(floors=8, unit_mix={"2BHK": 1.0}),
                   gross_area_sqm=plot.area, authority="HMDA", abutting_road_m=18.0)[0]
    summary = option.summary()
    assert summary["built_up_sqft"] > 0
    assert summary["built_up_sqft"] == round(sqm_to_sqft(option.built_up_sqm))
    assert summary["built_up_sqft"] != summary["saleable_sqft"]
