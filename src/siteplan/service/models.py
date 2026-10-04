"""What a caller of the service may send, and what it gets back.

The caller is meant to be a language model one day, so a request carries only identifiers (a
file in the workspace, a run, a candidate), the architect's own words and an enumerated intent:
never a legal dimension, a site measurement, a coordinate, a provenance label, a reading of the
law, a test profile, a validator, a strategy, a firm standard or an approval. Those come from the
project file the architect made through the human intake flow, from the firm's workspace file,
from rules.py, from the engine itself, or (an approval) from the person on the host's channel.
Every model refuses a field it does not know and is frozen, so nothing can be slipped in beside
a field or changed afterwards. Every number in an `Intent` must be written in the architect's
brief; the service checks it before anything runs.

The numbers here bound what a request may hold (lengths, counts); none of them shapes a layout.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from siteplan.contracts.common import Provenance, SourceKind, Status
from siteplan.contracts.design_brief import ParetoPoint
from siteplan.contracts.resolved_rules import Applicability, Eligibility, LimitBound
from siteplan.contracts.validation import Family, LegalVerdict, ProgramVerdict

MAX_NAME_CHARS = 255  # a file name in the workspace
MAX_BRIEF_CHARS = 2000  # the architect's brief, as the MCP server caps it
MAX_ITEM_CHARS = 400  # one acknowledged UNVERIFIED item
MAX_ITEMS = 200  # acknowledged items in one export
MAX_COMPARED = 10  # candidates compared at once
MAX_MIX_CATEGORIES = 8  # flat categories in a unit mix
MAX_FLOORS_ABOVE_STILT = 99  # a bound on the request, never a height the law allows
RUN_ID_CHARS = 12  # hexadecimal characters of a run's id
MAX_TEXT_CHARS = 400  # text read off a drawing, cleaned, in a reply

FileName = Annotated[str, StringConstraints(min_length=1, max_length=MAX_NAME_CHARS,
                                            pattern=r"^[^\x00-\x1f]+$")]
RunId = Annotated[str, StringConstraints(pattern=rf"^[0-9a-f]{{{RUN_ID_CHARS}}}$")]
CandidateId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")]
BriefText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_BRIEF_CHARS)]
Category = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9 +._-]{0,15}$")]
Percent = Annotated[float, Field(gt=0, le=100)]
ItemText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_ITEM_CHARS)]


class ServiceError(ValueError):
    """A request the service will not serve. The message is safe to show the caller; any detail
    that is not goes to the log."""


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Mode(StrEnum):
    """Set by the host when it builds the service, never by a caller."""

    BLIND = "BLIND"  # the firm's finished plans are refused, as blind.py refuses them
    DEBUG = "DEBUG"  # allowed, for regression; every output then says DEBUG RUN


class Decision(StrEnum):
    """What came back when the service asked the person. Only APPROVED is a yes."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    UNANSWERED = "UNANSWERED"  # no person answered: the page timed out, or no terminal to ask
    CHANNEL_FAILURE = "CHANNEL_FAILURE"  # the channel broke before an answer came


class Asked(StrEnum):
    PROPOSAL = "PROPOSAL"  # run the search for this request
    EXPORT = "EXPORT"  # draw this candidate with its UNVERIFIED items open


class ApprovalRecord(Frozen):
    """One approval the service asked of the person, as the service wrote it down when it asked:
    the words it showed (and their digest), the answer, the channel that carried it and when.
    Nothing here is taken from the caller of an operation: the run and the candidate are the
    stored ones, and an export's acknowledged items are the fresh report's own, never the
    caller's strings. Entries are only ever appended (service/audit.py)."""

    asked: Asked
    title: str
    lines: tuple[str, ...]
    asked_digest: str  # sha256 of the title and the lines, as shown
    decision: Decision
    channel: str  # the class of the approver the host chose
    at: str  # when the answer came, UTC, ISO 8601
    run_id: str | None = None  # the run a proposal made, or the run an export draws from
    candidate_id: str | None = None  # an export's candidate
    acknowledged: tuple[str, ...] = ()  # an export's UNVERIFIED items, as the fresh report names
    report_digest: str | None = None  # an export: the fresh ValidationReport it judged


# --- Requests ------------------------------------------------------------------------------


class HeightChoice(StrEnum):
    MOST_THE_RULES_ALLOW = "MOST_THE_RULES_ALLOW"
    FLOORS_ABOVE_STILT = "FLOORS_ABOVE_STILT"  # 'Stilt + N': N as the brief writes it


