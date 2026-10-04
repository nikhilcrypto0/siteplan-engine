"""The production service: the contract pipeline behind one small, structured surface.

    Service(workspace, out, approver, mode=Mode.BLIND)

What the host sets, and a caller never can: the workspace folder (the only one read; anything
outside it is refused with one message, the reason going to the log), the folder runs are
written to, the Approver (asked of the person, never answered by the caller of an operation),
and the mode (BLIND refuses the firm's finished plans as blind.py does; DEBUG allows them and
every output says DEBUG RUN). The firm's standards come from the workspace file only
(`intake.load_defaults`), or are the engine's defaults labelled ASSUMED_FOR_TEST. The readings
of the law and the project's own test mode are as the project file states them.

What a caller may do, each with one request model and one response model (models.py):
start_project, open_project, resolve_rules, inspect_envelope, list_prototypes, propose_layouts,
validate_candidate, compare_candidates and export_candidate.

The independent validator cannot be bypassed. propose_layouts runs the full search through
`optimize` without handing it a validator (so the core uses `siteplan.validator`), then judges
every alternative again itself with `siteplan.validator.validate` and stores that report beside
it. validate_candidate and export_candidate judge the stored contracts again and never trust a
stored report; export refuses a legal FAIL, a blocking discrepancy, a report that could not
measure the candidate and a reference that does not hold, and exports an UNVERIFIED candidate
only when the caller names exactly its UNVERIFIED items and the architect approves them.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from siteplan import validator
from siteplan.area_statement import render as render_statement
from siteplan.blind import blind_leaks, finished_values
from siteplan.contracts import (
    CandidateLayout,
    CanonicalSiteModel,
    ResolvedRules,
    ValidationReport,
    digest,
)
from siteplan.contracts.common import SourceKind
from siteplan.contracts.resolved_rules import WhenOpen
from siteplan.intake import WORKSPACE_FILE, WorkspaceDefaults, extract, load_defaults, questions
from siteplan.legal.envelope import NetPlotUnknown, envelope
from siteplan.legal.resolve import resolve
from siteplan.legal.site import readings_of, site_from_project
from siteplan.library import FlatLibrary
from siteplan.optimizer.core import OptimizerResult, optimize
from siteplan.optimizer.guard import inputs_of, why_refused
from siteplan.optimizer.search import FullSearchStrategy
from siteplan.project import Project
from siteplan.prototypes import compose_library
from siteplan.service import brief, judge, render, report, store, summaries
from siteplan.service.models import (
    RUN_ID_CHARS,
    CompareCandidates,
    CompareResult,
    CompareRow,
    EnvelopeResult,
    ExportCandidate,
    ExportResult,
    ExportStatus,
    InspectEnvelope,
    ListPrototypes,
    Mode,
    OpenProject,
    ProjectFiles,
    ProjectResult,
    ProposeLayouts,
    ProposeResult,
    ProposeStatus,
    PrototypesResult,
    ResolveRules,
    RulesResult,
    ServiceError,
    StartProject,
    StartProjectResult,
    UnresolvedItem,
    ValidateCandidate,
    ValidationResult,
)
from siteplan.service.store import Inputs, RunRecord, StoreError
from siteplan.sheet import SheetInfo
from siteplan.site_amenities import AmenityLibrary

__all__ = ["Approver", "Service", "ServiceError"]

log = logging.getLogger("siteplan.service")

SURVEYS = frozenset({".pdf", ".dxf"})
JSON = frozenset({".json"})
PDF_GAP = ("PDF: no runtime dependency of the project draws one (reportlab is a test "
           "dependency only, and PyMuPDF is AGPL); plot the A1 sheet DXF from ZWCAD")
NEXT_PROPOSED = ("Call validate_candidate for a candidate to see every check; export_candidate "
                 "then needs exactly the UNVERIFIED items that call lists, which the architect "
                 "is asked to approve.")
NOT_APPROVED = ("The architect did not approve, so nothing was run. Do not ask again unless the "
                "architect asks.")


class Approver(Protocol):
    """Asks the person. The host wires it to a channel only a person can answer; it is never
    answered by whoever called the operation."""

    def approve(self, title: str, lines: list[str]) -> bool: ...


@dataclass(frozen=True)
class _Loaded:
    file: str
    project: Project  # with the workspace's standards
    survey: Path | None
    defaults: WorkspaceDefaults
    finished: tuple[str, ...]  # inputs taken from the firm's finished plan


def _expect(request: object, model: type) -> None:
    if not isinstance(request, model):
        raise TypeError(f"expected a {model.__name__}, got {type(request).__name__}")


def _fields(error: ValidationError) -> str:
    return ", ".join(sorted({str(e["loc"][0]) for e in error.errors() if e["loc"]})) or "format"


def _finished_in(model) -> list[str]:
    """Where a contract holds a value taken from the firm's finished plan."""
    found = []

    def walk(data, path: str) -> None:
        if isinstance(data, dict):
            if data.get("source_kind") == SourceKind.FIRM_FINISHED_PLAN.value:
                found.append(f"{path} comes from the firm's finished plan")
            for key, value in data.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(data, list):
            for i, value in enumerate(data):
                walk(value, f"{path}[{i}]")

    walk(model.model_dump(mode="json"), "")
    return found


