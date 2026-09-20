"""Run the layout solver for a project and write every option's files.

Shared by `siteplan layout` and the assistant, so both produce identical outputs.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Polygon

from siteplan.area_statement import render
from siteplan.dxf_survey import read_dxf_survey
from siteplan.layout import LayoutRequest, area_statement, solve
from siteplan.layout_export import write_layout_dxf, write_layout_svg
from siteplan.library import FlatLibrary
from siteplan.pdf_survey import read_pdf_survey
from siteplan.project import Project
from siteplan.sheet import SheetInfo, write_sheet_dxf
from siteplan.survey import Survey

LAYOUT_CAVEAT = (
    "Layouts are first drafts for an architect. They now include the amenities block, the "
    "drive, surface parking bays and the gates, but the entry and exit assume the longest "
    "boundary faces the road, and cellar or podium parking, ramps and landscaping are not "
    "modelled. They use whatever flat library they are given."
)


def read_survey(path: Path) -> Survey:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_survey(path)
    if suffix == ".dxf":
        return read_dxf_survey(path)
    if suffix == ".dwg":
        raise ValueError("DWG is not read directly. Save it as DXF in ZWCAD first.")
    raise ValueError(f"Unsupported survey file type: {path.suffix}")


def load_plot(project: Project, survey: str | Path | None) -> tuple[Polygon, str]:
    """The plot to plan on, and a sentence saying where it came from."""
    if project.site.net_plot_m:
        return Polygon(project.site.net_plot_m), "net plot from the project file"
    if survey:
        boundary = read_survey(Path(survey)).boundary
        return boundary, "surveyed boundary (road-widening strip, if any, NOT deducted)"
    raise ValueError("Give a survey file, or net_plot_m in the project file.")


def run_layout(
    project: Project,
    library: FlatLibrary,
    plot: Polygon,
    request: LayoutRequest,
    out: Path,
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
