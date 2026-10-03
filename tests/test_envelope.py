"""The buildable envelope (stream A1): the legal land picture before any tower or road exists.

Made-up sites only. What the same stage does on the firm's real drawings is in
test_envelope_client.py, which skips without the client fixtures.
"""

import ast
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import ezdxf
import pytest
from contract_fixtures import SITES, load
from legal_fixtures import make_site, nala
from shapely.geometry import LineString, Point, Polygon, box

import siteplan.legal
from siteplan.cli import main
from siteplan.contracts import ALL_CONTRACTS, BuildableEnvelope, ResolvedRules
from siteplan.contracts.accounting import LayerKind, Permit, PhysicalUse
from siteplan.contracts.common import Shape, Status, digest, union_of
from siteplan.contracts.envelope import (
    CirculationRequirements,
    ExclusionKind,
    Obligation,
)
from siteplan.contracts.resolved_rules import (
    CIRCULATION_IN_SETBACK,
    BandKind,
    Eligibility,
)
from siteplan.legal.debug_drawing import write_debug_dxf, write_debug_svg
from siteplan.legal.envelope import NetPlotUnknown, envelope
from siteplan.legal.readings import ROAD_IN_WATER_BUFFER, VISITOR_PARKING_IN_SETBACK
from siteplan.legal.resolve import resolve
from siteplan.legal.site import readings_of, site_from_project

TEST_CLASS = "normative"
LEGAL = Path(siteplan.legal.__file__).parent
RECTANGLE = box(0, 0, 150, 100)  # 15,000 m², the access road along the south side
L_PLOT = Polygon([(0, 0), (150, 0), (150, 100), (24, 100), (24, 160), (0, 160)])  # a 24 m arm
THE_GENERATOR = ("siteplan.towers", "siteplan.layout", "siteplan.grounds", "siteplan.optimizer")
ROAD_CONSTANTS = {"EPS_M", "LANE_M", "R_OUT", "R_IN", "FIRE_BAND_M", "ROAD_M", "APPROACH_M"}


def _run(site, **kwargs):
    rules = resolve(site, **kwargs)
    return rules, envelope(site, rules)


def _band(env: BuildableEnvelope, above_m: float):
    """The band that runs on above a height (not the band of that one height, see _exactly)."""
    return next(b for b in env.bands if b.above_m == above_m and b.up_to_m > above_m)


def _exactly(env: BuildableEnvelope, height_m: float):
    """The band of one height: a building of exactly 21 m is a high-rise on its own band."""
    return next(b for b in env.bands if b.above_m == b.up_to_m == height_m)


def _land(shapes) -> Polygon:
    return union_of(list(shapes))


def _same(a, b, tolerance=1e-6) -> bool:
    return a.symmetric_difference(b).area < tolerance


def _modelled(env: BuildableEnvelope):
    return [b for b in env.bands if b.modelled]


# --- Criterion 1: nothing here is the generator -----------------------------------------------


