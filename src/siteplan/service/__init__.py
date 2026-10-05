"""The production surface of the engine (docs/ARCHITECTURE.md, section 3, "LLM strategy").

    from siteplan.service import Mode, ProposeLayouts, Service
    service = Service(workspace, out, approver)            # host-side: never a caller's to set
    service.propose_layouts(ProposeLayouts(project_file=..., brief=..., intent=...))

One small, structured API around the contract pipeline (raw survey -> CanonicalSiteModel ->
ResolvedRules -> BuildableEnvelope -> prototypes -> the full search -> CandidateLayout ->
the independent ValidationReport -> drawings and report), so that a language model can one day
call the deterministic engine without being able to bypass the validator or put in a legal or
site number. No model is connected here.

- models.py: the request and response models (extra fields refused, frozen), ServiceError, and
  the approval audit's entry;
- service.py: `Service` and its nine operations, the workspace it alone reads, the approval;
- host.py: `ToolHost`, the only object a future model-facing transport holds: the nine
  operations as tools (JSON schemas in, JSON out), the approval page as the only channel, and
  `out` kept clear of the workspace;
- approvers.py: the person channels a host gives it (the approval page, the terminal), one
  chosen at startup and never falling back to the other;
- audit.py: every approval asked, written down before anything it allows runs;
- standards.py: the firm's standards, from the project file, else the workspace, else the
  engine's default, and the prototypes within the firm's longest block;
- brief.py: the brief's numbers held to its words, the DesignBrief, what the architect approves;
- judge.py: the independent verdict made again from the stored contracts, and what blocks an
  export;
- store.py: a run on disk and the digests that tie its contracts together;
- summaries.py, report.py, render.py: the contracts said back, the report, the drawings.

The legacy generator and checker (layout, heights, towers, grounds, access's road builders,
runner, checks, access_checks, parking_checks, optimizer/legacy.py) are kept only for regression
comparison; nothing here imports them, nor the command line or the MCP server
(tests/test_service.py).
"""

from siteplan.service.approvers import PageApprover, TerminalApprover, approver_for
from siteplan.service.host import ToolHost
from siteplan.service.models import (
    ApprovalRecord,
    Asked,
    CompareCandidates,
    CompareResult,
    Decision,
    EnvelopeResult,
    ExportCandidate,
    ExportResult,
    ExportStatus,
    HeightChoice,
    InspectEnvelope,
    Intent,
    ListPrototypes,
    Mode,
    OpenProject,
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
    ValidateCandidate,
    ValidationResult,
)
from siteplan.service.service import Approver, Service

__all__ = ["ApprovalRecord", "Approver", "Asked", "CompareCandidates", "CompareResult",
           "Decision", "EnvelopeResult", "ExportCandidate", "ExportResult", "ExportStatus",
           "HeightChoice", "InspectEnvelope", "Intent", "ListPrototypes", "Mode", "OpenProject",
           "PageApprover", "ProjectResult", "ProposeLayouts", "ProposeResult", "ProposeStatus",
           "PrototypesResult", "ResolveRules", "RulesResult", "Service", "ServiceError",
           "StartProject", "StartProjectResult", "TerminalApprover", "ToolHost",
           "ValidateCandidate", "ValidationResult", "approver_for"]
