"""The legal envelope on the firm's real drawings (stream A1).

The drawings, the architect's answers and the debug profiles live in fixtures/ (gitignored), so no
client data is committed and these tests skip on a clean clone. Dhulapally is run two ways that
are never mixed: BLIND (the raw survey and the architect's answers: the net plot cannot be placed,
and the envelope stops and says so) and DEBUG (the firm's net outline, tagged FIRM_FINISHED_PLAN,
stands in for the strip: it carries the geometry checks and is never evidence for a rule).
"""

import functools
import json
from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import Polygon

from siteplan.cli import main
from siteplan.contracts.accounting import LayerKind
from siteplan.contracts.common import Provenance, Status, union_of
from siteplan.contracts.resolved_rules import (
    ALL,
    CIRCULATION_IN_SETBACK,
    OPEN_SPACE_BASIS,
    STILT_IN_RULE_HEIGHT,
    HeightMeasure,
    TableVColumn,
)
from siteplan.intake import build_project, extract, load_defaults, save
from siteplan.legal.debug_drawing import write_debug_dxf, write_debug_svg
from siteplan.legal.envelope import NetPlotUnknown, envelope
from siteplan.legal.resolve import resolve
from siteplan.legal.site import readings_of, site_from_project
from siteplan.profiles import apply_profile, load_profile
from siteplan.project import Project
from siteplan.runner import load_plot, load_water

TEST_CLASS = "normative"
FIXTURES = Path(__file__).parent.parent / "fixtures"
WORKSPACE = FIXTURES / "workspace"
DHULAPALLY = WORKSPACE / "dhulapally_survey.pdf"
ANSWERS = FIXTURES / "acceptance" / "dhulapally.answers.json"
COUNTED = FIXTURES / "profiles" / "dhulapally.debug.counted.profile.json"
NOT_COUNTED = FIXTURES / "profiles" / "dhulapally.debug.not-counted.profile.json"
SUCHITRA = WORKSPACE / "suchitra_survey.pdf"
ORDER = FIXTURES / "rules" / "go168-2012.pdf"
# Suchitra has no answers file in fixtures: the road is taken "as drawn", the nala is cyan.
SUCHITRA_ANSWERS = {
    "main_road": "2", "road_row": "as drawn", "dead_end": "unknown", "street_join": "unknown",
    "surrender": "no", "water": "#00FFFF nala over 10 m", "authority": "HMDA",
    "inside_cure": "no", "name": "Suchitra (survey only)", "mix": "70% 2BHK, 30% 3BHK",
    "floors": "max", "club_house": "yes"}


def _need(*paths: Path) -> None:
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"client fixtures not present: {', '.join(missing)}")


def _project(survey: Path, answers: dict, profile: Path | None = None) -> dict:
    """The project file as `siteplan start` writes it, a debug profile applied when given."""
    built = build_project(extract(survey), answers, load_defaults(WORKSPACE))
    return apply_profile(built, load_profile(profile)) if profile else built


@functools.cache
def _dhulapally(profile: Path | None = None):
    """The project and its site model, built once per profile (reading the PDF is the slow part;
    no test changes what it gets)."""
    _need(DHULAPALLY, ANSWERS, *([profile] if profile else []))
    project = Project.model_validate(_project(DHULAPALLY, json.loads(ANSWERS.read_text()),
                                              profile))
    return project, site_from_project(project, DHULAPALLY)


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


def _land(shapes) -> Polygon:
    return union_of(list(shapes))


def _limit(rules, measure):
    return [lim for lim in rules.height.limits if lim.measure is measure]


# --- Criterion 4: Dhulapally, the 60 ft road confirmed ----------------------------------------


def test_dhulapally_on_its_60_ft_road_may_rise_to_30_m_of_rule_height():
    _, site = _dhulapally()
    rules = resolve(site)
    limit, = _limit(rules, HeightMeasure.RULE_HEIGHT)
    assert limit.max_m == 30.0 and limit.status is Provenance.USER_CONFIRMED
    assert "the 18.29 m road" in limit.reason and "serves buildings up to 30 m" in limit.reason
    assert "up to 35 m needs 24 m of road" in limit.reason  # the next band needs the wider road
    assert "substituted by G.O.Ms.No.50 of 2019" in limit.clause
    assert rules.height.high_rise_from_m.value == 21.0
    assert rules.category.group_development.value and rules.circulation.applies.value
    assert [b.setback_m for b in rules.height.bands if b.modelled] == [
        8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 20]


