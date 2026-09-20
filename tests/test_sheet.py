"""The drawing sheet: dimensions, labels, north arrow, scale bar, statement, title block."""

import ezdxf
import pytest
from shapely.geometry import box

from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.sheet import SHEET_LAYERS, SheetInfo, pick_scale, write_sheet_dxf

PLOT = box(0, 0, 150, 120)
LIBRARY = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3})
INFO = SheetInfo(project="Test site", client="A client", architect="An architect",
                 number="SP-01", drawn_by="NK")


@pytest.fixture(scope="module")
def drawing(tmp_path_factory):
    option = solve(PLOT, LIBRARY, REQUEST, abutting_road_m=18.0)[0]
    path = write_sheet_dxf(option, PLOT, REQUEST, INFO,
                           tmp_path_factory.mktemp("sheet") / "option_1.sheet.dxf")
    return ezdxf.readfile(path), option


def test_the_sheet_carries_its_own_layers_and_leaves_the_plan_layers_alone(drawing):
    doc, _ = drawing
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert set(SHEET_LAYERS) <= layers            # sheet furniture is switchable
    assert {"Plot", "Building Plan", "Dwelling Unit"} <= layers  # the plan is still there


def test_every_tower_and_the_site_are_dimensioned(drawing):
    doc, option = drawing
    dims = [e for e in doc.modelspace() if e.dxftype() == "DIMENSION"]
    assert len(dims) == len(option.towers) + 2    # the two site extents, plus each tower


def test_the_sheet_says_what_it_is(drawing):
    doc, _ = drawing
    text = " ".join(e.dxf.text for e in doc.modelspace().query("TEXT"))
    assert "N" in text.split()                    # north arrow
    assert "Test site" in text and "SP-01" in text and "1:" in text
    assert "m" in text                            # scale bar units
    statement = " ".join(e.text for e in doc.modelspace().query("MTEXT"))
    assert "AREA STATEMENT" in statement and "TOTAL AREA OF ALL TOWERS" in statement


def test_towers_and_amenities_are_named_on_the_drawing(drawing):
    doc, option = drawing
    text = " ".join(e.dxf.text for e in doc.modelspace().query("TEXT"))
    assert "FLATS/FLOOR" in text and "TOT-LOT" in text
    assert ("CLUB HOUSE" in text) is (option.club_house is not None)
    for tower in option.towers:
        assert tower.name in text


@pytest.mark.parametrize(("plot", "expected"), [
    (box(0, 0, 60, 40), 100),        # a small site prints large
    (box(0, 0, 150, 120), 250),
    (box(0, 0, 900, 700), 1500),     # a big one steps down the standard scales
])
def test_the_scale_is_the_tightest_standard_one_that_fits(plot, expected):
    assert pick_scale(plot) == expected


def test_a_long_project_name_is_cut_to_the_title_block(tmp_path):
    long_name = "Dhulapally group housing (from the 18-09-2026 PDFs; heights ASSUMED 3 m)"
    option = solve(PLOT, LIBRARY, REQUEST, abutting_road_m=18.0)[0]
    path = write_sheet_dxf(option, PLOT, REQUEST, SheetInfo(project=long_name),
                           tmp_path / "long.sheet.dxf")
    texts = [e.dxf.text for e in ezdxf.readfile(path).modelspace().query("TEXT")]
    heading = [t for t in texts if t.startswith("Dhulapally group housing")]
    assert heading and max(len(t) for t in heading) <= 42
    assert any(t.endswith("…") for t in heading)


def test_the_drawing_fits_inside_the_border(drawing):
    doc, _ = drawing
    frames = [e for e in doc.modelspace().query("LWPOLYLINE[layer=='SHEET-BORDER']")]
    outer = max(frames, key=lambda e: abs(e.get_points("xy")[0][0] - e.get_points("xy")[2][0]))
    xs = [p[0] for p in outer.get_points("xy")]
    ys = [p[1] for p in outer.get_points("xy")]
    plan = [e for e in doc.modelspace().query("LWPOLYLINE[layer=='Plot']")][0]
    px = [p[0] for p in plan.get_points("xy")]
    py = [p[1] for p in plan.get_points("xy")]
    assert min(xs) < min(px) and max(xs) > max(px)
    assert min(ys) < min(py) and max(ys) > max(py)
