"""What the generator and an envelope say, held against what the validator recomputed.

Nothing here decides a legal outcome: each check is recomputed from the site model and the
rules. A discrepancy records where a claim and the recomputation part ways, and blocks a pass
when a legal quantity is claimed more favourably than it is (a footprint elsewhere than drawn, a
setback smaller than the law's, a built-up area smaller than it is, an open space larger).
"""

from __future__ import annotations

from siteplan.contracts.accounting import PartitionLedger
from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.common import Shape, Status, digest
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.envelope import BuildableEnvelope
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.contracts.validation import Check, Discrepancy
from siteplan.units import sqm_to_sqft
from siteplan.validator.accounting import Ledger
from siteplan.validator.context import Context
from siteplan.validator.drawn import Drawn
from siteplan.validator.measure import TowerGeometry
from siteplan.validator.parking import cellar_setback_m
from siteplan.validator.shapes import mended, union_of_all

FOOTPRINT_SQM = 0.1  # a footprint that differs by less than this is the same footprint
FOOTPRINT_SHARE = 0.001  # or by this share of its area
METRIC_SHARE = 0.005  # a figure that differs by less than this share is the same figure
PARTITION_SHARE = 0.005  # a ledger use that differs by less than this share of the net area
CARS_SHARE = 0.02  # a count of cars that differs by less than this share is the same count
SETBACK_SLACK_M = 0.01
BAND_SLACK_M = 1e-6
Z = Status


def _d(item: str, source: str, theirs: str, ours: str, blocks: bool) -> Discrepancy:
    return Discrepancy(item=item, source=source, theirs=theirs, ours=ours, blocks_pass=blocks)


def references(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
               candidate: CandidateLayout, envelope: BuildableEnvelope | None
               ) -> list[Discrepancy]:
    """Whether the candidate and the rules were made for these very inputs. A candidate made for
    another site, rules or brief proves nothing about this one."""
    out = []
    for item, theirs, ours in (("candidate.site_ref", candidate.site_ref, digest(site)),
                               ("candidate.rules_ref", candidate.rules_ref, digest(rules)),
                               ("candidate.brief_ref", candidate.brief_ref, digest(brief)),
                               ("rules.site_ref", rules.site_ref, digest(site))):
        if theirs != ours:
            out.append(_d(item, "generator", theirs, ours, True))
    if envelope is not None:
        if candidate.envelope_ref and candidate.envelope_ref != digest(envelope):
            out.append(_d("candidate.envelope_ref", "envelope", candidate.envelope_ref,
                          digest(envelope), False))
        for item, theirs, ours in (("envelope.site_ref", envelope.site_ref, digest(site)),
                                   ("envelope.rules_ref", envelope.rules_ref, digest(rules))):
            if theirs != ours:
                out.append(_d(item, "envelope", theirs, ours, False))
    return out


def flaws(towers: tuple[TowerGeometry, ...], drawn: Drawn | None) -> list[Discrepancy]:
    """Shapes that cross themselves. They were mended to be measured at all, but a layout that
    draws one is not a layout to pass."""
    found = [f for t in towers for f in t.flaws] + (list(drawn.flaws) if drawn else [])
    return [_d("shape that crosses itself", "generator", problem,
               "judged on the ground the shape encloses, mended", True) for problem in found]


def footprints(towers: tuple[TowerGeometry, ...]) -> list[Discrepancy]:
    """A tower's stated footprint against the one its prototype and placement make."""
    out = []
    for t in towers:
        off = t.footprint.symmetric_difference(t.stated).area
        if off > max(FOOTPRINT_SQM, FOOTPRINT_SHARE * t.footprint.area):
            out.append(_d(f"footprint {t.name}", "generator",
                          f"{t.stated.area:,.2f} m² at ({t.stated.centroid.x:.1f}, "
                          f"{t.stated.centroid.y:.1f})",
                          f"{t.footprint.area:,.2f} m² at ({t.footprint.centroid.x:.1f}, "
                          f"{t.footprint.centroid.y:.1f}); {off:,.2f} m² differ", True))
    return out


def claims(candidate: CandidateLayout, legal: list[Check]) -> list[Discrepancy]:
    """The generator's own findings against ours, rule by rule. It claiming PASS where the
    validator FAILs blocks a pass; any other disagreement is recorded without blocking."""
    ours = {c.finding.rule: c.finding for c in legal}
    judged = {Z.PASS, Z.FAIL, Z.UNVERIFIED}
    out = []
    for theirs in candidate.generator_claims:
        mine = ours.get(theirs.rule)
        if mine is None or theirs.status == mine.status:
            continue
        if theirs.status in judged and mine.status in judged:
            out.append(_d(theirs.rule, "generator", f"{theirs.status.value}: {theirs.measured}",
                          f"{mine.status.value}: {mine.measured}",
                          theirs.status is Z.PASS and mine.status is Z.FAIL))
    return out


