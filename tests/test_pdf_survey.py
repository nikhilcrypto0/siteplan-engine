"""The PDF reader, tested on a survey sheet built from scratch (no client data)."""

import math

import pytest
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas

from siteplan.pdf_survey import read_pdf_survey
from siteplan.units import format_acre_gunta

L_SHAPE_M = [(0, 0), (120, 0), (120, 60), (70, 60), (70, 100), (0, 100)]  # 10,000 m²
ORIGIN = (150, 120)


def _to_pt(scale):
    metres_per_pt = 0.0254 / 72 * scale
    return lambda x_m, y_m: (ORIGIN[0] + x_m / metres_per_pt, ORIGIN[1] + y_m / metres_per_pt)


def _label(c, _pt, a, b, text):
    (x1, y1), (x2, y2) = _pt(*a), _pt(*b)
    angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
    nx, ny = -(y2 - y1), x2 - x1
    norm = math.hypot(nx, ny)
    c.saveState()
    c.translate((x1 + x2) / 2 + 8 * nx / norm, (y1 + y2) / 2 + 8 * ny / norm)
    c.rotate(angle)
    c.drawCentredString(0, 0, text)
    c.restoreState()


def _build_sheet(path, wrong_label=True, area_text=None, scale=500, factor=1):
    """An L-shaped plot, `factor` times 120 m x 100 m, plotted at 1:`scale`."""
    _pt = _to_pt(scale)
    shape = [(x * factor, y * factor) for x, y in L_SHAPE_M]
    if area_text is None:
        area_text = f"TOTAL LAND AREA: {format_acre_gunta(10000 * factor**2)}"
    c = canvas.Canvas(str(path), pagesize=landscape(A3))
    width, height = landscape(A3)
    c.setStrokeColorRGB(0, 0, 0)
    c.rect(20, 20, width - 40, height - 40)  # sheet frame
    c.rect(width - 260, 40, 220, 300)  # title block
    c.setFont("Helvetica", 8)
    c.drawString(width - 250, 300, area_text)
    c.drawString(width - 250, 280, "Scale: 1:1000")  # deliberately wrong, as on real sheets

    c.setStrokeColorRGB(1, 0, 1)  # boundary
    ring = shape + [shape[0]]
    for a, b in zip(ring, ring[1:], strict=False):
        c.line(*_pt(*a), *_pt(*b))
    c.setFillColorRGB(0, 0, 0)
    for i, (a, b) in enumerate(zip(ring, ring[1:], strict=False)):
        true_length = math.dist(a, b)
        shown = true_length * 0.9 if (wrong_label and i == 3) else true_length
        _label(c, _pt, a, b, f"{shown:.2f}")

    c.setFillColorRGB(0, 0, 1)  # spot levels: falling from west (588) to east (585)
    for x, y in [(10, 10), (60, 30), (110, 50), (30, 80), (60, 90), (100, 20)]:
        c.drawString(*_pt(x * factor, y * factor), f"{588 - 3 * x / 120:.2f}")
    c.drawString(*_pt(140 * factor, 30 * factor), "584.10")  # off site

    c.setStrokeColorRGB(1, 0, 0)  # a road
    c.line(*_pt(-10 * factor, -8 * factor), *_pt(130 * factor, -8 * factor))
    c.save()
    return path


def test_reads_boundary_scale_levels_from_a_vector_sheet(tmp_path):
    survey = read_pdf_survey(_build_sheet(tmp_path / "sheet.pdf"))
    assert survey.area_sqm == pytest.approx(10000, rel=1e-3)
    assert survey.stated_area_sqm == pytest.approx(10000, rel=1e-3)
    assert survey.calibration.snapped_scale == 500
    assert [e.written_m for e in survey.calibration.rejected] == [pytest.approx(36.0)]  # 40 m edge
    assert sum(lv.on_site for lv in survey.levels) == 6
    assert sum(not lv.on_site for lv in survey.levels) == 1
    terrain = survey.terrain()
    assert terrain.falls_towards == "E"
    assert terrain.slope_pct == pytest.approx(2.5, abs=0.3)
    assert len(survey.roads) == 1


def test_without_written_area_it_still_calibrates_but_warns(tmp_path):
    sheet = _build_sheet(tmp_path / "noarea.pdf", area_text="AREA DETAILS")
    survey = read_pdf_survey(sheet)
    assert survey.area_sqm == pytest.approx(10000, rel=1e-3)
    assert any("No area was written" in w for w in survey.warnings)


def test_long_edges_labelled_in_the_level_range_are_dimensions_not_levels(tmp_path):
    # 600 m x 500 m plot at 1:2000: the 600 m and 500 m labels look like spot levels by size.
    survey = read_pdf_survey(_build_sheet(tmp_path / "big.pdf", scale=2000, factor=5))
    assert survey.area_sqm == pytest.approx(250000, rel=1e-3)
    assert survey.calibration.snapped_scale == 2000
    agreeing = sorted(e.written_m for e in survey.calibration.agreeing)
    assert agreeing == [250.0, 300.0, 350.0, 500.0, 600.0]
    assert all(583 < lv.z < 589 for lv in survey.levels)  # no 500 or 600 posing as a level
    assert sum(lv.on_site for lv in survey.levels) == 6


def test_sheet_without_dimension_labels_is_refused(tmp_path):
    path = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(path), pagesize=landscape(A3))
    c.setStrokeColorRGB(1, 0, 1)
    c.rect(200, 200, 300, 200)
    c.save()
    with pytest.raises(ValueError, match="dimension labels"):
        read_pdf_survey(path)
