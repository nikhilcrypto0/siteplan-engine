"""The contracts, said back to the caller: computed values and fixed wording.

Nothing here decides anything; each function reads one contract (or the survey's draft) into the
response models. Text read off a drawing (a mark, a place name, a warning) goes back cleaned of
role markers and capped (guards.sanitize_brief), because a label on a survey is text nobody
checked; what was removed goes to the log only.
"""

from __future__ import annotations

import logging

from siteplan.contracts import (
    BuildableEnvelope,
    CandidateLayout,
    CanonicalSiteModel,
    ResolvedRules,
    TowerPrototype,
    ValidationReport,
)
from siteplan.contracts.common import Provenance, Sourced
from siteplan.contracts.design_brief import ParetoPoint
from siteplan.contracts.resolved_rules import TableVColumn
from siteplan.guards import sanitize_brief
from siteplan.intake import Draft
from siteplan.optimizer.search.verdicts import rests_on
from siteplan.service.judge import unresolved_items
from siteplan.service.models import (
    MAX_TEXT_CHARS,
    BandLandOut,
    BandOut,
    CandidateSummary,
    CheckOut,
    EnvelopeResult,
    ExclusionOut,
    Fact,
    FamilyChecks,
    GroundOut,
    InterpretationOut,
    LimitOut,
    MarkSeen,
    PrototypeOut,
    QuestionOut,
    RegionOut,
    RoadSeen,
    RulesResult,
    StartProjectResult,
    TargetOut,
)

log = logging.getLogger("siteplan.service")

WEAK = (Provenance.UNVERIFIED, Provenance.ASSUMED_FOR_TEST)
INTAKE = ("The architect answers these through the intake flow (`siteplan start <survey>`), "
          "which records where each answer came from; this service does not take answers. "
          "Then call open_project with the project file it writes.")


def safe(text: str) -> str:
    """Text read off a drawing, fit to go back to a caller."""
    clean = sanitize_brief(text, MAX_TEXT_CHARS)
    if clean.removed:
        log.info("drawing text cleaned: %s", "; ".join(clean.removed))
    return clean.text


def _rounded(value):
    return round(value, 2) if isinstance(value, float) else value


def fact(name: str, sourced: Sourced | None, unit: str = "") -> Fact:
    if sourced is None:
        return Fact(name=name, status=Provenance.UNVERIFIED, source="not given")
    value = sourced.value
    shown = value if isinstance(value, str | int | float | bool) or value is None else "given"
    return Fact(name=name, value=_rounded(shown), unit=unit, status=sourced.status,
                source_kind=sourced.source_kind, source=sourced.source)


# --- start_project ---------------------------------------------------------------------------


def start_result(draft: Draft, questions) -> StartProjectResult:
    settled = [Fact(name="plot area as drawn", value=draft.gross_area_sqm, unit="m²",
                    status=Provenance.EXTRACTED, source="survey: the drawn boundary"),
               Fact(name="area written on the sheet", value=draft.written_area_sqm, unit="m²",
                    status=Provenance.EXTRACTED if draft.written_area_sqm
                    else Provenance.UNVERIFIED, source="survey: the largest area written"),
               Fact(name="spot levels on the plot", value=draft.on_site_levels,
                    status=Provenance.EXTRACTED, source="survey")]
    if draft.place:
        settled.append(Fact(name="place", value=safe(draft.place), status=Provenance.EXTRACTED,
                            source="survey: as written on the sheet"))
    roads = [RoadSeen(number=i, side=r.side, drawn_width_m=round(r.width_m, 2),
                      drawn_width_ft=round(r.width_ft, 1), divided=r.divided,
                      distance_from_plot_m=round(r.distance_m, 2))
             for i, r in enumerate(draft.roads, 1)]
    marks = [MarkSeen(kind=m.kind, text=safe(m.text), distance_m=m.distance_m,
                      nearest_lines=[safe(f"{key} {d:g} m") for key, d in m.nearby])
             for m in draft.marks]
    asked = [QuestionOut(key=q.key, question=safe(q.prompt), default=safe(q.default),
                         example=q.example,
                         asked_only_if="road_row is a width, not 'as drawn'" if q.when else "")
             for q in questions]
    return StartProjectResult(
        survey_file=draft.survey, settled=settled, roads=roads, marks=marks,
        line_work_near_plot=[safe(f"{g.key}: {g.length_m:g} m"
                                  f"{', crossing the plot' if g.crosses_plot else ''}")
                             for g in draft.line_work],
        warnings=[safe(w) for w in draft.warnings], questions=asked, next=INTAKE)


# --- open_project ----------------------------------------------------------------------------