class Service:
    def __init__(self, workspace: Path, out: Path, approver: Approver, *,
                 mode: Mode = Mode.BLIND) -> None:
        self._root = Path(workspace).resolve()
        self._out = Path(out).resolve()
        self._approver = approver
        self._mode = Mode(mode)

    @property
    def mode(self) -> Mode:
        return self._mode

    # --- LLM-facing operations -------------------------------------------------------------

    def start_project(self, request: StartProject) -> StartProjectResult:
        """What the survey settles, each value with its status, and the questions only the
        architect can answer. Read-only: answers go through the human intake flow."""
        _expect(request, StartProject)
        survey = self._file(request.survey_file, SURVEYS)
        self._refuse_finished(blind_leaks(survey, {}, None, self._defaults().finished_plans))
        try:
            draft = extract(survey)
        except ValueError as error:
            raise ServiceError(str(error)) from None
        return summaries.start_result(draft, questions(draft))

    def open_project(self, request: OpenProject) -> ProjectResult:
        """The site facts with their status, the firm's standards, the brief the project file
        holds, what is unresolved, and whether the inputs are blind."""
        _expect(request, OpenProject)
        loaded = self._load(request)
        site = self._site(loaded)
        selections, when_open = readings_of(loaded.project)
        stop = ""
        if site.net_plot is None:
            try:
                envelope(site, self._rules(site, loaded.project))
            except NetPlotUnknown as error:
                stop = str(error)
        facts = summaries.site_facts(site)
        standards = brief.standard_facts(loaded.project, loaded.defaults)
        finished = list(dict.fromkeys([*loaded.finished, *_finished_in(site)]))
        return ProjectResult(
            project_name=loaded.project.name, project_file=loaded.file,
            survey_file=loaded.survey.name if loaded.survey else None,
            run_kind=Mode.DEBUG if finished else Mode.BLIND,
            finished_plan_inputs=finished, site=facts,
            readings_stated=selections, conservative_parking=when_open is WhenOpen.CONSERVATIVE,
            firm_standards=standards, brief=brief.brief_facts(loaded.project),
            unresolved=summaries.unresolved_facts(facts + standards),
            net_plot_placed=site.net_plot is not None, stop=stop)

    def resolve_rules(self, request: ResolveRules) -> RulesResult:
        """What the law asks of the site: bands and permissions, limits, high-rise eligibility,
        every open reading with the one selected, and every UNVERIFIED item."""
        _expect(request, ResolveRules)
        loaded = self._load(request)
        site = self._site(loaded)
        return summaries.rules_result(loaded.project.name, self._rules(site, loaded.project))

    def inspect_envelope(self, request: InspectEnvelope) -> EnvelopeResult:
        """The land each height band leaves to build on, its permission, its width profile
        (reported, never judged) and the statutory exclusions."""
        _expect(request, InspectEnvelope)
        loaded = self._load(request)
        site = self._site(loaded)
        rules = self._rules(site, loaded.project)
        try:
            env = envelope(site, rules)
        except NetPlotUnknown as error:
            raise ServiceError(str(error)) from None
        return summaries.envelope_result(loaded.project.name, site, env)

    def list_prototypes(self, request: ListPrototypes) -> PrototypesResult:
        """The tower prototypes composed from the firm's flat library for the project's mix."""
        _expect(request, ListPrototypes)
        loaded = self._load(ProjectFiles(project_file=request.project_file))
        layout = loaded.project.layout
        if layout is None:
            raise ServiceError("The project file has no unit mix; start it through the intake "
                               "flow (siteplan start).")
        library = self._library(loaded.defaults)
        kit = compose_library(library, layout.unit_mix, source_kind=SourceKind.FIRM_STANDARD)
        return PrototypesResult(
            flat_library=loaded.defaults.flat_library,
            flat_library_status=loaded.defaults.standard_status("flat_library"),
            unit_mix=dict(layout.unit_mix),
            prototypes=[summaries.prototype_out(p) for p in kit])

    def propose_layouts(self, request: ProposeLayouts) -> ProposeResult:
        """Ask the architect to approve the interpreted request, then run the full search and
        judge every alternative independently; the run is stored for validation and export."""
        _expect(request, ProposeLayouts)
        loaded = self._load(request)
        library = self._library(loaded.defaults)
        words, missing = brief.read_brief(request.brief, request.intent, loaded.project, library)
        if missing:
            return ProposeResult(status=ProposeStatus.MISSING, missing=missing,
                                 next="Ask the architect for these. Do not guess them.")
        site = self._site(loaded)
        rules = self._rules(site, loaded.project)
        try:
            env = envelope(site, rules)
        except NetPlotUnknown as error:
            return ProposeResult(status=ProposeStatus.STOPPED, next=str(error))
        design = brief.design(loaded.project, loaded.defaults, self._amenities(loaded.defaults),
                              request.intent, words)
        kit = compose_library(library, design.program.unit_mix.value,
                              source_kind=SourceKind.FIRM_STANDARD)
        lines = brief.approval_lines(
            debug=self._mode is Mode.DEBUG, finished=loaded.finished, project_file=loaded.file,
            survey=loaded.survey, project=loaded.project, defaults=loaded.defaults, site=site,
            brief=design, intent=request.intent)
        if not self._ask(f"Generate layout options for {loaded.project.name}", lines):
            return ProposeResult(status=ProposeStatus.NOT_APPROVED, next=NOT_APPROVED)
        # The full search alone, and no validator handed in: the core judges with
        # siteplan.validator, and every alternative is judged again below.
        result = optimize(site, rules, design, [FullSearchStrategy()], envelope=env,
                          prototypes=kit)
        inputs = Inputs(site, rules, design, env)
        judged, rejected = _judged_again(inputs, result)
        record = RunRecord(
            run_id=uuid.uuid4().hex[:RUN_ID_CHARS], mode=self._mode,
            project_name=loaded.project.name, project_file=loaded.file,
            survey_file=loaded.survey.name if loaded.survey else None,
            sheet=loaded.project.sheet.model_dump(), approved=lines,
            candidates=[store.StoredCandidate(candidate_id=c.candidate_id, digest=digest(c),
                                              point=c.pareto_tag) for c, _ in judged],
            notes=list(result.notes), rejected=rejected,
            unfilled=[f"{point.value}: {why}" for point, why in result.unfilled])
        record = store.write_run(self._out / record.run_id, record, inputs, judged)
        log.info("run %s: approved and run, %d candidates", record.run_id, len(judged))
        return ProposeResult(
            status=ProposeStatus.PROPOSED if judged else ProposeStatus.NOTHING_PROPOSED,
            run_id=record.run_id, debug_run=self._mode is Mode.DEBUG,
            candidates=[summaries.candidate_summary(c, r, request.intent.massing)
                        for c, r in judged],
            unfilled=record.unfilled, notes=record.notes,
            next=NEXT_PROPOSED if judged else "Nothing passed: the notes say why.")

    def validate_candidate(self, request: ValidateCandidate) -> ValidationResult:
        """Judge a stored candidate again, from the stored contracts, and say why it could not
        be exported if it could not, and what an export would need acknowledged."""
        _expect(request, ValidateCandidate)
        record = self._record(request.run_id)
        judged = self._judge(record, request.candidate_id)
        refusals = judge.refusals(judged)
        items = judge.unresolved_items(judged.report)
        v = judged.report.verdict
        return ValidationResult(
            run_id=record.run_id, candidate_id=request.candidate_id,
            debug_run=self._debug(record), legal_verdict=v.legal, program_verdict=v.program,
            refusals=refusals, unverified=items, not_checked=list(judged.report.not_checked),
            checks_by_family=summaries.checks_by_family(judged.report),
            design_targets=summaries.targets(judged.report),
            program=[summaries.check_out(c) for c in judged.report.program],
            next="It cannot be exported." if refusals else (
                "export_candidate needs exactly these UNVERIFIED items acknowledged, and the "
                "architect's approval." if items else "It can be exported as it stands."))

    def compare_candidates(self, request: CompareCandidates) -> CompareResult:
        """The candidates side by side, from the stored metrics and reports, and what the
        numbers show, computed (never a model's words)."""
        _expect(request, CompareCandidates)
        record = self._record(request.run_id)
        rows = []
        for candidate_id in dict.fromkeys(request.candidate_ids):
            try:
                candidate = store.load_candidate(self._out, record, candidate_id)
                stored = store.load_report(self._out, record, candidate_id)
            except StoreError as error:
                raise ServiceError(str(error)) from None
            rows.append(_row(candidate, stored))
        return CompareResult(run_id=record.run_id, rows=rows, findings=_findings(rows),
                             judged="as the service judged each when the run was made; "
                                    "export_candidate judges again before anything is drawn")

    def export_candidate(self, request: ExportCandidate) -> ExportResult:
        """The drawings and the report of one candidate, after it is judged again: never a
        FAIL, a blocking discrepancy, an unmeasured candidate or a broken reference, and
        UNVERIFIED only with exactly its items acknowledged and the architect's approval."""
        _expect(request, ExportCandidate)
        record = self._record(request.run_id)
        judged = self._judge(record, request.candidate_id)
        debug = self._debug(record)
        base = {"run_id": record.run_id, "candidate_id": request.candidate_id,
                "debug_run": debug, "legal_verdict": judged.report.verdict.legal}
        reasons = judge.refusals(judged)
        if reasons:
            return ExportResult(status=ExportStatus.REFUSED, reasons=reasons, **base)
        items = judge.unresolved_items(judged.report)
        names = [item.item for item in items]
        given = set(request.acknowledged_unresolved)
        if given != set(names):
            unasked = [name for name in names if name not in given]
            extra = sorted(given - set(names))
            reasons = ([f"not acknowledged: {'; '.join(unasked)}"] if unasked else []) + (
                [f"acknowledged but not UNVERIFIED in the report judged now: "
                 f"{'; '.join(extra)}"] if extra else [])
            return ExportResult(status=ExportStatus.REFUSED, reasons=reasons, unverified=names,
                                **base)
        if items and not self._ask(
                f"Export {request.candidate_id} with {len(items)} unresolved item(s)",
                [f"Run {record.run_id}, candidate {request.candidate_id}: legal verdict "
                 f"{judged.report.verdict.legal.value}, judged again now",
                 *(f"UNVERIFIED {item.item}: {item.measured}" for item in items),
                 "Every drawing and the report will list these items."]):
            return ExportResult(status=ExportStatus.NOT_APPROVED, unverified=names,
                                reasons=["The architect did not approve exporting with these "
                                         "items unresolved; nothing was drawn."], **base)
        files = _write_outputs(self._out, judged, items, debug)
        log.info("run %s: exported %s", record.run_id, request.candidate_id)
        return ExportResult(status=ExportStatus.EXPORTED, unverified=names,
                            files=[str(p) for p in files], not_produced=[PDF_GAP], **base)

    # --- the workspace ---------------------------------------------------------------------

    def _file(self, name: str, suffixes: frozenset[str]) -> Path:
        path = (self._root / name).resolve()
        if (not path.is_relative_to(self._root) or path.suffix.lower() not in suffixes
                or not path.is_file()):
            log.warning("file refused: %r", name)  # the reason stays in the log
            raise ServiceError(f"'{name}' is not a readable file in the workspace.")
        return path

    def _defaults(self) -> WorkspaceDefaults:
        try:
            return load_defaults(self._root)
        except (ValidationError, ValueError) as error:
            log.warning("workspace file refused: %s", error)
            raise ServiceError(f"The workspace's {WORKSPACE_FILE} is not valid.") from None

    def _library(self, defaults: WorkspaceDefaults) -> FlatLibrary:
        if not defaults.flat_library:
            raise ServiceError(f"Set the firm's flat_library in {WORKSPACE_FILE}.")
        path = self._file(defaults.flat_library, JSON)
        try:
            return FlatLibrary.model_validate_json(path.read_text())
        except ValidationError as error:
            raise ServiceError(f"The firm's flat library is not valid ({_fields(error)}).") \
                from None

    def _amenities(self, defaults: WorkspaceDefaults) -> AmenityLibrary | None:
        if not defaults.amenities:
            return None
        path = self._file(defaults.amenities, JSON)
        try:
            return AmenityLibrary.model_validate_json(path.read_text())
        except ValidationError as error:
            raise ServiceError(f"The firm's amenity library is not valid ({_fields(error)}).") \
                from None

    def _refuse_finished(self, found: list[str]) -> None:
        if found and self._mode is Mode.BLIND:
            raise ServiceError("A blind run may not use the firm's finished plan: "
                               + "; ".join(found) + ".")

    def _load(self, request: ProjectFiles) -> _Loaded:
        path = self._file(request.project_file, JSON)
        text = path.read_text()
        try:
            project = Project.model_validate_json(text)
        except ValidationError as error:
            raise ServiceError(f"'{request.project_file}' is not a valid project file "
                               f"({_fields(error)}).") from None
        survey = self._file(request.survey_file, SURVEYS) if request.survey_file else None
        defaults = self._defaults()
        finished = blind_leaks(survey, {}, None, defaults.finished_plans) if survey else []
        if path.name in set(defaults.finished_plans):
            finished.append(f"the project file {path.name} is one of the firm's finished plans")
        finished += [f"project value '{key}' comes from the firm's finished plan"
                     for key in finished_values(json.loads(text))]
        self._refuse_finished(finished)
        return _Loaded(request.project_file, _with_standards(project, defaults), survey,
                       defaults, tuple(finished))

    def _site(self, loaded: _Loaded) -> CanonicalSiteModel:
        try:
            site = site_from_project(loaded.project, loaded.survey)
        except ValueError as error:
            raise ServiceError(str(error)) from None
        self._refuse_finished(_finished_in(site))
        return site

    @staticmethod
    def _rules(site: CanonicalSiteModel, project: Project) -> ResolvedRules:
        selections, when_open = readings_of(project)
        return resolve(site, selections=selections, when_open=when_open)

    def _ask(self, title: str, lines: list[str]) -> bool:
        try:
            return self._approver.approve(title, list(lines)) is True
        except Exception as error:  # a channel that fails is a no, never a yes
            log.warning("approval could not be asked: %s", error)
            return False

    # --- stored runs -----------------------------------------------------------------------

    def _record(self, run_id: str) -> RunRecord:
        try:
            record = store.read_record(self._out, run_id)
        except (StoreError, ValidationError, ValueError) as error:
            log.warning("run refused: %s", error)
            raise ServiceError(f"There is no readable run '{run_id}'.") from None
        if record.mode is Mode.DEBUG and self._mode is Mode.BLIND:
            raise ServiceError("That run used the firm's finished plan; a blind service does "
                               "not read it.")
        return record

    def _judge(self, record: RunRecord, candidate_id: str) -> judge.Judged:
        try:
            judged = judge.judge_again(self._out, record, candidate_id)
        except StoreError as error:
            raise ServiceError(str(error)) from None
        self._refuse_finished(_finished_in(judged.inputs.site))
        return judged

    def _debug(self, record: RunRecord) -> bool:
        return Mode.DEBUG in (record.mode, self._mode)


