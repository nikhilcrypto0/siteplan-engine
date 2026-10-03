"""The validator takes any candidate the contract allows and returns a report: turned towers,
mirrored ones, no towers, no circulation, and the same answer twice."""

import pytest
from shapely.geometry import Polygon
from validator_helpers import fixture, footprint, move_tower, shape, status

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


CROSSES_ITSELF = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])  # a bowtie: not a valid polygon


def _draw_bowtie(where):
    def edit(candidate):
        bowtie = shape(CROSSES_ITSELF)
        program, circulation = candidate.program, candidate.circulation
        if where == "road":
            circulation.roads[0].shapes = [bowtie]
        elif where == "fire hardstanding":
            circulation.fire_hardstanding = [bowtie]
        elif where == "the club house":
            program.club_house.shape = bowtie
        elif where == "a parking bay":
            program.bays = [*program.bays, bowtie]
        elif where == "open space":
            program.open_space = [*program.open_space, bowtie]
        elif where == "a ramp":
            program.ramps = [*program.ramps, bowtie]
        elif where == "the green strip":
            program.green_strip = [bowtie]
        elif where == "the cellar outline":
            program.cellars.outline = [bowtie]
        elif where == "the footprint it states":
            candidate.towers[0].footprint = bowtie
        elif where == "its prototype's footprint":
            candidate.prototypes_used[0].footprint = bowtie
    return edit


@pytest.mark.parametrize("where", ["road", "fire hardstanding", "the club house", "a parking bay",
                                   "open space", "a ramp", "the green strip",
                                   "the cellar outline", "the footprint it states",
                                   "its prototype's footprint"])
def test_a_shape_that_crosses_itself_is_named_and_blocks_a_pass_instead_of_stopping_the_run(where):
    report = fixture("rectangle").edited(_draw_bowtie(where)).report()
    found = [d for d in report.cross_checks if d.item == "malformed shape"]
    assert len(found) == 1 and found[0].blocks_pass, where
    assert where in found[0].theirs and "Self-intersection" in found[0].theirs
    assert report.verdict.legal is LegalVerdict.FAIL
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report


def test_a_site_whose_net_plot_crosses_itself_or_encloses_nothing_is_refused():
    for outline in (CROSSES_ITSELF, Polygon([(0, 0), (10, 0), (20, 0)])):
        def ruin(site, outline=outline):
            site.net_plot.value = shape(outline)
        report = fixture("rectangle").with_site(ruin).report()
        assert [c.finding.status for c in report.legal] == [Z.UNVERIFIED]
        assert report.legal[0].finding.rule == "Net plot"
        assert "crosses itself or encloses no ground" in report.legal[0].finding.measured
        assert report.verdict.legal is LegalVerdict.UNVERIFIED  # never a pass


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_number_that_is_not_a_number_fails_the_candidate_and_names_where(bad):
    def spoil(candidate):
        candidate.towers[1].x = bad
        candidate.metrics.saleable_sqft = bad
    report = fixture("rectangle").edited(spoil).report()
    assert [c.finding.status for c in report.legal] == [Z.FAIL]
    measured = report.legal[0].finding.measured
    assert "towers[1].x" in measured and "metrics.saleable_sqft" in measured
    assert report.verdict.legal is LegalVerdict.FAIL
    assert [c.finding.status for c in report.program] == [Z.UNVERIFIED]
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report


def _give_up(error):
    def raise_it(*args, **kwargs):
        raise error
    return raise_it


def test_a_geometry_error_in_one_group_of_checks_leaves_every_other_verdict_standing(
        monkeypatch):
    """One shape the library chokes on must not erase a FAIL found elsewhere (a review found a
    poisoned claim turning a FAIL into one UNVERIFIED line)."""
    from shapely.errors import GEOSException

    def too_close(candidate):
        move_tower(candidate, "T1", 0.0, 60.0)  # up against the north boundary
    inputs = fixture("rectangle").edited(too_close)
    clean = {c.finding.rule: c.finding.status for c in inputs.report().legal}
    assert clean["All-round setback: T1"] is Z.FAIL

    monkeypatch.setattr("siteplan.validator.open_space.qualifying", _give_up(GEOSException(
        "TopologyException: found non-noded intersection (made up)")))
    report = inputs.report()
    broken = [c for c in report.legal if c.finding.rule == "Open space: could not be measured"]
    assert len(broken) == 1 and broken[0].finding.status is Z.UNVERIFIED
    assert "non-noded intersection" in broken[0].finding.measured
    kept = {c.finding.rule: c.finding.status for c in report.legal}
    for rule, status_ in clean.items():
        if "open space" not in rule.lower() and "pocket" not in rule.lower():
            assert kept[rule] is status_, rule
    assert report.verdict.legal is LegalVerdict.FAIL
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report


def test_a_geometry_error_while_the_ground_is_laid_out_is_one_unverified_report(monkeypatch):
    from shapely.errors import GEOSException

    monkeypatch.setattr("siteplan.validator.accounting.recompute", _give_up(GEOSException(
        "TopologyException: found non-noded intersection (made up)")))
    report = fixture("rectangle").report()
    assert [c.finding.status for c in report.legal] == [Z.UNVERIFIED]
    assert report.legal[0].finding.rule == "Shapes the geometry library can measure"
    assert "non-noded intersection" in report.legal[0].finding.measured
    assert report.verdict.legal is LegalVerdict.UNVERIFIED
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report


def test_a_claim_the_library_cannot_compare_is_recorded_and_costs_no_verdict(monkeypatch):
    from shapely.errors import GEOSException

    clean = {c.finding.rule: c.finding.status for c in fixture("rectangle").report().legal}
    monkeypatch.setattr("siteplan.validator.cross_checks.metrics",
                        _give_up(GEOSException("made up")))
    report = fixture("rectangle").report()
    found = [d for d in report.cross_checks if d.item == "metrics could not be compared"]
    assert len(found) == 1 and not found[0].blocks_pass
    assert {c.finding.rule: c.finding.status for c in report.legal} == clean


def test_a_mistake_of_the_validators_own_is_not_hidden_as_a_geometry_error(monkeypatch):
    monkeypatch.setattr("siteplan.validator.open_space.qualifying",
                        _give_up(ValueError("a bug")))
    with pytest.raises(ValueError, match="a bug"):
        fixture("rectangle").report()
