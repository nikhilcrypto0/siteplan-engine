"""Run the layout solver for a project and write every option's files.

Shared by `siteplan layout` and the assistant, so both produce identical outputs.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import polygonize, unary_union

from siteplan import rules
from siteplan.area_statement import render
from siteplan.dxf_survey import DxfProfile, read_dxf_survey
from siteplan.geometry import less_road_strip
from siteplan.layout import LayoutRequest, area_statement, solve
from siteplan.layout_export import write_layout_dxf, write_layout_svg
from siteplan.library import FlatLibrary
from siteplan.pdf_survey import PdfProfile, read_pdf_survey
from siteplan.project import Project, WaterIn
from siteplan.sheet import SheetInfo, write_sheet_dxf
from siteplan.site_amenities import AmenityLibrary
from siteplan.survey import Survey

NET_AREA_TOLERANCE_SQM = 50.0  # drafting slop between a survey and a stated area

LAYOUT_CAVEAT = (
    "Layouts are first drafts for an architect. They now include the amenities block, the "
    "drive, surface parking bays and the gates, but the entry and exit assume the longest "
    "boundary faces the road, and cellar or podium parking, ramps and landscaping are not "
    "modelled. They use whatever flat library they are given."
)


def read_survey(path: Path, water: WaterIn | None = None) -> Survey:
    """Read a survey; with a water body named, its lines come back as Survey.water."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        colour = water.survey_colour if water else None
        rgb = tuple(round(int(colour[i:i + 2], 16) / 255, 3) for i in (1, 3, 5)) if colour else None
        return read_pdf_survey(path, PdfProfile(water_colour=rgb) if rgb else None)
    if suffix == ".dxf":
        layer = water.survey_layer if water else None
        return read_dxf_survey(path, DxfProfile(water_layer_hint=layer) if layer else None)
    if suffix == ".dwg":
        raise ValueError("DWG is not read directly. Save it as DXF in ZWCAD first.")
    raise ValueError(f"Unsupported survey file type: {path.suffix}")


def load_water(project: Project, survey: str | Path | None) -> tuple[Polygon | None, str]:
    """The land no block may stand on: each water body the project names, with its rule
    3(a)(ii) buffer round the lines the survey draws for it (and any channel those lines close),
    and a sentence saying what it is. None when the project names no water."""
    if not project.site.water:
        return None, ""
    if not survey:
        raise ValueError("The project names a water body; give the survey that draws it.")
    zones, parts = [], []
    for water in project.site.water:
        where = water.survey_colour or water.survey_layer
        lines = read_survey(Path(survey), water).water
        if not lines:
            raise ValueError(f"The survey has no lines in {where} for the {water.kind}.")
        drawn = unary_union(lines)
        buffer_m = rules.WATER_BUFFER_M[water.kind]
        zones.append(unary_union([drawn.buffer(buffer_m), *polygonize(drawn)]))
        parts.append(f"{water.kind.replace('_', ' ')} drawn in {where}: {buffer_m:g} m kept clear")
    return unary_union(zones), "; ".join(parts) + f" ({rules.WATER_BUFFER_CLAUSE})"


def load_plot(project: Project, survey: str | Path | None) -> tuple[Polygon, str]:
    """The plot to plan on, and a sentence saying where it came from."""
    if project.site.net_plot_m:
        return Polygon(project.site.net_plot_m), "net plot from the project file"
    if survey:
        boundary = read_survey(Path(survey)).boundary
        net = project.site.net_sqm()
        if net and net < boundary.area - NET_AREA_TOLERANCE_SQM:
            plot = less_road_strip(boundary, net)
            return plot, (
                f"surveyed boundary {boundary.area:,.0f} m², less the "
                f"{boundary.area - net:,.0f} m² the project states is deducted. ASSUMED: it "
                "comes off the longest boundary as a road-widening strip. For the real shape, "
                "give the architect's site-plan DXF as the survey (its plot outline is the net "
                "plot, strip already cut) or net_plot_m in the project file."
            )
        if net and abs(net - boundary.area) <= NET_AREA_TOLERANCE_SQM:
            return boundary, (f"plot outline {boundary.area:,.0f} m², matching the {net:,.0f} m² "
                              "the project states is net: taken as the net plot")
        return boundary, "surveyed boundary (road-widening strip, if any, NOT deducted)"
    raise ValueError("Give a survey file, or net_plot_m in the project file.")


def run_layout(
    project: Project,
    library: FlatLibrary,
    plot: Polygon,
    request: LayoutRequest,
    out: Path,
    amenities: AmenityLibrary | None = None,
    keep_out: Polygon | None = None,
) -> list[dict]:
    site = project.to_site()
    options = solve(
        plot,
        library,
        request,
        gross_area_sqm=site.gross_area_sqm,
        abutting_road_m=site.abutting_road_m,
        master_plan_road_m=site.master_plan_road_m,
        authority=site.authority,
        amenities=amenities,
        keep_out=keep_out,
    )
    summaries = []
    for i, option in enumerate(options, 1):
        stem = out / f"option_{i}"
        write_layout_dxf(option, plot, stem.with_suffix(".dxf"))
        write_sheet_dxf(option, plot, request, SheetInfo(project=project.name,
                                                         **project.sheet.model_dump()),
                        out / f"option_{i}.sheet.dxf")
        write_layout_svg(option, plot, stem.with_suffix(".svg"), f"{project.name}: option {i}")
        summary = {"option": i} | option.summary() | {
            "area_statement": render(area_statement(option, request)),
            "sheet_dxf": str(out / f"option_{i}.sheet.dxf"),
            "flat_library_note": library.note,
            "caveat": LAYOUT_CAVEAT,
        }
        stem.with_suffix(".json").write_text(json.dumps(summary, indent=2))
        summaries.append(summary)
    return summaries
