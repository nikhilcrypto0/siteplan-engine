"""Shared by the tests of blocks below 21 m: made-up non-high-rise bands and layouts edited to use
them. Every number here is MADE UP so the validator's logic can be tested before A2 encodes the
real Table III; none of it is a value of the order, and none may stand in for one.

The contract fixtures ship the band below 21 m as not modelled (stream A1). `with_bands_below`
replaces it with bands that are, in the shape the contract gives a band (`Band`): the heights it
covers, whether it is modelled, its road, its all-round setback and its gap between blocks.

A low block here normally has no stilt (`flat`), so every reading of the stilt gives it one rule
height and a test says nothing about which band the stilt puts it in: that open question is
pinned alone, in tests/test_validator_low_interim.py.
"""

from __future__ import annotations

from validator_helpers import Inputs, set_floors, tower

from siteplan.contracts import CandidateLayout, ResolvedRules
from siteplan.contracts.common import Provenance
from siteplan.contracts.resolved_rules import (
    ALL,
    MIXED_HEIGHT_SPACING,
    Band,
    BandKind,
    Eligibility,
    HeightMeasure,
)

MADE_UP = "MADE-UP band for a test, not Table III"


def low_band(above: float, up_to: float, *, setback: float | None, road: float | None,
             gap: float | None = None, front: float | None = None, up_to_inclusive: bool = True,
             modelled: bool = True, status: Provenance = Provenance.ASSUMED_FOR_TEST,
             permission: Eligibility = Eligibility.ALLOWED, note: str = "",
             strip: float | None = None, strip_sides: str = "ALL",
             measure: HeightMeasure = HeightMeasure.HEIGHT_ABOVE_STILT) -> Band:
    """A band below the high-rise height, read on the height above the stilt as Table III's are
    (rule 5(c)). A `gap` left out is left unset: the validator then reads the setback as the gap,
    as it always has. A `front` left out is the setback: the same all round."""
    return Band(above_m=above, up_to_m=up_to, up_to_inclusive=up_to_inclusive,
                kind=BandKind.NON_HIGH_RISE, measure=measure, modelled=modelled,
                min_road_m=road, setback_m=setback, front_setback_m=front, gap_m=gap,
                permission=permission, permission_note=note, green_strip_m=strip,
                green_strip_sides=strip_sides, clause=f"{MADE_UP}: {above:g}-{up_to:g} m",
                status=status)


# Heights are heights above the stilt. Made-up figures, chosen apart from each other and from the
# order's so a mix-up cannot pass by luck.
LOW_A = low_band(0, 12, setback=2.3, gap=3.1, road=0.0)  # asks no road
LOW_B = low_band(12, 18, setback=3.7, gap=4.3, road=8.4)
LOW_C = low_band(18, 21, setback=4.9, gap=5.7, road=11.6, up_to_inclusive=False)
MADE_UP_LOW_BANDS = (LOW_A, LOW_B, LOW_C)


def with_bands_below(inputs: Inputs, bands=MADE_UP_LOW_BANDS) -> Inputs:
    """The same rules with the bands below the high-rise height replaced (the high-rise rows are
    kept as they are). The result is validated as a whole, so bands that leave a gap or overlap
    are refused here rather than judged."""
    def edit(rules: ResolvedRules) -> None:
        keep = [b for b in rules.height.bands if b.kind is BandKind.HIGH_RISE]
        rules.height.bands = [*bands, *keep]
        ResolvedRules.model_validate(rules.model_dump())
    return inputs.with_rules(edit)


def with_low_bands(inputs: Inputs) -> Inputs:
    return with_bands_below(inputs, MADE_UP_LOW_BANDS)


def floors_of(inputs: Inputs, **floors: int) -> Inputs:
    """The named towers at the given number of floors above the stilt (the stilt kept)."""
    def edit(candidate: CandidateLayout) -> None:
        for name, n in floors.items():
            set_floors(candidate, name, n)
    return inputs.edited(edit)


def flat(inputs: Inputs, **floors: int) -> Inputs:
    """The named towers with no stilt and the given number of 3 m floors: every reading of the
    stilt gives each the same height (5 floors: 15 m, band B; 4: 12 m, band A; 7: exactly 21 m)."""
    def edit(candidate: CandidateLayout) -> None:
        for name, n in floors.items():
            tower(candidate, name).has_stilt = False
            set_floors(candidate, name, n)
    return inputs.edited(edit)


def all_low(inputs: Inputs, floors: int = 5) -> Inputs:
    """Every tower below the high-rise height, flat (15 m, band B, by default)."""
    return flat(inputs, **{t.name: floors for t in inputs.candidate.towers})


def spacing_open(inputs: Inputs) -> Inputs:
    """Leave mixed-height spacing open (the fixtures settle on the taller block's gap)."""
    return inputs.with_rules(
        lambda r: setattr(r.interpretation(MIXED_HEIGHT_SPACING), "selected", ALL))


def access_road_of(inputs: Inputs, width_m: float) -> Inputs:
    """The access road's legal width set to `width_m` (its status stays as the fixture has it)."""
    def edit(site) -> None:
        site.access_road().legal_row_m.value = width_m
    return inputs.with_site(edit)


def changed_rules(before, after) -> dict[str, tuple]:
    """The legal checks whose status or wording differ between two reports, by rule name."""
    old = {c.finding.rule: c for c in before.legal}
    new = {c.finding.rule: c for c in after.legal}
    return {rule: (old[rule], new[rule]) for rule in old.keys() & new.keys()
            if (old[rule].finding, old[rule].by_reading)
            != (new[rule].finding, new[rule].by_reading)}
