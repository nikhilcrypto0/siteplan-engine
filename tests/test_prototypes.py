"""Tower prototypes composed from a flat library: the four families, what a prototype may hold,
the library file and its loader, and placement. Made-up flats only (examples/ and below)."""

import ast
import json
import math
import re
from collections import Counter
from pathlib import Path

import pytest
from prototype_helpers import (
    EXAMPLE_FLATS,
    EXAMPLES,
    MIX,
    ROOT,
    example_kit,
    example_library,
    parts,
    place,
)
from pydantic import ValidationError
from shapely import affinity
from shapely.ops import unary_union

from siteplan import towers
from siteplan.contracts import TowerPrototype
from siteplan.contracts.common import Shape, SourceKind
from siteplan.contracts.prototype import PrototypeFamily, PrototypeHeights, Stretch
from siteplan.flat_import import BUILT_UP_FROM_CARPET, FlatPlan, Room, to_library
from siteplan.library import FlatLibrary
from siteplan.prototypes import (
    FAMILY_PLANS,
    compose_library,
    compose_prototype,
    dumps,
    effective_heights,
    load_library,
    problems,
    save_library,
    servable_families,
)
from siteplan.prototypes import compose as compose_module
from siteplan.prototypes.__main__ import main

TEST_CLASS = "normative"

PACKAGE = ROOT / "src" / "siteplan" / "prototypes"
EXAMPLE_PROTOTYPES = EXAMPLES / "prototypes.example.json"
FAMILIES = [PrototypeFamily.SINGLE_CORE_SMALL, PrototypeFamily.SINGLE_CORE,
            PrototypeFamily.TWO_CORE_MEDIUM, PrototypeFamily.TWO_CORE_LARGE]
BALANCE = 0.02  # footprint = modules + cores + corridor, within this share
# What a firm's own floor plan gives flat_import: made-up rooms, sizes in mm as CAD labels them.
TWO_BHK = [("KITCHEN 3000X2500", 2.0, 2.0), ("LIVING ROOM 4000X3500", 6.0, 2.0),
           ("MASTER BEDROOM 4000X3500", 2.0, 6.0), ("BED ROOM 3000X3500", 6.0, 6.0),
           ("TOILET 1500X2500", 9.0, 2.0)]
THREE_BHK = [("KITCHEN 3000X3000", 2.0, 2.0), ("LIVING ROOM 4500X3500", 6.0, 2.0),
             ("MASTER BEDROOM 4300X3500", 2.0, 6.0), ("BED ROOM 3400X3800", 6.0, 6.0),
             ("BEDROOM 3400X3600", 10.0, 6.0), ("TOILET 1500X2500", 10.0, 2.0)]


@pytest.fixture(scope="module")
def library() -> FlatLibrary:
    return example_library()


@pytest.fixture(scope="module")
def kit() -> list[TowerPrototype]:
    return example_kit()


def _firm_library() -> FlatLibrary:
    """A library made the way the firm's own floor plan makes one (flat_import)."""
    def flat(origin: float, rooms) -> FlatPlan:
        built = []
        for name, x, y in rooms:
            width, depth = (int(n) / 1000 for n in re.search(r"(\d+)X(\d+)", name).groups())
            built.append(Room(name, origin + x, y, width, depth))
        return FlatPlan(tuple(built))

    return to_library([flat(0.0, TWO_BHK), flat(40.0, TWO_BHK), flat(80.0, THREE_BHK),
                       flat(120.0, THREE_BHK)])


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


# ---------------------------------------------------------------- the four families


def test_the_kit_has_four_families_of_about_4_6_8_and_12_flats(kit):
    assert [p.family for p in kit] == FAMILIES
    assert [p.per_floor.flats for p in kit] == [4, 6, 8, 12]
    assert [p.cores for p in kit] == [1, 1, 2, 2]
    assert kit[-1].per_floor.flats >= 10  # "two-core large" is 10 or more
    assert [p.per_floor.flats for p in kit] == [FAMILY_PLANS[f].flats_per_floor for f in FAMILIES]
    assert len({p.id for p in kit}) == 4


