"""Reading a firm's floor-plan DXF into a flat library.

The fixture is made up: client drawings never enter git. It mimics what the firm's own file
does, which is to write each room's size into its label and nothing else machine-readable.
"""

import re

import ezdxf
import pytest

from siteplan.flat_import import group_into_flats, read_rooms, to_library

# One 2BHK, twice (a type has to repeat), and a 3BHK, twice. Sizes in mm, as CAD draws them.
TWO_BHK = [
    ("KITCHEN 3000X2500", 2.0, 2.0),
    ("LIVING ROOM 4000X3500", 6.0, 2.0),
    ("MASTER BEDROOM 4000X3500", 2.0, 6.0),
    ("BED ROOM 3000X3500", 6.0, 6.0),
    ("TOILET 1500X2500", 9.0, 2.0),
]
THREE_BHK = [
    ("KITCHEN 3000X3000", 2.0, 2.0),
    ("LIVING ROOM 4500X3500", 6.0, 2.0),
    ("MASTER BEDROOM 4300X3500", 2.0, 6.0),
    ("BED ROOM 3400X3800", 6.0, 6.0),
    ("BEDROOM 3400X3600", 10.0, 6.0),
    ("TOILET 1500X2500", 10.0, 2.0),
]
def _size(label):
    w, d = re.search(r"(\d{3,5})X(\d{3,5})", label).groups()
    return int(w) / 1000, int(d) / 1000


NOT_ROOMS = [("OPEN TO SKY 3000X3000", 40.0, 40.0), ("STAIRCASE 2000X4000", 44.0, 40.0)]


def _draw(path, flats, noise=NOT_ROOMS, layer="A-TEXT"):
    doc = ezdxf.new()
    doc.layers.add(layer)
    msp = doc.modelspace()
    for origin_x, rooms in flats:
        for name, x, y in rooms:
            msp.add_text(name, dxfattribs={"layer": layer}).set_placement(
                ((origin_x + x) * 1000, y * 1000)
            )
    for name, x, y in noise:
        msp.add_text(name, dxfattribs={"layer": layer}).set_placement((x * 1000, y * 1000))
    doc.saveas(path)
    return path


@pytest.fixture
def plan(tmp_path):
    return _draw(tmp_path / "floors.dxf",
                 [(0.0, TWO_BHK), (40.0, TWO_BHK), (80.0, THREE_BHK), (120.0, THREE_BHK)])


def test_rooms_come_back_with_the_size_the_architect_wrote(plan):
    rooms = read_rooms(plan)
    kitchen = next(r for r in rooms if r.is_kitchen)
    assert (kitchen.width_m, kitchen.depth_m) == (3.0, 2.5)
    assert kitchen.area_sqm == pytest.approx(7.5)


def test_what_is_not_a_room_inside_a_flat_is_left_out(plan):
    names = {r.name for r in read_rooms(plan)}
    assert not any("OPEN TO SKY" in n or "STAIRCASE" in n for n in names)


def test_a_flat_is_found_for_every_kitchen(plan):
    flats = group_into_flats(read_rooms(plan))
    assert len(flats) == 4
    assert all(sum(1 for r in f.rooms if r.is_kitchen) == 1 for f in flats)
    assert sorted(f.category for f in flats) == ["2BHK", "2BHK", "3BHK", "3BHK"]


def test_the_library_keeps_the_areas_and_one_depth(plan):
    library = to_library(group_into_flats(read_rooms(plan)), common_area_pct=22.0)
    assert {f.bhk for f in library.flats} == {"2BHK", "3BHK"}
    assert len({f.depth_m for f in library.flats}) == 1  # v0 assembles towers from one depth

    two = next(f for f in library.flats if f.bhk == "2BHK")
    carpet_sqm = sum(_size(name)[0] * _size(name)[1] for name, _, _ in TWO_BHK)
    assert two.saleable_sqft == pytest.approx(carpet_sqm * 10.7639 * 1.22, rel=0.01)
    # The frontage follows the area at that depth, with an allowance for the walls.
    assert two.width_m * two.depth_m > carpet_sqm


def test_a_type_that_never_repeats_is_not_a_standard(tmp_path):
    """One-offs are corner units or misreads, not something the firm builds again."""
    one_off = _draw(tmp_path / "one.dxf", [(0.0, TWO_BHK), (40.0, TWO_BHK), (80.0, THREE_BHK)])
    library = to_library(group_into_flats(read_rooms(one_off)))
    assert {f.bhk for f in library.flats} == {"2BHK"}


def test_a_grouping_that_swallowed_a_neighbour_room_is_not_used(tmp_path):
    """Four bedrooms sharing one small kitchen's floor means rooms were pulled in."""
    cramped = [("KITCHEN 2000X2000", 2.0, 2.0)] + [
        ("BED ROOM 2000X2000", 2.0 + i, 4.0) for i in range(4)
    ]
    path = _draw(tmp_path / "cramped.dxf", [(0.0, cramped), (40.0, cramped),
                                            (80.0, TWO_BHK), (120.0, TWO_BHK)])
    flats = group_into_flats(read_rooms(path))
    assert any(not f.plausible for f in flats)
    assert {f.bhk for f in to_library(flats).flats} == {"2BHK"}
