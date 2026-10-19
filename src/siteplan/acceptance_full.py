"""Acceptance on the production search (2026-10-18): the raw survey and the answers, run through the
service's full search with the readings the project selects, every layout judged by the
independent validator; the firm's plan read only once the layouts exist, and measured the same way.

`siteplan acceptance` runs this. The legacy flow (`acceptance.generate`, the legacy layout and its
checker) is kept only for the regression baseline it pins (tests/client_baseline.py), as the other
legacy paths are.

The service is given a workspace of its own inside the run's folder: the firm's settings and
libraries, the survey and the project built from the answers, since it reads nothing else. Its
approval is the acceptance command itself, which the architect ran to get exactly this search;
the run's audit records it under that channel. A blind run is the service's BLIND mode, which
refuses the firm's finished plan as the acceptance always has.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Polygon

from siteplan.acceptance import _inputs, _unresolved, spacing
from siteplan.area_statement import AreaStatement
from siteplan.blind import BLIND, DEBUG, BlindLeak, finished_values
from siteplan.blind import check as check_blind
from siteplan.cases import Case
from siteplan.constraints import Basis, by_basis
from siteplan.contracts import CandidateLayout, ValidationReport
from siteplan.intake import WORKSPACE_FILE, Draft, build_project, extract, load_defaults, save
from siteplan.intake import render as render_draft
from siteplan.max_floors import FloorLimit, max_floors
from siteplan.optimizer.search.verdicts import rests_on
from siteplan.profiles import AssumptionProfile, apply_profile, describe
from siteplan.project import Project
from siteplan.provenance import Provenance
from siteplan.service import HeightChoice, Intent, Mode, ProposeLayouts, Service, store
from siteplan.service import describe as describe_layout
from siteplan.service.models import ProposeResult, ProposeStatus

SQFT = 10.7639
PROJECT_FILE = "acceptance.project.json"


class AcceptanceCommand:
    """The approval channel of an acceptance run: the architect ran the command to get exactly
    this search, so the command is the yes; the audit records the channel by this name."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, list[str]]] = []

    def approve(self, title: str, lines: list[str]) -> bool:
        self.asked.append((title, list(lines)))
        return True


@dataclass(frozen=True)
class FullRun:
    draft: Draft
    project: dict
    out: Path
    limit: FloorLimit
    result: ProposeResult
    shown: tuple[tuple[CandidateLayout, ValidationReport], ...]
    net: Polygon | None
    basis: str
    standards: dict
    profile: AssumptionProfile | None = None
    mode: str = BLIND

    @property
    def best(self) -> tuple[CandidateLayout, ValidationReport] | None:
        """The layout shown for maximum yield, else the first shown."""
        return next((s for s in self.shown if s[0].pareto_tag == "MAX_YIELD"),
                    self.shown[0] if self.shown else None)


def _service_workspace(folder: Path, workspace: Path, survey: Path, project: dict) -> Path:
    """The firm's settings and the libraries they name, the survey and the project, copied into
    a folder of the run's own: the service reads nothing outside its workspace."""
    folder.mkdir(parents=True, exist_ok=True)
    settings = workspace / WORKSPACE_FILE
    if settings.exists():
        defaults = load_defaults(workspace)
        named = defaults.model_dump(exclude={"status"})
        for key in ("flat_library", "amenities"):
            if defaults.model_dump().get(key):
                source = (workspace / named[key]).resolve()
                shutil.copy(source, folder / source.name)
                named[key] = source.name
        (folder / WORKSPACE_FILE).write_text(defaults.model_validate(
            {**named, "status": defaults.status}).model_dump_json(exclude_defaults=True))
    shutil.copy(survey, folder / survey.name)
    save(project, folder / PROJECT_FILE)
    return folder