class Intent(Frozen):
    """What the brief asks for, read into enumerations and the numbers the brief writes. A field
    left out is taken from the project file the architect made; nothing is guessed."""

    height: HeightChoice | None = None
    floors_above_stilt: Annotated[int, Field(gt=0, le=MAX_FLOORS_ABOVE_STILT)] | None = None
    unit_mix_percent: dict[Category, Percent] = Field(default_factory=dict,
                                                      max_length=MAX_MIX_CATEGORIES)
    massing: ParetoPoint | None = None  # the alternative the architect wants shown first

    @model_validator(mode="after")
    def _floors_go_with_their_height(self) -> Intent:
        named = self.height is HeightChoice.FLOORS_ABOVE_STILT
        if named != (self.floors_above_stilt is not None):
            raise ValueError("floors_above_stilt is given exactly when height is "
                             "FLOORS_ABOVE_STILT; ask the architect rather than guess")
        return self


class StartProject(Frozen):
    survey_file: FileName


class ProjectFiles(Frozen):
    project_file: FileName
    # A project file does not name its survey; the survey draws the roads, the water lines and
    # where land given up lies, so it is named beside it.
    survey_file: FileName | None = None


class OpenProject(ProjectFiles):
    pass


class ResolveRules(ProjectFiles):
    pass


class InspectEnvelope(ProjectFiles):
    pass


class ListPrototypes(Frozen):
    project_file: FileName  # its unit mix picks the flats of each prototype


class ProposeLayouts(ProjectFiles):
    brief: BriefText  # the architect's own words, copied exactly
    intent: Intent = Intent()


class ValidateCandidate(Frozen):
    run_id: RunId
    candidate_id: CandidateId


class CompareCandidates(Frozen):
    run_id: RunId
    candidate_ids: list[CandidateId] = Field(min_length=1, max_length=MAX_COMPARED)


class ExportCandidate(Frozen):
    run_id: RunId
    candidate_id: CandidateId
    # Exactly the UNVERIFIED items of the report the export judges again (validate_candidate
    # lists them), each in its own words; the architect is then asked to approve them.
    acknowledged_unresolved: list[ItemText] = Field(default_factory=list, max_length=MAX_ITEMS)


REQUESTS = (StartProject, OpenProject, ResolveRules, InspectEnvelope, ListPrototypes,
            ProposeLayouts, ValidateCandidate, CompareCandidates, ExportCandidate, Intent)


# --- Responses -----------------------------------------------------------------------------


class Fact(Frozen):
    """A value with how far it can be trusted and where it came from."""

    name: str
    value: str | int | float | bool | None = None
    unit: str = ""
    status: Provenance | None = None
    source_kind: SourceKind | None = None
    source: str = ""


class RoadSeen(Frozen):
    number: int
    side: str
    drawn_width_m: float  # as drawn: may be the carriageway alone
    drawn_width_ft: float
    divided: bool
    distance_from_plot_m: float
    status: Provenance = Provenance.EXTRACTED


class MarkSeen(Frozen):
    kind: str  # 'road widening', 'water' or 'HT line'
    text: str
    distance_m: float
    nearest_lines: list[str]  # offered, never chosen


class QuestionOut(Frozen):
    key: str
    question: str
    default: str = ""
    example: str = ""
    asked_only_if: str = ""


class StartProjectResult(Frozen):
    survey_file: str
    settled: list[Fact]
    roads: list[RoadSeen]
    marks: list[MarkSeen]
    line_work_near_plot: list[str]
    warnings: list[str]
    questions: list[QuestionOut]
    next: str


class ProjectResult(Frozen):
    project_name: str
    project_file: str
    survey_file: str | None
    run_kind: Mode  # DEBUG when an input comes from the firm's finished plan
    finished_plan_inputs: list[str]
    site: list[Fact]
    readings_stated: dict[str, str]  # open readings the project file itself settles
    conservative_parking: bool  # the project's own test mode, as it states it
    firm_standards: list[Fact]
    brief: list[Fact]
    unresolved: list[str]
    net_plot_placed: bool
    stop: str = ""  # what the architect must give before anything can be laid out


class GroundOut(Frozen):
    id: str
    met: bool | None
    measured: str
    required: str
    clause: str
    status: Provenance


class BandOut(Frozen):
    heights: str
    kind: str
    measure: str
    permission: Eligibility
    permission_note: str
    modelled: bool
    setback_m: float | None
    front_setback_m: float | None
    gap_m: float | None
    min_road_m: float | None
    green_strip_m: float | None
    clause: str
    status: Provenance


class LimitOut(Frozen):
    id: str
    measure: str
    bound: LimitBound
    max_m: float | None
    applicability: Applicability
    status: Provenance
    reason: str
    clause: str


class InterpretationOut(Frozen):
    id: str
    question: str
    selected: str  # one reading, or ALL: every reading is evaluated
    readings_evaluated: list[str]
    status: Provenance


