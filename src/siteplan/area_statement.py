"""The area statement block, in the firm's format and with its rounding.

Rounding: the firm's statements drop the fraction after adding common area (a loaded
total of x.64 sft is printed as x), so loaded totals are truncated to whole square feet.
Confirm with the firm before relying on it for a new project.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt

from siteplan.units import SQM_PER_SQFT, format_indian, sqyd_to_sqm


class FloorLine(BaseModel):
    label: str = Field(description="How the floor is named in the statement, e.g. 'TYPICAL'.")
    area_sqft: PositiveFloat = Field(description="Area of one such floor, all towers in the group.")
    count: PositiveInt = 1
    includes_balconies: bool = False


class TowerGroup(BaseModel):
    name: str = Field(description="e.g. 'TOWER - 1, 2, 3, 4'")
    storeys: str = Field(description="e.g. 'STILT + 8 FLOORS'")
    floors: list[FloorLine] = Field(min_length=1)
    common_area_pct: float = Field(22.0, ge=0, le=100)

    @property
    def subtotal_sqft(self) -> float:
        return sum(f.area_sqft * f.count for f in self.floors)

    @property
    def with_common_area_sqft(self) -> int:
        return math.floor(self.subtotal_sqft * (1 + self.common_area_pct / 100) + 1e-9)


class AreaStatement(BaseModel):
    site_area_sqyd: PositiveFloat
    open_space_sqft: PositiveFloat | None = None
    groups: list[TowerGroup] = Field(min_length=1)

    @property
    def total_sqft(self) -> int:
        return sum(g.with_common_area_sqft for g in self.groups)

    @property
    def open_space_share(self) -> float | None:
        if self.open_space_sqft is None:
            return None
        return self.open_space_sqft * SQM_PER_SQFT / sqyd_to_sqm(self.site_area_sqyd)


def _sft(value: float) -> str:
    return f"{format_indian(value)} SFT"


def render(statement: AreaStatement) -> str:
    lines = ["AREA STATEMENT:", f"TOTAL SITE AREA: {format_indian(statement.site_area_sqyd)} SQYDS"]
    if statement.open_space_sqft is not None:
        share = statement.open_space_share or 0.0
        lines.append(
            f"TOT-LOT AREA: {format_indian(statement.open_space_sqft)} SQFT "
            f"({share * 100:.2f}% OF SITE AREA)"
        )
    for group in statement.groups:
        lines += ["", f"{group.name} ({group.storeys})"]
        for floor in group.floors:
            balconies = " (INCLUDING BALCONIES)" if floor.includes_balconies else ""
            lines.append(f"{floor.label} FLOOR AREA: {_sft(floor.area_sqft)}{balconies}")
            if floor.count > 1:
                lines.append(
                    f"{floor.label} AREA FOR {floor.count} FLOORS: "
                    f"{_sft(floor.area_sqft * floor.count)}{balconies}"
                )
        lines.append(f"TOTAL AREA: {_sft(group.subtotal_sqft)}")
        lines.append(
            f"TOTAL AREA: {_sft(group.with_common_area_sqft)} "
            f"(INCLUDING COMMON AREA {group.common_area_pct:g}%)"
        )
    lines += ["", f"TOTAL AREA OF ALL TOWERS: {_sft(statement.total_sqft)}"]
    return "\n".join(lines)