def test_dhulapally_keeps_the_dead_end_street_join_and_airport_open_not_guessed():
    project, site = _dhulapally()
    rules = resolve(site)
    physical, = _limit(rules, HeightMeasure.PHYSICAL_HEIGHT)
    assert physical.max_m == 30.0 and physical.status is Provenance.UNVERIFIED
    assert physical.applies_if == "the access road ends at the plot"
    airport, = _limit(rules, HeightMeasure.AMSL)
    assert airport.max_m is None and airport.status is Provenance.UNVERIFIED
    assert site.access.joins_12m_street.value is None
    assert site.access.joins_12m_street.status is Provenance.UNVERIFIED
    assert rules.jurisdiction.table_v_column is TableVColumn.OPEN  # CMC and CURE not confirmed
    assert rules.parking.share_pct is None


def test_dhulapally_open_space_is_asked_under_each_reading_of_its_area():
    _, site = _dhulapally()
    rules = resolve(site)
    asked = rules.open_space.requirement_sqm_by_reading
    assert asked["gross_before_surrender"] == pytest.approx(2013.11, rel=1e-4)
    assert asked["net_after_surrender"] == pytest.approx(1896.84, rel=1e-4)
    assert asked["gross_after_surrender"] == pytest.approx(asked["net_after_surrender"])
    for reading in (STILT_IN_RULE_HEIGHT, OPEN_SPACE_BASIS, CIRCULATION_IN_SETBACK):
        assert rules.interpretation(reading).selected == ALL


def test_no_floor_count_is_asserted_anywhere_in_dhulapallys_rules_or_envelope():
    _, site = _dhulapally(COUNTED)
    rules = resolve(site)
    env = envelope(site, rules)
    for dumped in (rules.model_dump_json(), env.model_dump_json()):
        assert not [k for k in _keys(json.loads(dumped)) if "floor" in k.lower()]
    assert not [f for f in env.facts if "floor" in f.rule.lower()]


# --- The blind run stops where the strip is unknown -------------------------------------------


def test_the_blind_dhulapally_site_has_no_net_plot_and_the_envelope_stops_and_says_so():
    project, site = _dhulapally()
    assert site.net_plot is None
    deduction, = site.ownership.deductions
    assert deduction.location.how.value == "UNKNOWN" and deduction.location.side == "E"
    with pytest.raises(NetPlotUnknown) as stop:
        envelope(site, resolve(site))
    for what in ("net plot cannot be placed", "the E side is named", "road_strip_width_m",
                 "net_plot_m", "does not guess a strip's location"):
        assert what in str(stop.value)


def test_the_command_stops_on_the_blind_dhulapally_project_and_writes_nothing(tmp_path, capsys):
    _need(DHULAPALLY, ANSWERS)
    path = save(_project(DHULAPALLY, json.loads(ANSWERS.read_text())), tmp_path / "blind.json")
    out = tmp_path / "out"
    assert main(["envelope", str(path), "--survey", str(DHULAPALLY), "--out", str(out)]) == 2
    assert "net plot cannot be placed" in capsys.readouterr().err
    assert not (out / "rules.json").exists()


# --- Dhulapally, debug: the geometry ----------------------------------------------------------


def test_the_debug_envelope_cuts_each_band_from_the_firms_net_outline():
    _, site = _dhulapally(COUNTED)
    assert site.net_plot.source_kind.value == "FIRM_FINISHED_PLAN"
    rules = resolve(site)
    env = envelope(site, rules)
    net = site.net_plot.value.to_shapely()
    assert net.area == pytest.approx(18_968.9, rel=1e-3)
    below, *high = env.bands
    assert not below.modelled and below.kind.value == "NON_HIGH_RISE"
    assert [(b.up_to_m, b.setback_m) for b in high] == [(24.0, 8.0), (27.0, 9.0), (30.0, 10.0)]
    assert [b.area_sqm for b in high] == pytest.approx([13_198, 12_512, 11_834], rel=1e-3)
    for shorter, taller in zip(high, high[1:], strict=False):
        assert _land(taller.buildable).difference(_land(shorter.buildable)).area < 1e-6
    for band in high:
        assert net.buffer(-band.setback_m, join_style="mitre").difference(
            _land(band.setback_envelope)).area < 1e-3
    assert env.exclusions == []
    finding = next(f for f in env.facts if f.rule == "Net plot outline")
    assert finding.status is Status.UNVERIFIED and "DEBUG ONLY" in finding.note
    unverified = {f.rule for f in env.facts if f.status is Status.UNVERIFIED}
    assert {"Physical-height limit", "Height above sea level", "Street join (NBC 4.6(a))",
            "Table V column"} <= unverified


