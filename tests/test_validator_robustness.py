"""The validator takes any candidate the contract allows and returns a report: turned towers,
mirrored ones, no towers, no circulation, and the same answer twice."""

import pytest
from shapely.geometry import Polygon
from validator_helpers import fixture, footprint, shape, status

from siteplan.cases import CaseBuilding
from siteplan.contracts import ValidationReport
from siteplan.contracts.candidate import SiteProgram
from siteplan.contracts.common import Status
from siteplan.contracts.validation import LegalVerdict

TEST_CLASS = "normative"
Z = Status


def _turn_towers(degrees):
    def edit(candidate):
        for t in candidate.towers:
            t.rotation_deg = (t.rotation_deg + degrees) % 360
            t.footprint = shape(candidate.placed_footprint(t))
    return edit


@pytest.mark.parametrize("degrees", [15.0, 45.0, 133.0, 270.0])
def test_towers_turned_to_any_angle_are_judged_without_error(degrees):
    inputs = fixture("rectangle").edited(_turn_towers(degrees))
    report = inputs.report()
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report
    for t in inputs.candidate.towers:  # turning moves a tower, it does not change its area
        assert footprint(inputs.candidate, t.name).area == pytest.approx(
            footprint(fixture("rectangle").candidate, t.name).area, rel=1e-6)
    assert not [d for d in report.cross_checks if d.item.startswith("footprint")]


def _l_tower(candidate, mirrored):
    """T1 replaced by an L-shaped block, mirrored if asked, its stated footprint as placed."""
    from validator_cases import _prototype

    building = CaseBuilding(name="L", floors=8, stilt_height_m=3, floor_height_m=3, outline=[
        (0, 0), (40, 0), (40, 12), (16, 12), (16, 28), (0, 28)])
    prototype, outline = _prototype(building, "l-block")
    candidate.prototypes_used.append(prototype)
    t = candidate.towers[0]
    t.prototype_id, t.mirrored, t.rotation_deg, t.x, t.y = "l-block", mirrored, 0.0, 70.0, 60.0
    t.footprint = shape(candidate.placed_footprint(t))
    assert outline


def test_a_mirrored_tower_is_placed_as_the_contract_says_and_a_forgotten_mirror_is_caught():
    plain = fixture("rectangle").edited(lambda c: _l_tower(c, mirrored=False))
    mirrored = fixture("rectangle").edited(lambda c: _l_tower(c, mirrored=True))
    a, b = footprint(plain.candidate, "T1"), footprint(mirrored.candidate, "T1")
    assert a.area == pytest.approx(b.area) and a.symmetric_difference(b).area > 100

    assert not [d for d in mirrored.report().cross_checks if d.item == "footprint T1"]

    def forget(candidate):  # the generator states the unmirrored footprint for a mirrored tower
        _l_tower(candidate, mirrored=True)
        candidate.towers[0].footprint = shape(a)
    d = [x for x in fixture("rectangle").edited(forget).report().cross_checks
         if x.item == "footprint T1"]
    assert len(d) == 1 and d[0].blocks_pass


def test_a_non_rectangular_block_is_measured_on_its_own_outline():
    inputs = fixture("rectangle").edited(lambda c: _l_tower(c, mirrored=False))
    report = inputs.report()
    assert report.recomputed.towers[0].setback_m == pytest.approx(
        Polygon([(0, 0), (150, 0), (150, 100), (0, 100)]).boundary.distance(
            footprint(inputs.candidate, "T1")))
    assert status(report, "Fire access: T1") in (Z.PASS, Z.FAIL)


def test_a_candidate_with_no_towers_is_judged_and_cannot_pass():
    inputs = fixture("rectangle").edited(lambda c: (setattr(c, "towers", []),
                                                    setattr(c, "prototypes_used", [])))
    report = inputs.report()
    assert report.verdict.legal is not LegalVerdict.PASS
    assert report.recomputed.towers == [] and report.recomputed.units_by_type == {}


def test_a_candidate_that_draws_only_towers_is_judged_and_cannot_pass():
    def bare(candidate):
        candidate.circulation.roads, candidate.circulation.gates = [], []
        candidate.circulation.fire_hardstanding = []
        candidate.program = SiteProgram()
    report = fixture("rectangle").edited(bare).report()
    assert report.verdict.legal is not LegalVerdict.PASS
    assert status(report, "Fire access: around each block") is Z.UNVERIFIED
    assert status(report, "Organized open space (tot-lot)") is Z.UNVERIFIED


def test_the_same_inputs_give_the_same_report():
    inputs = fixture("l_plot_with_arm")
    assert inputs.report(envelope=True) == inputs.report(envelope=True)


def _shifted(node, dx, dy, key=None):
    """A contract's dumped content with every survey coordinate moved (the prototypes keep their
    own frame)."""
    if isinstance(node, dict):
        out = {k: (v if k == "prototypes_used" else _shifted(v, dx, dy, k))
               for k, v in node.items()}
        if "prototype_id" in node:
            out["x"], out["y"] = node["x"] + dx, node["y"] + dy
        return out
    if isinstance(node, (list, tuple)):
        if key in ("outer", "points"):
            return [(x + dx, y + dy) for x, y in node]
        if key == "holes":
            return [[(x + dx, y + dy) for x, y in ring] for ring in node]
        return [_shifted(v, dx, dy) for v in node]
    return node


@pytest.mark.parametrize("name", ["rectangle", "nala_plot"])
def test_a_survey_far_from_the_origin_gives_the_same_statuses(name):
    """Real survey coordinates are large; nothing in the validator may depend on where the
    origin is."""
    from dataclasses import replace

    from siteplan.contracts import CandidateLayout, CanonicalSiteModel, digest

    base = fixture(name)
    dx, dy = 812_345.25, 1_234_567.75
    site = CanonicalSiteModel.model_validate(_shifted(base.site.model_dump(), dx, dy))
    candidate = CandidateLayout.model_validate(_shifted(base.candidate.model_dump(), dx, dy))
    rules = base.rules.model_copy(update={"site_ref": digest(site)})
    far = replace(base, site=site, rules=rules, candidate=candidate, envelope=None).restated()
    near, shifted = base.report(), far.report()
    assert {c.finding.rule: c.finding.status for c in shifted.legal} == {
        c.finding.rule: c.finding.status for c in near.legal}
    for key, value in near.recomputed.quantities.items():
        assert shifted.recomputed.quantities[key] == pytest.approx(value, rel=1e-4, abs=0.05), key
