"""The land of each height band: the net plot inset by the band's setback, less the exclusions.

Setbacks are measured on the net plot with mitre joins, each wall's setback taken square to it
(rules.SETBACK_ON_NET_PLOT_CLAUSE). A band whose front setback (the Building Line) is larger than
its setback on the other sides is inset by the larger all round: never more lenient than the law,
and conservative where the front is the smaller figure, which an inset on the frontage alone would
give back. A taller band has a wider setback, so its land lies inside a shorter band's: each band
is cut to the one before it, which makes that exact rather than true up to float noise. A band
nothing may stand in (a height Table III does not permit, a high-rise that is prohibited) has no
land; bands run up to the legal height and no further, and stop at the first whose land is empty,
since every taller band would be empty too.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from siteplan.contracts.resolved_rules import (
    HEIGHT_TOL_M,
    Applicability,
    Band,
    BandKind,
    Eligibility,
    HeightMeasure,
    LimitBound,
    ResolvedRules,
)


@dataclass(frozen=True)
class BandLand:
    band: Band
    key: str
    inset: BaseGeometry  # the setback envelope: the net plot less the setback all round
    buildable: BaseGeometry  # the setback envelope less the exclusions


def band_key(above_m: float, up_to_m: float) -> str:
    """A band as people write it, e.g. '27-30 m', or '21 m' for a band of one height."""
    return f"{above_m:g} m" if above_m == up_to_m else f"{above_m:g}-{up_to_m:g} m"


def height_cap(rules: ResolvedRules) -> tuple[float | None, str]:
    """The tallest rule height the law allows here, in metres, and why there is none to give.

    A limit in force binds. Limits whose condition is unsettled are alternatives (which road
    width counts, say): the envelope takes the most any of them allows, so it shows the land of
    every reading. A limit that does not apply, has no number or cannot be worked out caps
    nothing; the second value then says why, and is empty when there is a cap.
    """
    limits = [lim for lim in rules.height.limits if lim.measure is HeightMeasure.RULE_HEIGHT
              and lim.applicability is not Applicability.DOES_NOT_APPLY]
    bounded = [lim for lim in limits if lim.bound is LimitBound.BOUNDED]
    caps = [lim.max_m for lim in bounded if lim.applicability is Applicability.APPLIES]
    either = [lim for lim in limits if lim.applicability is Applicability.UNKNOWN]
    if either and all(lim.bound is LimitBound.BOUNDED for lim in either):
        caps.append(max(lim.max_m for lim in either))
    if caps:
        return min(caps), ""
    return None, "; ".join(lim.reason for lim in limits if lim.bound is not LimitBound.BOUNDED)


def _lowest(band: Band) -> float:
    """The lowest height a band holds."""
    return band.above_m if band.above_inclusive else band.above_m + 2 * HEIGHT_TOL_M


def inset_m(band: Band) -> float:
    """How far a band's land lies from the net plot's line: the larger of its two setbacks."""
    return max(band.setback_m, band.front_setback_m or 0.0)


def band_lands(rules: ResolvedRules, net, excluded) -> list[BandLand]:
    """The bands with a setback to plan on, up to the height cap, tallest last, each inside the
    one before. A band that is not permitted has no land (where a high-rise is prohibited no
    high-rise band has any); a band whose permission is open (UNVERIFIED) keeps its land, which
    the envelope labels."""
    cap, _ = height_cap(rules)
    lands: list[BandLand] = []
    previous = net
    for band in rules.height.bands:
        if (not band.modelled or band.setback_m is None
                or rules.height.band_permission(band) is Eligibility.PROHIBITED
                or (band.kind is BandKind.HIGH_RISE and cap is not None
                    and _lowest(band) > cap + HEIGHT_TOL_M)):
            continue
        inset = net.buffer(-inset_m(band), join_style="mitre").intersection(previous)
        buildable = inset if excluded is None else inset.difference(excluded)
        lands.append(BandLand(band, band_key(band.above_m, band.up_to_m), inset, buildable))
        previous = inset
        if buildable.is_empty:
            break
    return lands