def _with_standards(project: Project, defaults: WorkspaceDefaults) -> Project:
    """The project with the firm's standards as the workspace sets them now, each recorded as
    intake records it: the firm's (its file's status) or the engine's default."""
    if project.layout is None:
        return project
    values = {key: getattr(defaults, key) for key in brief.STANDARDS}
    try:
        layout = type(project.layout).model_validate(
            {**project.layout.model_dump(exclude_unset=True), **values})
    except ValidationError as error:
        raise ServiceError(f"The workspace's standards are not valid ({_fields(error)}).") \
            from None
    sources, status = dict(project.sources), dict(project.status)
    kinds = dict(project.source_kinds)
    for key in brief.STANDARDS:
        firms = key in defaults.model_fields_set
        sources[key] = "firm standard (workspace)" if firms else "engine default"
        status[key] = defaults.standard_status(key)
        kinds[key] = SourceKind.FIRM_STANDARD if firms else SourceKind.ENGINE_DEFAULT
    return project.model_copy(update={"layout": layout, "sources": sources, "status": status,
                                      "source_kinds": kinds})


def _judged_again(inputs: Inputs, result: OptimizerResult
                  ) -> tuple[list[tuple[CandidateLayout, ValidationReport]], list[str]]:
    """Each alternative the optimizer returned, judged by the independent validator here, now:
    the report stored beside it is this one. One the fresh report refuses is not kept."""
    site, rules, design, env = inputs.site, inputs.rules, inputs.brief, inputs.envelope
    judged = []
    rejected = [f"{r.candidate_id}: {'; '.join(r.reasons)}" for r in result.rejected]
    for alternative in result.alternatives:
        candidate = alternative.candidate
        fresh = validator.validate(site, rules, design, candidate, env)
        reasons = why_refused(candidate, fresh, inputs_of(site, rules, design))
        if reasons:
            rejected.append(f"{candidate.candidate_id}: {'; '.join(reasons)}")
        else:
            judged.append((candidate, fresh))
    return judged, rejected


