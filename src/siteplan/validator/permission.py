"""Whether a building of a band's heights may stand on this site at all.

A band says whether its heights may stand here (plot size, road): ALLOWED, PROHIBITED with the
reason, or UNVERIFIED (`Band.permission`); `HeightRules.band_permission` adds the site's high-rise
eligibility to a high-rise band, whichever is weaker. A height the tables do not permit is a band
of its own, so a block in it fails on that alone, naming the reason; one in a band whose permission
is not settled is UNVERIFIED. The check is made for every block below the high-rise height in a
band the rules model, and for a high-rise block only where its band's own permission is not
ALLOWED (the high-rise eligibility, with its grounds, is `blocks.eligibility_check`).
"""

from __future__ import annotations

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT, BandKind, Eligibility
from siteplan.contracts.validation import Check, Family
from siteplan.validator.context import Context
from siteplan.validator.measure import UNCONFIRMED_NOTE, HeightClass
from siteplan.validator.readings import Assignment, Cell, check_from, run, unknown_reading

STATUS = {Eligibility.ALLOWED: Status.PASS, Eligibility.PROHIBITED: Status.FAIL,
          Eligibility.UNVERIFIED: Status.UNVERIFIED}
REQUIRED = "a band of heights the site may take (plot size, road)"


def _asked(cls: HeightClass) -> bool:
    """Whether a band's permission is something this check holds a block to."""
    band = cls.band
    if band is None or not band.modelled:
        return False
    return band.kind is BandKind.NON_HIGH_RISE or band.permission is not Eligibility.ALLOWED


def _reason(ctx: Context, cls: HeightClass, permission: Eligibility) -> str:
    band = cls.band
    if band.permission is not Eligibility.ALLOWED:
        return band.permission_note
    return f"the site's high-rise eligibility is {ctx.rules.height.high_rise.eligibility.value}"


def _cell(ctx: Context, cls: HeightClass) -> Cell:
    if cls.band is None or not cls.band.modelled:
        return Cell(Status.NOT_CHECKED, f"{cls.height_text}: {cls.label}", REQUIRED,
                    "The rules do not model this band, so whether it may stand here is not "
                    "judged.")
    permission = ctx.rules.height.band_permission(cls.band)
    shown = f"{cls.label}: {permission.value.lower()}"
    reason = _reason(ctx, cls, permission) if permission is not Eligibility.ALLOWED else ""
    if reason:
        shown += f", {reason}"
    if not cls.confirmed:
        return Cell(Status.UNVERIFIED, shown, REQUIRED, UNCONFIRMED_NOTE)
    return Cell(STATUS[permission], shown, REQUIRED)


def permission_checks(ctx: Context) -> list[Check]:
    out = []
    for t in ctx.towers:
        held = [classes[t.name] for classes in ctx.classes.values() if t.name in classes]
        if not any(_asked(c) for c in held):
            continue

        def cell(a: Assignment, t=t) -> Cell:
            reading = a[STILT_IN_RULE_HEIGHT]
            cls = ctx.classes.get(reading, {}).get(t.name)
            if cls is None:
                return unknown_reading(STILT_IN_RULE_HEIGHT, reading)
            return _cell(ctx, cls)

        clause = "; ".join(dict.fromkeys(c.table for c in held if c.table))
        out.append(check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.HEIGHT,
                              rule=f"Height permitted: {t.name}", clause=clause, subject=t.name))
    return out