def generate(survey: Path, answers: dict, out: Path, workspace: Path | None = None,
             conservative_parking: bool = False, profile: AssumptionProfile | None = None,
             mode: str = BLIND) -> FullRun:
    """The project from the survey and the answers (as `acceptance.generate` builds it), then the
    service's full search on it, with the readings and the application status the project
    states; a blind run refuses anything taken from the firm's finished plan."""
    workspace = workspace or survey.parent
    defaults = load_defaults(workspace)
    check_blind(mode, survey, answers, profile, defaults.finished_plans)
    if not defaults.flat_library:
        raise ValueError(f"Set the firm's flat_library in {workspace}/{WORKSPACE_FILE}.")
    draft = extract(survey)
    project = build_project(draft, answers, defaults)
    if conservative_parking:
        project["layout"]["conservative_parking"] = True
        project["sources"]["conservative_parking"] = "run in the conservative test mode"
        project["status"]["conservative_parking"] = Provenance.ASSUMED_FOR_TEST
    if profile is not None:
        project = apply_profile(project, profile)
    leaked = finished_values(project)
    if mode == BLIND and leaked:
        raise BlindLeak(f"A blind acceptance run may not use the firm's finished plan: {leaked}")
    out.mkdir(parents=True, exist_ok=True)
    save(project, out / "project.json")
    model = Project.model_validate(project)
    site = model.to_site()
    limit = max_floors(model.site.net_sqm() or draft.area_sqm, site.abutting_road_m,
                       model.layout.floor_height_m, model.layout.stilt_height_m,
                       model.site.road_dead_end)
    folder = _service_workspace(out / "service-workspace", workspace, survey, project)
    service = Service(folder, out / "runs", AcceptanceCommand(),
                      mode=Mode.DEBUG if mode == DEBUG else Mode.BLIND)
    most = bool(model.layout.maximise)
    intent = (Intent(height=HeightChoice.MOST_THE_RULES_ALLOW) if most else
              Intent(height=HeightChoice.FLOORS_ABOVE_STILT,
                     floors_above_stilt=model.layout.floors))
    words = ("The most floors the rules allow" if most else
             f"Stilt + {model.layout.floors}") + ", the unit mix the project gives"
    result = service.propose_layouts(ProposeLayouts(
        project_file=PROJECT_FILE, survey_file=survey.name, brief=words, intent=intent))
    shown: list[tuple[CandidateLayout, ValidationReport]] = []
    net, basis = None, ""
    if result.run_id:
        record = store.read_record(out / "runs", result.run_id)
        shown = [(store.load_candidate(out / "runs", record, s.candidate_id),
                  store.load_report(out / "runs", record, s.candidate_id))
                 for s in record.candidates]
        site_model = store.load_inputs(out / "runs", record).site
        if site_model.net_plot is not None:
            net = site_model.net_plot.value.to_shapely()
            basis = site_model.net_plot.source
    return FullRun(draft, project, out, limit, result, tuple(shown), net, basis,
                   defaults.model_dump(exclude={"status"}), profile, mode)


def _floor_sqm(candidate: CandidateLayout) -> float:
    """Every floor of every tower, wall to wall: what a firm's area statement prints."""
    protos = {p.id: p for p in candidate.prototypes_used}
    return sum(protos[t.prototype_id].per_floor.gross_floor_sqm * t.floors_above_stilt
               for t in candidate.towers)


def _said(report: ValidationReport, rule_start: str) -> str:
    check = next((c for c in report.legal if c.finding.rule.startswith(rule_start)), None)
    if check is None:
        return "not reported"
    status = (check.selected_status or check.finding.status).value
    return f"{status}: {check.finding.measured}"


def _rests(report: ValidationReport) -> str:
    readings = rests_on(report).readings
    return ", ".join(f"{k} ({'/'.join(v)})" for k, v in readings.items()) or "no open reading"