def site_facts(site: CanonicalSiteModel) -> list[Fact]:
    own = site.ownership
    out = [fact("gross ownership", own.gross_sqm, "m²"), fact("net ownership", own.net_sqm, "m²")]
    for d in own.deductions:
        where = d.location
        placed = (f"{where.side} side, {where.width_m:g} m wide" if where.width_m
                  else "its own outline" if where.shape
                  else f"{where.side} side, where along it not known" if where.side
                  else "where it lies is not known")
        out.append(Fact(name=f"land given up ({d.kind.value.lower()}): {placed}",
                        value=round(d.area_sqm.value, 1), unit="m²", status=d.area_sqm.status,
                        source_kind=d.area_sqm.source_kind, source=d.area_sqm.source))
    net = site.net_plot
    out.append(Fact(name="net plot outline", value=round(net.value.area_sqm, 1) if net else None,
                    unit="m²", status=net.status if net else Provenance.UNVERIFIED,
                    source_kind=net.source_kind if net else None,
                    source=net.source if net else "not placed"))
    road = site.access_road()
    if road is not None:
        out.append(fact("access road: legal right of way", road.legal_row_m, "m"))
        out.append(Fact(name="access road: how its width is documented", value=road.row_status,
                        status=road.legal_row_m.status if road.legal_row_m else None))
        out.append(Fact(name="access road: width as drawn", value=road.drawn_width_m, unit="m",
                        status=Provenance.EXTRACTED if road.drawn_width_m else None,
                        source="survey: measured across itself; never used by the rules"))
    else:
        out.append(Fact(name="access road", status=Provenance.UNVERIFIED,
                        source="which road the site takes its access from is not settled"))
    a, j = site.access, site.jurisdiction
    out += [fact("access road: side", a.side), fact("access road ends at the plot", a.dead_end),
            fact("access road joins a 12 m street", a.joins_12m_street),
            fact("whose rules apply", j.authority), fact("inside CURE", j.inside_cure)]
    out += [fact(f"water body {w.id} ({w.drawn_as})", w.water_class) for w in site.water]
    out.append(fact("site coordinates", site.coordinates))
    if site.place is not None:
        p = site.place.value
        out.append(Fact(name="place", value=safe(", ".join(filter(None, (p.village, p.mandal,
                                                                       p.district)))),
                        status=site.place.status, source_kind=site.place.source_kind))
    for name, value in (("floors proposed on a drawing", site.proposed_floors),
                        ("floors sanctioned", site.sanctioned_floors)):
        if value is not None:
            out.append(fact(name, value))
    return out


def unresolved_facts(facts: list[Fact]) -> list[str]:
    return [f"{f.name}: {f.status.value}" for f in facts if f.status in WEAK]


# --- resolve_rules ---------------------------------------------------------------------------


def _heights(above: float, up_to: float) -> str:
    return f"{above:g} m" if above == up_to else f"{above:g}-{up_to:g} m"


def _unverified(data, path: str = "") -> list[str]:
    """Every value the rules leave UNVERIFIED, by where it sits and why."""
    found = []
    if isinstance(data, dict):
        if data.get("status") == Provenance.UNVERIFIED.value:
            why = next((data[k] for k in ("reason", "permission_note", "note", "question")
                        if data.get(k)), "not confirmed")
            found.append(f"{path}: {why}")
        for key, value in data.items():
            found += _unverified(value, f"{path}.{key}" if path else key)
    elif isinstance(data, list):
        for i, value in enumerate(data):
            label = value.get("id") if isinstance(value, dict) and "id" in value else i
            found += _unverified(value, f"{path}[{label}]")
    return found


def rules_result(project_name: str, rules: ResolvedRules) -> RulesResult:
    h = rules.height
    unverified = _unverified(rules.model_dump(mode="json"))
    if rules.jurisdiction.table_v_column is TableVColumn.OPEN:
        unverified.append("jurisdiction.table_v_column: whose rules apply is not established")
    share = rules.parking.share_pct
    return RulesResult(
        project_name=project_name, group_development=rules.category.group_development.value,
        high_rise_from_m=h.high_rise_from_m.value, high_rise_eligibility=h.high_rise.eligibility,
        eligibility_grounds=[GroundOut(id=g.id, met=g.met, measured=g.measured,
                                       required=g.required, clause=g.clause, status=g.status)
                             for g in h.high_rise.grounds],
        bands=[BandOut(heights=_heights(b.above_m, b.up_to_m), kind=b.kind.value,
                       measure=b.measure.value, permission=h.band_permission(b),
                       permission_note=b.permission_note, modelled=b.modelled,
                       setback_m=b.setback_m, front_setback_m=b.front_setback_m, gap_m=b.gap_m,
                       min_road_m=b.min_road_m, green_strip_m=b.green_strip_m, clause=b.clause,
                       status=b.status) for b in h.bands],
        limits=[LimitOut(id=lim.id, measure=lim.measure.value, bound=lim.bound, max_m=lim.max_m,
                         applicability=lim.applicability, status=lim.status, reason=lim.reason,
                         clause=lim.clause) for lim in h.limits],
        table_v_column=rules.jurisdiction.table_v_column.value,
        when_open=rules.jurisdiction.when_open.value,
        parking_share_pct=share.value if share is not None else None,
        interpretations=[InterpretationOut(id=i.id, question=i.question, selected=i.selected,
                                           readings_evaluated=i.readings(), status=i.status)
                         for i in rules.interpretations],
        unverified=unverified)