def _write_outputs(out: Path, judged: judge.Judged, items: list[UnresolvedItem],
                   debug: bool) -> list[Path]:
    """The DXF, the A1 sheet, the SVG and the report of a candidate judged again just now, the
    fresh report beside them; DEBUG RUN and the acknowledged items on every one."""
    record, candidate, fresh = judged.record, judged.candidate, judged.report
    folder = out / record.run_id / "exports" / candidate.candidate_id
    notes = ["DEBUG RUN: the firm's finished plan was an input; not blind acceptance"] if debug \
        else []
    if items:
        notes += ["UNRESOLVED (UNVERIFIED), ACKNOWLEDGED BY THE ARCHITECT:",
                  *(f"- {item.item}" for item in items)]
    statement = render_statement(report.area_statement_of(candidate, judged.inputs.site,
                                                          judged.inputs.brief))
    plan = render.plan_of(judged.inputs.site, candidate)
    sheet = record.sheet
    info = SheetInfo(project=record.project_name, client=sheet.get("client", ""),
                     architect=sheet.get("architect", ""),
                     drawing="SITE PLAN, DEBUG RUN" if debug else "SITE PLAN",
                     number=sheet.get("number") or candidate.candidate_id,
                     revision=sheet.get("revision", ""), drawn_by=sheet.get("drawn_by", ""))
    stem = candidate.candidate_id
    title = f"{'DEBUG RUN: ' if debug else ''}{record.project_name}: {stem}"
    subtitle = (f"legal {fresh.verdict.legal.value}, program {fresh.verdict.program.value} "
                f"(judged again at export) · {len(candidate.towers)} towers")
    text = report.report_text(project_name=record.project_name, run_id=record.run_id,
                              candidate=candidate, report=fresh, items=items, debug=debug,
                              statement=statement)
    written = [render.write_dxf(plan, folder / f"{stem}.dxf", notes),
               render.write_sheet(plan, folder / f"{stem}.sheet.dxf", info, statement, notes),
               render.write_svg(plan, folder / f"{stem}.svg", title, subtitle, notes)]
    (folder / f"{stem}.report.txt").write_text(text)
    (folder / f"{stem}.validation.json").write_text(fresh.model_dump_json(indent=1))
    return [*written, folder / f"{stem}.report.txt", folder / f"{stem}.validation.json"]