def compare(run: FullRun, case: Case, statement: AreaStatement | None = None
            ) -> list[tuple[str, str, str]]:
    """The engine's best layout against the firm's plan, measure by measure, both measured the
    same way (acceptance.spacing on the tower outlines and the net plot)."""
    candidate, report = run.best
    towers = [candidate.placed_footprint(t) for t in candidate.towers]
    setback, gap = spacing(run.net, towers)
    firm_plot = Polygon(case.net_plot)
    firm_setback, firm_gap = spacing(firm_plot, [Polygon(b.outline) for b in case.buildings])
    floors = sorted({t.floors_above_stilt for t in candidate.towers})
    floor_sqft = _floor_sqm(candidate) * SQFT
    rows = [
        ("Net plot", f"{run.net.area:,.0f} m²", f"{firm_plot.area:,.0f} m²"),
        ("Towers", str(len(candidate.towers)), str(len(case.buildings))),
        ("Floors above the stilt", ", ".join(f"stilt + {f}" for f in floors),
         ", ".join(f"{b.name} stilt + {b.floors}" for b in case.buildings)),
        ("Least setback from the plot line", f"{setback:.2f} m", f"{firm_setback:.2f} m"),
        ("Least gap between towers", f"{gap:.2f} m" if gap else "one tower",
         f"{firm_gap:.2f} m" if firm_gap else "one tower"),
        ("Organised open space", _said(report, "Organized open space"),
         f"{case.open_space_sqm:,.0f} m² drawn" if case.open_space_sqm else "not given"),
        ("Flats", str(candidate.metrics.total_flats), "not in the area statement"),
    ]
    if statement is not None:
        firm_area = sum(g.subtotal_sqft for g in statement.groups)
        loading = statement.groups[0].common_area_pct
        rows += [
            ("Tower floor area, all floors, no loading", f"{floor_sqft:,.0f} sft",
             f"{firm_area:,.0f} sft (engine {(floor_sqft / firm_area - 1) * 100:+.1f}%)"),
            (f"The same with the firm's {loading:g}% loading (its statement's total)",
             f"{floor_sqft * (1 + loading / 100):,.0f} sft", f"{statement.total_sqft:,} sft"),
        ]
    rows += [
        ("Saleable from the flats' own sale areas", f"{candidate.metrics.saleable_sqft:,.0f} sft",
         "not in the area statement"),
        ("Club house", _said(report, "Amenities"), "as the firm's drawing shows it"),
        ("Parking", _said(report, "Parking (Table V)"), "as the firm's drawing shows it"),
        ("Verdict (the independent validator)",
         f"{report.verdict.legal.value}, resting on {_rests(report)}",
         f"{len(case.known_disagreements)} rule FAILs known, as the case records"),
    ]
    return rows


def _layout(candidate: CandidateLayout, report: ValidationReport, net: Polygon,
            shown: list[CandidateLayout]) -> list[str]:
    protos = {p.id: p for p in candidate.prototypes_used}
    feet = [candidate.placed_footprint(t) for t in candidate.towers]
    setback, gap = spacing(net, feet)
    head = candidate.pareto_tag or "a further different idea"
    lines = [f"  {candidate.candidate_id} ({head}): "
             f"{describe_layout.describe(candidate, net, shown)}"]
    for t, foot in zip(candidate.towers, feet, strict=True):
        p = protos[t.prototype_id]
        lines.append(f"    {t.name}: {p.id}, {p.length_m:.1f} x {p.depth_m:.1f} m, stilt + "
                     f"{t.floors_above_stilt}, {p.per_floor.flats} flats a floor, "
                     f"{p.per_floor.flats * t.floors_above_stilt} flats; footprint "
                     f"{foot.area:,.0f} m²")
    m = candidate.metrics
    lines += [
        f"    Flats: {m.total_flats} ({', '.join(f'{k} {v}' for k, v in m.flats_by_type.items())});"
        f" saleable {m.saleable_sqft:,.0f} sft; tower floor {_floor_sqm(candidate) * SQFT:,.0f}"
        " sft (every floor, wall to wall)",
        f"    Least setback {setback:.2f} m; least gap {f'{gap:.2f} m' if gap else 'one tower'}"
        " (measured on the outlines, as the firm's plan is)",
        f"    Tot-lot: {_said(report, 'Organized open space')}",
        f"    Club house: {_said(report, 'Amenities')}",
        f"    Parking: {_said(report, 'Parking (Table V)')}",
        f"    Verdict: {report.verdict.legal.value} (the study's: "
        f"{report.verdict.study.value if report.verdict.study else '-'}); resting on "
        f"{_rests(report)}",
    ]
    return lines


