from shapely import affinity
from shapely.geometry import Polygon, box

from siteplan.checks import Building, Site, Status, check_site


def _by_rule(findings):
    return {f.rule: f for f in findings}


def _tower(name, x0, y0, x1, y1, floors=8):
    footprint = box(x0, y0, x1, y1)
    return Building(name, stilt_height_m=3, floors=floors, floor_height_m=3, footprint=footprint)


def test_compliant_site_passes_geometry_checks():
    site = Site(
        gross_area_sqm=12000,
        net_area_sqm=10000,
        abutting_road_m=18,
        open_space_sqm=1300,
        net_plot=box(0, 0, 100, 100),
        open_space_pockets=(box(40, 40, 60, 60),),
        buildings=(_tower("A", 10, 10, 30, 50), _tower("B", 70, 10, 90, 50)),
    )
    found = _by_rule(check_site(site))
    assert found["Height class: A"].measured == "27.00 m"
    assert found["Abutting road width (for A)"].status is Status.PASS
    assert found["All-round setback: A"].status is Status.PASS
    assert found["Gap between blocks: A / B"].measured == "40.00 m"  # 30 to 70
    assert found["Gap between blocks: A / B"].status is Status.PASS
    assert found["Organized open space (tot-lot)"].status is Status.PASS
    assert found["Open-space pocket 1"].status is Status.PASS


def test_narrow_road_fails_unless_master_plan_widens_it():
    base = dict(net_area_sqm=10000, buildings=(Building("A", height_m=27),))
    narrow = _by_rule(check_site(Site(abutting_road_m=12.19, **base)))
    assert narrow["Abutting road width (for A)"].status is Status.FAIL
    widened = _by_rule(check_site(Site(abutting_road_m=12.19, master_plan_road_m=18.29, **base)))
    assert widened["Abutting road width (for A)"].status is Status.PASS
    assert "surrendered" in widened["Abutting road width (for A)"].note


def test_setback_and_spacing_failures_are_measured():
    site = Site(
        net_area_sqm=10000,
        abutting_road_m=18,
        net_plot=box(0, 0, 100, 100),
        buildings=(_tower("A", 5, 10, 30, 90), _tower("B", 37, 10, 60, 90)),
    )
    found = _by_rule(check_site(site))
    assert found["All-round setback: A"].status is Status.FAIL
    assert found["All-round setback: A"].measured == "5.00 m"
    assert found["Gap between blocks: A / B"].status is Status.FAIL
    assert found["Gap between blocks: A / B"].measured == "7.00 m"


def test_open_space_that_passes_on_one_basis_only_asks_which_basis():
    site = Site(gross_area_sqm=10000, net_area_sqm=9400, open_space_sqm=960)
    finding = _by_rule(check_site(site))["Organized open space (tot-lot)"]
    assert finding.status is Status.NEEDS_INPUT
    assert "10.21% of net" in finding.measured
    assert "9.60% of gross" in finding.measured


def test_narrow_or_small_pockets_fail():
    site = Site(
        net_area_sqm=1000,
        open_space_sqm=200,
        open_space_pockets=(box(0, 0, 2, 50), box(0, 0, 6, 6), box(0, 0, 3, 20)),
    )
    found = _by_rule(check_site(site))
    assert found["Open-space pocket 1"].status is Status.FAIL  # 2 m wide
    assert found["Open-space pocket 2"].status is Status.FAIL  # 36 m²
    assert found["Open-space pocket 3"].status is Status.PASS  # exactly 3 m by 20 m


def test_missing_inputs_are_reported_not_guessed():
    site = Site(buildings=(Building("A", height_m=27), Building("B", height_m=27)))
    found = _by_rule(check_site(site))
    assert found["Height class: A"].status is Status.INFO
    assert found["Abutting road width (for A)"].status is Status.NEEDS_INPUT
    assert found["All-round setbacks"].status is Status.NEEDS_INPUT
    assert found["Gaps between blocks"].status is Status.NEEDS_INPUT
    assert "1 to check" in found["Gaps between blocks"].measured
    assert found["Organized open space (tot-lot)"].status is Status.NEEDS_INPUT


def test_partly_drawn_site_checks_what_it_can():
    site = Site(
        net_area_sqm=10000,
        abutting_road_m=18,
        net_plot=box(0, 0, 100, 100),
        buildings=(_tower("A", 10, 10, 30, 50), Building("B", height_m=27)),
    )
    found = _by_rule(check_site(site))
    assert found["All-round setback: A"].status is Status.PASS
    assert found["All-round setback: B"].status is Status.NEEDS_INPUT
    assert found["Gap between blocks: A / B"].status is Status.NEEDS_INPUT


