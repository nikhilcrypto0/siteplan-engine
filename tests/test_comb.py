"""The comb (2026-10-21, the user's sketch, after the firm's Dhulapally plan): blocks at right
angles to the road that serves them, the road meeting each at its short end, like the teeth of a
comb; and the tot-lot in few large pieces, one by the entrance. Both are the client's design
wishes, never rules: a project names them (`LayoutRequest.preferences`), the objective weighs
them, and only when the brief asks for the comb does the search also lay blocks turned a quarter
in their columns. Made-up land."""

from functools import cache

import pytest
from search_support import made_up, strategy
from shapely.geometry import Polygon, box

from siteplan.adapters.legacy_site import _preferences, _preferences_back
from siteplan.contracts.common import Provenance
from siteplan.contracts.design_brief import SoftPreference
from siteplan.layout import DesignPreference, LayoutRequest
from siteplan.optimizer import preferences
from siteplan.optimizer.search.build import placement_of
from siteplan.optimizer.search.columns import Choice, Standing
from siteplan.optimizer.search.frame import Frame
from siteplan.validator import validate

TEST_CLASS = "normative"
COMB = SoftPreference(kind="at_right_angles_to_road")


@cache
def _search(wish: bool):
    made = made_up(box(0, 0, 200, 120))
    brief = made.brief.model_copy(deep=True)
    if wish:
        brief.objectives.soft_preferences.append(COMB)
    inputs = made.__class__(made.site, made.rules, brief, made.envelope, made.kit)
    return inputs, strategy().propose(inputs.context())


def test_a_turned_block_stands_exactly_in_its_column_its_long_side_across_it():
    made = made_up(box(0, 0, 200, 120))
    p = made.kit[0]
    for angle in (0.0, 17.4, 63.0):
        frame = Frame(angle)
        s = Standing(Choice(p, None, p.depth_m, p.length_m, 0.0, True), 0, 10.0, 20.0)
        placed = placement_of(s, "T1", frame)
        column = frame.to_survey(box(10, 20, 10 + p.length_m, 20 + p.depth_m))
        assert placed.footprint.hausdorff_distance(column) < 1e-6


def test_asked_for_the_comb_the_search_offers_one_and_the_validator_judges_it():
    inputs, proposal = _search(True)
    combs = [c for c in proposal.candidates
             if preferences._right_angles_to_road(c, {}) > 0.99]
    assert combs, [round(preferences._right_angles_to_road(c, {}), 2)
                   for c in proposal.candidates]
    for c in combs:
        report = validate(inputs.site, inputs.rules, inputs.brief, c, inputs.envelope)
        assert report.verdict.legal.value != "FAIL"


def test_not_asked_the_search_lays_no_turned_block():
    _, without = _search(False)
    assert not any(preferences._right_angles_to_road(c, {}) > 0.99
                   for c in without.candidates)
    assert not preferences.wants_comb([])


def test_a_tot_lot_in_few_large_pieces_by_the_entrance_scores_higher():
    _, proposal = _search(False)
    c = proposal.candidates[0]
    gates = preferences._gates(c)
    near = gates.centroid
    two = [Polygon(box(near.x - 20, near.y, near.x + 20, near.y + 25)),
           Polygon(box(150, 90, 190, 115))]
    scattered = [Polygon(box(10 + 15 * k, 100, 20 + 15 * k, 110)) for k in range(8)]

    def score(pieces):
        program = c.program.model_copy(update={"open_space": [
            type(c.program.open_space[0]).from_shapely(p) for p in pieces]})
        return preferences._tot_lot_few_large(c.model_copy(update={"program": program}), {})

    assert score(two) == 1.0 and score(scattered) < 0.5