def report(run: FullRun, rows: list[tuple[str, str, str]]) -> str:
    """Plain text for the terminal and the report file; its first sections are the legacy
    report's own (what the survey settled, the inputs, what is unresolved)."""
    project, profile = run.project, run.profile
    debug = run.mode == DEBUG or (profile is not None and profile.debug_fixture)
    result = run.result
    lines = [
        f"{'DEBUG RUN (test fixture, not blind acceptance)' if debug else 'ACCEPTANCE'}: "
        f"{project['name']}",
        "The plot outline comes from the firm's finished plan; the towers, roads and everything "
        "else were generated, and the firm's plan was read again only for the comparison."
        if debug else
        "The generator saw the raw survey, the answers and the firm's standard libraries; the "
        "firm's plan for this site was read only for the comparison at the end.",
        "Generated by the service's full search with the readings the project selects; every "
        "layout judged by the independent validator.",
        "",
        *(["0. TEST PROFILE: TEMPORARY ASSUMPTIONS FOR THIS SITE ONLY", *describe(profile), ""]
          if profile is not None else []),
        "1. EXTRACTED FROM THE SURVEY",
        *("  " + line.strip() for line in render_draft(run.draft).splitlines()[1:]),
        f"  plot planned on: {run.net.area:,.0f} m², {run.basis}" if run.net is not None else
        "  plot planned on: the net plot could not be placed",
        "",
        "2. INPUTS AND HOW FAR EACH IS TRUSTED",
        *_inputs(project, run.standards),
        "",
        "3. UNRESOLVED FACTS AND ASSUMPTIONS",
        *_unresolved(project),
        "  UNRESOLVED_INTERPRETATION: the engine's readings of what the orders leave open, each "
        "taken for this test (siteplan constraints lists what would settle each):",
        *(f"    - {c.what} {c.value}." for c in by_basis(Basis.UNRESOLVED_INTERPRETATION)),
        "  ENGINE_DESIGN_ASSUMPTION: the engine's own numbers, neither law nor the firm's "
        "standards:",
        *(f"    - {c.what} {c.value}." for c in by_basis(Basis.ENGINE_DESIGN_ASSUMPTION)),
        "",
        "4. HEIGHT",
        f"  Maximum legally allowed by the floors calculator: stilt + "
        f"{run.limit.floors_stilt_counted} if the stilt counts, stilt + "
        f"{run.limit.floors_stilt_not_counted} if not, stopped by {run.limit.limited_by}",
        "  Readings the project selects: " + (", ".join(
            f"{k} = {v['reading']}" for k, v in project["layout"].get("readings", {}).items())
            or "none: every reading of every open question is searched"),
        "  Heights the layouts shown use: " + (", ".join(sorted({
            f"stilt + {t.floors_above_stilt}" for c, _ in run.shown for t in c.towers}))
            or "none"),
        "",
        "5. LAYOUTS SHOWN",
    ]
    if not run.shown:
        lines.append(f"  None: {result.status.value}. {result.next}")
    shown = [c for c, _ in run.shown]
    for candidate, judged in run.shown:
        lines += _layout(candidate, judged, run.net, shown)
    lines += ["", "6. THE SEARCH'S NOTES AND THE LAYOUTS IT DID NOT SHOW",
              *(f"  - {n}" for n in result.notes), *(f"  - unfilled: {u}" for u in result.unfilled)]
    width = max(len(r[0]) for r in rows)
    lines += ["", "7. COMPARED WITH THE FIRM'S PLAN (read only now)",
              f"  {'':<{width}}  Engine  |  Firm"]
    lines += [f"  {name:<{width}}  {ours}  |  {theirs}" for name, ours, theirs in rows]
    return "\n".join(lines)


def proposed(run: FullRun) -> bool:
    return run.result.status is ProposeStatus.PROPOSED and bool(run.shown)
