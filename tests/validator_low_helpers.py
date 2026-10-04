"""Shared by the tests of blocks below 21 m: made-up non-high-rise bands and layouts edited to use
them. Every number here is MADE UP so the validator's logic can be tested before A2 encodes the
real Table III; none of it is a value of the order, and none may stand in for one.

The contract fixtures ship the band below 21 m as not modelled (stream A1). `with_bands_below`
replaces it with bands that are, in the shape the contract gives a band (`Band`): the heights it
covers, whether it is modelled, its road, its all-round setback and its gap between blocks.
"""

from __future__ import annotations

from validator_helpers import Inputs, set_floors

from siteplan.contracts import CandidateLayout, ResolvedRules
from siteplan.contracts.common import Provenance
from siteplan.contracts.resolved_rules import ALL, MIXED_HEIGHT_SPACING, Band, BandKind

MADE_UP = "MADE-UP band for a test, not Table III"


def low_band(above: float, up_to: float, *, setback: float | None, road: float | None,
             gap: float | None = None, up_to_inclusive: bool = True, modelled: bool = True,
             status: Provenance = Provenance.ASSUMED_FOR_TEST) -> Band:
    """A band below the high-rise height. A `gap` left out is left unset: the validator then reads
    the setback as the gap, as it always has."""
    return Band(above_m=above, up_to_m=up_to, up_to_inclusive=up_to_inclusive,
                kind=BandKind.NON_HIGH_RISE, modelled=modelled, min_road_m=road, setback_m=setback,
                gap_m=gap, clause=f"{MADE_UP}: {above:g}-{up_to:g} m", status=status)


# Heights are rule heights (the stilt read under the reading in force). Made-up figures, chosen
# apart from each other and from the order's so a mix-up cannot pass by luck.
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
    """The named towers at the given number of floors above the stilt."""
    def edit(candidate: CandidateLayout) -> None:
        for name, n in floors.items():
            set_floors(candidate, name, n)
    return inputs.edited(edit)


def all_low(inputs: Inputs, floors: int = 4) -> Inputs:
    """Every tower below the high-rise height: 4 floors on a 3 m stilt is 15 m with the stilt and
    12 m without, so band B or band A of the made-up bands, by the reading."""
    return inputs.edited(lambda c: [set_floors(c, t.name, floors) for t in c.towers])


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