def test_non_high_rise_is_flagged_as_not_checked():
    found = _by_rule(check_site(Site(buildings=(Building("Villa", height_m=10),))))
    assert found["Height class: Villa"].status is Status.NOT_CHECKED
    assert not any(rule.startswith("Abutting road") for rule in found)


def test_a_tower_above_55_m_is_checked_against_the_2019_bands():
    site = Site(net_area_sqm=10000, abutting_road_m=30, buildings=(Building("Tall", height_m=60),))
    found = _by_rule(check_site(site))
    assert found["Plot size for high-rise"].status is Status.PASS
    assert found["Abutting road width (for Tall)"].status is Status.PASS   # 30 m is enough
    assert "17" in found["All-round setbacks"].required                     # the 55 to 70 band


def test_a_long_building_needs_more_setback_than_the_table_alone():
    """G.O.Ms.No.50 of 2019: over 40 m, add 10% of the length minus 4 m."""
    short = Site(net_area_sqm=10000, abutting_road_m=18, net_plot=box(0, 0, 100, 100),
                 buildings=(_tower("A", 10, 10, 30, 50),))          # 40 m long, needs 9 m
    long = Site(net_area_sqm=10000, abutting_road_m=18, net_plot=box(0, 0, 100, 100),
                buildings=(_tower("A", 10, 10, 30, 90),))           # 80 m long, needs 13 m
    assert _by_rule(check_site(short))["All-round setback: A"].status is Status.PASS
    finding = _by_rule(check_site(long))["All-round setback: A"]
    assert finding.status is Status.FAIL                            # 10 m is no longer enough
    assert "13.00 m" in finding.required and "80 m long" in finding.required
    assert finding.clause.startswith("G.O.Ms.No.50")


def test_a_building_turned_to_suit_the_site_is_measured_on_its_own_axes():
    """Turning a block does not lengthen it, and the 2019 note charges by length."""
    straight = _tower("A", 60, 90, 140, 110)                        # 80 m long, 20 m deep
    turned = Building("A", stilt_height_m=3, floors=8, floor_height_m=3,
                      footprint=affinity.rotate(straight.footprint, 30))
    plot = box(0, 0, 200, 200)

    def required(building):
        site = Site(net_area_sqm=10000, abutting_road_m=18, net_plot=plot,
                    buildings=(building,))
        return _by_rule(check_site(site))["All-round setback: A"].required

    assert required(turned) == required(straight)
    assert "13.00 m" in required(turned) and "80 m long" in required(turned)


def test_a_block_whose_long_sides_jog_is_still_measured_end_to_end():
    """A real outline's long side is rarely one straight edge. The firm's Dhulapally blocks were
    charged as 59-67 m long when drawn 66-73 m, because the longest single edge of the outline
    stops at the first jog; the length is the outline's extent along the building's own axis."""
    jogged = Polygon([(0, 0), (29, 0), (29, -1), (31, -1), (31, 0), (60, 0), (60, 20),
                      (31, 20), (31, 21), (29, 21), (29, 20), (0, 20)])  # 60 m, longest edge 29 m
    building = Building("A", stilt_height_m=3, floors=8, floor_height_m=3,
                        footprint=affinity.translate(jogged, 50, 50))
    site = Site(net_area_sqm=10000, abutting_road_m=18, net_plot=box(0, 0, 200, 200),
                buildings=(building,))
    required = _by_rule(check_site(site))["All-round setback: A"].required
    assert "11.00 m" in required and "60 m long" in required   # 9 m + (10% of 60 - 4 m)


def test_the_gap_between_blocks_is_quoted_to_the_centimetre():
    site = Site(net_area_sqm=10000, abutting_road_m=18, net_plot=box(0, 0, 300, 200),
                buildings=(_tower("A", 20, 20, 83, 43), _tower("B", 20, 50, 83, 73)))
    assert _by_rule(check_site(site))["Gap between blocks: A / B"].required == ">= 11.30 m"


def test_the_green_strip_is_only_asked_for_where_the_setback_reaches_9_m():
    """G.O.Ms.No.7 of 2016 limited rule 7(viii) to setbacks of 9 m and above."""
    shallow = Site(net_area_sqm=10000, abutting_road_m=12, net_plot=box(0, 0, 100, 100),
                   buildings=(_tower("A", 10, 10, 30, 40, floors=6),))   # 21 m tall -> 7 m
    deep = Site(net_area_sqm=10000, abutting_road_m=18, net_plot=box(0, 0, 100, 100),
                buildings=(_tower("A", 10, 10, 30, 50),))                # 27 m tall -> 9 m
    shallow_finding = _by_rule(check_site(shallow))["Peripheral green strip"]
    assert shallow_finding.status is Status.INFO
    assert "9 m" in shallow_finding.note
    assert _by_rule(check_site(deep))["Peripheral green strip"].status is Status.NOT_CHECKED