def test_a_prototype_is_a_double_loaded_slab_with_cores_across_the_full_depth(kit, library):
    flat_types = {f.name: f for f in library.flats}
    for p in kit:
        footprint = p.footprint.to_shapely()
        minx, miny, maxx, maxy = footprint.bounds
        assert (maxx - minx, maxy - miny) == pytest.approx((p.length_m, p.depth_m))
        assert p.depth_m == pytest.approx(library.tower_depth_m)
        assert p.length_m >= p.depth_m  # long axis along x
        north = [m for m in p.modules if m.shape.to_shapely().centroid.y > 0]
        south = [m for m in p.modules if m.shape.to_shapely().centroid.y < 0]
        assert len(north) == len(south) == len(p.modules) / 2
        for m in p.modules:  # each flat is the library's, at its frontage and depth
            minx, miny, maxx, maxy = m.shape.to_shapely().bounds
            flat = flat_types[m.type_id]
            assert (maxx - minx, maxy - miny) == pytest.approx((flat.width_m, flat.depth_m))
            assert m.category == flat.bhk and m.saleable_sqft == flat.saleable_sqft
        for a, b in zip(north, south, strict=True):  # the same flat stands opposite itself
            assert a.type_id == b.type_id
            ends = (a.shape.to_shapely().bounds[::2], b.shape.to_shapely().bounds[::2])
            assert ends[0] == pytest.approx(ends[1])
        for zone in p.core_zones:  # a core spans the whole depth, at the library's width
            minx, miny, maxx, maxy = zone.shape.to_shapely().bounds
            assert (maxx - minx, maxy - miny) == pytest.approx(
                (library.core_width_m, library.tower_depth_m))
        for piece in p.corridor:
            assert piece.to_shapely().bounds[3] - piece.to_shapely().bounds[1] == pytest.approx(
                library.corridor_width_m)
        assert p.length_m == pytest.approx(
            sum(m.shape.to_shapely().bounds[2] - m.shape.to_shapely().bounds[0] for m in north)
            + p.cores * library.core_width_m)


