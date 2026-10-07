"""Site use and quality, the objective's two numbers of the ground (C4-11): ground no use takes
counts against a layout unless a rule keeps it open, and quality is the plain mean of four measures
of an ordinary scheme. Scores the search ranks by, never rules: nothing fails for them. Made-up
land only."""

from __future__ import annotations

import pytest
from optimizer_support import HALF_DEPTH_M, candidate, fixture, module_prototype, tower
from search_support import proposal_on_the_rectangle, rectangle
from shapely.geometry import box

from siteplan.contracts.accounting import LayerKind, PartitionLedger, RuleLayers
from siteplan.contracts.candidate import Circulation, RoadKind, RoadPiece
from siteplan.contracts.common import Shape
from siteplan.contracts.design_brief import Objectives, ParetoPoint, Priority
from siteplan.optimizer.objective import AXES, Scores, measure, priority_weights
from siteplan.optimizer.pareto import Scored, dominates, select

TEST_CLASS = "normative"

_, _, BRIEF = fixture()
P1, P2 = module_prototype(1), module_prototype(2)
NET_SQM = 10_000.0  # a made-up 100 m square
STRIP = box(0, 0, 100, 20)  # 2,000 m² left over along one side
ROADS = box(0, 90, 100, 100)  # 1,000 m² paved
KEPT_OPEN = (LayerKind.SETBACK, LayerKind.BLOCK_GAP, LayerKind.FIRE_CLEAR_BAND,
             LayerKind.TURNING_SECTOR, LayerKind.WATER_BUFFER, LayerKind.GREEN_STRIP_ZONE)


def _ledger(*, left=(), roads=()):
    """A ledger of the square holding these leftover and paved pieces (the objective reads only
    those two uses)."""
    entries = [{"use": "UNALLOCATED", "shapes": [Shape.from_shapely(b)], "area_sqm": b.area,
                "reason": "made up"} for b in left]
    entries += [{"use": "ROAD", "shapes": [Shape.from_shapely(b)], "area_sqm": b.area}
                for b in roads]
    return PartitionLedger(net_area_sqm=NET_SQM, entries=entries)


def _layers(*kept):
    return RuleLayers(layers=[
        {"id": f"L{i}", "kind": kind, "shapes": [Shape.from_shapely(b)], "clause": "made up",
         "basis": "LEGAL_RULE", "status": "ASSUMED_FOR_TEST"} for i, (kind, b) in enumerate(kept)])


def _on(made, ledger, layers=None, roads=()):
    """The candidate on this ground, with these (kind, shape) pieces of pavement drawn."""
    circulation = Circulation(roads=[
        RoadPiece(id=f"R{i}", kind=kind, shapes=[Shape.from_shapely(b)], declared_width_m=6.0)
        for i, (kind, b) in enumerate(roads)])
    return made.model_copy(update={"partition": ledger, "rule_layers": layers or _layers(),
                                   "circulation": circulation})


def _blocks(candidate_id, rotations=(0.0, 0.0), floors=8, prototypes=None):
    prototypes = prototypes or [P1] * len(rotations)
    return candidate(candidate_id, [tower(f"T{i}", p, 20 + 30 * i, 50, floors, r)
                                    for i, (r, p) in enumerate(zip(rotations, prototypes,
                                                                   strict=True))],
                     list({p.id: p for p in prototypes}.values()), open_space_sqm=400)


@pytest.mark.parametrize("kind", KEPT_OPEN)
def test_leftover_ground_a_rule_keeps_open_is_not_counted_against_a_layout(kind):
    """2,000 m² left over, 500 m² of it inside a setback, gap, fire band, turning ground, buffer
    or green strip: 1,500 m² of the 10,000 counts against the layout."""
    bare = measure(_on(_blocks("blocks"), _ledger(left=[STRIP])), BRIEF)
    assert bare.site_use == pytest.approx(1 - 2_000 / NET_SQM)
    kept = _on(_blocks("blocks"), _ledger(left=[STRIP]), _layers((kind, box(0, 0, 100, 5))))
    assert measure(kept, BRIEF).site_use == pytest.approx(1 - 1_500 / NET_SQM)


