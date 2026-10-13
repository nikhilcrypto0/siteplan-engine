"""Floor plates composed from a flat library and sized to the land (2026-10-13, the architect):
`PlateSpec` and `compose_plate` (the generalised composer), the area schedule (`account`: each flat
type's saleable fixed, the gross, cores, corridor and the effective loading reported apart, a
shortfall against the loading said and never hidden), what is assumed (`preliminary`), and
`plates_for` (the plates each region of the envelope's land takes). Passing these establishes that
a plate is drawn consistently and fits its land, not that it is architecturally compliant.
Made-up flats and made-up land only."""

TEST_CLASS = "normative"

from functools import cache  # noqa: E402

import pytest  # noqa: E402
from search_support import made_up  # noqa: E402
from shapely.geometry import Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from siteplan.library import FlatLibrary  # noqa: E402
from siteplan.prototypes import compose_library, problems  # noqa: E402
from siteplan.prototypes.compose import Corridor, Loading, PlateSpec, compose_plate  # noqa: E402
from siteplan.prototypes.plates import (  # noqa: E402
    GALLERY_UNKNOWN,
    MISSING_STANDARDS,
    PLATE_SOURCE,
    fits,
    kit_for,
    own_areas,
    plate,
    plates_for,
)

SQFT_A_SQM = 10.7639
LOADING_PCT = 22.0
DEPTH_M = 11.0


def _flat(name: str, bhk: str, width_m: float) -> dict:
    """A made-up flat whose saleable is its share of the floor times the 22% loading."""
    return {"name": name, "bhk": bhk, "width_m": width_m, "depth_m": DEPTH_M,
            "saleable_sqft": round(width_m * DEPTH_M * SQFT_A_SQM * (1 + LOADING_PCT / 100), 3)}


LIBRARY = FlatLibrary(flats=[_flat("1A", "1BHK", 5.5), _flat("2A", "2BHK", 7.5),
                             _flat("3A", "3BHK", 9.0)],
                      core_width_m=7.5, corridor_width_m=2.0, core_depth_m=8.0)
MIX = {"1BHK": 0.2, "2BHK": 0.5, "3BHK": 0.3}


@cache
def _own() -> dict[str, float]:
    return own_areas(compose_library(LIBRARY, MIX)[-1])


SPECS = [PlateSpec(Loading.SINGLE_ROW, ("2A", "2A", "3A"), 1, Corridor.ENCLOSED),
         PlateSpec(Loading.SINGLE_ROW, ("2A", "3A", "2A", "3A"), 1, Corridor.OPEN_GALLERY),
         PlateSpec(Loading.SINGLE_ROW, ("1A", "2A", "2A", "3A"), 2, Corridor.ENCLOSED),
         PlateSpec(Loading.DOUBLE_LOADED, ("2A", "3A", "2A"), 1),
         PlateSpec(Loading.DOUBLE_LOADED, ("1A", "2A", "3A", "2A", "2A"), 2)]


def _plates():
    return [plate(LIBRARY, s, reference_own=_own(), loading_pct=LOADING_PCT) for s in SPECS]


def test_every_plate_closes_and_measures_exactly_its_stated_size():
    for p in _plates():
        assert problems(p.prototype) == [], p.spec
        x0, y0, x1, y1 = p.prototype.footprint.to_shapely().bounds
        assert (x1 - x0, y1 - y0) == pytest.approx(
            (p.prototype.length_m, p.prototype.depth_m), abs=1e-9)


def test_every_flat_meets_the_outer_wall_and_the_corridor_or_a_core():
    for p in _plates():
        foot = p.prototype.footprint.to_shapely()
        reach = unary_union([*(s.to_shapely() for s in p.prototype.corridor),
                             *(z.shape.to_shapely() for z in p.prototype.core_zones)])
        for m in p.prototype.modules:
            flat = m.shape.to_shapely()
            assert flat.boundary.intersection(foot.boundary).length > 1.0, (p.spec, m.id)
            assert flat.boundary.intersection(reach.boundary).length > 1.0, (p.spec, m.id)