def test_asked_for_the_tot_lot_at_the_north_end_the_layout_packs_it_from_there():
    """2026-10-21, the user: the tot-lot at the north arm's tip, as the firm laid it. Asked, every
    layout lays its pockets from the north end first; the objective scores it."""
    made = made_up(box(0, 0, 200, 120))
    north = SoftPreference(kind="tot_lot_toward", params={"bearing_deg": 0})
    brief = made.brief.model_copy(deep=True)
    brief.objectives.soft_preferences.append(north)
    inputs = made.__class__(made.site, made.rules, brief, made.envelope, made.kit)
    asked = strategy().propose(inputs.context()).candidates
    _, plain = _search(False)

    def mean_y(c) -> float:
        pieces = [s.to_shapely() for s in c.program.open_space]
        return sum(p.centroid.y * p.area for p in pieces) / sum(p.area for p in pieces)

    assert asked and plain.candidates
    def average(cs) -> float:
        return sum(mean_y(c) for c in cs) / len(cs)

    assert average(asked) > average(plain.candidates) + 1  # metres further north, on average
    best = max(asked, key=mean_y)
    assert preferences._tot_lot_toward(best, north.params) > 0.5
    assert preferences.tot_lot_toward([north]) == pytest.approx((0.0, 1.0))
    assert preferences.tot_lot_toward([]) is None


def test_asked_for_the_club_house_at_the_south_end_the_layout_places_it_there():
    """2026-10-21, the user: the club house out of Dhulapally's north arm, so the arm goes to a
    tower. Asked toward the south, it stands further south than the search would put it."""
    made = made_up(box(0, 0, 200, 120))
    south = SoftPreference(kind="club_toward", params={"bearing_deg": 180})
    brief = made.brief.model_copy(deep=True)
    brief.objectives.soft_preferences.append(south)
    inputs = made.__class__(made.site, made.rules, brief, made.envelope, made.kit)
    asked = strategy().propose(inputs.context()).candidates
    _, plain = _search(False)

    def club_y(cs) -> float:
        ys = [c.program.club_house.shape.to_shapely().centroid.y for c in cs
              if c.program.club_house]
        return sum(ys) / len(ys)

    assert asked and club_y(asked) < club_y(plain.candidates) - 1
    assert preferences.club_toward([south]) == pytest.approx((0.0, -1.0))
    assert preferences.club_toward([]) is None


def test_a_club_house_kept_short_of_a_line_never_stands_beyond_it():
    """2026-10-21, the user: the club house never in Dhulapally's north arm, so the arm's ground
    goes to the tot-lot and a tower. Here kept south of y = 60 m on the made-up rectangle (its
    net plot runs to 100 m): every layout's club house stands wholly short of the line."""
    made = made_up(box(0, 0, 200, 120))
    line = SoftPreference(kind="club_not_beyond", params={"bearing_deg": 0, "along_m": 60})
    brief = made.brief.model_copy(deep=True)
    brief.objectives.soft_preferences.append(line)
    inputs = made.__class__(made.site, made.rules, brief, made.envelope, made.kit)
    asked = strategy().propose(inputs.context()).candidates
    clubs = [c for c in asked if c.program.club_house]
    assert clubs
    for c in clubs:
        assert c.program.club_house.shape.to_shapely().bounds[3] <= 60.01, c.candidate_id
        assert preferences._club_not_beyond(c, line.params) == 1.0
    _, plain = _search(False)
    assert any(c.program.club_house.shape.to_shapely().bounds[3] > 60.01
               for c in plain.candidates if c.program.club_house)  # it binds here


def test_a_project_names_its_wishes_and_they_reach_the_brief_and_back():
    r = LayoutRequest(floors=8, unit_mix={"2BHK": 1.0}, preferences=[
        DesignPreference(kind="at_right_angles_to_road", source="the user, 2026-10-21"),
        DesignPreference(kind="tot_lot_few_large", params={"pieces": 2, "near_m": 30},
                         source="the user, 2026-10-21", status="USER_CONFIRMED")])
    wishes = _preferences(r)
    assert [w.kind for w in wishes] == ["at_right_angles_to_road", "tot_lot_few_large"]
    assert wishes[1].status is Provenance.USER_CONFIRMED and not wishes[1].required
    assert all(preferences.understood(w) for w in wishes)
    brief_like = type("B", (), {"objectives": type("O", (), {"soft_preferences": wishes})})
    back = _preferences_back(brief_like)
    assert [b["kind"] for b in back] == ["at_right_angles_to_road", "tot_lot_few_large"]
    assert not preferences.understood(SoftPreference(kind="tot_lot_few_large",
                                                     params={"pieces": "two"}))
