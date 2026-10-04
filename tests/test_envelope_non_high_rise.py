"""The envelope below 21 m (stream A2): the land of Table III's bands, and what a narrow region
can take.

Made-up sites only. The L plot is the contract fixtures': a 150 x 100 m body and a 24 m wide arm
60 m long, its access road along the south side, 60 ft.
"""

import ezdxf
import pytest
from legal_fixtures import make_site
from shapely.geometry import Polygon, box

from siteplan.contracts.common import Status, union_of
from siteplan.contracts.resolved_rules import BandKind, Eligibility
from siteplan.legal.debug_drawing import write_debug_dxf, write_debug_svg
from siteplan.legal.envelope import envelope
from siteplan.legal.resolve import resolve

TEST_CLASS = "normative"
L_PLOT = Polygon([(0, 0), (150, 0), (150, 100), (24, 100), (24, 160), (0, 160)])
RECTANGLE = box(0, 0, 150, 100)
ARM = box(0, 100, 24, 160)


def _run(site):
    rules = resolve(site)
    return rules, envelope(site, rules)


def _land(shapes) -> Polygon:
    return union_of(list(shapes))


def _arm_width(env, key: str) -> float:
    profile = next(p for p in env.width_profiles if p.applies_to == key)
    arm = min(profile.regions, key=lambda r: r.max_inscribed_width_m)
    return arm.max_inscribed_width_m


# --- Only a Table III block fits a narrow region ----------------------------------------------


def test_a_block_11_m_wide_fits_the_24_m_arm_below_15_m_and_in_no_high_rise_band():
    """The arm is 24 m wide. Each band keeps its setback from both walls: 5 m for a block up to
    7 m, 6 m up to 15 m, 7 m up to 18 m, then a high-rise's 7 m and more. An 11 m wide block fits
    where the land is 12 m or 14 m across, and in none of the bands at 10 m or less: only a block
    below 21 m can stand in the arm."""
    rules, env = _run(make_site(L_PLOT, side="S"))
    widths = {key: _arm_width(env, key) for key in ("0-7 m", "7-15 m", "15-18 m", "21 m",
                                                    "21-24 m", "24-27 m", "27-30 m")}
    assert widths == pytest.approx({"0-7 m": 14, "7-15 m": 12, "15-18 m": 10, "21 m": 10,
                                    "21-24 m": 8, "24-27 m": 6, "27-30 m": 4}, abs=0.1)
    block = box(6.5, 110, 17.5, 130)  # 11 m across, 20 m along the arm
    fits = []
    for band in env.bands:
        if band.buildable and _land(band.buildable).buffer(1e-9).contains(block):
            fits.append((band.above_m, band.up_to_m, band.kind))
    assert fits == [(0.0, 7.0, BandKind.NON_HIGH_RISE), (7.0, 15.0, BandKind.NON_HIGH_RISE)]
    # the contract finds a block's band: 15 m above a 3 m stilt is a 15 m block whichever way the
    # stilt is read, and it is the band whose land holds it
    for counted in (True, False):
        band = rules.height.band_for_block(15.0, 3.0, stilt_counted=counted)
        assert _land(env.of_band(band).buildable).buffer(1e-9).contains(block)
    taller = rules.height.band_for_block(18.0, 3.0, stilt_counted=True)  # 21 m: a high-rise
    assert taller.kind is BandKind.HIGH_RISE
    assert not _land(env.of_band(taller).buildable).buffer(1e-9).contains(block)


def test_a_block_is_found_in_the_arm_on_its_height_above_the_stilt_not_its_rule_height():
    rules, env = _run(make_site(L_PLOT, side="S"))
    block = box(6.5, 110, 17.5, 130)
    by_rule_height = rules.height.band_for(18.0)  # what 15 m above a 3 m stilt reads as
    assert by_rule_height.setback_m is None  # the open stretch: no setback, no land
    assert not env.of_band(by_rule_height).buildable
    right = rules.height.band_for_block(15.0, 3.0, stilt_counted=True)
    assert _land(env.of_band(right).buildable).buffer(1e-9).contains(block)


# --- The land of a band below 21 m ------------------------------------------------------------


