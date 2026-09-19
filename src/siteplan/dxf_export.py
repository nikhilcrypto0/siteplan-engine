"""Write a survey as a DXF that opens in ZWCAD, using BuildNow plugin layer names.

Layer names follow the BuildNow plugin's layer index
(buildnow.floww.ai/docs/layers-tutorials/layers-index). Whether the plugin accepts a
drawing that already uses these names, or needs them re-marked in its own UI, has not
been tested yet: that needs ZWCAD 2025 with the plugin installed.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from shapely.geometry import Polygon

from siteplan.survey import Survey
from siteplan.units import format_acre_gunta

# BuildNow layer name -> AutoCAD colour index used for it here.
BUILDNOW_LAYERS = {
    "Plot": 6,  # magenta
    "Net Plot": 200,
    "Road": 1,  # red
    "Contour Plan": 30,  # orange
}
SPOT_LEVEL_LAYER = "SURVEY-SPOT-LEVELS"  # not a BuildNow layer; kept for the architect
NOTES_LAYER = "SURVEY-NOTES"  # not a BuildNow layer
SPOT_LEVEL_TEXT_HEIGHT_M = 0.8
NOTE_TEXT_HEIGHT_M = 3.0


def _open_ring(polygon: Polygon) -> list[tuple[float, float]]:
    return [(x, y) for x, y in list(polygon.exterior.coords)[:-1]]


def write_survey_dxf(survey: Survey, path: str | Path, net_plot: Polygon | None = None) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    for name, colour in BUILDNOW_LAYERS.items():
        doc.layers.add(name, color=colour)
    doc.layers.add(SPOT_LEVEL_LAYER, color=5)
    doc.layers.add(NOTES_LAYER, color=7)
    msp = doc.modelspace()

    msp.add_lwpolyline(_open_ring(survey.boundary), close=True, dxfattribs={"layer": "Plot"})
    if survey.stated_area_sqm:
        # Carry the surveyor's written area so a read-back can still cross-check the boundary.
        minx, miny, _, _ = survey.boundary.bounds
        msp.add_text(
            f"SURVEYED AREA: {format_acre_gunta(survey.stated_area_sqm)}",
            height=NOTE_TEXT_HEIGHT_M,
            dxfattribs={"layer": NOTES_LAYER},
        ).set_placement((minx, miny - 4 * NOTE_TEXT_HEIGHT_M))
    if net_plot is not None:
        msp.add_lwpolyline(_open_ring(net_plot), close=True, dxfattribs={"layer": "Net Plot"})
    for road in survey.roads:
        msp.add_lwpolyline(list(road.coords), dxfattribs={"layer": "Road"})
    for contour in survey.contours:
        msp.add_lwpolyline(list(contour.coords), dxfattribs={"layer": "Contour Plan"})
    for level in survey.levels:
        msp.add_point((level.x, level.y, level.z), dxfattribs={"layer": SPOT_LEVEL_LAYER})
        msp.add_text(
            f"{level.z:.2f}",
            height=SPOT_LEVEL_TEXT_HEIGHT_M,
            dxfattribs={"layer": SPOT_LEVEL_LAYER},
        ).set_placement((level.x, level.y))

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    return out
