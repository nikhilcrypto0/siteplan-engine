"""What Table III and its notes give the land below the high-rise height: the permissible heights
of the plot's row, the setback and the road each asks, and the heights nothing permits.

Pure rules. It reads rules.py and the figures a site gives (the net plot's area, the access road's
legal widths, whether the site is a group development scheme) and returns one stretch of height at
a time, so that the stretches tile every height below the high-rise height once. legal/resolve.py
turns them into the contract's bands; nothing here draws.

Heights are read with the parking stilt left out (rule 5(c)), the way Table III reads them.
Nothing below the row's last height is guessed: a stretch the orders read give no figure for is
PROHIBITED where nothing permits it and UNVERIFIED where something might (TDR), and carries no
setback.
"""

from __future__ import annotations

from dataclasses import dataclass

from siteplan import rules
from siteplan.contracts.common import Provenance
from siteplan.contracts.resolved_rules import Eligibility
from siteplan.provenance import confirmed, weakest

Width = tuple[float, Provenance]  # a legal width of the access road, and how far it is trusted
WIDTH_TOL_M = 1e-6


@dataclass(frozen=True)
class Stretch:
    """One stretch of height below the high-rise height, on the stilt-free height."""

    above_m: float
    up_to_m: float
    above_inclusive: bool
    up_to_inclusive: bool
    side_m: float | None  # the setback on the remaining sides; None where no figure is given
    front_m: float | None  # the Building Line on the access road; None where it is not known
    min_road_m: float | None
    permission: Eligibility
    note: str  # why the height is not permitted, or what the road's condition rests on
    clause: str
    status: Provenance
    row: int | None = None  # the Table III row the stretch belongs to


def _meets(widths: tuple[Width, ...], need_m: float) -> tuple[bool | None, bool]:
    """Whether the access road is wide enough, and whether that is settled (confirmed widths
    only). With a master-plan width as well, both must meet it for it to be met, neither for it to
    be unmet, and it is unknown when the two disagree."""
    if not widths:
        return None, False
    meets = {rules.reckoned_road_width_m(w) >= need_m - WIDTH_TOL_M for w, _ in widths}
    settled = all(confirmed(status) for _, status in widths)
    return (meets.pop() if len(meets) == 1 else None), settled


def _front(line: rules.TableIIILine, widths: tuple[Width, ...]) -> tuple[float | None, bool]:
    """The Building Line for the access road, and whether the road settles it. With two widths
    that give different lines the larger stands, and the line is not settled."""
    if not widths:
        return None, False
    lines = {rules.building_line_m(line, w) for w, _ in widths}
    return max(lines), len(lines) == 1


def _road_needed(line: rules.TableIIILine, group: bool) -> tuple[float, str]:
    """The road a line's height asks, and the clause that asks it. A group development scheme
    needs 12 m whatever the height (rule 8(b)); otherwise a block above 15 m needs 12 m (rule
    5(e), Table II row B2) and one up to 15 m needs 9 m (Table II row B1)."""
    if group:
        return rules.GROUP_DEVELOPMENT_MIN_ROAD_M, rules.GROUP_DEVELOPMENT_ROAD_CLAUSE
    if line.below:
        return rules.TABLE_III_TOP_TIER_MIN_ROAD_M, rules.TABLE_III_TOP_TIER_CLAUSE
    return rules.TABLE_II_B1_ROAD_M, rules.TABLE_II_CLAUSE


def _permission(met: bool | None, settled: bool) -> Eligibility:
    if met is None:
        return Eligibility.UNVERIFIED
    if met:
        return Eligibility.ALLOWED
    return Eligibility.PROHIBITED if settled else Eligibility.UNVERIFIED


def _road_note(widths: tuple[Width, ...], need: float, met: bool | None, why: str) -> str:
    if not widths:
        return f"the access road's legal width is not given; {need:g} m is asked ({why})"
    measured = " or ".join(f"{w:.2f} m ({status})" for w, status in widths)
    verdict = {True: "meets it", False: "falls short of it", None: "is not settled"}[met]
    return f"{need:g} m of road is asked ({why}); the road, {measured}, {verdict}"