def test_the_corridor_and_cores_are_one_piece_that_every_flat_reaches():
    for p in _plates():
        circulation = unary_union([*(s.to_shapely().buffer(1e-6) for s in p.prototype.corridor),
                                   *(z.shape.to_shapely().buffer(1e-6)
                                     for z in p.prototype.core_zones)])
        assert circulation.geom_type == "Polygon", p.spec


def test_the_area_schedule_adds_up_and_keeps_each_flat_types_saleable():
    for p in _plates():
        a = p.account
        assert a.gross_sqm == pytest.approx(a.flats_own_sqm + a.cores_sqm + a.corridor_sqm,
                                            rel=1e-6)
        library_sale = {f.name: f.saleable_sqft for f in LIBRARY.flats}
        assert a.saleable_sqft == pytest.approx(
            sum(library_sale[m.type_id] for m in p.prototype.modules))
        assert a.effective_loading == pytest.approx(
            a.saleable_sqft / SQFT_A_SQM / a.gross_sqm)


def test_a_double_loaded_plate_is_paid_for_by_its_loading_and_a_single_row_is_not():
    for p in _plates():
        if p.spec.loading is Loading.DOUBLE_LOADED:
            assert p.account.shortfall_sqm == 0.0
            assert p.account.effective_loading == pytest.approx(1.22, abs=1e-3)
        else:  # fewer flats share a core and a corridor: more common floor than 22% pays for
            assert p.account.shortfall_sqm > 0
            assert "not raised" in p.account.note()


def test_what_is_assumed_is_always_said():
    for p in _plates():
        assert p.preliminary and all(item in p.preliminary for item in MISSING_STANDARDS)
        assert (GALLERY_UNKNOWN in p.preliminary) == (p.spec.corridor is Corridor.OPEN_GALLERY)
        assert p.prototype.source.startswith(PLATE_SOURCE)
        assert p.account.note() in p.prototype.source


def test_a_spec_the_library_cannot_build_is_refused():
    with pytest.raises(ValueError, match="no \\['4A'\\]"):
        compose_plate(LIBRARY, PlateSpec(Loading.SINGLE_ROW, ("4A",)), reference_own=_own())
    with pytest.raises(ValueError, match="enclosed"):
        compose_plate(LIBRARY, PlateSpec(Loading.DOUBLE_LOADED, ("2A", "2A"), 1,
                                         Corridor.OPEN_GALLERY))
    with pytest.raises(ValueError, match="cores serve"):
        compose_plate(LIBRARY, PlateSpec(Loading.SINGLE_ROW, ("2A",) * 5, 1),
                      reference_own=_own())
    with pytest.raises(ValueError, match="reference_own"):
        compose_plate(LIBRARY, PlateSpec(Loading.SINGLE_ROW, ("2A", "3A")))


def test_the_fit_test_takes_the_region_whole():
    strip = box(0, 0, 40, 15)
    assert fits(strip, 30.0, 14.0) and not fits(strip, 30.0, 16.0)
    assert not fits(strip, 41.0, 14.0)
    slanted = Polygon([(0, 0), (60, 30), (52, 46), (-8, 16)])  # an 18 m wide strip at 26.6 deg
    assert fits(slanted, 40.0, 14.0) and not fits(slanted, 40.0, 19.0)


@cache
def _plates_on(name: str):
    lands = {
        "narrow strip": box(0, 0, 180, 30),
        "wide rectangle": box(0, 0, 200, 120),
        "l-plot": Polygon([(0, 0), (150, 0), (150, 100), (24, 100), (24, 160), (0, 160)]),
        "trapezoid": Polygon([(0, 0), (160, 0), (130, 70), (20, 70)]),
    }
    made = made_up(lands[name], side="S")
    return made, plates_for(made.envelope, LIBRARY, MIX, loading_pct=LOADING_PCT,
                            reference_own=_own())


