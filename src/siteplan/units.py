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

# A written number, with Indian or western digit grouping: "22,686", "1,23,456", "8,063.80".
_NUM = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_SQYD = r"(?:SQ\.?\s*YDS?\.?|SQ\.?\s*YARDS?|SQYDS?)"
_SQM = r"(?:SQ\.?\s*M(?:TS|TRS?|ETERS?|ETRES?)?\.?|SQM|M2|M²)(?![A-Z])"

# Matches "3 AC 12.50 GTS", "3 Acres 12.50 Guntas", "3AC-12.50GTS" and, as surveyors write the
# remainder, "1 ACR 39 GTS 85 Sq yds".
_ACRE_GUNTA = re.compile(
    rf"(\d+(?:\.\d+)?)\s*(?:ACRES?|ACR|AC)\b[\s\-]*(\d+(?:\.\d+)?)\s*(?:GUNTAS?|GTS?)\b"
    rf"(?:[\s,+\-]*({_NUM})\s*{_SQYD})?",
    re.IGNORECASE,
)
_SQM_AREA = re.compile(rf"({_NUM})\s*{_SQM}", re.IGNORECASE)
_SQYD_AREA = re.compile(rf"({_NUM})\s*{_SQYD}", re.IGNORECASE)


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


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _acre_gunta_sqm(match: re.Match) -> float:
    sqm = acres_guntas_to_sqm(float(match.group(1)), float(match.group(2)))
    return sqm + (sqyd_to_sqm(_number(match.group(3))) if match.group(3) else 0.0)


def parse_acre_gunta(text: str) -> float | None:
    """Return the area in m² for the first "<n> AC <n> GTS" phrase in text, else None."""
    match = _ACRE_GUNTA.search(text)
    return _acre_gunta_sqm(match) if match else None


def written_areas(text: str) -> list[float]:
    """Every land area written in text, in m²: acres and guntas, square metres, square yards.

    Square feet are left out on purpose: sheets use them for flats and tot-lots, never for the
    land itself, so a flat's "1,190 SFT" can never pass for the site.
    """
    areas = [_acre_gunta_sqm(m) for m in _ACRE_GUNTA.finditer(text)]
    rest = _ACRE_GUNTA.sub(" ", text)
    areas += [_number(m.group(1)) for m in _SQM_AREA.finditer(rest)]
    areas += [sqyd_to_sqm(_number(m.group(1))) for m in _SQYD_AREA.finditer(rest)]
    return areas


def site_area(texts: list[str]) -> float | None:
    """The land area a sheet states: the largest one written on it. A survey also writes the
    small strips it carves off (a road-affected corner of 141 sq yd), never anything larger
    than the land itself."""
    areas = [area for text in texts for area in written_areas(text)]
    return max(areas) if areas else None


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