def _row(candidate: CandidateLayout, stored: ValidationReport) -> CompareRow:
    m = candidate.metrics
    return CompareRow(
        candidate_id=candidate.candidate_id, towers=len(candidate.towers),
        floors=sorted({t.floors_above_stilt for t in candidate.towers}),
        flats=m.total_flats if m else 0, flats_by_type=dict(m.flats_by_type) if m else {},
        saleable_sqft=round(m.saleable_sqft) if m else 0.0,
        open_space_sqm=round(m.open_space_sqm, 1) if m else 0.0,
        open_space_share_pct=round(m.open_space_share_pct, 2) if m else 0.0,
        mix_error=round(m.mix_error, 4) if m else 0.0, legal_verdict=stored.verdict.legal,
        program_verdict=stored.verdict.program,
        unverified=len(judge.unresolved_items(stored)))


def _findings(rows: list[CompareRow]) -> list[str]:
    """What the numbers show, computed as assistant.compare_options computes it."""
    if not rows:
        return []
    sale = max(rows, key=lambda r: (r.saleable_sqft, r.candidate_id))
    space = max(rows, key=lambda r: (r.open_space_share_pct, r.candidate_id))
    mix = min(rows, key=lambda r: (r.mix_error, r.candidate_id))
    lines = [f"{sale.candidate_id} sells the most: {sale.saleable_sqft:,.0f} sft in "
             f"{sale.flats} flats.",
             f"{space.candidate_id} leaves the most open space: "
             f"{space.open_space_share_pct:g}% of the site.",
             f"{mix.candidate_id} comes closest to the unit mix asked "
             f"(error {mix.mix_error:g})."]
    lines += [f"{r.candidate_id}: {r.towers} tower{'' if r.towers == 1 else 's'}, stilt + "
              f"{'/'.join(map(str, r.floors))}, {r.flats} flats, {r.saleable_sqft:,.0f} sft, "
              f"open space {r.open_space_share_pct:g}%; legal {r.legal_verdict.value} with "
              f"{r.unverified} UNVERIFIED item(s); program {r.program_verdict.value}."
              for r in rows]
    return lines
