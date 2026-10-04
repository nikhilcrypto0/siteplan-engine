"""Prototypes as DXF blocks: one block each, in metres, on clear layers; surviving an ezdxf round
trip; and placed by a tower's own placement. Made-up flats only."""

from collections import Counter

import ezdxf
import pytest
from prototype_helpers import example_kit, place
from shapely.geometry import Polygon
from shapely.ops import unary_union

from siteplan.dxf_entities import open_blocks, polyline_points
from siteplan.prototypes import (
    add_block,
    add_blocks,
    block_name,
    insert_tower,
    new_drawing,
    write_library_dxf,
)
from siteplan.prototypes.draw import CORES, CORRIDOR, FLATS, FOOTPRINT, LABELS, LAYERS, TOWERS

TEST_CLASS = "normative"

EPS = 1e-6  # m², the symmetric difference two shapes may have and still be one


@pytest.fixture(scope="module")
def kit():
    return example_kit()


def _outlines(entities, layer: str) -> list[Polygon]:
    return [Polygon(e.get_points("xy")) for e in entities
            if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == layer]


def _placed_outlines(opened, layer: str) -> list[Polygon]:
    """The polylines of one layer once every block reference is opened out into the drawing."""
    return [Polygon(polyline_points(d.entity)) for d in opened.drawn
            if d.entity.dxftype() == "LWPOLYLINE" and d.layer == layer]


def test_every_prototype_is_one_block_in_metres_on_clear_layers(kit, tmp_path):
    doc = ezdxf.readfile(write_library_dxf(kit, tmp_path / "library.dxf"))
    assert doc.dxfversion == "AC1032"  # ezdxf's R2018
    assert doc.header["$INSUNITS"] == 6  # metres
    assert set(LAYERS) <= {layer.dxf.name for layer in doc.layers}
    for p in kit:
        block = list(doc.blocks.get(block_name(p.id)))
        drawn = Counter(e.dxf.layer for e in block if e.dxftype() == "LWPOLYLINE")
        assert drawn == {FOOTPRINT: 1, FLATS: len(p.modules), CORES: p.cores,
                         CORRIDOR: len(p.corridor)}
        labels = [e.dxf.text for e in block if e.dxftype() == "TEXT" and e.dxf.layer == LABELS]
        assert sorted(labels) == sorted([*(m.type_id for m in p.modules), *["CORE"] * p.cores])


def test_a_block_survives_an_ezdxf_round_trip_unchanged(kit, tmp_path):
    doc = ezdxf.readfile(write_library_dxf(kit, tmp_path / "library.dxf"))
    assert not doc.audit().has_errors
    for p in kit:
        block = list(doc.blocks.get(block_name(p.id)))
        wanted = {FOOTPRINT: [p.footprint], FLATS: [m.shape for m in p.modules],
                  CORES: [z.shape for z in p.core_zones], CORRIDOR: p.corridor}
        for layer, shapes in wanted.items():
            found = _outlines(block, layer)
            assert len(found) == len(shapes)
            for polygon, shape in zip(found, shapes, strict=True):
                assert polygon.symmetric_difference(shape.to_shapely()).area < EPS


@pytest.mark.parametrize("rotation", [0.0, 30.0, 90.0, 137.0, -45.0])
@pytest.mark.parametrize("mirrored", [False, True])
def test_a_placed_block_is_where_the_towers_own_placement_puts_it(kit, tmp_path, rotation,
                                                                  mirrored):
    for p in (kit[0], kit[2], kit[3]):
        placed = place(p, x=412.5, y=-87.25, rotation=rotation, mirrored=mirrored)
        doc = new_drawing()
        add_blocks(doc, [p])
        insert_tower(doc.modelspace(), placed)
        doc.saveas(tmp_path / "site.dxf")
        opened = open_blocks(ezdxf.readfile(tmp_path / "site.dxf").modelspace())
        assert opened.missing_blocks == ()
        footprint = _placed_outlines(opened, FOOTPRINT)
        assert len(footprint) == 1
        assert footprint[0].symmetric_difference(placed.footprint.to_shapely()).area < EPS
        for layer, shapes in ((FLATS, [m.shape for m in p.modules]),
                              (CORES, [z.shape for z in p.core_zones]),
                              (CORRIDOR, p.corridor)):
            found = _placed_outlines(opened, layer)
            assert len(found) == len(shapes)
            for polygon in found:  # each drawn piece is one of the prototype's, placed
                assert min(polygon.symmetric_difference(placed.world(s.to_shapely())).area
                           for s in shapes) < EPS
            total = unary_union([placed.world(s.to_shapely()) for s in shapes])
            assert unary_union(found).symmetric_difference(total).area < EPS


def test_a_tower_needs_its_block_in_the_drawing_first(kit):
    doc = new_drawing()
    with pytest.raises(ValueError, match="no block"):
        insert_tower(doc.modelspace(), place(kit[0]))
    add_block(doc, kit[0])
    insert_tower(doc.modelspace(), place(kit[0]))
    with pytest.raises(ValueError, match="already has a block"):
        add_blocks(doc, [kit[0]])  # a second prototype under one id would be drawn as the first


def test_a_block_name_is_clean_whatever_the_id(kit, tmp_path):
    odd = kit[0].model_copy(update={"id": "single core/small: 4"})
    assert block_name(odd.id) == "PROTO-single_core_small__4"
    doc = new_drawing()
    add_block(doc, odd)
    doc.saveas(tmp_path / "odd.dxf")
    assert block_name(odd.id) in ezdxf.readfile(tmp_path / "odd.dxf").blocks


def test_the_library_drawing_shows_every_block_once_side_by_side(kit, tmp_path):
    doc = ezdxf.readfile(write_library_dxf(kit, tmp_path / "library.dxf"))
    references = [e for e in doc.modelspace() if e.dxftype() == "INSERT"]
    assert sorted(e.dxf.name for e in references) == sorted(block_name(p.id) for p in kit)
    assert all(e.dxf.layer == TOWERS for e in references)
    footprints = _placed_outlines(open_blocks(doc.modelspace()), FOOTPRINT)
    assert len(footprints) == len(kit)
    assert unary_union(footprints).area == pytest.approx(sum(f.area for f in footprints))
    titles = [e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT"]
    assert all(any(p.id in title for title in titles) for p in kit)