def test_the_northern_arm_is_in_every_width_profile_and_held_back_by_nothing():
    _, site = _dhulapally(COUNTED)
    env = envelope(site, resolve(site))
    arms = {}
    for profile in env.width_profiles:
        north = [r for r in profile.regions
                 if r.shape.to_shapely().centroid.y > 180]  # the tail, above the main body
        assert north, profile.applies_to
        arms[profile.applies_to] = max(north, key=lambda r: r.area_sqm)
    assert list(arms) == ["net plot", "21-24 m", "24-27 m", "27-30 m"]
    assert 20 < arms["net plot"].max_inscribed_width_m < 30  # about 24 m where it tapers
    bands = ["21-24 m", "24-27 m", "27-30 m"]
    widths = [arms[b].max_inscribed_width_m for b in bands]
    areas = [arms[b].area_sqm for b in bands]
    assert widths == sorted(widths, reverse=True) and areas == sorted(areas, reverse=True)
    assert 10 < widths[-1] < widths[0] < 18 and all(a > 900 for a in areas)
    assert env.exclusions == [] and all(r.length_m > 40 for r in arms.values())
    for band, key in zip(env.bands[1:], bands, strict=True):  # kept in the buildable land
        kept = _land(band.buildable).intersection(arms[key].shape.to_shapely())
        assert kept.area == pytest.approx(arms[key].area_sqm, rel=0.02)
    assert not [layer for layer in env.rule_layers.layers
                if layer.kind in (LayerKind.WATER_BUFFER, LayerKind.BLOCK_GAP)]
    text = env.model_dump_json().lower()  # narrow land is reported, never classed
    assert not [word for word in ("unusable", "reserved", "too narrow", "not buildable")
                if word in text]


def test_the_firms_own_site_plan_given_as_the_survey_is_a_debug_outline_with_the_same_bands():
    """The firm's DXF draws the net outline itself, so the blind project needs no strip placed;
    the outline is FIRM_FINISHED_PLAN (the workspace lists the file), and the land it gives is
    the land the registered debug profile gives."""
    plan = WORKSPACE / "DULAPALLY_SITE_PLANS.dxf"
    _need(plan)
    project, blind = _dhulapally()
    assert blind.net_plot is None
    site = site_from_project(project, plan)
    assert site.net_plot.source_kind.value == "FIRM_FINISHED_PLAN"
    assert site.net_plot.status.value == "ASSUMED_FOR_TEST"
    here = envelope(site, resolve(site))
    there = envelope(_dhulapally(COUNTED)[1], resolve(_dhulapally(COUNTED)[1]))
    assert [b.area_sqm for b in here.bands] == pytest.approx([b.area_sqm for b in there.bands],
                                                             rel=1e-3)


def test_the_stilt_reading_changes_the_rules_record_and_not_the_land():
    project, site = _dhulapally(NOT_COUNTED)
    selections, when_open = readings_of(project)
    assert selections == {STILT_IN_RULE_HEIGHT: "not_counted"}
    rules = resolve(site, selections=selections, when_open=when_open)
    stilt = rules.interpretation(STILT_IN_RULE_HEIGHT)
    assert stilt.selected == "not_counted" and stilt.status is Provenance.ASSUMED_FOR_TEST
    counted = _dhulapally(COUNTED)[1]
    here, there = envelope(site, rules), envelope(counted, resolve(counted))
    assert [b.area_sqm for b in here.bands] == pytest.approx([b.area_sqm for b in there.bands])


