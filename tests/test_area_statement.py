import pytest
from pydantic import ValidationError

from siteplan.area_statement import AreaStatement, FloorLine, TowerGroup, render


def _statement():
    return AreaStatement(
        site_area_sqyd=10000,
        open_space_sqft=9000,
        groups=[
            TowerGroup(
                name="TOWER - A, B",
                storeys="STILT + 5 FLOORS",
                common_area_pct=22,
                floors=[
                    FloorLine(label="FIRST", area_sqft=10001),
                    FloorLine(label="TYPICAL", area_sqft=10000, count=4, includes_balconies=True),
                ],
            ),
            TowerGroup(
                name="TOWER - C",
                storeys="STILT + 2 FLOORS",
                floors=[FloorLine(label="TYPICAL", area_sqft=2500, count=2)],
            ),
        ],
    )


def test_loaded_area_is_truncated_like_the_firm_does():
    group = _statement().groups[0]
    assert group.subtotal_sqft == 50001
    # 50,001 x 1.22 = 61,001.22 -> 61,001
    assert group.with_common_area_sqft == 61001


def test_total_and_open_space_share():
    statement = _statement()
    assert statement.total_sqft == 61001 + 6100
    assert statement.open_space_share == pytest.approx(9000 * 0.09290304 / (10000 * 0.83612736))


def test_render_uses_indian_grouping_and_firm_wording():
    text = render(_statement())
    assert "TOTAL SITE AREA: 10,000 SQYDS" in text
    assert "TYPICAL AREA FOR 4 FLOORS: 40,000 SFT (INCLUDING BALCONIES)" in text
    assert "TOTAL AREA: 61,001 SFT (INCLUDING COMMON AREA 22%)" in text
    assert text.endswith("TOTAL AREA OF ALL TOWERS: 67,101 SFT")


def test_rejects_nonsense_input():
    with pytest.raises(ValidationError):
        FloorLine(label="TYPICAL", area_sqft=-5)
    with pytest.raises(ValidationError):
        TowerGroup(name="T", storeys="S", floors=[])
