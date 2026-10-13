"""The typical floor a block is composed to (2026-10-12, the architect): a flat's saleable area is
the flat and its share of the corridors, lifts and stairs times the loading, as the firm's area
statement has it (its 474,912 sft of floor x 1.22 is its 579,392 saleable), so a library flat's
width x depth is its share of the floor (AreaBasis.PLATE_SHARE) and the cores and corridor are
laid out of it, not added on top: before, every flat of the firm's own run used 131.8 m² of
floor where it sells on 91.4. A core is compact (`core_depth_m`), across the corridor, where it
spanned the block's whole depth. Made-up flats only."""

import pytest

from siteplan.contracts.prototype import PrototypeFamily
from siteplan.library import AreaBasis, FlatLibrary, FlatType
from siteplan.prototypes import compose_library, problems
from siteplan.prototypes.compose import compose_single_rows

TEST_CLASS = "normative"

SQFT_A_SQM = 10.7639
LOADING = 1.22
DEPTH_M = 12.0
MIX = {"2BHK": 0.6, "3BHK": 0.4}


def _flat(name: str, bhk: str, width_m: float) -> dict:
    """A made-up flat whose saleable is its share of the floor times the loading."""
    return {"name": name, "bhk": bhk, "width_m": width_m, "depth_m": DEPTH_M,
            "saleable_sqft": round(width_m * DEPTH_M * SQFT_A_SQM * LOADING, 3)}


LIBRARY = FlatLibrary(flats=[_flat("2A", "2BHK", 8.0), _flat("3A", "3BHK", 9.0)],
                      core_width_m=7.5, corridor_width_m=2.0, core_depth_m=8.0)


@pytest.fixture(scope="module")
def kit():
    return compose_library(LIBRARY, MIX)


def test_a_flats_floor_is_what_it_sells_on_less_the_loading(kit):
    """The floor of every block is its flats' shares, cores and corridor included: a flat uses
    its saleable over the loading, not that plus a core and a corridor."""
    for p in kit:
        sold_on = sum(m.saleable_sqft for m in p.modules) / LOADING / SQFT_A_SQM
        assert p.per_floor.gross_floor_sqm == pytest.approx(sold_on, rel=1e-6), p.id


def test_the_old_way_adds_the_cores_and_corridor_to_the_flats():
    """FLAT_ONLY with a full-depth core is the composer before 2026-10-12: the same flats need
    more floor than they sell on, the double count the plate share removes."""
    old = compose_library(LIBRARY.model_copy(update={"area_basis": AreaBasis.FLAT_ONLY,
                                                     "core_depth_m": None}), MIX)
    for before, now in zip(old, compose_library(LIBRARY, MIX), strict=True):
        assert before.per_floor.flats == now.per_floor.flats
        assert before.per_floor.flats_own_sqm == pytest.approx(
            sum(m.saleable_sqft for m in before.modules) / LOADING / SQFT_A_SQM)
        assert before.per_floor.gross_floor_sqm > now.per_floor.gross_floor_sqm * 1.2


def test_a_core_is_compact_across_the_corridor(kit):
    for p in kit:
        across = "y" if p.length_m >= p.depth_m and not _turned(p) else "x"
        for zone in p.core_zones:
            x0, y0, x1, y1 = zone.shape.to_shapely().bounds
            along_m, across_m = (x1 - x0, y1 - y0) if across == "y" else (y1 - y0, x1 - x0)
            assert (along_m, across_m) == pytest.approx((7.5, 8.0)), p.id
            assert (y0 + y1 if across == "y" else x0 + x1) == pytest.approx(0.0)  # centred


def test_every_flat_of_a_type_has_the_same_floor_whether_or_not_it_wraps_a_core(kit):
    for p in kit:
        by_type: dict[str, set[float]] = {}
        for m in p.modules:
            # to a thousandth of a m²: corners are rounded to a micrometre
            by_type.setdefault(m.type_id, set()).add(round(m.shape.area_sqm, 3))
        assert all(len(areas) == 1 for areas in by_type.values()), (p.id, by_type)
        corners = {len(m.shape.outer) for m in p.modules}
        assert corners <= {4, 6}, p.id  # a rectangle, or an L round the back of a core