def test_the_debug_command_writes_all_four_files_and_flags_the_outline_as_debug(tmp_path, capsys):
    _need(DHULAPALLY, ANSWERS, COUNTED)
    path = save(_project(DHULAPALLY, json.loads(ANSWERS.read_text()), COUNTED),
                tmp_path / "debug.json")
    out = tmp_path / "out"
    assert main(["envelope", str(path), "--survey", str(DHULAPALLY), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert {p.name for p in out.iterdir()} == {"rules.json", "envelope.json", "envelope.dxf",
                                               "envelope.svg"}
    assert "DEBUG ONLY: the net outline comes from the firm's finished plan" in printed
    assert "rule_height: 30 m [USER_CONFIRMED]" in printed
    assert "OPEN SPACE REQUIRED (10%" in printed and "net_after_surrender: 1,897 m2" in printed
    doc = ezdxf.readfile(out / "envelope.dxf")
    assert doc.header["$INSUNITS"] == 6
    assert {"NET-SITE", "SETBACK-21-24", "BUILDABLE-27-30", "WIDTH-REGIONS-27-30"} <= {
        layer.dxf.name for layer in doc.layers}


def test_the_debug_drawing_of_dhulapally_keeps_the_survey_boundary_beside_the_net_outline(
        tmp_path):
    _, site = _dhulapally(COUNTED)
    rules = resolve(site)
    env = envelope(site, rules)
    doc = ezdxf.readfile(write_debug_dxf(site, rules, env, tmp_path / "d.dxf"))
    polylines = {layer: [Polygon([(x, y) for x, y, *_ in e.get_points()]).area
                         for e in doc.modelspace().query("LWPOLYLINE") if e.dxf.layer == layer]
                 for layer in ("ORIGINAL-SITE", "NET-SITE")}
    assert polylines["ORIGINAL-SITE"][0] == pytest.approx(site.boundary.area_sqm)
    assert polylines["NET-SITE"][0] == pytest.approx(18_968.9, rel=1e-3)
    assert polylines["ORIGINAL-SITE"][0] > polylines["NET-SITE"][0]  # the strip is outside
    assert write_debug_svg(site, rules, env, tmp_path / "d.svg").read_text().startswith("<svg")


# --- Criterion 5: Suchitra --------------------------------------------------------------------


@functools.cache
def _suchitra():
    _need(SUCHITRA)
    project = Project.model_validate(_project(SUCHITRA, SUCHITRA_ANSWERS))
    return project, site_from_project(project, SUCHITRA)


def test_suchitras_nala_buffer_is_an_exclusion_the_same_land_the_layout_keeps_clear():
    project, site = _suchitra()
    rules = resolve(site)
    env = envelope(site, rules)
    water, = env.exclusions
    assert water.kind.value == "WATER_BUFFER" and water.source_ref == "water-1"
    assert rules.water.buffer_m_by_class.value[site.water[0].water_class.value] == 9.0
    kept_clear, _ = load_water(project, SUCHITRA)  # what the layout keeps off
    plot, _ = load_plot(project, SUCHITRA)
    assert _land(water.shapes).area == pytest.approx(plot.intersection(kept_clear).area, abs=0.5)
    assert _land(water.shapes).area == pytest.approx(702, abs=2)  # AGENTS.md: 702 m² of the plot
    assert len(site.water[0].lines) == 4  # the lines the survey draws in cyan
    for band in env.bands:
        assert _land(band.buildable).intersection(_land(water.shapes)).area < 1e-6
    layer, = env.rule_layers.of(LayerKind.WATER_BUFFER)
    assert abs(layer.area_sqm - _land(water.shapes).area) < 1e-6


def test_suchitras_12_38_m_road_allows_24_m_and_says_the_width_is_only_a_drawing_value():
    _, site = _suchitra()
    road = site.access_road()
    assert road.legal_row_m.value == pytest.approx(12.38) and (
        road.row_status == "UNVERIFIED_DRAWING_VALUE")
    rules = resolve(site)
    limit, = _limit(rules, HeightMeasure.RULE_HEIGHT)
    assert limit.max_m == 24.0 and limit.status is Provenance.UNVERIFIED
    assert "UNVERIFIED_DRAWING_VALUE" in limit.reason
    env = envelope(site, rules)
    assert [b.up_to_m for b in env.bands if b.modelled] == [24.0]
    eligibility = next(f for f in env.facts if f.rule == "High-rise eligibility")
    assert eligibility.status is Status.UNVERIFIED  # a high-rise rests on an unverified road
    assert next(f for f in env.facts if f.rule == "Rule-height limit").status is Status.UNVERIFIED


# --- The 5% amenity clause is not in rule 8 ---------------------------------------------------


def test_the_five_percent_amenity_clause_stands_under_rules_9_and_10_and_not_under_rule_8():
    """A brief called it rule 8(o). On the order's own text it is rule 9(o) (row housing) and
    rule 10(i) (cluster housing); rule 8 (group development) has no such clause."""
    _need(ORDER)
    import pdfplumber

    with pdfplumber.open(ORDER) as pdf:
        text = " ".join(" ".join((page.extract_text() or "").split())
                        for page in pdf.pages[13:17])  # pages 14 to 17
    heads = {n: text.index(h) for n, h in (
        (8, "8. GROUP DEVELOPMENT SCHEMES"), (9, "9. ROW TYPE HOUSING"),
        (10, "10. CLUSTER HOUSING"), (11, "11. PROVISIONS FOR ECONOMICALLY"))}
    assert heads[8] < heads[9] < heads[10] < heads[11]
    phrase = "very large projects more than 5 acres"
    section = {n: text[heads[n]:heads[n + 1]] for n in (8, 9, 10)}
    assert phrase not in section[8]
    assert phrase in section[9] and phrase in section[10]
    assert "(o) In case of very large projects" in section[9]
    assert "(i) In case of very large projects" in section[10]
