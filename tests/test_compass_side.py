"""One reading of a compass side (`geometry.faces`): the envelope's frontage (the access zones a
gate may open in, the front zone, the frontage strip), the full search's setbacks and the
validator's front select the same stretches of the plot line, for every label, on a plot set
square to the compass and on plots turned off it.

A side is a label, the nearest of eight compass points to where the road really lies, so a
diagonal label stands for either side it lies between. The envelope used to read a strict 45
degrees for every label: on a square-set plot SW faced no stretch at all, and on a turned plot
it took one of the two stretches the validator holds to the front. Made-up plots only.
"""

import pytest
from legal_fixtures import make_site
from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from siteplan.geometry import COMPASS_DEG, angle_between
from siteplan.legal.envelope import envelope
from siteplan.legal.frontage import front_runs
from siteplan.legal.resolve import resolve
from siteplan.optimizer.search.land import Plot, setback_land
from siteplan.validator import zones

TEST_CLASS = "normative"
SIDES = list(COMPASS_DEG)  # N, NE, E, SE, S, SW, W, NW
SQUARE = box(0, 0, 150, 100)  # set square to the compass
PLOTS = {
    "square": SQUARE,
    # no stretch within a degree of a limit: 10 or 80 degrees off a cardinal label, 35 or 55
    # off a diagonal one
    "turned 10 degrees": affinity.rotate(SQUARE, 10, origin="centroid"),
    # every stretch exactly 45 degrees off a cardinal label: the limit, which is included
    "turned 45 degrees": affinity.rotate(SQUARE, 45, origin="centroid"),
}
FRONT_M, SIDE_M = 12.0, 7.0  # a Building Line deeper than the side setback


def _ends(lines) -> set[frozenset]:
    """Each stretch as its two ends, rounded, whichever way it runs."""
    return {frozenset((round(x, 6), round(y, 6)) for x, y in (line.coords[0], line.coords[-1]))
            for line in lines}


def _cases():
    return [pytest.param(plot, side, id=f"{plot}-{side}") for plot in PLOTS for side in SIDES]


@pytest.mark.parametrize("plot, side", _cases())
def test_the_envelopes_frontage_is_the_validators_front(plot, side):
    """front_runs is what the access zones, the front zone and the frontage strip are cut from."""
    net = PLOTS[plot]
    front = zones.front_edges(net, side)
    assert front, "every label faces some stretch of these plots"
    assert _ends(front_runs(net, side)) == _ends(front)


@pytest.mark.parametrize("plot, side", _cases())
def test_the_envelopes_access_zones_run_along_the_validators_front(plot, side):
    net = PLOTS[plot]
    site = make_site(net, side=side)
    zones_ = envelope(site, resolve(site)).circulation.access_zones
    assert zones_ and all(zone.side == side for zone in zones_)
    drawn = unary_union([LineString(zone.frontage.points) for zone in zones_])
    assert drawn.equals(unary_union(zones.front_edges(net, side)))


def _held(net, figure) -> Polygon:
    """The land at least `figure(edge, bearing)` from every stretch of the plot line."""
    return net.difference(unary_union([edge.buffer(figure(edge, bearing))
                                       for edge, bearing in zones.boundary_edges(net)]))


@pytest.mark.parametrize("plot, side", _cases())
def test_the_search_holds_the_validators_front_to_the_building_line(plot, side):
    """The full search keeps a block FRONT_M from every stretch the validator calls the front and
    SIDE_M from the rest, measured from each stretch as the validator measures it."""
    net = PLOTS[plot]
    front = zones.front_edges(net, side)
    expected = _held(net, lambda edge, _: FRONT_M if any(edge.equals(f) for f in front)
                     else SIDE_M)
    land = setback_land(Plot(net, Polygon(), (), side), FRONT_M, SIDE_M)
    assert land.symmetric_difference(expected).area < 1e-6


@pytest.mark.parametrize("turn, west_m", [(-21, 4.0), (-22, 6.0)])
def test_a_stretch_within_a_degree_of_the_limit_keeps_the_larger_setback_in_the_search(
        turn, west_m):
    """Turned 22 degrees, the west stretch faces 67 degrees off SW, half a degree inside the
    reach: the validator holds it to the front's 4 m, and the search keeps the larger 6 m, never
    more lenient (FACING_DOUBT_DEG). Turned 21 degrees it is plainly the front."""
    net = affinity.rotate(SQUARE, turn, origin="centroid")
    front = zones.front_edges(net, "SW")
    assert len(front) == 2  # the south and the west, to the validator

    def figure(edge, bearing):
        if not any(edge.equals(f) for f in front):
            return 6.0
        return west_m if angle_between(bearing, COMPASS_DEG["SW"]) > 60 else 4.0

    land = setback_land(Plot(net, Polygon(), (), "SW"), 4.0, 6.0)
    assert land.symmetric_difference(_held(net, figure)).area < 1e-6


@pytest.mark.parametrize("side", ["NE", "SE", "SW", "NW"])
def test_a_diagonal_label_on_a_square_set_plot_takes_both_sides_it_lies_between(side):
    """Both stretches are exactly 45 degrees off the label: the old strict reading took neither,
    so the envelope gave no access zone and the search no gate."""
    both = {zones.compass_name(bearing) for edge, bearing in zones.boundary_edges(SQUARE)
            if any(edge.equals(f) for f in zones.front_edges(SQUARE, side))}
    assert both == set(side)  # SW: the south and the west
    assert len(front_runs(SQUARE, side)) == 2
    site = make_site(SQUARE, side=side)
    zones_ = envelope(site, resolve(site)).circulation.access_zones
    assert sum(zone.length_m for zone in zones_) == pytest.approx(150 + 100)
