"""Random damage to made-up candidates: whatever is drawn, the validator answers with a report.

A gate that stops on a strange shape stops the optimizer that feeds it. Each fixture is damaged
in one to three random ways (towers moved, turned, mirrored, re-floored or sent off to nan,
roads, bays, the club house and the cellars dropped, shapes that cross themselves, a prototype
that crosses itself, an open reading the validator has never heard of, a net plot that crosses
itself) and the report must come back, survive JSON, and never be the geometry library giving up.
Seeded, so a failure repeats. The same loop was run for 16,000 mutations, also on the generator's
real Suchitra options, when the validator was built."""

import contextlib
import random

import pytest
from shapely import affinity
from shapely.geometry import Polygon
from validator_helpers import fixture, move_tower, shape

from siteplan.contracts import ValidationReport
from siteplan.contracts.candidate import Cellars

TEST_CLASS = "normative"
FIXTURES = ("rectangle", "l_plot_with_arm", "small_plot", "nala_plot")
MUTANTS = 25
CROSSES_ITSELF = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])
HAIRLINE = Polygon([(0, 0), (30, 0), (30, 1e-9), (0, 1e-9)])
UNKNOWN = "a_reading_nobody_has_heard_of"
GAVE_UP = "Shapes the geometry library can measure"


def _restated(candidate, tower):
    with contextlib.suppress(Exception):  # a tower already sent to nan has no footprint to restate
        tower.footprint = shape(candidate.placed_footprint(tower))


def _damage(candidate, rng):
    """One random way to spoil a candidate, in place."""
    towers, program, roads = candidate.towers, candidate.program, candidate.circulation.roads
    kinds = ["drop_club", "drop_cellars", "deep_cellars", "drop_bays", "drop_open_space",
             "drop_ramps", "drop_gates", "hairline_open_space", "crossing_bay",
             "crossing_prototype"]
    if towers:
        kinds += ["move", "move", "turn", "mirror", "floors", "drop_tower", "no_stilt",
                  "nan", "far_away", "crossing_core"]
    if roads:
        kinds += ["drop_road", "shift_roads", "crossing_road", "declared_width"]
    kind = rng.choice(kinds)
    if kind in ("move", "turn", "mirror", "floors", "no_stilt", "nan", "far_away", "drop_tower"):
        tower = rng.choice(towers)
        if kind == "move":
            move_tower(candidate, tower.name, rng.uniform(-25, 25), rng.uniform(-25, 25))
        elif kind == "turn":
            tower.rotation_deg = rng.choice([15.0, 45.0, 90.0, 137.5, 270.0])
            _restated(candidate, tower)
        elif kind == "mirror":
            tower.mirrored = not tower.mirrored
            _restated(candidate, tower)
        elif kind == "floors":
            tower.floors_above_stilt = max(1, tower.floors_above_stilt + rng.choice([-5, 1, 12]))
        elif kind == "no_stilt":
            tower.has_stilt = False
        elif kind == "nan":
            tower.x = float("nan")
        elif kind == "far_away":
            tower.x, tower.y = 1e12, -1e12
            _restated(candidate, tower)
        else:
            towers.remove(tower)
    elif kind == "crossing_core":
        prototype = rng.choice(candidate.prototypes_used)
        if prototype.core_zones:
            prototype.core_zones[0].shape = shape(CROSSES_ITSELF)
    elif kind == "crossing_prototype":
        rng.choice(candidate.prototypes_used).footprint = shape(CROSSES_ITSELF)
    elif kind == "drop_road":
        roads.pop(rng.randrange(len(roads)))
    elif kind == "shift_roads":
        for road in roads:
            road.shapes = [shape(affinity.translate(s.to_shapely(), 1.0, -0.7))
                           for s in road.shapes]
    elif kind == "crossing_road":
        rng.choice(roads).shapes = [shape(CROSSES_ITSELF)]
    elif kind == "declared_width":
        rng.choice(roads).declared_width_m = rng.choice([4.5, 8.9, 18.5, 40.0])
    elif kind == "drop_club":
        program.club_house = None
    elif kind == "drop_cellars":
        program.cellars = rng.choice([None, Cellars(levels=0)])
    elif kind == "deep_cellars":
        program.cellars = Cellars(levels=rng.choice([1, 3, 6]), setback_m=0.5, outline=[
            shape(Polygon([(0, 0), (100, 0), (100, 80), (0, 80)]))])
    elif kind == "drop_bays":
        program.bays = []
    elif kind == "drop_open_space":
        program.open_space = []
    elif kind == "drop_ramps":
        program.ramps = []
    elif kind == "drop_gates":
        candidate.circulation.gates = []
    elif kind == "hairline_open_space":
        program.open_space = [*program.open_space, shape(HAIRLINE)]
    elif kind == "crossing_bay":
        program.bays = [*program.bays, shape(CROSSES_ITSELF)]


def _damaged_world(inputs, rng):
    """The site and rules, sometimes spoiled in a way the contract still admits or the validator
    must refuse: an open reading it does not know, a net plot that crosses itself."""
    site, rules = inputs.site.model_copy(deep=True), inputs.rules.model_copy(deep=True)
    kind = rng.choice(["none", "none", "unknown_reading", "all_readings", "net_plot_crosses"])
    if kind == "unknown_reading":
        reading = rng.choice(rules.interpretations)
        reading.alternatives = {**reading.alternatives, UNKNOWN: "an invented reading"}
        reading.selected = rng.choice(["ALL", UNKNOWN])
        if reading.id == "open_space_basis":
            rules.open_space.requirement_sqm_by_reading[UNKNOWN] = 1234.5
    elif kind == "all_readings":
        for reading in rules.interpretations:
            reading.selected = "ALL"
    elif kind == "net_plot_crosses" and site.net_plot is not None:
        site.net_plot.value = shape(CROSSES_ITSELF)
    return site, rules


@pytest.mark.parametrize("name", FIXTURES)
def test_whatever_is_drawn_the_validator_answers_with_a_report(name):
    from siteplan.validator import validate

    inputs = fixture(name)
    rng = random.Random(f"{name}-fuzz")
    for n in range(MUTANTS):
        candidate = inputs.candidate.model_copy(deep=True)
        for _ in range(rng.choice([1, 1, 2, 3])):
            _damage(candidate, rng)
        site, rules = _damaged_world(inputs, rng)
        report = validate(site, rules, inputs.brief, candidate)
        assert ValidationReport.model_validate_json(report.model_dump_json()) == report, (name, n)
        assert GAVE_UP not in {c.finding.rule for c in report.legal}, (name, n)