# --- inspect_envelope ------------------------------------------------------------------------


def _regions(profile) -> list[RegionOut]:
    if profile is None:
        return []
    return [RegionOut(area_sqm=round(r.area_sqm, 1),
                      max_inscribed_width_m=round(r.max_inscribed_width_m, 2),
                      length_m=round(r.length_m, 1)) for r in profile.regions]


def envelope_result(project_name: str, site: CanonicalSiteModel,
                    envelope: BuildableEnvelope) -> EnvelopeResult:
    profiles = {p.applies_to: p for p in envelope.width_profiles}
    bands = []
    for b in envelope.bands:
        key = _heights(b.above_m, b.up_to_m)
        profile = profiles.get(key)
        bands.append(BandLandOut(
            heights=key, kind=b.kind.value, permission=b.permission, setback_m=b.setback_m,
            front_setback_m=b.front_setback_m, buildable_sqm=round(b.area_sqm, 1),
            regions=_regions(profile),
            area_narrower_than=list(profile.area_narrower_than) if profile else [],
            note=b.note))
    net = site.net_plot.value.area_sqm if site.net_plot else 0.0
    return EnvelopeResult(
        project_name=project_name, net_plot_sqm=round(net, 1),
        net_plot_regions=_regions(profiles.get("net plot")), bands=bands,
        exclusions=[ExclusionOut(id=e.id, kind=e.kind.value,
                                 area_sqm=round(sum(s.area_sqm for s in e.shapes), 1),
                                 clause=e.clause) for e in envelope.exclusions],
        facts=[f"{f.rule}: {f.status.value}, {f.measured}" for f in envelope.facts])


# --- list_prototypes -------------------------------------------------------------------------


def prototype_out(p: TowerPrototype) -> PrototypeOut:
    return PrototypeOut(id=p.id, family=p.family.value, cores=p.cores,
                        flats_per_floor=p.per_floor.flats,
                        flats_by_type=dict(p.per_floor.flats_by_type),
                        length_m=round(p.length_m, 2), depth_m=round(p.depth_m, 2),
                        saleable_sqft_per_floor=round(p.per_floor.saleable_sqft, 1))


# --- candidates and reports ------------------------------------------------------------------


def candidate_summary(candidate: CandidateLayout, report: ValidationReport,
                      preferred: ParetoPoint | None) -> CandidateSummary:
    m = candidate.metrics
    return CandidateSummary(
        candidate_id=candidate.candidate_id, strategy=candidate.strategy,
        pareto_point=candidate.pareto_tag,
        preferred_massing=preferred is not None and candidate.pareto_tag == preferred.value,
        towers=len(candidate.towers),
        floors=sorted({t.floors_above_stilt for t in candidate.towers}),
        flats=m.total_flats if m else 0, saleable_sqft=round(m.saleable_sqft) if m else 0.0,
        open_space_sqm=round(m.open_space_sqm, 1) if m else 0.0,
        open_space_share_pct=round(m.open_space_share_pct, 2) if m else 0.0,
        legal_verdict=report.verdict.legal, program_verdict=report.verdict.program,
        unverified=unresolved_items(report),
        holds_under_every_reading=rests_on(report).holds_under_every_reading)


def check_out(check) -> CheckOut:
    f = check.finding
    return CheckOut(rule=f.rule, status=f.status, measured=f.measured, required=f.required,
                    clause=f.clause)


def checks_by_family(report: ValidationReport) -> list[FamilyChecks]:
    families: dict = {}
    for check in report.legal:
        families.setdefault(check.family, []).append(check_out(check))
    return [FamilyChecks(family=family, checks=checks) for family, checks in families.items()]


def targets(report: ValidationReport) -> list[TargetOut]:
    return [TargetOut(item=t.item.value, subject=t.subject, unit=t.unit,
                      legal_minimum=round(t.legal_minimum, 2), target=round(t.target, 2),
                      provided=round(t.provided, 2), meets_target=t.meets_target,
                      basis=t.basis.value) for t in report.design_targets]
