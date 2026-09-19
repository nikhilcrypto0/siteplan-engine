"""Land-area units used on Telangana drawings, with exact conversion factors."""

from __future__ import annotations

import re

SQM_PER_SQYD = 0.83612736  # 0.9144 m squared, exact
SQM_PER_SQFT = 0.09290304  # 0.3048 m squared, exact
SQYD_PER_ACRE = 4840
SQYD_PER_GUNTA = 121
GUNTAS_PER_ACRE = 40
SQM_PER_ACRE = SQYD_PER_ACRE * SQM_PER_SQYD
SQM_PER_GUNTA = SQYD_PER_GUNTA * SQM_PER_SQYD
M_PER_FT = 0.3048

# Matches "3 AC 12.50 GTS", "3 Acres 12.50 Guntas", "3AC-12.50GTS".
_ACRE_GUNTA = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:AC|ACRES?)\b[\s\-]*(\d+(?:\.\d+)?)\s*(?:GTS?|GUNTAS?)\b",
    re.IGNORECASE,
)


def acres_guntas_to_sqm(acres: float, guntas: float = 0.0) -> float:
    return acres * SQM_PER_ACRE + guntas * SQM_PER_GUNTA


def sqm_to_sqyd(sqm: float) -> float:
    return sqm / SQM_PER_SQYD


def sqyd_to_sqm(sqyd: float) -> float:
    return sqyd * SQM_PER_SQYD


def sqm_to_sqft(sqm: float) -> float:
    return sqm / SQM_PER_SQFT


def sqft_to_sqm(sqft: float) -> float:
    return sqft * SQM_PER_SQFT


def ft_to_m(feet: float) -> float:
    return feet * M_PER_FT


def parse_acre_gunta(text: str) -> float | None:
    """Return the area in m² for the first "<n> AC <n> GTS" phrase in text, else None."""
    match = _ACRE_GUNTA.search(text)
    if match is None:
        return None
    return acres_guntas_to_sqm(float(match.group(1)), float(match.group(2)))


def format_acre_gunta(sqm: float) -> str:
    """The way Telangana drawings write land area: 13405.2 m² -> '3 AC 12.50 GTS'."""
    guntas_total = round(sqm / SQM_PER_GUNTA, 2)
    acres = int(guntas_total // GUNTAS_PER_ACRE)
    return f"{acres} AC {guntas_total - acres * GUNTAS_PER_ACRE:.2f} GTS"


def format_indian(value: float) -> str:
    """Format a whole number with Indian digit grouping: 612345 -> '6,12,345'."""
    whole = int(value)
    sign = "-" if whole < 0 else ""
    digits = str(abs(whole))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups) + "," + tail
