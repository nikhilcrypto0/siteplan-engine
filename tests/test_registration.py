"""Fitting one outline onto another's frame (registration.py), on made-up land: a net outline
drawn in its own frame is laid back where it belongs, and the strip it lacks shows."""

import pytest
from shapely import affinity
from shapely.geometry import Polygon, box

from siteplan.registration import register

SURVEY = Polygon([(0, 0), (180, 0), (180, 90), (90, 90), (90, 170), (0, 170)])
STRIP = box(170, 0, 180, 90)  # 10 m given up along part of the east side
NET = SURVEY.difference(STRIP)


@pytest.mark.parametrize("turn, shift", [(-17.44, (3.0, 62.5)), (33.0, (-40.0, 7.5)),
                                         (0.0, (0.0, 0.0))])
def test_a_net_outline_in_its_own_frame_is_laid_back_where_it_belongs(turn, shift):
    drawn = affinity.translate(affinity.rotate(NET, turn, origin=(0, 0)), *shift)
    fit = register(drawn, SURVEY)
    assert fit.polygon.symmetric_difference(NET).area < 1.0
    assert fit.outside_sqm < 1.0
    assert fit.gap_sqm == pytest.approx(STRIP.area, rel=0.01)
    assert fit.agreeing_share > 0.8 and fit.rms_m < 0.05


def test_the_fit_reports_itself():
    fit = register(affinity.rotate(NET, 10.0, origin=(0, 0)), SURVEY)
    text = fit.describe()
    assert "turned" in text and "within" in text and "not covered" in text
    assert fit.rotation_deg == pytest.approx(-10.0, abs=0.05)
