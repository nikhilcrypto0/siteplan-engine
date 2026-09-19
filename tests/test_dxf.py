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
