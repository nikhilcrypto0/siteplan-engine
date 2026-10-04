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
from siteplan.geometry import strip_along_side
from siteplan.heights import HeightSearch, search_heights
from siteplan.layout import LayoutRequest, SiteFacts, area_statement
from siteplan.layout import stop_reason as _stop_reason
from siteplan.layout_export import write_layout_dxf, write_layout_svg
from siteplan.library import FlatLibrary
from siteplan.pdf_survey import PdfProfile, read_pdf_survey
from siteplan.project import Project, WaterIn
from siteplan.provenance import confirmed
from siteplan.sheet import SheetInfo, write_sheet_dxf
from siteplan.site_amenities import AmenityLibrary
from siteplan.survey import Survey

NET_AREA_TOLERANCE_SQM = 50.0  # drafting slop between a survey and a stated area
STRIP_AREA_TOLERANCE = 0.02  # a described strip may differ from the stated deduction by this

LAYOUT_CAVEAT = (
    "Layouts are first drafts for an architect. Each carries the rule 8(m) internal roads, the "
    "NBC fire lanes with their 9 m turns, the tot-lot, the club house, the cellars and ramp that "
    "Table V's parking needs, the facilities and surface bays, and has passed every rule the "
    "checker applies. Not modelled: podium parking (unsupported), blocks of mixed heights, "
    "landscaping, and the 45 t specification of the paving and the cellar roof. They use "
    "whatever flat library they are given."
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
    """The plot to plan on, and a sentence saying where it came from. Setbacks are measured on
    the net plot (rules.SETBACK_ON_NET_PLOT_CLAUSE), so land given up for road widening comes
    off first; where it lies is taken from a drawing or the architect, never guessed from the
    area alone."""
    if project.site.net_plot_m:
        return Polygon(project.site.net_plot_m), "net plot from the project file"
    if survey:
        boundary = read_survey(Path(survey)).boundary
        net = project.site.net_sqm()
        if net and net < boundary.area - NET_AREA_TOLERANCE_SQM:
            return _less_strip(project, boundary, net)
        if net and abs(net - boundary.area) <= NET_AREA_TOLERANCE_SQM:
            return boundary, (f"plot outline {boundary.area:,.0f} m², matching the {net:,.0f} m² "
                              "the project states is net: taken as the net plot")
        return boundary, "surveyed boundary (road-widening strip, if any, NOT deducted)"
    raise ValueError("Give a survey file, or net_plot_m in the project file.")


def _less_strip(project: Project, boundary: Polygon, net: float) -> tuple[Polygon, str]:
    """The boundary less the strip the architect describes; refused when nobody has said where
    it lies, or when what they describe does not come to the deduction they state."""
    site = project.site
    deducted = boundary.area - net
    if site.road_strip_m:
        rest = boundary.difference(Polygon(site.road_strip_m))
        parts = [p for p in getattr(rest, "geoms", [rest]) if p.geom_type == "Polygon"]
        plot, how = max(parts, key=lambda p: p.area), "the strip outline in the project file"
    elif site.road_strip_side and site.road_strip_width_m:
        plot = strip_along_side(boundary, site.road_strip_side, site.road_strip_width_m)
        how = (f"a {site.road_strip_width_m:g} m strip along the {site.road_strip_side} side, "
               "as the architect gave it")
    else:
        raise ValueError(
            f"The project states {deducted:,.0f} m² is given up for road widening, but neither "
            "the survey nor the answers show where it lies. Give the side and the width of the "
            "strip (road_strip_side and road_strip_width_m), its outline (road_strip_m), or the "
            "net plot outline (net_plot_m). The engine does not guess a strip's location.")
    taken = boundary.area - plot.area
    if abs(taken - deducted) > max(NET_AREA_TOLERANCE_SQM, STRIP_AREA_TOLERANCE * deducted):
        raise ValueError(
            f"{how.capitalize()} takes {taken:,.0f} m², but the project states {deducted:,.0f} m² "
            "is given up: the strip does not lie as described (it may run along only part of "
            "the side). Give its outline (road_strip_m) or the net plot outline (net_plot_m).")
    return plot, (f"surveyed boundary {boundary.area:,.0f} m², less {taken:,.0f} m² of road "
                  f"widening: {how} ({rules.SETBACK_ON_NET_PLOT_CLAUSE})")


def site_facts(project: Project, keep_out: Polygon | None = None) -> SiteFacts:
    """What the project knows about the site besides its shape, as the layout needs it. Whose
    rules apply counts as settled only when the answers behind it are confirmed."""
    s, site = project.site, project.to_site()
    settled = all(confirmed(project.status.get(key)) for key in ("authority", "inside_cure")
                  if key in project.status)
    return SiteFacts(
        gross_area_sqm=site.gross_area_sqm, abutting_road_m=site.abutting_road_m,
        master_plan_road_m=site.master_plan_road_m, authority=site.authority,
        inside_cure=site.inside_cure, keep_out=keep_out, access_side=s.access_side,
        road_dead_end=s.road_dead_end, street_joins_12m=s.street_joins_12m,
        jurisdiction_confirmed=settled, site_coordinates=s.site_coordinates,
    )


class NoLayout(ValueError):
    """No height has a layout that passes. The message gives every height tried, its verdict
    and the reasons the search recorded, so the caller never has to guess why."""


def why_none(found: HeightSearch) -> str:
    """Every height tried, top down, with its verdict and why it gave no layout."""
    lines = ["No layout passes at any height tried. Height by height, top down:"]
    for r in found.results:
        reasons = "; ".join(r.reasons()) or "no reason was recorded"
        lines.append(f"- stilt + {r.floors} ({r.height_m:g} m): {r.verdict}: {reasons}")
    return "\n".join(lines)


def stop_reason(project: Project, plot: Polygon, request: LayoutRequest,
                keep_out: Polygon | None = None) -> str | None:
    """Why no height can be tried at all (layout.stop_reason), asked before any approval."""
    return _stop_reason(plot, request, site_facts(project, keep_out))


def run_search(project: Project, library: FlatLibrary, plot: Polygon, request: LayoutRequest,
               amenities: AmenityLibrary | None = None,
               keep_out: Polygon | None = None) -> HeightSearch:
    """The legacy height search for a project. LEGACY, not for production generation by a
    language model: kept for regression comparison; production is `siteplan.service`."""
    return search_heights(plot, library, request, site_facts(project, keep_out), amenities)


def run_layout(
    project: Project,
    library: FlatLibrary,
    plot: Polygon,
    request: LayoutRequest,
    out: Path,
    amenities: AmenityLibrary | None = None,
    keep_out: Polygon | None = None,
) -> list[dict]:
    """The legacy layouts, written as files. LEGACY, not for production generation by a
    language model: kept for regression comparison; production is `siteplan.service`."""
    found = run_search(project, library, plot, request, amenities, keep_out)
    if not found.options:
        raise NoLayout(why_none(found))
    return write_options(found, project, library, plot, request, out)


def heights_table(found: HeightSearch) -> list[dict]:
    """One row per height tried: the verdict and, when it fails, exactly why."""
    return [{"floors_above_stilt": r.floors, "height_m": round(r.height_m, 2),
             "verdict": r.verdict, "reasons": r.reasons(),
             "best_saleable_sqft": round(max((o.saleable_sqft for o in r.options), default=0))}
            for r in found.results]


def write_options(found: HeightSearch, project: Project, library: FlatLibrary, plot: Polygon,
                  request: LayoutRequest, out: Path) -> list[dict]:
    """Every option's drawings and summary, each at its own height."""
    tried = heights_table(found) if request.maximise else []
    summaries = []
    for i, option in enumerate(found.options, 1):
        at = request.model_copy(update={"floors": option.floors})
        stem = out / f"option_{i}"
        write_layout_dxf(option, plot, stem.with_suffix(".dxf"))
        write_sheet_dxf(option, plot, at, SheetInfo(project=project.name,
                                                    **project.sheet.model_dump()),
                        out / f"option_{i}.sheet.dxf")
        write_layout_svg(option, plot, stem.with_suffix(".svg"), f"{project.name}: option {i}")
        summary = {"option": i, "floors_above_stilt": option.floors} | option.summary() | {
            "area_statement": render(area_statement(option, at)),
            "sheet_dxf": str(out / f"option_{i}.sheet.dxf"),
            "flat_library_note": library.note,
            "caveat": LAYOUT_CAVEAT,
        } | ({"heights_tried": tried} if tried else {})
        stem.with_suffix(".json").write_text(json.dumps(summary, indent=2))
        summaries.append(summary)
    return summaries