@pytest.mark.parametrize("kind", [k for k in LayerKind if k not in KEPT_OPEN])
def test_a_layer_that_keeps_nothing_open_at_grade_explains_no_leftover_ground(kind):
    """A cellar's setback, where ramps or bays may not go, where open space qualifies or where the
    fire route runs: the ground can still be put to a use, so leaving it empty is not the rule's."""
    layered = _on(_blocks("blocks"), _ledger(left=[STRIP]), _layers((kind, box(0, 0, 100, 5))))
    assert measure(layered, BRIEF).site_use == pytest.approx(1 - 2_000 / NET_SQM)


def test_a_layout_whose_ground_is_not_drawn_scores_nothing_on_it():
    """Unknown is not good: no ledger, no site use or quality; a ledger with nothing left over is
    the whole of the site used."""
    undrawn = measure(_blocks("blocks"), BRIEF)
    assert (undrawn.site_use, undrawn.quality) == (0.0, 0.0)
    assert measure(_on(_blocks("blocks"), _ledger()), BRIEF).site_use == 1.0


def test_quality_is_the_mean_of_less_road_one_prototype_one_direction_access_and_few_fragments():
    """1,000 m² of road on 10,000 (0.9); three blocks of one prototype (1); two running at 0 and
    179.9999 degrees, which is one way, and one across (2/3); no pavement drawn beside any block
    (0); a 60 m² piece left over, which is a fragment, and a 30 m² one, which is not (1/2)."""
    ground = _ledger(left=[box(0, 0, 10, 6), box(50, 0, 56, 5)], roads=[ROADS])
    three = _blocks("three", rotations=(0.0, 179.9999, 90.0))
    assert measure(_on(three, ground), BRIEF).quality == pytest.approx(
        (0.9 + 1 + 2 / 3 + 0 + 1 / 2) / 5)
    mixed = _blocks("mixed", rotations=(0.0, 179.9999, 90.0), prototypes=[P1, P1, P2])
    assert measure(_on(mixed, ground), BRIEF).quality == pytest.approx(
        (0.9 + 2 / 3 + 2 / 3 + 0 + 1 / 2) / 5)


def test_a_block_a_road_meets_only_at_a_corner_counts_against_the_layout():
    """Two blocks, a road along the first one's long side. The second is reached by a road along
    its side, or by a 6 m pathway meeting it (a pathway's width of its outline faces pavement), but
    not by a road that meets it at a corner: one block in two is reached, a fifth of the gap
    between full and half access off quality."""
    top = HALF_DEPTH_M + 50  # the blocks' upper sides; T0 runs x 4.5-35.5, T1 x 34.5-65.5
    first = (RoadKind.INTERNAL, box(0, top, 36, top + 9))
    beside = (RoadKind.INTERNAL, box(40, top, 66, top + 9))
    pathway = (RoadKind.PATHWAY, box(47, top, 53, top + 10))
    corner = (RoadKind.INTERNAL, box(65.5, top, 75, top + 9))
    blocks = _blocks("blocks")

    def quality(*roads):
        return measure(_on(blocks, _ledger(), roads=roads), BRIEF).quality

    assert quality(first, beside) == pytest.approx(quality(first, pathway))
    assert quality(first, beside) - quality(first, corner) == pytest.approx((1 - 1 / 2) / 5)


def test_site_use_and_quality_are_axes_of_the_front_and_weights_a_brief_may_set():
    """The same blocks with less left over dominate; the brief may weigh either number."""
    assert AXES[-2:] == (Priority.SITE_USE.value, Priority.QUALITY.value)
    tidy = measure(_on(_blocks("blocks"), _ledger(left=[box(0, 0, 100, 5)])), BRIEF)
    loose = measure(_on(_blocks("blocks"), _ledger(left=[STRIP])), BRIEF)
    by_axis = dict(zip(AXES, tidy.vector, strict=True))
    assert (by_axis["site_use"], by_axis["quality"]) == (tidy.site_use, tidy.quality)
    assert {"site_use", "quality"} <= set(tidy.as_dict())
    assert dominates(tidy, loose) and not dominates(loose, tidy)
    weighted = BRIEF.model_copy(update={"objectives": Objectives(
        priorities={Priority.SITE_USE: 3.0})})
    assert priority_weights(weighted)[AXES.index("site_use")] == 3.0


