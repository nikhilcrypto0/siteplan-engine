import ezdxf
import pytest
from shapely.geometry import LineString, Polygon

from siteplan.dxf_export import write_survey_dxf
from siteplan.dxf_survey import DxfProfile, read_dxf_survey
from siteplan.survey import SpotLevel, Survey

L_SHAPE = Polygon([(0, 0), (120, 0), (120, 60), (70, 60), (70, 100), (0, 100)])  # 10,000 m²


def _survey():
    return Survey(
        source="synthetic",
        boundary=L_SHAPE,
        stated_area_sqm=10000,
        calibration=None,
        levels=(SpotLevel(10, 10, 587.5, True), SpotLevel(100, 50, 585.0, True),
                SpotLevel(60, 90, 588.0, True), SpotLevel(150, 10, 584.0, False)),
        roads=(LineString([(-10, -5), (130, -5)]),),
    )


def test_export_uses_buildnow_layers_and_metres(tmp_path):
    path = write_survey_dxf(_survey(), tmp_path / "s.dxf")
    doc = ezdxf.readfile(path)
    assert doc.header["$INSUNITS"] == 6
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"Plot", "Road", "SURVEY-SPOT-LEVELS"} <= layers
    plot = next(iter(doc.modelspace().query('LWPOLYLINE[layer=="Plot"]')))
    assert plot.closed


def test_round_trip_keeps_area_levels_and_roads(tmp_path):
    path = write_survey_dxf(_survey(), tmp_path / "s.dxf")
    back = read_dxf_survey(path, DxfProfile(road_layer_hint="ROAD"))
    assert back.area_sqm == pytest.approx(10000)
    assert back.stated_area_sqm == pytest.approx(10000, rel=1e-3)  # carried in SURVEY-NOTES
    assert back.warnings == ()
    assert sorted(lv.z for lv in back.levels) == [584.0, 585.0, 587.5, 588.0]
    assert sum(lv.on_site for lv in back.levels) == 3
    assert len(back.roads) == 1


def _feet_dxf(path, insunits):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    ring = [(x / 0.3048, y / 0.3048) for x, y in list(L_SHAPE.exterior.coords)[:-1]]
    msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": "SITE-BOUNDARY"})
    hut = [(0, 0), (10, 0), (10, 10), (0, 10)]
    msp.add_lwpolyline(hut, close=True, dxfattribs={"layer": "HUT"})
    msp.add_text("AREA: 2 AC 18.84 GTS", height=5).set_placement((10, 10))
    doc.saveas(path)
    return path


def test_reads_feet_drawings_and_picks_boundary_by_written_area(tmp_path):
    survey = read_dxf_survey(_feet_dxf(tmp_path / "ft.dxf", insunits=2))
    assert survey.area_sqm == pytest.approx(10000, rel=1e-6)
    assert survey.stated_area_sqm == pytest.approx(10000, rel=1e-3)
    assert survey.warnings == ()


def test_unitless_drawing_must_be_told_its_units(tmp_path):
    path = _feet_dxf(tmp_path / "nounits.dxf", insunits=0)
    with pytest.raises(ValueError, match="units are not set"):
        read_dxf_survey(path)
    survey = read_dxf_survey(path, DxfProfile(metres_per_unit_if_unset=0.3048))
    assert survey.area_sqm == pytest.approx(10000, rel=1e-6)
    assert any("assumed" in w for w in survey.warnings)


def test_arcs_in_legacy_polylines_are_warned_about(tmp_path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    poly = doc.modelspace().add_polyline2d(
        [(0, 0), (100, 0), (100, 100), (0, 100)], close=True, dxfattribs={"layer": "PLOT"}
    )
    poly.vertices[1].dxf.bulge = 0.5
    doc.saveas(tmp_path / "arc.dxf")
    survey = read_dxf_survey(tmp_path / "arc.dxf")
    assert any("arcs" in w for w in survey.warnings)


def test_a_site_area_in_square_yards_picks_the_net_plot_over_an_older_outline(tmp_path):
    """The firm's Dhulapally DWG holds two outlines, 19,944 m² on A-BOUNDARY and the net plot of
    18,969 m² on layer 0, and writes "TOTAL SITE AREA: 22,686 SQYDS". Reading only acres and
    guntas, the reader missed the written area and took the older outline."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    net = [(0, 0), (120, 0), (120, 60), (70, 60), (70, 100), (0, 100)]  # 10,000 m²
    msp.add_lwpolyline([(-6, 0), *net[1:5], (-6, 100)], close=True,
                       dxfattribs={"layer": "A-BOUNDARY"})  # 600 m² more: strip not yet cut
    msp.add_lwpolyline(net, close=True, dxfattribs={"layer": "0"})
    msp.add_text(f"TOTAL SITE AREA: {10000 / 0.83612736:,.0f} SQYDS").set_placement((10, 10))
    msp.add_text("FLAT AREA: 1,190 SFT").set_placement((20, 20))
    doc.saveas(tmp_path / "siteplan.dxf")
    survey = read_dxf_survey(tmp_path / "siteplan.dxf")
    assert survey.area_sqm == pytest.approx(10000, rel=1e-6)
    assert survey.stated_area_sqm == pytest.approx(10000, rel=1e-4)
    assert survey.warnings == ()


def test_a_boundary_drawn_inside_a_block_is_read_where_the_block_places_it(tmp_path):
    """A block is placed by its own position, scale and rotation; its 50 m square, placed at
    twice the size, is a 100 m plot, and its layer-0 lines take the block's layer."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    block = doc.blocks.new("PLOT")
    block.add_lwpolyline([(0, 0), (50, 0), (50, 50), (0, 50)], close=True)
    block.add_text("AREA: 2 AC 18.84 GTS").set_placement((5, 5))  # 10,000 m²
    ref = doc.modelspace().add_blockref("PLOT", (1000, 500),
                                        dxfattribs={"layer": "SITE-BOUNDARY", "rotation": 30})
    ref.dxf.xscale = ref.dxf.yscale = 2.0
    doc.saveas(tmp_path / "block.dxf")
    survey = read_dxf_survey(tmp_path / "block.dxf", DxfProfile(boundary_layer="SITE-BOUNDARY"))
    assert survey.area_sqm == pytest.approx(10000, rel=1e-6)
    assert survey.stated_area_sqm == pytest.approx(10000, rel=1e-3)
    assert survey.warnings == ()


def test_a_level_in_a_mirrored_block_lands_on_the_right_side(tmp_path):
    """Mirroring turns a block's own coordinate system over. Read raw, this level sits 30 m
    west of the plot; in world coordinates it is 30 m inside it."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True,
                       dxfattribs={"layer": "PLOT"})
    msp.add_text("AREA: 2 AC 18.84 GTS").set_placement((5, 5))
    level = doc.blocks.new("LEVEL")
    level.add_text("587.50").set_placement((30, 0))
    for x in (60, 160):  # lands at 30 m (on the plot) and 130 m (off it)
        msp.add_blockref("LEVEL", (x, 50)).dxf.xscale = -1.0
    doc.saveas(tmp_path / "mirrored.dxf")
    survey = read_dxf_survey(tmp_path / "mirrored.dxf")
    on_site = [lv for lv in survey.levels if lv.on_site]
    assert len(survey.levels) == 2 and len(on_site) == 1
    assert on_site[0].x == pytest.approx(30.0) and on_site[0].z == 587.5