def test_the_land_of_a_band_is_the_net_plot_inset_by_the_larger_of_its_two_setbacks():
    """On a 35 m road Table III's Building Line is 7.5 m, larger than the 5 m a block of up to 7 m
    keeps on its other sides: until an edge-wise inset exists the land is inset all round by the
    larger, never more lenient than the law."""
    rules, env = _run(make_site(RECTANGLE, road_m=35.0))
    first = env.bands[0]
    assert (first.setback_m, first.front_setback_m) == (5.0, 7.5)
    inset = _land(first.setback_envelope)
    assert inset.symmetric_difference(box(7.5, 7.5, 142.5, 92.5)).area < 1e-6
    on_60_ft = _land(_run(make_site(RECTANGLE, road_m=18.288))[1].bands[0].setback_envelope)
    assert on_60_ft.symmetric_difference(box(5, 5, 145, 95)).area < 1e-6


def test_a_taller_line_keeps_a_wider_setback_so_its_land_lies_inside_the_shorter_ones():
    env = _run(make_site(L_PLOT, side="S"))[1]
    lines = [b for b in env.bands if b.kind is BandKind.NON_HIGH_RISE and b.buildable]
    assert len(lines) == 3
    for shorter, taller in zip(lines, lines[1:], strict=False):
        assert _land(taller.buildable).difference(_land(shorter.buildable)).area < 1e-6
        assert taller.area_sqm < shorter.area_sqm
    high = next(b for b in env.bands if b.above_m == b.up_to_m == 21.0)
    assert _land(high.buildable).difference(_land(lines[-1].buildable)).area < 1e-6


def test_a_plot_too_narrow_for_a_taller_lines_setbacks_says_the_land_ran_out():
    """9 m wide, 1,350 m² (row 9): the setbacks of the first two lines (4 m: the front's, larger
    than the sides) leave 1 m of land, the third line's 5 m leave none, and the fourth, whose land
    is inside the third's, has none either. Each is permitted and says the land ran out."""
    rules, env = _run(make_site(box(0, 0, 9, 150), road_m=18.288))
    lines = [b for b in env.bands if b.kind is BandKind.NON_HIGH_RISE and b.setback_m is not None]
    assert [b.up_to_m for b in lines] == [7.0, 12.0, 15.0, 18.0]
    assert all(b.permission is Eligibility.ALLOWED for b in lines)
    assert [bool(b.buildable) for b in lines] == [True, True, False, False]
    assert all("leave no land" in b.note for b in lines[2:])
    assert not any("leave no land" in b.note for b in lines[:2])
    assert rules.height.permissible_non_high_rise().up_to_m == 18.0  # permitted, though no land


def test_a_height_nothing_permits_has_a_band_and_says_why_and_has_no_land():
    rules, env = _run(make_site(box(0, 0, 30, 20), road_m=18.288))  # 600 m²: stops at 15 m
    *lines, above = env.bands
    assert [b.up_to_m for b in lines] == [7.0, 12.0, 15.0] and all(b.buildable for b in lines)
    assert (above.above_m, above.up_to_m, above.permission) == (15.0, 21.0, Eligibility.PROHIBITED)
    assert not above.buildable and not above.setback_envelope and above.setback_m is None
    assert "no order read permits" in above.note
    assert rules.height.permissible_non_high_rise().up_to_m == 15.0


def test_the_facts_name_the_permissible_non_high_rise_height_and_what_is_still_open():
    rules, env = _run(make_site(RECTANGLE, road_m=18.288))
    fact = next(f for f in env.facts if f.rule == "Non-high-rise height")
    assert fact.measured == "18 m (below it)" and fact.status is Status.UNVERIFIED
    assert "up to 21 m (below it) if what is open is settled" in fact.note
    assert "only through TDR" not in fact.note and "no order read gives a setback" in fact.note
    small = _run(make_site(box(0, 0, 40, 30), road_m=18.288))[1]  # 1,200 m²: TDR above 18 m
    assert "only through TDR" in next(f for f in small.facts
                                      if f.rule == "Non-high-rise height").note


# --- The drawing ------------------------------------------------------------------------------


def test_the_debug_drawing_names_the_bands_below_21_m_and_survives_a_band_with_no_land(tmp_path):
    site = make_site(box(0, 0, 30, 20), road_m=18.288)
    rules, env = _run(site)
    dxf = write_debug_dxf(site, rules, env, tmp_path / "e.dxf")
    svg = write_debug_svg(site, rules, env, tmp_path / "e.svg")
    layers = {layer.dxf.name for layer in ezdxf.readfile(dxf).layers}
    assert {"SETBACK-0-7", "BUILDABLE-7-12", "BUILDABLE-12-15"} <= layers
    assert not any(name.endswith("15-21") for name in layers)  # a band with no land has no layer
    text = svg.read_text()
    assert "15-21 m: prohibited" in text and "0-7 m: 2.5 m, front 4 m, 264 m2" in text