def test_the_conventional_option_is_the_plainer_of_two_equally_open_conventional_schemes():
    """Two single-core schemes with the same open space: one a floor taller with its blocks
    running two ways, one running one way. Yield used to break the tie; the plainer scheme is the
    conventional one."""
    turned = _on(_blocks("turned", rotations=(0.0, 90.0), floors=9), _ledger(roads=[ROADS]))
    plain = _on(_blocks("plain", rotations=(0.0, 0.0), floors=8), _ledger(roads=[ROADS]))
    brief = BRIEF.model_copy(update={"objectives": Objectives(
        pareto=[ParetoPoint.CONVENTIONAL_OPEN_SPACE], options=1)})
    picks = select([Scored(c, measure(c, brief)) for c in (turned, plain)], brief).picks
    assert [p.scored.candidate.candidate_id for p in picks] == ["plain"]


@pytest.mark.parametrize("point", [ParetoPoint.MAX_YIELD, ParetoPoint.ROBUST,
                                   ParetoPoint.CONVENTIONAL_OPEN_SPACE])
def test_between_layouts_a_point_ties_on_the_one_leaving_less_ground_unused_is_chosen(point):
    """The same yield, flats, open space, blocks and quality; one sells more at a worse mix, the
    other leaves less ground to no use. Both are on the front; listed first, the looser one used
    to be taken."""
    loose = Scores(saleable_sqft=2_000.0, units=10, open_space_sqm=400.0, mix_fit=0.5,
                   conventionality=1.0, towers=2, site_use=0.90, quality=0.8)
    tidy = Scores(saleable_sqft=1_000.0, units=10, open_space_sqm=400.0, mix_fit=1.0,
                  conventionality=1.0, towers=2, site_use=0.95, quality=0.8)
    pool = [Scored(_blocks("loose"), loose, (0, 0)),
            Scored(_blocks("tidy", rotations=(90.0, 90.0)), tidy, (0, 0))]
    brief = BRIEF.model_copy(update={"objectives": Objectives(pareto=[point], options=1)})
    assert [p.scored.candidate.candidate_id for p in select(pool, brief).picks] == ["tidy"]


def test_the_last_digits_of_an_area_never_choose_between_layouts():
    """Two schemes of the same blocks, one with 5 billionths of a square metre more open space
    (a polygon's floating point) and 1,500 m² more ground left to no use: to a drawing's precision
    the open space is the same, so the conventional point takes the one that uses its ground."""
    noisy = _on(candidate("noisy", _blocks("b").towers, [P1], open_space_sqm=400.000000005),
                _ledger(left=[STRIP]))
    tidy = _on(candidate("tidy", _blocks("b").towers, [P1], open_space_sqm=400.0),
               _ledger(left=[box(0, 0, 100, 5)]))
    brief = BRIEF.model_copy(update={"objectives": Objectives(
        pareto=[ParetoPoint.CONVENTIONAL_OPEN_SPACE], options=1)})
    pool = [Scored(c, measure(c, brief)) for c in (noisy, tidy)]
    assert pool[0].scores.open_space_sqm == pool[1].scores.open_space_sqm
    assert [p.scored.candidate.candidate_id for p in select(pool, brief).picks] == ["tidy"]


def test_the_full_search_draws_the_ground_its_candidates_are_scored_on():
    made, proposal = rectangle(), proposal_on_the_rectangle()
    assert proposal.candidates
    for laid in proposal.candidates:
        assert laid.partition is not None and laid.rule_layers is not None
        scores = measure(laid, made.brief)
        assert 0 < scores.site_use <= 1 and 0 < scores.quality <= 1