def test_the_flats_cores_and_corridor_tile_every_block_its_long_side_along_x(kit):
    assert [p.family for p in kit] == list(PrototypeFamily)[:4]
    for p in kit:
        assert problems(p) == [], p.id
        assert p.length_m >= p.depth_m


def test_a_block_shorter_than_it_is_deep_is_turned_a_quarter():
    small = compose_library(LIBRARY, MIX, families=[PrototypeFamily.SINGLE_CORE_SMALL])[0]
    assert _turned(small)
    assert small.length_m == pytest.approx(2 * DEPTH_M + 2.0)  # the depth now lies along x
    assert problems(small) == []


def test_a_core_that_does_not_reach_across_the_corridor_is_refused():
    with pytest.raises(ValueError, match="does not reach across"):
        LIBRARY.model_copy(update={"core_depth_m": 2.0}).model_validate(
            {**LIBRARY.model_dump(), "core_depth_m": 2.0})


def test_cores_that_take_the_whole_block_are_refused():
    tiny = LIBRARY.model_copy(update={"flats": [
        FlatType.model_validate(_flat("2A", "2BHK", 1.0)),
        FlatType.model_validate(_flat("3A", "3BHK", 1.0))]})
    with pytest.raises(ValueError, match="cores"):
        compose_library(tiny, MIX, families=[PrototypeFamily.TWO_CORE_MEDIUM])


def test_a_blocks_footprint_measures_exactly_its_stated_length_and_depth():
    """Found 2026-10-12: a flat narrowed to its share of the floor has a frontage off the
    micrometre grid, and a block an odd number of micrometres long could not be centred on it,
    so its footprint ran a micrometre longer than stated; the search, spacing blocks by the
    stated length, left half a micrometre too little between two end to end, and the validator
    failed the layout. Frontages are on the grid and every block an even number of micrometres
    long."""
    odd = LIBRARY.model_copy(update={"flats": [
        FlatType.model_validate(_flat("2A", "2BHK", 7.4433)),
        FlatType.model_validate(_flat("3A", "3BHK", 8.2917))]})
    kit = compose_library(odd, MIX)
    for p in [*kit, *compose_single_rows(odd, MIX, kit[-1])]:
        x0, y0, x1, y1 = p.footprint.to_shapely().bounds
        assert (x1 - x0, y1 - y0) == pytest.approx((p.length_m, p.depth_m), abs=1e-9), p.id
        assert (x0 + x1, y0 + y1) == pytest.approx((0.0, 0.0), abs=1e-9), p.id


def test_a_single_row_block_keeps_each_flats_own_area_and_says_it_is_preliminary():
    """2026-10-12, the architect: where no library block fits, a single row of the same flats
    beside a corridor, one core in line; labelled engine-composed and preliminary until the
    firm's own plate is measured. A flat is the same flat in it as in the double-loaded blocks."""
    kit = compose_library(LIBRARY, MIX)
    reference = kit[-1]
    own = {m.type_id: m.shape.area_sqm for m in reference.modules}
    rows = compose_single_rows(LIBRARY, MIX, reference)
    assert [p.per_floor.flats for p in rows] == [3, 4]
    for p in rows:
        assert p.family is PrototypeFamily.SINGLE_ROW
        assert "ENGINE-COMPOSED" in p.source and "PRELIMINARY" in p.source
        assert problems(p) == []
        assert min(p.length_m, p.depth_m) == pytest.approx(DEPTH_M + 2.0)  # a flat + corridor
        for m in p.modules:
            assert m.shape.area_sqm == pytest.approx(own[m.type_id], abs=1e-4)
        # fewer flats share its core and corridor: more floor a flat than the double-loaded
        assert (p.per_floor.gross_floor_sqm / p.per_floor.flats
                > reference.per_floor.gross_floor_sqm / reference.per_floor.flats)


def _turned(prototype) -> bool:
    """A turned block's corridor runs along y."""
    x0, y0, x1, y1 = prototype.corridor[0].to_shapely().bounds
    return (y1 - y0) > (x1 - x0)