class RulesResult(Frozen):
    project_name: str
    group_development: bool
    high_rise_from_m: float
    high_rise_eligibility: Eligibility
    eligibility_grounds: list[GroundOut]
    bands: list[BandOut]
    limits: list[LimitOut]
    table_v_column: str
    when_open: str
    parking_share_pct: float | None
    interpretations: list[InterpretationOut]
    unverified: list[str]


class RegionOut(Frozen):
    area_sqm: float
    max_inscribed_width_m: float
    length_m: float


class BandLandOut(Frozen):
    heights: str
    kind: str
    permission: Eligibility
    setback_m: float | None
    front_setback_m: float | None
    buildable_sqm: float
    regions: list[RegionOut]  # reported, never judged
    area_narrower_than: list[tuple[float, float]]  # (width m, area of land narrower)
    note: str


class ExclusionOut(Frozen):
    id: str
    kind: str
    area_sqm: float
    clause: str


class EnvelopeResult(Frozen):
    project_name: str
    net_plot_sqm: float
    net_plot_regions: list[RegionOut]
    bands: list[BandLandOut]
    exclusions: list[ExclusionOut]
    facts: list[str]


class PrototypeOut(Frozen):
    id: str
    family: str
    cores: int
    flats_per_floor: int
    flats_by_type: dict[str, int]
    length_m: float
    depth_m: float
    saleable_sqft_per_floor: float


class PrototypesResult(Frozen):
    flat_library: str
    flat_library_status: Provenance
    unit_mix: dict[str, float]
    prototypes: list[PrototypeOut]  # the kit the search may use
    left_out: list[str] = []  # composed, but longer than the firm's longest block


class UnresolvedItem(Frozen):
    item: str  # the name to acknowledge it by
    family: Family
    measured: str
    required: str
    # interpretation id -> the readings under which it passes; empty when it rests on an input
    # nobody has confirmed rather than on a reading of the law
    holds_under: dict[str, list[str]]


class CandidateSummary(Frozen):
    candidate_id: str
    strategy: str
    pareto_point: str | None
    preferred_massing: bool
    towers: int
    floors: list[int]
    flats: int
    saleable_sqft: float
    open_space_sqm: float
    open_space_share_pct: float
    legal_verdict: LegalVerdict
    program_verdict: ProgramVerdict
    unverified: list[UnresolvedItem]
    holds_under_every_reading: bool


class ProposeStatus(StrEnum):
    PROPOSED = "PROPOSED"
    NOTHING_PROPOSED = "NOTHING_PROPOSED"
    NOT_APPROVED = "NOT_APPROVED"
    MISSING = "MISSING"
    STOPPED = "STOPPED"


class ProposeResult(Frozen):
    status: ProposeStatus
    run_id: str | None = None
    debug_run: bool = False
    candidates: list[CandidateSummary] = []
    missing: list[str] = []
    unfilled: list[str] = []
    notes: list[str] = []
    next: str = ""


class CheckOut(Frozen):
    rule: str
    status: Status
    measured: str
    required: str
    clause: str


class FamilyChecks(Frozen):
    family: Family
    checks: list[CheckOut]


class TargetOut(Frozen):
    item: str
    subject: str | None
    unit: str
    legal_minimum: float
    target: float
    provided: float
    meets_target: bool
    basis: str


class ValidationResult(Frozen):
    run_id: str
    candidate_id: str
    debug_run: bool
    legal_verdict: LegalVerdict
    program_verdict: ProgramVerdict
    refusals: list[str]  # why it cannot be exported whatever is acknowledged
    unverified: list[UnresolvedItem]
    not_checked: list[str]
    checks_by_family: list[FamilyChecks]
    design_targets: list[TargetOut]  # beside the verdict, never in it
    program: list[CheckOut]  # never decides legality
    next: str
    approvals: tuple[ApprovalRecord, ...] = ()  # the run's, as recorded: who approved what


class CompareRow(Frozen):
    candidate_id: str
    towers: int
    floors: list[int]
    flats: int
    flats_by_type: dict[str, int]
    saleable_sqft: float
    open_space_sqm: float
    open_space_share_pct: float
    mix_error: float
    legal_verdict: LegalVerdict
    program_verdict: ProgramVerdict
    unverified: int


class CompareResult(Frozen):
    run_id: str
    rows: list[CompareRow]
    findings: list[str]  # computed, never written by a model
    judged: str


class ExportStatus(StrEnum):
    EXPORTED = "EXPORTED"
    REFUSED = "REFUSED"
    NOT_APPROVED = "NOT_APPROVED"


class ExportResult(Frozen):
    status: ExportStatus
    run_id: str
    candidate_id: str
    debug_run: bool
    legal_verdict: LegalVerdict | None = None
    reasons: list[str] = []
    unverified: list[str] = []
    files: list[str] = []
    not_produced: list[str] = []
    approvals: tuple[ApprovalRecord, ...] = ()  # the run's, this export's included