def _imports(path: Path):
    """Every import in a module as (absolute module, names), relative imports resolved."""
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found += [(alias.name, ()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "siteplan.legal".rsplit(".", node.level - 1)[0] if node.level else ""
            module = ".".join(part for part in (base, node.module) if part)
            found.append((module, tuple(alias.name for alias in node.names)))
    return found


def test_the_legal_package_imports_no_tower_layout_ground_optimizer_or_road_generator():
    files = sorted(LEGAL.glob("*.py"))
    assert {f.name for f in files} >= {"resolve.py", "envelope.py", "widths.py", "site.py",
                                       "debug_drawing.py"}
    for path in files:
        for module, names in _imports(path):
            for banned in THE_GENERATOR:
                assert module != banned and not module.startswith(banned + "."), (
                    f"{path.name} imports {module}")
            if module == "siteplan.access":
                assert names and set(names) <= ROAD_CONSTANTS, (
                    f"{path.name} takes {names or 'the whole module'} from access: only "
                    "constants, never a road generator")
            if module == "siteplan":
                assert not set(names) & {"towers", "layout", "grounds", "optimizer", "access"}, (
                    f"{path.name} imports {names} from siteplan")


def test_the_stages_load_no_generator_module_even_transitively():
    """resolve, envelope and the drawing pull in the contracts and rules.py, and nothing that
    places a tower or draws a road (site.py reaches the adapters on purpose and is left out)."""
    code = ("import sys, siteplan.legal.resolve, siteplan.legal.envelope, "
            "siteplan.legal.debug_drawing\n"
            "print(' '.join(sorted(m for m in sys.modules if m.startswith('siteplan.'))))")
    loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            check=True).stdout.split()
    generator = {"towers", "layout", "grounds", "access", "optimizer", "layout_export", "heights",
                 "runner", "adapters", "checks", "access_checks", "parking_checks"}
    assert not [m for m in loaded if m.split(".")[1] in generator], loaded


# --- Stopping, and refusing stale rules -------------------------------------------------------


def test_without_a_net_plot_the_envelope_stops_and_names_what_the_architect_must_give():
    site = make_site(RECTANGLE, surrendered=450.0, strip_known=False, net_plot=False)
    with pytest.raises(NetPlotUnknown) as stop:
        envelope(site, resolve(site))
    message = str(stop.value)
    assert "net plot cannot be placed" in message and "450 m² of surrender" in message
    assert "the E side is named, but not the strip's width or outline" in message
    for what in ("road_strip_side", "road_strip_width_m", "road_strip_m", "net_plot_m"):
        assert what in message
    assert "does not guess a strip's location" in message
    assert isinstance(stop.value, ValueError)  # the command line reports it and exits 2


def test_with_no_net_plot_and_nothing_given_up_it_asks_for_an_outline_or_a_survey():
    site = make_site(RECTANGLE, net_plot=False)
    with pytest.raises(NetPlotUnknown, match="no net plot outline"):
        envelope(site, resolve(site))


def test_rules_resolved_for_another_site_are_refused():
    rules = resolve(make_site(RECTANGLE))
    with pytest.raises(ValueError, match="different site model"):
        envelope(make_site(box(0, 0, 160, 100)), rules)


# --- The bands: Table IV rows up to the legal height ------------------------------------------


def test_the_bands_are_the_high_rise_rows_up_to_the_height_the_road_allows():
    rules, env = _run(make_site(RECTANGLE, road_m=18.288))
    below, *high = env.bands
    assert (below.kind, below.modelled, below.above_m, below.up_to_m) == (
        BandKind.NON_HIGH_RISE, False, 0.0, 21.0)
    assert not below.buildable and not below.setback_envelope and below.area_sqm == 0
    assert "Table III" in below.note
    # a building of exactly 21 m is a high-rise on Table IV's first row (7 m): its own band
    assert [(b.above_m, b.up_to_m, b.setback_m) for b in high] == [
        (21.0, 21.0, 7.0), (21.0, 24.0, 8.0), (24.0, 27.0, 9.0), (27.0, 30.0, 10.0)]
    assert [b.green_strip_applies for b in high] == [False, False, True, True]
    taller = _run(make_site(RECTANGLE, road_m=24.0))[1]
    assert [b.up_to_m for b in _modelled(taller)] == [21.0, 24.0, 27.0, 30.0, 35.0, 40.0, 45.0]


def test_the_setback_is_the_net_plot_inset_all_round_square_to_each_wall():
    env = _run(make_site(RECTANGLE))[1]
    assert _same(_land(_exactly(env, 21.0).setback_envelope), box(7, 7, 143, 93))
    first = _band(env, 21.0)
    assert _same(_land(first.setback_envelope), box(8, 8, 142, 92))
    assert _same(_land(first.buildable), box(8, 8, 142, 92))
    assert first.area_sqm == pytest.approx(134 * 84)
    assert _same(_land(_band(env, 27.0).setback_envelope), box(10, 10, 140, 90))


@pytest.mark.parametrize("site", [
    make_site(RECTANGLE, water=[nala([[(75, -5), (75, 105)]])]),
    make_site(L_PLOT, side="S"),
    make_site(Polygon([(0, 0), (120, 0), (150, 90), (40, 130), (0, 70)]))],
    ids=["a nala across the plot", "an L plot", "an irregular plot"])
def test_a_taller_bands_land_lies_inside_a_shorter_bands(site):
    env = _run(site)[1]
    bands = _modelled(env)
    assert len(bands) >= 3
    for shorter, taller in zip(bands, bands[1:], strict=False):
        assert _land(taller.buildable).difference(_land(shorter.buildable)).area < 1e-6
        assert taller.area_sqm <= shorter.area_sqm
    for band in bands:
        assert _land(band.buildable).difference(_land(band.setback_envelope)).area < 1e-6
        assert band.area_sqm == pytest.approx(_land(band.buildable).area)


def test_a_road_that_sets_no_limit_gives_bands_until_the_land_runs_out():
    plot = box(0, 0, 60, 34)  # 2,040 m²: setbacks eat it at 17 m, which is the 55-70 m band
    rules, env = _run(make_site(plot, road_m=30.0))
    bands = _modelled(env)
    assert bands[-1].up_to_m == 70.0 and not bands[-1].buildable and bands[-1].area_sqm == 0
    assert all(b.buildable for b in bands[:-1])
    assert "no land" in bands[-1].note
    assert not any(b.above_m > 55.0 for b in bands)  # nothing after the first empty band


def test_a_plot_under_2000_m2_has_only_the_unmodelled_band_and_no_high_rise_eligibility():
    rules, env = _run(make_site(box(0, 0, 40, 40)))
    assert [b.modelled for b in env.bands] == [False]
    eligibility = next(f for f in env.facts if f.rule == "High-rise eligibility")
    assert eligibility.status is Status.FAIL and eligibility.measured == "PROHIBITED"
    assert "permits nothing below it" in eligibility.note  # no license for a lower building
    assert not env.bands[0].buildable
    assert [p.applies_to for p in env.width_profiles] == ["net plot"]
    fire_lanes = next(o for o in env.circulation.obligations if o.id == "fire lanes")
    assert fire_lanes.applies is False


def test_a_road_too_narrow_for_a_high_rise_draws_no_band_and_passes_nothing_lower():
    rules, env = _run(make_site(RECTANGLE, road_m=9.0))
    assert rules.height.high_rise.eligibility is Eligibility.PROHIBITED
    assert [b.modelled for b in env.bands] == [False]


def test_an_unknown_road_width_gives_the_bands_the_land_holds_and_says_the_limit_is_open():
    rules, env = _run(make_site(RECTANGLE, road_m=None))
    assert len(_modelled(env)) > 3
    assert all("no height limit is known from the road" in b.note for b in _modelled(env))
    eligibility = next(f for f in env.facts if f.rule == "High-rise eligibility")
    assert eligibility.status is Status.UNVERIFIED


def test_the_envelope_follows_the_rules_it_is_given_not_rules_py():
    site = make_site(RECTANGLE, water=[nala([[(75, -5), (75, 105)]])])
    rules = resolve(site)
    changed = rules.model_copy(deep=True)
    next(b for b in changed.height.bands if b.above_m == 21.0).setback_m = 12.0
    changed.water.buffer_m_by_class.value["nala_over_10m"] = 20.0
    env = envelope(site, changed)
    assert _same(_land(_band(env, 21.0).setback_envelope), box(12, 12, 138, 88))
    assert env.rules_ref == digest(changed) != envelope(site, rules).rules_ref
    water, = env.exclusions
    assert _land(water.shapes).area == pytest.approx(40 * 100)  # 20 m either side of the line


# --- Statutory exclusions ---------------------------------------------------------------------


def test_a_water_buffer_is_an_exclusion_recomputed_from_the_lines_and_the_rules():
    site = make_site(RECTANGLE, water=[nala([[(75, -5), (75, 105)]])])
    rules, env = _run(site)
    water, = env.exclusions
    assert water.kind is ExclusionKind.WATER_BUFFER and water.source_ref == "water-1"
    assert water.clause == rules.water.buffer_m_by_class.clause
    assert _same(_land(water.shapes), box(66, 0, 84, 100))  # 9 m each side, clipped to the plot
    for band in _modelled(env):
        assert _land(band.buildable).intersection(_land(water.shapes)).area < 1e-6
        assert not _land(band.setback_envelope).difference(_land(water.shapes)).is_empty
    assert _band(env, 21.0).area_sqm == pytest.approx(11_256 - 18 * 84)


def test_a_narrower_class_takes_a_narrower_buffer():
    site = make_site(RECTANGLE, water=[nala([[(75, -5), (75, 105)]], water_class="nala_up_to_10m")])
    water, = _run(site)[1].exclusions
    assert _land(water.shapes).area == pytest.approx(4 * 100)  # 2 m each side


def test_a_lake_drawn_as_a_ring_excludes_the_water_it_closes_too():
    ring = [(60, 40), (90, 40), (90, 70), (60, 70), (60, 40)]
    pond = nala([ring], water_class="lake_under_10ha")
    pond["channel"] = [Shape.from_shapely(Polygon(ring[:-1])).model_dump()]
    water, = _run(make_site(RECTANGLE, water=[pond]))[1].exclusions
    assert _land(water.shapes).contains(Point(75, 55))  # the water itself, not just its edge


def test_a_survey_feature_that_gives_an_ht_corridor_is_excluded_one_that_does_not_is_reported():
    corridor = Shape.from_shapely(box(100, -10, 106, 110)).model_dump()
    given = {"kind": "HT_LINE", "text": "HT line", "shapes": [corridor], "source": "survey"}
    marked = {"kind": "MARK", "text": "HT line: HT LINE 11KV, 5.0 m from the plot"}
    env = _run(make_site(RECTANGLE, features=[given]))[1]
    ht, = env.exclusions
    assert ht.kind is ExclusionKind.HT_CORRIDOR and _same(_land(ht.shapes), box(100, 0, 106, 100))
    bare = _run(make_site(RECTANGLE, features=[marked]))[1]
    assert not bare.exclusions
    finding = next(f for f in bare.facts if f.rule == "HT line")
    assert finding.status is Status.UNVERIFIED and "not excluded" in finding.note


def test_an_input_that_is_missing_is_reported_never_guessed():
    unread = _run(make_site(RECTANGLE, water=[nala([])]))[1]
    assert not unread.exclusions
    finding = next(f for f in unread.facts if f.rule == "Water body water-1")
    assert finding.status is Status.UNVERIFIED and "not excluded" in finding.note
    far = _run(make_site(RECTANGLE, water=[nala([[(400, 0), (400, 100)]])]))[1]
    assert not far.exclusions
    assert next(f for f in far.facts if f.rule == "Water body water-1").status is Status.INFO


def test_a_net_plot_taken_from_the_firms_finished_plan_is_flagged_debug_only():
    site = make_site(RECTANGLE)
    data = site.model_dump(mode="json")
    data["net_plot"].update(source_kind="FIRM_FINISHED_PLAN", status="ASSUMED_FOR_TEST")
    debug = type(site).model_validate(data)
    env = _run(debug)[1]
    finding = next(f for f in env.facts if f.rule == "Net plot outline")
    assert finding.status is Status.UNVERIFIED and "DEBUG ONLY" in finding.note
    assert not any(f.rule == "Net plot outline" for f in _run(site)[1].facts)


# --- Criterion 7: narrow land is reported, never judged ---------------------------------------


def test_the_narrow_arm_is_in_the_width_profile_with_its_area_and_width_in_every_band():
    rules, env = _run(make_site(L_PLOT))
    profiles = {p.applies_to: p for p in env.width_profiles}
    assert list(profiles) == ["net plot", "21 m", "21-24 m", "24-27 m", "27-30 m"]
    for name, setback in (("net plot", 0), ("21 m", 7), ("21-24 m", 8), ("24-27 m", 9),
                          ("27-30 m", 10)):
        arm = min(profiles[name].regions, key=lambda r: r.max_inscribed_width_m)
        width = 24 - 2 * setback
        assert arm.max_inscribed_width_m == pytest.approx(width, abs=0.1), name
        assert arm.area_sqm == pytest.approx(width * 60, rel=0.01), name
        assert arm.length_m == pytest.approx(60, abs=0.5), name
        assert arm.shape.to_shapely().representative_point().y > 100  # it is the northern arm
    body = max(profiles["net plot"].regions, key=lambda r: r.area_sqm)
    assert body.area_sqm == pytest.approx(15_000) and body.max_inscribed_width_m == 100


def test_the_arm_is_kept_in_the_buildable_land_and_in_no_exclusion():
    rules, env = _run(make_site(L_PLOT))
    assert env.exclusions == []
    arm = box(0, 100, 24, 160)
    for band, setback in ((_band(env, 21.0), 8), (_band(env, 27.0), 10)):
        kept = _land(band.buildable).intersection(arm)
        assert kept.area == pytest.approx((24 - 2 * setback) * (60 - setback))
    for layer in env.rule_layers.layers:  # the only land the layers hold back is the setbacks
        assert layer.kind in (LayerKind.SETBACK, LayerKind.GREEN_STRIP_ZONE,
                              LayerKind.RAMP_FORBIDDEN)


@pytest.mark.parametrize("name", SITES)
def test_no_land_is_classed_unusable_reserved_or_too_narrow(name):
    site = load(name, "CanonicalSiteModel")
    env = _run(site)[1]
    text = env.model_dump_json().lower() + json.dumps(
        BuildableEnvelope.model_json_schema()).lower()
    for word in ("unusable", "reserved", "too narrow", "not buildable", "dead land"):
        assert word not in text, word
    for profile in env.width_profiles:
        widths = [w for w, _ in profile.area_narrower_than]
        areas = [a for _, a in profile.area_narrower_than]
        assert widths == sorted(widths) and areas == sorted(areas)  # more land is narrower
        assert all(a >= 0 for a in areas)
    land = [site.net_plot.value.to_shapely(), *(_land(b.buildable) for b in _modelled(env))]
    for profile, whole in zip(env.width_profiles, land, strict=True):
        assert sum(r.area_sqm for r in profile.regions) == pytest.approx(whole.area, rel=0.01)


def test_a_rectangle_has_one_region_and_no_land_narrower_than_any_reported_width():
    profile = _run(make_site(RECTANGLE))[1].width_profiles[0]
    region, = profile.regions
    assert (region.area_sqm, region.max_inscribed_width_m, region.length_m) == pytest.approx(
        (15_000, 100, 150))
    assert all(area == 0 for _, area in profile.area_narrower_than)  # corners are not narrow


def test_a_narrow_plot_is_one_region_whose_width_is_reported_not_judged():
    plot = box(0, 0, 100, 26)  # 2,600 m², 26 m wide: under the 30 m split, over 25
    profile = _run(make_site(plot))[1].width_profiles[0]
    region, = profile.regions
    assert region.max_inscribed_width_m == pytest.approx(26) and region.area_sqm == 2600
    assert dict(profile.area_narrower_than)[25.0] == 0
    assert dict(profile.area_narrower_than)[30.0] == pytest.approx(2600)


# --- Criterion 8: circulation as requirements only --------------------------------------------


def _at(dump: dict, path: str):
    node = dump
    for step in path.split("."):
        node = node[step]
    return node


def test_circulation_is_requirements_pointing_at_the_rules_and_holds_no_road():
    assert set(CirculationRequirements.model_fields) == {"access_zones", "obligations"}
    schema = json.dumps(BuildableEnvelope.model_json_schema()).lower()
    assert '"roads"' not in schema and "carriageway" not in schema
    rules, env = _run(make_site(RECTANGLE))
    dump = json.loads(rules.model_dump_json())
    refs = [o.rule_ref for o in (*env.circulation.obligations, *env.requirements)]
    assert len(refs) >= 9
    for ref in refs:  # each points at a value that exists in ResolvedRules
        assert _at(dump, ref) is not None, ref
    by_id = {o.id: o for o in env.circulation.obligations}
    assert by_id["internal roads"].applies and by_id["main approach"].applies
    assert by_id["fire lanes"].applies and by_id["gate"].applies
    assert by_id["no dead end above the physical limit"].rule_ref == "fire.dead_end_max_physical_m"


def test_roads_inside_a_group_development_scheme_only_and_fire_lanes_only_for_a_high_rise():
    small = _run(make_site(box(0, 0, 60, 50)))[1]  # 3,000 m²: not a group development scheme
    by_id = {o.id: o for o in small.circulation.obligations}
    assert not by_id["internal roads"].applies and not by_id["main approach"].applies
    assert by_id["fire lanes"].applies  # a high-rise can still stand here
    low = _run(make_site(box(0, 0, 40, 40)))[1]
    assert not {o.id: o for o in low.circulation.obligations}["fire lanes"].applies


def test_the_access_zone_is_the_frontage_facing_the_access_road():
    env = _run(make_site(RECTANGLE, side="S"))[1]
    zone, = env.circulation.access_zones
    assert (zone.side, zone.road_id, zone.length_m) == ("S", 1, pytest.approx(150))
    frontage = LineString(zone.frontage.points)
    assert frontage.distance(RECTANGLE.boundary) < 1e-9
    assert all(abs(y) < 1e-9 for _, y in zone.frontage.points)  # along the south edge
    west = _run(make_site(RECTANGLE, side="W"))[1].circulation.access_zones[0]
    assert west.length_m == pytest.approx(100) and all(abs(x) < 1e-9
                                                       for x, _ in west.frontage.points)


def test_a_water_buffer_across_the_frontage_splits_the_zone_and_no_side_means_no_zone():
    env = _run(make_site(RECTANGLE, water=[nala([[(75, -5), (75, 105)]])]))[1]
    assert sorted(round(z.length_m) for z in env.circulation.access_zones) == [66, 66]
    unknown = _run(make_site(RECTANGLE, side=None))[1]
    assert unknown.circulation.access_zones == []


# --- Criterion 9: rule layers with permissions ------------------------------------------------


def _permits(layer) -> dict:
    return {p.use: p for p in layer.permits}


def test_every_setback_layer_forbids_towers_and_makes_roads_and_fire_lanes_conditional():
    rules, env = _run(make_site(RECTANGLE))
    setbacks = env.rule_layers.of(LayerKind.SETBACK)
    assert [layer.applies_to for layer in setbacks] == ["21 m", "21-24 m", "24-27 m", "27-30 m"]
    for layer, band in zip(setbacks, _modelled(env), strict=True):
        assert layer.interpretation_ref == CIRCULATION_IN_SETBACK
        assert layer.area_sqm == pytest.approx(RECTANGLE.area - _land(band.setback_envelope).area)
        permits = _permits(layer)
        assert permits[PhysicalUse.TOWER].permit is Permit.FORBIDDEN
        assert PhysicalUse.CLUB_HOUSE not in permits  # a lower block: its own band's setback
        for use in (PhysicalUse.ROAD, PhysicalUse.FIRE_HARDSTANDING):
            assert permits[use].permit is Permit.CONDITIONAL, "never simply allowed"
            assert permits[use].interpretation_ref == CIRCULATION_IN_SETBACK
        ramp = permits[PhysicalUse.RAMP]
        assert ramp.permit is Permit.CONDITIONAL and rules.parking.ramp_in_setbacks.clause in (
            ramp.condition)
        assert "13(c)(vii)" in ramp.condition
        assert f"{rules.parking.ramp_fire_clearance_m.value:g} m for fire" in ramp.condition


def test_a_bay_in_a_setback_rests_on_the_reading_of_rule_13_c_xii_not_on_a_flat_ban():
    """Rule 13(c)(xii) lets visitors' parking use a side or rear setback wider than 6 m (green
    strip left out); NBC 4.6(c) keeps the compulsory open space free of parking. The text does
    not settle it, so the permission is conditional and names the reading."""
    layer = _run(make_site(RECTANGLE))[1].rule_layers.of(LayerKind.SETBACK)[0]
    parking = _permits(layer)[PhysicalUse.SURFACE_PARKING]
    assert parking.permit is Permit.CONDITIONAL
    assert parking.interpretation_ref == VISITOR_PARKING_IN_SETBACK
    assert "never the front setback" in parking.condition


def test_the_green_strip_is_a_layer_only_where_the_setback_is_9_m_or_more():
    rules, env = _run(make_site(RECTANGLE))
    strips = env.rule_layers.of(LayerKind.GREEN_STRIP_ZONE)
    assert [s.applies_to for s in strips] == ["24-27 m", "27-30 m"]
    strip = rules.green_strip.width_m.value
    for layer in strips:
        assert _same(_land(layer.shapes), RECTANGLE.difference(RECTANGLE.buffer(
            -strip, join_style="mitre")))
        assert _permits(layer)[PhysicalUse.GREEN_STRIP].permit is Permit.ALLOWED
        assert _permits(layer)[PhysicalUse.TOWER].permit is Permit.FORBIDDEN


def test_no_ramp_in_the_front_setback_and_the_front_is_where_the_access_road_runs():
    rules, env = _run(make_site(RECTANGLE, side="S"))
    layers = env.rule_layers.of(LayerKind.RAMP_FORBIDDEN)
    assert [layer.applies_to for layer in layers] == ["21 m", "21-24 m", "24-27 m", "27-30 m"]
    assert _same(_land(layers[0].shapes), box(0, 0, 150, 7))  # the south strip, setback deep
    assert _same(_land(layers[1].shapes), box(0, 0, 150, 8))
    assert _same(_land(layers[3].shapes), box(0, 0, 150, 10))
    assert layers[0].permits[0].permit is Permit.FORBIDDEN
    assert layers[0].permits[0].use is PhysicalUse.RAMP
    assert layers[0].clause == rules.parking.ramp_in_setbacks.clause


def test_with_no_access_side_every_side_is_treated_as_the_front_and_the_layer_says_so():
    layer = _run(make_site(RECTANGLE, side=None))[1].rule_layers.of(LayerKind.RAMP_FORBIDDEN)[0]
    assert layer.status.value == "UNVERIFIED"
    assert layer.area_sqm == pytest.approx(RECTANGLE.area - 136 * 86)  # the 21 m band's 7 m
    assert "every side" in layer.permits[0].condition


def test_a_water_buffer_layer_forbids_building_and_leaves_a_road_to_the_open_reading():
    rules, env = _run(make_site(RECTANGLE, water=[nala([[(75, -5), (75, 105)]])]))
    layer, = env.rule_layers.of(LayerKind.WATER_BUFFER)
    assert layer.clause == rules.water.buffer_m_by_class.clause
    assert layer.interpretation_ref == ROAD_IN_WATER_BUFFER
    permits = _permits(layer)
    assert permits[PhysicalUse.TOWER].permit is Permit.FORBIDDEN
    assert permits[PhysicalUse.SOFT_OPEN_SPACE].permit is Permit.ALLOWED
    for use in (PhysicalUse.ROAD, PhysicalUse.FIRE_HARDSTANDING):
        assert permits[use].permit is Permit.CONDITIONAL
        assert permits[use].interpretation_ref == ROAD_IN_WATER_BUFFER
    assert _same(_land(layer.shapes), box(66, 0, 84, 100))


def test_the_open_space_requirement_stays_in_the_rules_and_the_envelope_points_at_it():
    rules, env = _run(make_site(RECTANGLE, surrendered=450.0))
    pointer = next(o for o in env.requirements if o.id == "open space")
    assert pointer.rule_ref == "open_space.requirement_sqm_by_reading" and pointer.applies
    asked = _at(json.loads(rules.model_dump_json()), pointer.rule_ref)
    assert set(asked) == {"gross_before_surrender", "gross_after_surrender", "net_after_surrender"}
    assert asked["gross_before_surrender"] > asked["net_after_surrender"]
    assert set(Obligation.model_fields) == {"id", "applies", "rule_ref", "note"}  # no value


# --- Facts ------------------------------------------------------------------------------------


def test_the_facts_say_the_category_the_limits_in_metres_and_everything_still_unknown():
    rules, env = _run(make_site(RECTANGLE, dead_end=None, joins=None, authority="CMC",
                                inside_cure=True, jurisdiction_status="UNVERIFIED"))
    by_rule = {f.rule: f for f in env.facts}
    assert by_rule["Group Development Scheme"].measured == "yes"
    assert by_rule["High-rise eligibility"].status is Status.PASS
    assert by_rule["High-rise eligibility"].measured == "ALLOWED"
    assert by_rule["Rule-height limit"].measured == "30 m"
    assert by_rule["Physical-height limit"].status is Status.UNVERIFIED
    assert by_rule["Physical-height limit"].required == "the access road ends at the plot"
    assert by_rule["Height above sea level"].status is Status.UNVERIFIED
    assert by_rule["Street join (NBC 4.6(a))"].status is Status.UNVERIFIED
    assert by_rule["Table V column"].status is Status.UNVERIFIED
    assert "A building of exactly 21 m" not in by_rule  # it has its own band now
    assert _exactly(env, 21.0).setback_m == 7.0
    assert not [f for f in env.facts if "floor" in f.rule.lower()]


def test_a_street_that_does_not_join_a_wide_street_is_a_failed_fact_a_confirmed_one_passes():
    assert next(f for f in _run(make_site(RECTANGLE, joins=False))[1].facts
                if f.rule.startswith("Street join")).status is Status.FAIL
    assert next(f for f in _run(make_site(RECTANGLE, joins=True))[1].facts
                if f.rule.startswith("Street join")).status is Status.PASS


# --- Criterion 10: the debug drawing ----------------------------------------------------------

BASE_LAYERS = {"ORIGINAL-SITE", "NET-SITE", "EXCLUSIONS", "WIDTH-REGIONS", "ACCESS-ZONES",
               "RULE-LAYERS", "NOTES"}


def _drawn(tmp_path, site):
    rules, env = _run(site)
    dxf = write_debug_dxf(site, rules, env, tmp_path / "e.dxf")
    svg = write_debug_svg(site, rules, env, tmp_path / "e.svg")
    return rules, env, ezdxf.readfile(dxf), svg


def _on(doc, layer, kind="LWPOLYLINE"):
    return [e for e in doc.modelspace().query(kind) if e.dxf.layer == layer]


def _area(polyline) -> float:
    return Polygon([(x, y) for x, y, *_ in polyline.get_points()]).area


def test_the_dxf_survives_a_round_trip_with_every_layer_in_metres(tmp_path):
    site = make_site(RECTANGLE, surrendered=450.0, water=[nala([[(75, -5), (75, 105)]])])
    rules, env, doc, _ = _drawn(tmp_path, site)
    assert doc.dxfversion == "AC1032" and doc.header["$INSUNITS"] == 6  # R2018, metres
    layers = {layer.dxf.name for layer in doc.layers}
    bands = ["21-24", "24-27", "27-30"]
    assert BASE_LAYERS | {f"{kind}-{b}" for b in bands for kind in ("SETBACK", "BUILDABLE")
                          } <= layers
    net, = _on(doc, "NET-SITE")
    assert _area(net) == pytest.approx(RECTANGLE.area)
    assert sum(_area(p) for p in _on(doc, "BUILDABLE-21-24")) == pytest.approx(
        _band(env, 21.0).area_sqm)
    assert sum(_area(p) for p in _on(doc, "SETBACK-27-30")) == pytest.approx(
        _land(_band(env, 27.0).setback_envelope).area)
    assert sum(_area(p) for p in _on(doc, "EXCLUSIONS")) == pytest.approx(18 * 100)
    assert len(_on(doc, "ACCESS-ZONES")) == len(env.circulation.access_zones) == 2
    assert _on(doc, "WIDTH-REGIONS") and _on(doc, "WIDTH-REGIONS-21-24")
    assert len(_on(doc, "RULE-LAYERS")) >= len(env.rule_layers.layers)


def test_the_dxf_text_block_carries_the_open_space_under_each_reading_and_the_height_limits(
        tmp_path):
    site = make_site(RECTANGLE, surrendered=450.0, dead_end=None)
    rules, env, doc, _ = _drawn(tmp_path, site)
    text = "\n".join(t.dxf.text for t in _on(doc, "NOTES", "TEXT"))
    for reading, area in rules.open_space.requirement_sqm_by_reading.items():
        assert f"{reading}: {area:,.0f} m2" in text
    assert "OPEN SPACE REQUIRED (10%" in text
    assert "rule_height: 30 m [USER_CONFIRMED]" in text
    assert "physical_height: 30 m, only if the access road ends at the plot" in text
    assert "amsl: not evaluated [UNVERIFIED]" in text
    assert "0-21 m: not modelled" in text and "21-24 m: 8 m, 11,256 m2" in text
    assert "stilt_in_rule_height = ALL" in text
    assert "DEBUG ONLY" not in text  # nothing from the firm's finished plan here


def test_the_svg_has_a_group_per_layer_and_the_same_text_block(tmp_path):
    site = make_site(L_PLOT, dead_end=None)
    rules, env, _, svg = _drawn(tmp_path, site)
    root = ET.fromstring(svg.read_text())
    ns = {"s": "http://www.w3.org/2000/svg"}
    groups = {g.get("id") for g in root.findall("s:g", ns)}
    assert groups >= BASE_LAYERS | {"SETBACK-21-24", "BUILDABLE-27-30"}
    words = " ".join("".join(t.itertext()) for t in root.iter("{http://www.w3.org/2000/svg}text"))
    assert "net_after_surrender" in words and "OPEN SPACE REQUIRED" in words
    assert "amsl: not evaluated" in words
    arm = [t for t in root.iter("{http://www.w3.org/2000/svg}text")
           if "24.0 m wide" in "".join(t.itertext())]
    assert arm  # the arm's width is labelled on its region


def test_a_debug_net_plot_says_so_on_the_drawing(tmp_path):
    site = make_site(RECTANGLE)
    data = site.model_dump(mode="json")
    data["net_plot"].update(source_kind="FIRM_FINISHED_PLAN", status="ASSUMED_FOR_TEST")
    rules, env, doc, svg = _drawn(tmp_path, type(site).model_validate(data))
    text = "\n".join(t.dxf.text for t in _on(doc, "NOTES", "TEXT"))
    assert "DEBUG ONLY: the net outline comes from the firm's finished plan" in text
    assert "DEBUG ONLY" in svg.read_text()


# --- The contracts, and the command line ------------------------------------------------------


@pytest.mark.parametrize("name", SITES)
def test_the_envelope_and_rules_for_every_made_up_site_validate_and_survive_json(name):
    site = load(name, "CanonicalSiteModel")
    rules, env = _run(site)
    assert ResolvedRules.model_validate_json(rules.model_dump_json()) == rules
    assert BuildableEnvelope.model_validate_json(env.model_dump_json()) == env
    assert env.site_ref == rules.site_ref == digest(site) and env.rules_ref == digest(rules)
    assert set(ALL_CONTRACTS) >= {"BuildableEnvelope", "ResolvedRules"}
    placed = [shape for band in _modelled(env) for shape in band.buildable]
    assert all(s.to_shapely().is_valid for s in placed)


def _project_file(tmp_path, name="rectangle"):
    from contract_fixtures.build import SITES as SPECS
    from contract_fixtures.build import project

    path = tmp_path / f"{name}.project.json"
    path.write_text(project(name, SPECS[name]).model_dump_json())
    return path


def test_the_command_writes_the_rules_the_envelope_the_dxf_and_the_svg(tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["envelope", str(_project_file(tmp_path)), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert {p.name for p in out.iterdir()} == {"rules.json", "envelope.json", "envelope.dxf",
                                               "envelope.svg"}
    rules = ResolvedRules.model_validate_json((out / "rules.json").read_text())
    env = BuildableEnvelope.model_validate_json((out / "envelope.json").read_text())
    assert env.rules_ref == digest(rules) and _band(env, 21.0).area_sqm > 0
    assert "OPEN SPACE REQUIRED" in printed and "Still open or not checked:" in printed
    assert {layer.dxf.name for layer in ezdxf.readfile(out / "envelope.dxf").layers} >= BASE_LAYERS


def test_the_command_stops_with_the_reason_when_no_net_plot_can_be_placed(tmp_path, capsys):
    path = _project_file(tmp_path)
    data = json.loads(path.read_text())
    data["site"].pop("net_plot_m")
    data["site"].pop("road_strip_m")
    path.write_text(json.dumps(data))
    assert main(["envelope", str(path), "--out", str(tmp_path / "out")]) == 2
    assert "net plot cannot be placed" in capsys.readouterr().err
    assert not (tmp_path / "out" / "rules.json").exists()


# --- The survey glue --------------------------------------------------------------------------


def _survey(tmp_path, boundary, *, nala_line=None, name="survey.dxf"):
    doc = ezdxf.new("R2018")
    doc.units = ezdxf.units.M
    msp = doc.modelspace()
    msp.add_lwpolyline(boundary, close=True, dxfattribs={"layer": "SITE-BOUNDARY"})
    if nala_line:
        msp.add_lwpolyline(nala_line, dxfattribs={"layer": "NALA"})
    doc.saveas(tmp_path / name)
    return tmp_path / name


def _project(**site):
    from siteplan.project import Project

    base = {"abutting_road_ft": 60, "abutting_road_status": "DECLARED_ON_SITE_PLAN",
            "access_side": "S", "road_dead_end": False, "authority": "HMDA", "inside_cure": False}
    return Project.model_validate({
        "name": "Made-up survey", "site": {**base, **site},
        "sources": {"abutting_road": "architect: 60 ft", "access_side": "survey: road 1"},
        "status": {"abutting_road": "USER_CONFIRMED", "authority": "USER_CONFIRMED",
                   "inside_cure": "USER_CONFIRMED", "road_dead_end": "USER_CONFIRMED"},
        "layout": {"floors": 8, "unit_mix": {"2BHK": 1.0}}})


def test_the_survey_gives_the_net_plot_and_the_lines_of_a_named_water_body(tmp_path):
    survey = _survey(tmp_path, [(0, 0), (150, 0), (150, 100), (0, 100)],
                     nala_line=[(75, -5), (75, 105)])
    project = _project(gross_area_sqm=15_000, net_area_sqm=15_000,
                       water=[{"kind": "nala_over_10m", "survey_layer": "NALA"}])
    site = site_from_project(project, survey)
    assert site.net_plot.status.value == "EXTRACTED" and site.net_plot.source_kind.value == "SURVEY"
    assert site.net_plot.value.area_sqm == pytest.approx(15_000)
    body, = site.water
    assert len(body.lines) == 1 and body.lines[0].points == [(75, -5), (75, 105)]
    rules, env = _run(site)
    assert _land(env.exclusions[0].shapes).area == pytest.approx(18 * 100)


def test_a_strip_the_architect_places_is_cut_off_and_one_nobody_has_placed_is_not_guessed(tmp_path):
    survey = _survey(tmp_path, [(0, -3), (150, -3), (150, 100), (0, 100)])
    placed = _project(gross_area_sqm=15_450, net_area_sqm=15_000, road_strip_side="S",
                      road_strip_width_m=3.0)
    site = site_from_project(placed, survey)
    assert site.net_plot.value.area_sqm == pytest.approx(15_000, rel=0.01)
    assert site.net_plot.source_kind.value == "ARCHITECT"
    # the reader puts the survey's south-west corner at the origin, so the cut is 3 m up
    assert min(y for _, y in site.net_plot.value.outer) == pytest.approx(3.0)
    unplaced = _project(gross_area_sqm=15_450, net_area_sqm=15_000, road_strip_side="S")
    assert site_from_project(unplaced, survey).net_plot is None  # the envelope will stop and ask


def test_a_survey_that_draws_the_net_outline_places_the_net_plot_without_a_strip(tmp_path):
    """When the drawing's own outline is the area the project states as net, there is no strip to
    place: the outline is the net plot, as the survey drew it."""
    survey = _survey(tmp_path, [(0, 0), (150, 0), (150, 100), (0, 100)])
    project = _project(gross_area_sqm=15_450, net_area_sqm=15_000, road_strip_side="S")
    site = site_from_project(project, survey)
    deduction, = site.ownership.deductions
    assert deduction.location.how.value == "UNKNOWN"  # nobody placed the strip, and none is needed
    assert site.net_plot.value.area_sqm == pytest.approx(15_000)
    assert site.net_plot.source_kind.value == "SURVEY" and site.net_plot.status.value == "EXTRACTED"
    assert envelope(site, resolve(site)).bands[1].area_sqm > 0


def test_a_survey_kept_as_a_finished_plan_makes_the_outline_a_debug_one(tmp_path):
    survey = _survey(tmp_path, [(0, 0), (150, 0), (150, 100), (0, 100)], name="plan.dxf")
    (tmp_path / "siteplan.workspace.json").write_text(json.dumps({"finished_plans": ["plan.dxf"]}))
    site = site_from_project(_project(gross_area_sqm=15_000, net_area_sqm=15_000), survey)
    assert site.net_plot.source_kind.value == "FIRM_FINISHED_PLAN"
    assert site.net_plot.status.value == "ASSUMED_FOR_TEST"


def test_a_water_body_needs_the_survey_that_draws_it_and_lines_in_it(tmp_path):
    water = [{"kind": "nala_over_10m", "survey_layer": "NALA"}]
    project = _project(gross_area_sqm=15_000, net_area_sqm=15_000, water=water)
    with pytest.raises(ValueError, match="give the survey that draws it"):
        site_from_project(project, None)
    bare = _survey(tmp_path, [(0, 0), (150, 0), (150, 100), (0, 100)])
    with pytest.raises(ValueError, match="no lines in NALA"):
        site_from_project(project, bare)


def _layout(**stated):
    from siteplan.project import Project

    return Project.model_validate_json(json.dumps({
        "name": "x", "site": {}, "layout": {"floors": 8, "unit_mix": {"2BHK": 1.0}, **stated}}))


def test_a_project_states_a_reading_only_by_naming_it():
    assert readings_of(_layout())[0] == {}  # a request's defaults are not a choice
    selections, when_open = readings_of(_layout(stilt_in_rule_height=False))
    assert selections == {"stilt_in_rule_height": "not_counted"} and when_open.value == "STOP"
    selections, when_open = readings_of(_layout(circulation_in_setback=True,
                                                conservative_parking=True))
    assert selections == {"circulation_in_setback": "allowed"}
    assert when_open.value == "CONSERVATIVE"
    assert readings_of(_layout(conservative_parking=False))[1].value == "STOP"


@pytest.mark.parametrize("name", SITES)
def test_the_real_envelope_agrees_with_the_p0_fixtures_on_the_land_of_each_band(name):
    """The stand-in cut each band with round joins; the setback is a line square to each wall,
    so a reflex corner of the plot keeps a square of land back (mitre joins). On a plot without
    one the two agree; on the L plot the real land is the smaller, by the corner only."""
    site = load(name, "CanonicalSiteModel")
    ours, theirs = _run(site)[1], load(name, "BuildableEnvelope")
    plot = site.net_plot.value.to_shapely()
    convex = _same(plot, plot.convex_hull)
    assert [(b.above_m, b.up_to_m, b.modelled, b.setback_m) for b in ours.bands] == [
        (b.above_m, b.up_to_m, b.modelled, b.setback_m) for b in theirs.bands]
    for mine, fixture in zip(ours.bands, theirs.bands, strict=True):
        assert mine.green_strip_applies == fixture.green_strip_applies
        assert _land(mine.buildable).difference(_land(fixture.buildable)).area < 1e-6
        if convex:
            assert mine.area_sqm == pytest.approx(fixture.area_sqm)
        elif mine.modelled:
            corner = _land(fixture.buildable).difference(_land(mine.buildable))
            # the square at a reflex corner less its quarter circle, (1 - pi/4) d squared
            assert 0 < corner.area < 0.25 * mine.setback_m**2
            assert corner.distance(Point(24, 100)) < 1.5 * mine.setback_m
    assert [(e.kind, e.source_ref) for e in ours.exclusions] == [
        (e.kind, e.source_ref) for e in theirs.exclusions]
    for mine, fixture in zip(ours.exclusions, theirs.exclusions, strict=True):
        assert _land(mine.shapes).area == pytest.approx(_land(fixture.shapes).area)