def metrics(ctx: Context, built_up_sqm: float, qualifying_sqm: float, units: dict[str, int]
            ) -> list[Discrepancy]:
    """The generator's own totals against the recomputed ones. A built-up area claimed smaller
    than it is, or open space claimed larger than counts, flatters the layout: those block."""
    m = ctx.candidate.metrics
    if m is None:
        return []
    out = []
    built_up_sqft = sqm_to_sqft(built_up_sqm)
    if abs(m.built_up_sqft - built_up_sqft) > METRIC_SHARE * max(built_up_sqft, 1.0):
        out.append(_d("built-up area", "generator", f"{m.built_up_sqft:,.0f} sft",
                      f"{built_up_sqft:,.0f} sft", m.built_up_sqft < built_up_sqft))
    tower_floor_sqft = sqm_to_sqft(sum(t.built_up_sqm for t in ctx.towers))
    if abs(m.tower_floor_sqft - tower_floor_sqft) > METRIC_SHARE * max(tower_floor_sqft, 1.0):
        out.append(_d("tower floor area", "generator", f"{m.tower_floor_sqft:,.0f} sft",
                      f"{tower_floor_sqft:,.0f} sft", m.tower_floor_sqft < tower_floor_sqft))
    if m.open_space_sqm > qualifying_sqm + METRIC_SHARE * max(qualifying_sqm, 1.0):
        out.append(_d("open space", "generator", f"{m.open_space_sqm:,.1f} m²",
                      f"{qualifying_sqm:,.1f} m² counts", True))
    total = sum(units.values())
    if m.total_flats != total:
        out.append(_d("flats", "generator", str(m.total_flats), str(total), False))
    if m.flats_by_type and m.flats_by_type != units:
        out.append(_d("flats by type", "generator", str(dict(sorted(m.flats_by_type.items()))),
                      str(dict(sorted(units.items()))), False))
    return out


def cellars(ctx: Context) -> list[Discrepancy]:
    """A cellar setback stated smaller than rule 13(c)(x) asks flatters the layout."""
    d = ctx.drawn
    if d.cellar_setback_claimed_m is None or not d.cellar_levels:
        return []
    need = cellar_setback_m(ctx.rules, ctx.net.area, d.cellar_levels)
    if d.cellar_setback_claimed_m + SETBACK_SLACK_M < need:
        return [_d("cellar setback", "generator", f"{d.cellar_setback_claimed_m:g} m",
                   f"{need:g} m", True)]
    return []


def cars(candidate: CandidateLayout, laid_out: float) -> list[Discrepancy]:
    """The cars the generator says fit, against the ones laid out here. Said to fit more than
    were found, it is recorded (not blocked: the layout rules are the validator's own)."""
    m = candidate.metrics
    claimed = (m.extra.get("parking", {}).get("cars") or {}) if m else {}
    total = sum(claimed.values())
    if total > laid_out * (1 + CARS_SHARE) + 1:
        return [_d("cars that fit", "generator", f"{total:,}", f"{laid_out:,.0f}", False)]
    return []


def partition(candidate: CandidateLayout, ledger: Ledger, net: Shape) -> list[Discrepancy]:
    """The candidate's own ledger, held to the contract's invariants and compared with ours,
    use by use."""
    claimed: PartitionLedger | None = candidate.partition
    if claimed is None:
        return []
    out = [_d("partition invariant", "generator", problem, "every square metre once, summing "
              "to the net area", True) for problem in claimed.problems(net)]
    tolerance = PARTITION_SHARE * ledger.ledger.net_area_sqm
    mine = ledger.ledger.by_use()
    theirs = claimed.by_use()
    for use in sorted(set(mine) | set(theirs), key=lambda u: u.value):
        a, b = theirs.get(use, 0.0), mine.get(use, 0.0)
        if abs(a - b) > tolerance:
            out.append(_d(f"partition: {use.value}", "generator", f"{a:,.1f} m²", f"{b:,.1f} m²",
                          False))
    if abs(claimed.net_area_sqm - ledger.ledger.net_area_sqm) > tolerance:
        out.append(_d("partition: net area", "generator", f"{claimed.net_area_sqm:,.1f} m²",
                      f"{ledger.ledger.net_area_sqm:,.1f} m²", True))
    return out


def envelope_checks(ctx: Context, envelope: BuildableEnvelope) -> list[Discrepancy]:
    """The envelope's setbacks, buildable land and exclusions against ours. An envelope more
    lenient than the law (a smaller setback, more buildable land, a smaller buffer) would let a
    layout pass that the law forbids, so it blocks; a stricter one only costs room."""
    if envelope.site_ref != digest(ctx.site) or envelope.rules_ref != digest(ctx.rules):
        return []  # an envelope for other inputs says nothing about these
    out = []
    keep_out = ctx.land.keep_out_on_site
    for band in envelope.bands:
        mine = next((b for b in ctx.rules.height.bands if abs(b.above_m - band.above_m) < 1e-6
                     and abs(b.up_to_m - band.up_to_m) < 1e-6), None)
        if mine is None or mine.setback_m is None or band.setback_m is None:
            continue
        label = f"{band.above_m:g}-{band.up_to_m:g} m"
        if abs(band.setback_m - mine.setback_m) > BAND_SLACK_M:
            out.append(_d(f"envelope setback, band {label}", "envelope", f"{band.setback_m:g} m",
                          f"{mine.setback_m:g} m", band.setback_m < mine.setback_m))
        land = ctx.net.buffer(-mine.setback_m).difference(keep_out)
        stated = union_of_all([mended(s.to_shapely())[0] for s in band.buildable]).area
        if abs(stated - land.area) > METRIC_SHARE * max(land.area, 1.0):
            out.append(_d(f"envelope buildable land, band {label}", "envelope",
                          f"{stated:,.1f} m²", f"{land.area:,.1f} m²", stated > land.area))
    if envelope.exclusions or not keep_out.is_empty:
        stated = union_of_all([mended(s.to_shapely())[0]
                               for e in envelope.exclusions for s in e.shapes])
        stated_area = stated.intersection(ctx.net).area
        if abs(stated_area - keep_out.area) > METRIC_SHARE * max(keep_out.area, 1.0):
            out.append(_d("envelope exclusions", "envelope", f"{stated_area:,.1f} m²",
                          f"{keep_out.area:,.1f} m² of water buffer", stated_area < keep_out.area))
    return out