def test_a_block_is_laid_out_the_way_todays_towers_are(library):
    """The generator's own towers (towers.build_tower) put the core after the first half of each
    group of flats; a prototype of the same flats is the same drawing, turned to run along x."""
    for family, plan in FAMILY_PLANS.items():
        served = library.model_copy(
            update={"flats_per_core_per_side": plan.flats_per_core_per_side})
        prototype = compose_prototype(served, family, MIX)
        flats = compose_module.pick_flats(served, MIX, plan.flats_per_side)
        old = towers.build_tower("T", 0.0, 0.0, flats, served, alpha=0)
        # today's tower runs along y; turn it to run along x and centre it, as a prototype is
        centred = [affinity.translate(affinity.affine_transform(s, [0, 1, 1, 0, 0, 0]),
                                      -old.length_m / 2, -old.width_m / 2)
                   for s in (*old.flat_outlines, *old.cores)]
        outlines, cores = centred[:len(old.flat_outlines)], centred[len(old.flat_outlines):]
        assert len(prototype.core_zones) == len(cores)
        for zone in prototype.core_zones:
            assert min(zone.shape.to_shapely().symmetric_difference(c).area
                       for c in cores) < 1e-4
        for module in prototype.modules:
            flat_at = [i for i, o in enumerate(outlines)
                       if module.shape.to_shapely().symmetric_difference(o).area < 1e-4]
            assert len(flat_at) == 1
            assert old.flats_per_side[flat_at[0] // 2].name == module.type_id


def test_the_footprint_is_the_flats_the_cores_and_the_corridor(kit):
    for p in kit:
        drawn = parts(p)
        footprint = p.footprint.to_shapely()
        assert abs(footprint.area - sum(s.area for s in drawn)) <= BALANCE * footprint.area
        assert unary_union(drawn).area == pytest.approx(sum(s.area for s in drawn))  # no overlap
        assert footprint.buffer(1e-6).contains(unary_union(drawn))
        assert problems(p) == []


def test_per_floor_numbers_come_from_the_modules_and_the_saleable_from_nothing_else(kit, library):
    for p in kit:
        f = p.per_floor
        footprint = p.footprint.to_shapely().area
        own = sum(m.shape.area_sqm for m in p.modules)
        assert f.flats == len(p.modules)
        assert f.flats_by_type == dict(Counter(m.category for m in p.modules))
        assert f.gross_floor_sqm == pytest.approx(footprint)
        assert f.flats_own_sqm == pytest.approx(own)
        assert f.common_core_sqm == pytest.approx(footprint - own)
        assert f.saleable_sqft == pytest.approx(sum(m.saleable_sqft for m in p.modules))
        # not the plate times a loading: the sum of what each flat sells for
        library_sale = {x.name: x.saleable_sqft for x in library.flats}
        assert f.saleable_sqft == pytest.approx(sum(library_sale[m.type_id]
                                                    for m in p.modules))
        wrong = p.model_dump(mode="json")
        wrong["per_floor"]["saleable_sqft"] += 100
        with pytest.raises(ValidationError, match="saleable_sqft"):
            TowerPrototype.model_validate(wrong)


def test_every_prototype_round_trips_through_json_unchanged(kit, tmp_path):
    for p in kit:
        again = TowerPrototype.model_validate_json(p.model_dump_json())
        assert again == p
        assert json.loads(again.model_dump_json()) == json.loads(p.model_dump_json())
    save_library(kit, tmp_path / "kit.json")
    assert load_library(tmp_path / "kit.json") == kit


def test_the_modules_stand_inside_the_footprint_without_touching_one_another(kit):
    for p in kit:
        footprint = p.footprint.to_shapely()
        modules = [m.shape.to_shapely() for m in p.modules]
        assert all(footprint.buffer(1e-6).contains(m) for m in modules)
        assert unary_union(modules).area == pytest.approx(sum(m.area for m in modules))
        ids = [m.id for m in p.modules]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------- the unit mix


def test_a_single_category_mix_gives_blocks_of_that_category_alone(library):
    for category in ("2BHK", "3BHK"):
        for p in compose_library(library, {category: 1.0}):
            assert set(p.per_floor.flats_by_type) == {category}


def test_the_mix_asked_for_is_followed_as_closely_as_the_blocks_allow(kit):
    for p in kit:
        share_3bhk = p.per_floor.flats_by_type.get("3BHK", 0) / p.per_floor.flats
        # four flats a floor cannot do better than half and half
        assert abs(share_3bhk - MIX["3BHK"]) <= 0.2 + 1e-9
        if p.per_floor.flats >= 6:
            assert abs(share_3bhk - MIX["3BHK"]) <= 0.05 + 1e-9
    both = {c for p in kit for c in p.per_floor.flats_by_type}
    assert both == {"2BHK", "3BHK"}


def test_with_no_mix_asked_every_category_gets_an_even_share(library):
    large = compose_prototype(library, PrototypeFamily.TWO_CORE_LARGE)
    assert large.per_floor.flats_by_type == {"2BHK": 6, "3BHK": 6}


def test_a_mix_the_library_cannot_serve_is_refused(library):
    with pytest.raises(ValueError, match="4BHK"):
        compose_library(library, {"4BHK": 1.0})
    with pytest.raises(ValueError, match="add up to 1"):
        compose_library(library, {"2BHK": 0.7, "3BHK": 0.7})


# ---------------------------------------------------------------- whose library it is


def test_a_kit_from_the_example_flats_is_an_engine_default_and_says_so(kit):
    assert {p.source_kind for p in kit} == {SourceKind.ENGINE_DEFAULT}
    assert all("EXAMPLE sizes only" in p.source for p in kit)  # the library's own caveat travels


def test_a_kit_from_the_firms_own_library_at_run_time_is_the_firms_standard():
    firm = _firm_library()
    assert firm.flats[0].carpet_sqft is not None  # flat_import keeps what the plan knows
    kit = compose_library(firm, MIX, source_kind=SourceKind.FIRM_STANDARD)
    assert [p.family for p in kit] == FAMILIES
    flat_types = {f.name: f for f in firm.flats}
    for p in kit:
        assert p.source_kind is SourceKind.FIRM_STANDARD
        assert problems(p) == []
        assert p.depth_m == pytest.approx(firm.tower_depth_m)
        for m in p.modules:
            flat = flat_types[m.type_id]
            assert (m.carpet_sqft, m.built_up_sqft, m.saleable_sqft) == (
                flat.carpet_sqft, flat.built_up_sqft, flat.saleable_sqft)
            assert m.carpet_sqft < m.built_up_sqft < m.saleable_sqft
            assert m.built_up_sqft / m.carpet_sqft == pytest.approx(BUILT_UP_FROM_CARPET, abs=0.01)


def test_only_the_engines_default_or_the_firms_standard_can_be_a_composed_source(library):
    for kind in (SourceKind.SURVEY, SourceKind.ARCHITECT, SourceKind.FIRM_FINISHED_PLAN):
        with pytest.raises(ValueError, match="engine's default or the firm's standard"):
            compose_prototype(library, PrototypeFamily.SINGLE_CORE, MIX, source_kind=kind)


def test_a_family_the_librarys_cores_cannot_serve_is_not_composed(library):
    small_cores = library.model_copy(update={"flats_per_core_per_side": 2})
    assert servable_families(small_cores) == [PrototypeFamily.SINGLE_CORE_SMALL,
                                              PrototypeFamily.TWO_CORE_MEDIUM]
    assert [p.family for p in compose_library(small_cores, MIX)] == servable_families(small_cores)
    with pytest.raises(ValueError, match="cores serve 2"):
        compose_prototype(small_cores, PrototypeFamily.SINGLE_CORE, MIX)
    with pytest.raises(ValueError, match="legacy rectangle"):
        compose_prototype(library, PrototypeFamily.LEGACY_RECTANGLE, MIX)
    one_flat_cores = library.model_copy(update={"flats_per_core_per_side": 1})
    assert servable_families(one_flat_cores) == []
    with pytest.raises(ValueError, match="no family can be composed"):
        compose_library(one_flat_cores, MIX)  # a kit of nothing is a refusal, not an empty answer


# ---------------------------------------------------------------- what a prototype may not hold


def test_a_prototype_holds_no_legal_value_and_no_floor_count(kit):
    forbidden = {"floors", "floors_above_stilt", "floor_count", "max_floors", "setback_m", "gap_m",
                 "min_road_m", "min_open_space_m", "clause", "height_m", "rule_height_m",
                 "physical_height_m", "road_m"}
    schema = {k for k in _keys(TowerPrototype.model_json_schema())}
    assert not (schema & forbidden)
    for p in kit:
        assert not (_keys(p.model_dump(mode="json")) & forbidden)
        with pytest.raises(ValidationError, match="Extra inputs"):
            TowerPrototype.model_validate({**p.model_dump(mode="json"), "floors_above_stilt": 8})
        with pytest.raises(ValidationError, match="Extra inputs"):
            TowerPrototype.model_validate({**p.model_dump(mode="json"), "setback_m": 9.0})


def test_composed_prototypes_set_no_heights_so_the_briefs_firm_standards_apply(kit):
    assert all(p.heights == PrototypeHeights() for p in kit)
    assert all(effective_heights(p, stilt_height_m=3.0, floor_to_floor_m=3.15) == (3.0, 3.15)
               for p in kit)


def test_a_prototype_overrides_the_briefs_heights_only_where_it_sets_its_own(kit):
    own = kit[0].model_copy(update={"heights": PrototypeHeights(floor_to_floor_m=3.4)})
    assert effective_heights(own, stilt_height_m=3.0, floor_to_floor_m=3.15) == (3.0, 3.4)
    both = kit[0].model_copy(update={"heights": PrototypeHeights(stilt_height_m=4.5,
                                                                 floor_to_floor_m=3.4)})
    assert effective_heights(both, stilt_height_m=3.0, floor_to_floor_m=3.15) == (4.5, 3.4)
    stilt_only = kit[0].model_copy(update={"heights": PrototypeHeights(stilt_height_m=4.5)})
    assert effective_heights(stilt_only, stilt_height_m=3.0, floor_to_floor_m=3.15) == (4.5, 3.15)
    with pytest.raises(ValidationError):
        PrototypeHeights(floor_to_floor_m=0)  # a set height is a real one


# ---------------------------------------------------------------- the library file


def test_the_committed_example_is_what_the_command_makes(tmp_path, capsys):
    out = tmp_path / "prototypes.json"
    assert main([str(EXAMPLE_FLATS), "--mix", "2BHK=0.7,3BHK=0.3", "--out", str(out)]) == 0
    assert out.read_text() == EXAMPLE_PROTOTYPES.read_text(), (
        "regenerate: uv run python -m siteplan.prototypes examples/flat_library.example.json "
        "--mix 2BHK=0.7,3BHK=0.3 --out examples/prototypes.example.json")
    assert "TWO_CORE_LARGE, 12 flats a floor" in capsys.readouterr().out


def test_the_example_library_loads_validated_and_is_the_four_families(kit):
    loaded = load_library(EXAMPLE_PROTOTYPES)
    assert loaded == kit
    assert {p.source_kind for p in loaded} == {SourceKind.ENGINE_DEFAULT}
    assert dumps(loaded) == EXAMPLE_PROTOTYPES.read_text()


def test_the_command_reads_the_mix_and_whose_library_it_is(tmp_path, capsys):
    out = tmp_path / "firm.json"
    assert main([str(EXAMPLE_FLATS), "--mix", "2BHK=1", "--source-kind", "FIRM_STANDARD",
                 "--out", str(out), "--dxf", str(tmp_path / "blocks.dxf")]) == 0
    assert {p.source_kind for p in load_library(out)} == {SourceKind.FIRM_STANDARD}
    assert (tmp_path / "blocks.dxf").is_file()
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main([str(EXAMPLE_FLATS), "--mix", "lots of 2BHK"])
    with pytest.raises(SystemExit):
        main([str(EXAMPLE_FLATS), "--source-kind", "SURVEY"])


def _broken(kit, change) -> list:
    data = [p.model_dump(mode="json") for p in kit[:2]]
    change(data)
    return data


def _write(tmp_path, data) -> Path:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    return path


def _move_a_flat_out(data):
    ring = data[0]["modules"][0]["shape"]["outer"]
    data[0]["modules"][0]["shape"]["outer"] = [[x + 40, y] for x, y in ring]


def _stack_two_flats(data):
    data[0]["modules"][1]["shape"] = data[0]["modules"][0]["shape"]


def _lose_the_corridor(data):
    data[0]["corridor"] = []


def _shift_off_the_origin(data):
    for shape in [data[0]["footprint"], *(m["shape"] for m in data[0]["modules"]),
                  *(z["shape"] for z in data[0]["core_zones"]), *data[0]["corridor"]]:
        shape["outer"] = [[x + 5, y] for x, y in shape["outer"]]


def _turn_the_long_axis(data):
    for shape in [data[0]["footprint"], *(m["shape"] for m in data[0]["modules"]),
                  *(z["shape"] for z in data[0]["core_zones"]), *data[0]["corridor"]]:
        shape["outer"] = [[y, x] for x, y in shape["outer"]]


@pytest.mark.parametrize("change, message", [
    (lambda d: d[1].update(id=d[0]["id"]), "used more than once"),
    (lambda d: d[0].update(id="bad id/1"), "letters, digits"),
    (_move_a_flat_out, "outside the footprint"),
    (_stack_two_flats, "overlap"),
    (_lose_the_corridor, "more than 2% apart"),
    (_shift_off_the_origin, "not centred on the origin"),
    (_turn_the_long_axis, "long axis is not along x"),
    (lambda d: d[0].update(length_m=d[0]["length_m"] + 3), "length_m x depth_m say"),
    (lambda d: d[0].update(stretch={"module_pitch_m": 10, "min_modules": 5, "max_modules": 3}),
     "stretch runs from 5"),
    (lambda d: d[0].update(floors_above_stilt=8), "Extra inputs"),
], ids=["duplicate id", "bad id", "flat outside", "flats overlap", "no corridor", "off origin",
        "long axis on y", "wrong length", "stretch backwards", "a floor count"])
def test_the_loader_refuses_a_file_that_does_not_close_and_says_why(tmp_path, kit, change,
                                                                    message):
    with pytest.raises(ValueError, match=message):
        load_library(_write(tmp_path, _broken(kit, change)))


def test_the_loader_refuses_what_is_not_a_list_of_prototypes(tmp_path):
    for text in ("{}", "[]", "3"):
        (tmp_path / "x.json").write_text(text)
        with pytest.raises(ValueError, match="JSON list of at least one prototype"):
            load_library(tmp_path / "x.json")
    (tmp_path / "x.json").write_text("[{")
    with pytest.raises(ValueError, match=r"x\.json: not valid JSON"):
        load_library(tmp_path / "x.json")


def test_a_stretch_the_right_way_round_is_accepted(tmp_path, kit):
    """A firm's own prototype may be longer or shorter by whole modules (the contract's Stretch)."""
    stretched = kit[-1].model_copy(update={"stretch": Stretch(
        module_pitch_m=10.0, min_modules=5, max_modules=8)})
    assert problems(stretched) == []
    save_library([stretched], tmp_path / "s.json")
    assert load_library(tmp_path / "s.json")[0].stretch == stretched.stretch


# ---------------------------------------------------------------- placement


@pytest.mark.parametrize("rotation", [0.0, 17.5, 90.0, 135.0, 200.0, -45.0])
@pytest.mark.parametrize("mirrored", [False, True])
def test_a_rotated_and_mirrored_prototype_is_still_the_same_building(kit, rotation, mirrored):
    for p in kit:
        placed = place(p, x=412.5, y=-87.25, rotation=rotation, mirrored=mirrored)
        footprint = placed.world(p.footprint.to_shapely())
        modules = [placed.world(m.shape.to_shapely()) for m in p.modules]
        assert footprint.area == pytest.approx(p.footprint.area_sqm)
        assert all(footprint.buffer(1e-6).contains(m) for m in modules)
        assert unary_union(modules).area == pytest.approx(sum(m.area for m in modules))
        assert (footprint.centroid.x, footprint.centroid.y) == pytest.approx((412.5, -87.25))
        assert Shape.from_shapely(footprint) == placed.footprint
        assert sum(m.area for m in modules) == pytest.approx(p.per_floor.flats_own_sqm)


@pytest.mark.parametrize("rotation", [0.0, 30.0, 90.0, 215.0])
@pytest.mark.parametrize("mirrored", [False, True])
def test_a_placement_mirrors_then_turns_anticlockwise_then_moves(kit, rotation, mirrored):
    """The meaning of a placement, worked out by hand for one corner of one flat."""
    p = kit[2]
    corner = p.modules[0].shape.outer[0]
    x, y = (-corner[0] if mirrored else corner[0]), corner[1]  # mirrored: x -> -x
    c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    expected = (c * x - s * y + 100.0, s * x + c * y + 50.0)  # turned anticlockwise, then moved
    placed = place(p, x=100.0, y=50.0, rotation=rotation, mirrored=mirrored)
    got = placed.world(p.modules[0].shape.to_shapely())
    assert min(math.dist(expected, point) for point in got.exterior.coords) < 1e-9


def test_mirroring_swaps_the_ends_of_a_block(kit):
    p = kit[2]  # two cores, its ends differ
    plain = place(p).world(p.modules[0].shape.to_shapely()).centroid
    mirror = place(p, mirrored=True).world(p.modules[0].shape.to_shapely()).centroid
    assert (mirror.x, mirror.y) == pytest.approx((-plain.x, plain.y))


def test_the_prototype_package_imports_nothing_from_the_generator():
    """The generator (towers, layout) imports the prototypes, never the other way round."""
    allowed = ("siteplan.contracts", "siteplan.library", "siteplan.prototypes")
    for path in sorted(PACKAGE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module
                     else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                assert not name.startswith("siteplan") or name.startswith(allowed), (
                    f"{path.name} imports {name}")


def test_the_generator_gets_its_mix_rule_from_the_prototype_composer():
    assert towers.MixTracker is compose_module.MixTracker
