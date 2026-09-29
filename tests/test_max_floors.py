"""The most floors a plot can take: the road caps the height, the plot must be big enough."""

import math

import pytest

from siteplan.cli import main
from siteplan.max_floors import max_floors
from siteplan.rules import max_height_for_road, tdr_extra_floors


@pytest.mark.parametrize(("road_m", "height"), [
    (9.0, None), (12.0, 24.0), (12.19, 24.0), (17.9, 24.0), (18.0, 30.0), (18.28, 30.0),
    (24.0, 45.0), (29.9, 45.0), (30.0, math.inf), (40.0, math.inf),
])
def test_the_road_caps_the_height_as_table_iv_column_3_says(road_m, height):
    assert max_height_for_road(road_m) == height


@pytest.mark.parametrize(("plot_sqm", "road_m", "extra"), [
    (18969, 12.19, 3), (18969, 18.28, 4), (18969, 24.4, 5), (18969, 9.0, 0),
    (2000, 18.28, 0),  # "plots above 2000 sq.m"
])
def test_tdr_buys_extra_floors_on_plots_above_2000_m2_by_road(plot_sqm, road_m, extra):
    assert tdr_extra_floors(plot_sqm, road_m) == extra


def test_dhulapally_on_its_60_ft_road_takes_stilt_plus_9_or_10():
    limit = max_floors(plot_sqm=18969, road_m=18.28)
    assert limit.high_rise and limit.max_height_m == 30.0
    assert (limit.floors_stilt_counted, limit.floors_stilt_not_counted) == (9, 10)
    assert limit.setback_m == 10.0 and limit.tdr_extra_floors == 4
    assert "road" in limit.limited_by


def test_a_40_ft_road_stops_at_24_m():
    limit = max_floors(plot_sqm=8064, road_m=12.19)
    assert limit.max_height_m == 24.0
    assert (limit.floors_stilt_counted, limit.floors_stilt_not_counted) == (7, 8)
    assert limit.setback_m == 8.0 and limit.tdr_extra_floors == 3


def test_taller_floors_mean_fewer_of_them():
    limit = max_floors(plot_sqm=18969, road_m=18.28, floor_height_m=3.2)
    assert (limit.floors_stilt_counted, limit.floors_stilt_not_counted) == (8, 9)


def test_a_road_30_m_wide_sets_no_height_limit_of_its_own():
    limit = max_floors(plot_sqm=18969, road_m=30.0)
    assert limit.high_rise and limit.max_height_m is None
    assert limit.floors_stilt_counted is None and limit.tdr_extra_floors == 5
    assert "no height limit" in limit.limited_by


def test_a_road_under_12_m_rules_out_a_high_rise():
    limit = max_floors(plot_sqm=18969, road_m=9.0)
    assert not limit.high_rise and "12 m" in limit.limited_by
    assert (limit.floors_stilt_counted, limit.floors_stilt_not_counted) == (5, 6)  # under 21 m
    assert any("Table III" in note for note in limit.notes)


def test_a_plot_under_2000_m2_rules_out_a_high_rise_whatever_the_road():
    limit = max_floors(plot_sqm=1500, road_m=24.0)
    assert not limit.high_rise and "2,000" in limit.limited_by
    assert limit.tdr_extra_floors == 0
    assert any("TDR" in note and "18" in note for note in limit.notes)  # 18-21 m only via TDR


def test_every_answer_says_what_it_does_not_check():
    notes = " ".join(max_floors(plot_sqm=18969, road_m=18.28).notes)
    assert "legal width" in notes and "airport" in notes.lower() and "stilt" in notes.lower()


def test_the_command_prints_both_stilt_readings(capsys):
    assert main(["floors", "--plot-sqyd", "22686", "--road-ft", "60"]) == 0
    out = capsys.readouterr().out
    assert "stilt + 9" in out and "stilt + 10" in out and "30 m" in out
