"""The export's report and area statement, written from the contracts and the fresh verdict.

The report follows the order an architect checks a plan in: the legal verdict, every check by
family with its status, the UNVERIFIED items with the readings each rests on (the architect
acknowledged and approved them), what the engine does not check, the design targets (the firm's
margins, never law), the program verdict (never legality), the discrepancies between the
candidate's claims and the validator's measures, and the area statement. The area statement is
the firm's format (area_statement.py) filled from the candidate's own prototypes and metrics,
and the net site ledger from its partition; the validator has held both against its own
measures, and a claim more favourable than measured would have blocked the export.
"""

from __future__ import annotations

from siteplan.area_statement import AreaStatement, FloorLine, TowerGroup
from siteplan.contracts import CandidateLayout, CanonicalSiteModel, DesignBrief, ValidationReport
from siteplan.contracts.common import Status
from siteplan.service.models import UnresolvedItem
from siteplan.units import sqm_to_sqft, sqm_to_sqyd

ORDER = (Status.FAIL, Status.UNVERIFIED, Status.NOT_CHECKED, Status.PASS, Status.INFO)


def area_statement_of(candidate: CandidateLayout, site: CanonicalSiteModel,
                      brief: DesignBrief) -> AreaStatement:
    """Identical towers grouped (one prototype at one height), each floor the prototype's own
    footprint, the loading the firm's standard, the site area the net ownership."""
    groups: dict[tuple[str, int, bool], list[str]] = {}
    for tower in candidate.towers:
        key = (tower.prototype_id, tower.floors_above_stilt, tower.has_stilt)
        groups.setdefault(key, []).append(tower.name.removeprefix("T"))
    open_sqm = candidate.metrics.open_space_sqm if candidate.metrics else 0.0
    return AreaStatement(
        site_area_sqyd=sqm_to_sqyd(site.ownership.net_sqm.value),
        open_space_sqft=sqm_to_sqft(open_sqm) if open_sqm > 0 else None,
        groups=[TowerGroup(
            name=f"TOWER - {', '.join(names)}",
            storeys=f"STILT + {floors} FLOORS" if stilt else f"{floors} FLOORS",
            common_area_pct=brief.firm_standards.common_area_loading_pct.value,
            floors=[FloorLine(label="TYPICAL", count=floors, area_sqft=sqm_to_sqft(
                candidate.prototype(prototype_id).per_floor.gross_floor_sqm) * len(names))])
            for (prototype_id, floors, stilt), names in groups.items()])


def _item_line(item: UnresolvedItem) -> str:
    rests = "; ".join(f"holds only if {interpretation} is read as "
                      + " or ".join(f"'{r}'" for r in readings)
                      for interpretation, readings in item.holds_under.items())
    return f"  - {item.item}: {item.measured}" + (f" ({rests})" if rests else "")


def _figures(candidate: CandidateLayout) -> list[str]:
    m = candidate.metrics
    lines = []
    if m is not None:
        mix = ", ".join(f"{k} {v}" for k, v in sorted(m.flats_by_type.items()))
        lines += [f"  Flats: {m.total_flats} ({mix})",
                  f"  Saleable (from the flats' own sale areas): {m.saleable_sqft:,.0f} sft",
                  f"  Tower floor, every floor wall to wall: {m.tower_floor_sqft:,.0f} sft "
                  f"(flats {m.flats_own_sqft:,.0f}, corridors, lifts and stairs "
                  f"{m.common_core_sqft:,.0f})",
                  f"  Built-up: {m.built_up_sqft:,.0f} sft",
                  f"  Organised open space: {m.open_space_sqm:,.0f} m² "
                  f"({m.open_space_share_pct:.2f}% of the site)"]
    if candidate.partition is not None:
        uses = sorted(candidate.partition.by_use().items(), key=lambda kv: -kv[1])
        lines.append("  Net site by physical use (every square metre once): "
                     + ", ".join(f"{use.value} {sqm:,.0f} m²" for use, sqm in uses))
    return lines


def report_text(*, project_name: str, run_id: str, candidate: CandidateLayout,
                report: ValidationReport, items: list[UnresolvedItem], debug: bool,
                statement: str) -> str:
    v = report.verdict
    lines = []
    if debug:
        lines += ["DEBUG RUN: the firm's finished plan was an input (a regression run, not blind "
                  "acceptance); nothing here is evidence for a rule.", ""]
    lines += [f"SITE PLAN CANDIDATE {candidate.candidate_id}: {project_name}",
              f"Run {run_id}, strategy {candidate.strategy}. Judged again at export by "
              f"{report.validator_version}, from the stored site model ({report.site_ref}), "
              f"rules ({report.rules_ref}), brief ({report.brief_ref}) and envelope "
              f"({report.envelope_ref}).", "",
              f"1. LEGAL VERDICT: {v.legal.value}",
              f"   Program: {v.program.value} (the program never decides legality)",
              *(f"   - {reason}" for reason in v.reasons), "",
              "2. CHECKS BY FAMILY"]
    families: dict = {}
    for check in report.legal:
        families.setdefault(check.family, []).append(check)
    for family, checks in families.items():
        lines.append(f"  {family.value}")
        for check in sorted(checks, key=lambda c: ORDER.index(c.finding.status)):
            f = check.finding
            lines.append(f"    {f.status.value:<11} {f.rule}: {f.measured}"
                         + (f" (needs {f.required})" if f.required else "")
                         + (f" [{f.clause}]" if f.clause else ""))
    lines += ["", "3. UNRESOLVED (UNVERIFIED) ITEMS, ACKNOWLEDGED AND APPROVED BY THE ARCHITECT",
              *([_item_line(item) for item in items] or ["  None."]), "",
              "4. NOT CHECKED (rules the engine does not model)",
              *([f"  - {rule}" for rule in report.not_checked] or ["  None."]), "",
              "5. DESIGN TARGETS (the firm's margins above the legal minimum; never law)"]
    lines += [f"  - {t.item.value}{' ' + t.subject if t.subject else ''}: provided "
              f"{t.provided:,.2f} {t.unit}, legal minimum {t.legal_minimum:,.2f}, target "
              f"{t.target:,.2f} ({t.basis.value}){'' if t.meets_target else ', target missed'}"
              for t in report.design_targets] or ["  None."]
    lines += ["", f"6. PROGRAM: {v.program.value}"]
    lines += [f"    {c.finding.status.value:<11} {c.finding.rule}: {c.finding.measured}"
              for c in report.program]
    lines += ["", "7. CROSS-CHECKS (the candidate's claims against the validator's measures)"]
    lines += [f"  - {d.item}: the {d.source} says {d.theirs}, measured {d.ours}"
              f"{' (blocks a pass)' if d.blocks_pass else ''}"
              for d in report.cross_checks] or ["  None."]
    lines += ["", "8. AREA STATEMENT (from the candidate's prototypes, metrics and ledger)",
              *(f"  {line}" if line else "" for line in statement.splitlines()),
              *_figures(candidate)]
    return "\n".join(lines) + "\n"
