"""Survey glue: a CanonicalSiteModel from a project file and the survey that draws it.

The adapter (siteplan.adapters.site_model) turns a project file into the contract but reads no
drawing: it leaves the net plot None unless the project states its outline, and it names a water
body without the lines the survey draws for it. This fills both in from the survey, and nothing
more: a net plot is placed only where the survey or the architect shows where the land given up
lies or draws the net outline itself, never guessed (a surrender whose location is unknown, in
a survey that is not the net outline, leaves the net plot None, and the envelope stops and says
what to give).

This module imports the adapters, which import the generator; the stages themselves
(resolve, envelope, the drawing) do not.
"""

from __future__ import annotations

from pathlib import Path

from shapely.ops import polygonize, unary_union

from siteplan.adapters import site_model
from siteplan.contracts.accounting import LocationHow
from siteplan.contracts.common import Line, SourceKind, shapes_from
from siteplan.contracts.resolved_rules import (
    CIRCULATION_IN_SETBACK,
    STILT_IN_RULE_HEIGHT,
    WhenOpen,
)
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.intake import extract, load_defaults
from siteplan.project import Project
from siteplan.provenance import Provenance, weakest
from siteplan.runner import NET_AREA_TOLERANCE_SQM, load_plot, read_survey

PLACED_BY_ARCHITECT = (LocationHow.OUTLINE, LocationHow.SIDE_AND_WIDTH)


def site_from_project(project: Project, survey: str | Path | None = None, *,
                      site_id: str | None = None) -> CanonicalSiteModel:
    """The site model of a project, with what the survey adds: its roads, marks and place, the
    net plot where it can be placed, and the lines of each named water body."""
    path = Path(survey) if survey else None
    draft = extract(path) if path else None
    boundary = read_survey(path).boundary if path else None
    site = site_model(project, site_id=site_id, boundary=boundary, draft=draft)
    if site.net_plot is None and path is not None:
        is_net = _is_the_net_outline(project, boundary)
        if is_net or _placeable(site):
            by_architect = bool(site.ownership.deductions) and not is_net
            site = site_model(_with_net_plot(project, path, by_architect), site_id=site_id,
                              boundary=boundary, draft=draft)
    return _with_water(site, project, path)


def readings_of(project: Project) -> tuple[dict[str, str], WhenOpen]:
    """The readings of the law a project file states for itself, for `resolve`. Only what the
    file says counts: a request's defaults are not a choice, so an unstated reading stays open
    (ALL) and an unstated conservative mode stays off."""
    layout = project.layout
    stated = layout.model_fields_set if layout is not None else set()
    selections = {}
    if "stilt_in_rule_height" in stated:
        selections[STILT_IN_RULE_HEIGHT] = "counted" if layout.stilt_in_rule_height else (
            "not_counted")
    if "circulation_in_setback" in stated:
        selections[CIRCULATION_IN_SETBACK] = "allowed" if layout.circulation_in_setback else (
            "not_allowed")
    conservative = "conservative_parking" in stated and layout.conservative_parking
    return selections, WhenOpen.CONSERVATIVE if conservative else WhenOpen.STOP


def _placeable(site: CanonicalSiteModel) -> bool:
    """Whether the architect says where the land given up lies (or nothing was given up)."""
    return all(d.location.how in PLACED_BY_ARCHITECT for d in site.ownership.deductions)


def _is_the_net_outline(project: Project, boundary) -> bool:
    """Whether the survey already draws the net plot: its outline is the area the project states
    as net (runner.load_plot then takes it as it is), so no strip needs placing."""
    net = project.site.net_sqm()
    return net is not None and abs(net - boundary.area) <= NET_AREA_TOLERANCE_SQM


def _with_net_plot(project: Project, survey: Path, by_architect: bool) -> Project:
    """The project with the net plot the survey and the answers place (runner.load_plot), its
    source and how far it can be trusted recorded beside it. A survey the firm keeps as one of
    its finished plans makes the outline FIRM_FINISHED_PLAN: for debugging, never a blind run."""
    plot, basis = load_plot(project, survey)
    if survey.name in load_defaults(survey.parent).finished_plans:
        status, kind = Provenance.ASSUMED_FOR_TEST, SourceKind.FIRM_FINISHED_PLAN
    elif by_architect:
        asked = (project.status.get(key, Provenance.USER_CONFIRMED)
                 for key in ("net_area_sqm", "road_strip"))
        status, kind = weakest(*asked), SourceKind.ARCHITECT
    else:
        status, kind = Provenance.EXTRACTED, SourceKind.SURVEY
    out = project.model_copy(deep=True)
    out.site.net_plot_m = [tuple(point) for point in list(plot.exterior.coords)[:-1]]
    out.sources["net_plot_m"] = basis
    out.status["net_plot_m"] = status
    out.source_kinds["net_plot_m"] = kind
    return out


def _with_water(site: CanonicalSiteModel, project: Project,
                survey: Path | None) -> CanonicalSiteModel:
    """Each named water body with the lines the survey draws for it, and any channel they close."""
    if not project.site.water:
        return site
    if survey is None:
        raise ValueError("The project names a water body; give the survey that draws it.")
    bodies = []
    for body, spec in zip(site.water, project.site.water, strict=True):
        lines = read_survey(survey, spec).water
        if not lines:
            raise ValueError(f"The survey has no lines in {spec.survey_colour or spec.survey_layer}"
                             f" for the {spec.kind}.")
        channel = unary_union(list(polygonize(unary_union(lines))))
        bodies.append(body.model_copy(update={
            "lines": [Line(points=list(line.coords)) for line in lines],
            "channel": shapes_from(channel)}))
    return site.model_copy(update={"water": bodies})
