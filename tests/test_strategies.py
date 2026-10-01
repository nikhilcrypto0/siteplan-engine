"""Three massing strategies, each reported tower by tower. Design categories, never law."""

from pathlib import Path

from shapely.geometry import box

from siteplan.layout import (
    BALANCED_MAX_CORES,
    BALANCED_MAX_LENGTH_M,
    CONVENTIONAL_MAX_CORES,
    LayoutRequest,
    SiteFacts,
    missing_strategies,
    same_idea,
    search,
)
from siteplan.library import FlatLibrary

LIBRARY = FlatLibrary.model_validate_json(
    (Path(__file__).parent.parent / "examples" / "flat_library.example.json").read_text())
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3})
FACTS = SiteFacts(abutting_road_m=18.0, authority="HMDA", inside_cure=False, access_side="S")


def _options():
    return search(box(0, 0, 160, 130), LIBRARY, REQUEST, FACTS).options


def test_each_strategy_keeps_to_its_cores_and_is_a_different_idea():
    options = {o.strategy.split(":")[0]: o for o in _options()}
    assert set(options) == {"Option A", "Option B", "Option C"}, missing_strategies(
        list(options.values()))
    balanced = options["Option B"]
    assert CONVENTIONAL_MAX_CORES < balanced.max_cores <= BALANCED_MAX_CORES
    assert max(t.length_m for t in balanced.towers) <= BALANCED_MAX_LENGTH_M + 0.01
    assert options["Option C"].max_cores == CONVENTIONAL_MAX_CORES
    assert options["Option A"].score >= max(o.score for o in options.values())
    picked = list(options.values())
    assert not any(same_idea(a, b) for i, a in enumerate(picked) for b in picked[i + 1:])
    assert all(not o.fails for o in picked)


def test_every_tower_is_reported_with_its_size_flats_and_cores():
    option = _options()[0]
    detail = option.summary()["towers_detail"]
    assert len(detail) == len(option.towers)
    for tower, d in zip(option.towers, detail, strict=True):
        assert d["length_m"] >= d["width_m"] > 0
        assert d["cores"] == len(tower.cores)
        assert d["flats_per_floor"] == sum(tower.flats_per_floor().values())
        assert d["flats_per_core_per_floor"] * d["cores"] == d["flats_per_floor"]
        assert d["flats"] == d["flats_per_floor"] * option.floors


def test_a_strategy_nothing_passes_for_is_named_not_filled_in():
    only_a = [o for o in _options() if o.strategy.startswith("Option A")]
    said = missing_strategies(only_a)
    assert any("Option B" in s for s in said) and any("Option C" in s for s in said)
