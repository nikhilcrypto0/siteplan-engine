"""Sanctioned permits as tests of our Table III (2026-10-19): a rule is right only if every
sanctioned scheme passes it.

A Table III case (fixtures/cases/*.table3.json, gitignored: the permits are a private reference) is
a building below 21 m from a sanctioned permit that prints its plot, height and minimum setbacks
but carries no drawing. It is held to the Table III lookup the validator and the optimizer make
(`HeightRules.band_for_block`, its row by plot size, its line by the height above the stilt,
rule 5(c)), resolved on a made-up square site of the permit's plot size: the band must permit the
height, the front must meet the Building Line in some road column the permit allows (a permit
that prints no road is tried at every column) and the rear and the sides the band's setback. A
disagreement the case does not list fails, and so does a listed one that stops disagreeing: that
is a rule fixed, to be recorded. The legacy checker (`siteplan cases`) does not encode Table III.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from search_support import made_up
from shapely.geometry import box

from siteplan.contracts.resolved_rules import Eligibility

TEST_CLASS = "normative"
CASES = sorted((Path(__file__).parent.parent / "fixtures" / "cases").glob("*.table3.json"))
# One road in each of Table III's road columns (up to 12 m, 12-18, 18-24, 24-30, above 30), in
# the feet a survey gives them: 9.1, 15.2, 21.3, 27.4 and 33.5 m.
ROAD_COLUMNS_FT = (30, 50, 70, 90, 110)
STILT_M = 2.5  # rule 5(c)'s least stilt: Table III's line is read above it, so it never decides
FT_M = 0.3048

pytestmark = pytest.mark.skipif(not CASES, reason="no sanctioned Table III cases in fixtures/")


def review(case: dict) -> tuple[dict[str, str], list[float]]:
    """What our Table III says of the case: the disagreements by name (`height`, `front`, `rear and
    sides`) with what it asks, and the road columns (in metres) whose figures the permit meets."""
    side = math.sqrt(case["net_sqm"])
    roads = ([case["road_m"] / FT_M] if case.get("road_m") else ROAD_COLUMNS_FT)
    set_ = case["setbacks_m"]
    rest = min(set_["rear"], set_["side_1"], set_["side_2"])
    seen: dict[str, list[str]] = {"height": [], "front": [], "rear and sides": []}
    fits = []
    for road_ft in roads:
        rules = made_up(box(0, 0, side, side), road_ft=road_ft).rules
        band = rules.height.band_for_block(case["height_m"], STILT_M, stilt_counted=False)
        road = f"a {road_ft * FT_M:.1f} m road"
        if band is None or rules.height.band_permission(band) is not Eligibility.ALLOWED:
            seen["height"].append(f"{case['height_m']} m not permitted beside {road}")
            continue
        front = band.front_setback_m if band.front_setback_m is not None else band.setback_m
        ok_front = set_["front"] + 1e-9 >= front
        ok_rest = rest + 1e-9 >= band.setback_m
        if not ok_front:
            seen["front"].append(f"{front:g} m beside {road}")
        if not ok_rest:
            seen["rear and sides"].append(f"{band.setback_m:g} m")
        if ok_front and ok_rest:
            fits.append(round(road_ft * FT_M, 1))
    found = {name: "; ".join(dict.fromkeys(asked)) for name, asked in seen.items()
             if len(asked) == len(roads)}  # it disagrees under every road the permit allows
    return found, fits


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_every_sanctioned_case_meets_our_table_iii_or_its_disagreement_is_understood(path):
    case = json.loads(path.read_text())
    assert case["evidence"] == "sanctioned" and case["sources"]
    found, _ = review(case)
    listed = case.get("known_disagreements", {})
    new = sorted(set(found) - set(listed))
    assert not new, f"{case['name']}: our Table III disagrees with a sanctioned plan: " + "; ".join(
        f"{n} (it asks {found[n]})" for n in new)
    fixed = sorted(set(listed) - set(found))
    assert not fixed, f"{case['name']}: no longer disagrees on {fixed}: record the rule fixed"