@pytest.mark.parametrize("name", ["narrow strip", "wide rectangle", "l-plot", "trapezoid"])
def test_every_plate_offered_fits_a_region_of_its_land(name):
    made, plates = _plates_on(name)
    assert plates
    regions = {f"{w.applies_to}: region {n}": r for w in made.envelope.width_profiles
               for n, r in enumerate(w.regions, 1)}
    for p in plates:
        assert p.fits
        for where in p.fits:
            region = regions[where]
            assert min(p.prototype.length_m, p.prototype.depth_m) <= \
                region.max_inscribed_width_m + 1e-6
            assert fits(region.shape.to_shapely(), p.prototype.length_m, p.prototype.depth_m)


def test_no_plate_stands_on_the_plot_before_its_setbacks():
    for name in ("narrow strip", "wide rectangle", "l-plot", "trapezoid"):
        _, plates = _plates_on(name)
        assert not [p for p in plates if any(w.startswith("net plot") for w in p.fits)], name


def test_a_narrow_strip_takes_single_rows_and_only_short_double_loaded_blocks_across_it():
    """The 30 m strip's high-rise land is 16 m wide or less: single rows (13 m deep) along it, both
    corridors; a double-loaded block (24 m deep) only where it is short enough to stand across it.
    The wide plot takes double-loaded blocks along their length."""
    made, narrow = _plates_on("narrow strip")
    high_rise = [w for w in made.envelope.width_profiles if w.applies_to.startswith(("21", "24"))]
    widest = max(r.max_inscribed_width_m for w in high_rise for r in w.regions)
    on_high_rise = [p for p in narrow if any(f.startswith(("21", "24")) for f in p.fits)]
    assert {(p.spec.loading, p.spec.corridor) for p in on_high_rise} >= {
        (Loading.SINGLE_ROW, Corridor.ENCLOSED), (Loading.SINGLE_ROW, Corridor.OPEN_GALLERY)}
    for p in on_high_rise:
        if p.spec.loading is Loading.DOUBLE_LOADED:
            assert min(p.prototype.length_m, p.prototype.depth_m) <= widest + 1e-6
            assert max(p.prototype.length_m, p.prototype.depth_m) > widest  # across the strip
    _, wide = _plates_on("wide rectangle")
    assert {p.spec.flats_per_floor for p in wide if p.spec.loading is Loading.DOUBLE_LOADED} == {
        4, 6, 8, 10, 12}



def test_what_is_said_of_the_core_is_the_core_drawn():
    """A single row's core spans the flats' depth; a double-loaded one the library's core depth
    (once said 8 m across for a single row whose core was 11 m: the words are tested now)."""
    for p in _plates():
        core = p.prototype.core_zones[0].shape.to_shapely()
        x0, y0, x1, y1 = core.bounds
        across = y1 - y0 if p.prototype.length_m >= p.prototype.depth_m else x1 - x0
        [said] = [item for item in p.preliminary if item.startswith("core:")]
        assert f"{across:g} m" in said or f"({across:g} m)" in said, (p.spec, said, across)


def test_no_plate_offered_is_one_of_the_librarys_own_blocks():
    made, _ = _plates_on("wide rectangle")
    families, plates = kit_for(LIBRARY, MIX, made.envelope, loading_pct=LOADING_PCT)
    blocks = {(round(f.length_m, 2), round(f.depth_m, 2), f.cores,
               tuple(sorted(f.per_floor.flats_by_type.items()))) for f in families[:4]}
    assert plates
    for p in plates:
        q = p.prototype
        assert (round(q.length_m, 2), round(q.depth_m, 2), q.cores,
                tuple(sorted(q.per_floor.flats_by_type.items()))) not in blocks, q.id