def stretches(*, plot_sqm: float, plot_status: Provenance, gross_sqm: float,
              gross_status: Provenance, widths: tuple[Width, ...],
              high_rise_from_m: float) -> list[Stretch]:
    """Every height from nothing up to the high-rise height, once: the lines of the plot's Table
    III row, then what lies above the row's last line. `widths` are the access road's legal
    widths (the road as it stands, and the master-plan width when one is given)."""
    lines = rules.table_iii_lines(plot_sqm)
    group = rules.is_group_development(gross_sqm)
    out: list[Stretch] = []
    above, above_inclusive = 0.0, False
    for line in lines:
        need, why = _road_needed(line, group)
        met, settled = _meets(widths, need)
        front, front_settled = _front(line, widths)
        status = weakest(Provenance.VERIFIED, plot_status, *(s for _, s in widths),
                         *([gross_status] if group else []),
                         *([] if front_settled else [Provenance.UNVERIFIED]))
        below = " (below it)" if line.below else ""
        out.append(Stretch(
            above, line.up_to_m, above_inclusive, not line.below,
            side_m=line.side_m or 0.0, front_m=front, min_road_m=need,
            permission=_permission(met, settled), status=status, row=line.row,
            note=_road_note(widths, need, met, why),
            clause=f"{rules.TABLE_III_CLAUSE}; row {line.row}, up to {line.up_to_m:g} m{below}"))
        above, above_inclusive = line.up_to_m, line.below
    return [*out, *_above_the_row(lines[-1], plot_sqm, plot_status, high_rise_from_m)]


def _above_the_row(last: rules.TableIIILine, plot_sqm: float, plot_status: Provenance,
                   high_rise_from_m: float) -> list[Stretch]:
    """What lies between the row's last line and the high-rise height. Table III permits nothing
    above its last line; the only order read that gives anything is G.O.Ms.No.95 of 2026, which
    lets a plot of 750 to 2,000 m² build 18 to 21 m through TDR and gives no setback for it."""
    tdr_low, tdr_high = rules.TDR_BAND_M
    small, large = rules.TDR_PLOT_RANGE_SQM
    through_tdr = small <= plot_sqm <= large
    edge, edge_inclusive = last.up_to_m, last.below
    found: list[Stretch] = []

    def stretch(upper: float, permission: Eligibility, note: str, status: Provenance,
                clause: str) -> Stretch:
        return Stretch(edge, upper, edge_inclusive, False, side_m=None, front_m=None,
                       min_road_m=None, permission=permission, note=note, clause=clause,
                       status=status, row=last.row)

    if edge < tdr_low:
        upper = tdr_low if through_tdr else high_rise_from_m
        found.append(stretch(
            upper, Eligibility.PROHIBITED,
            f"Table III's row {last.row} stops at {last.up_to_m:g} m, the stilt left out, and no "
            "order read permits a taller building on a plot of this size",
            weakest(Provenance.VERIFIED, plot_status), rules.TABLE_III_CLAUSE))
        edge, edge_inclusive = upper, True  # what ends below 18 m is followed by 18 m itself
    if edge < high_rise_from_m:
        if through_tdr:
            note = (f"{tdr_low:g} to {tdr_high:g} m is permitted on a plot of {small:,.0f} to "
                    f"{large:,.0f} m² only through TDR, and no setback is given for it")
        else:
            note = (f"Table III stops below {tdr_low:g} m and a high-rise starts at "
                    f"{high_rise_from_m:g} m: no order read gives a setback between them on a "
                    f"plot above {large:,.0f} m²")
        found.append(stretch(high_rise_from_m, Eligibility.UNVERIFIED, note,
                             Provenance.UNVERIFIED, rules.TDR_BAND_CLAUSE))
    return found


def high_rise_front(all_round_m: float, plot_sqm: float, widths: tuple[Width, ...]
                    ) -> tuple[float | None, bool]:
    """Rule 7(a)(xi): the front of a high-rise is the higher of Table IV column 4 and the Building
    Line of Table III. Returns the front where it is higher than the all-round figure (None where
    it is not) and whether the road settles that: the answer is settled when every width the road
    may have gives the same one, which it does whatever the road where even the widest Building
    Line could not exceed the all-round figure."""
    line = rules.table_iii_lines(plot_sqm)[-1]
    most = max(line.front_m)
    if not widths:
        return (float(most) if most > all_round_m else None), most <= all_round_m
    lines = {rules.building_line_m(line, w) for w, _ in widths}
    front = max(lines)
    return (front if front > all_round_m else None), len({m > all_round_m for m in lines}) == 1
