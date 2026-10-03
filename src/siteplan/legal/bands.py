"""The land of each height band: the net plot inset by the band's setback, less the exclusions.

Setbacks are measured on the net plot with mitre joins, each wall's setback taken square to it
(rules.SETBACK_ON_NET_PLOT_CLAUSE). A taller band has a wider setback, so its land lies inside a
shorter band's: each band is cut to the one before it, which makes that exact rather than true up
to float noise. Bands run up to the legal height and no further, and stop at the first whose land
is empty, since every taller band would be empty too.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from siteplan.contracts.resolved_rules import Band, HeightMeasure, ResolvedRules


@dataclass(frozen=True)
class BandLand:
    band: Band
    key: str
    inset: BaseGeometry  # the setback envelope: the net plot less the setback all round
    buildable: BaseGeometry  # the setback envelope less the exclusions


def band_key(above_m: float, up_to_m: float) -> str:
    """A band as people write it, e.g. '27-30 m'."""
    return f"{above_m:g}-{up_to_m:g} m"


def height_cap(rules: ResolvedRules) -> tuple[float | None, str]:
    """The tallest rule height the law allows here, in metres, and why there is none to give.

    A limit with no condition always binds. Limits with a condition are alternatives (which road
    width counts, say): the envelope takes the most any of them allows, so it shows the land of
    every reading. A limit that cannot be evaluated, or that is not there, caps nothing; the
    second value then says why, and is empty when there is a cap.
    """
    limits = [lim for lim in rules.height.limits if lim.measure is HeightMeasure.RULE_HEIGHT]
    caps = [lim.max_m for lim in limits if lim.applies_if is None and lim.max_m is not None]
    either = [lim for lim in limits if lim.applies_if is not None]
    if either and all(lim.max_m is not None for lim in either):
        caps.append(max(lim.max_m for lim in either))
    if caps:
        return min(caps), ""
    return None, "; ".join(lim.reason for lim in limits if lim.max_m is None)


def band_lands(rules: ResolvedRules, net, excluded) -> list[BandLand]:
    """The modelled bands up to the height cap, tallest last, each inside the one before."""
    cap, _ = height_cap(rules)
    lands: list[BandLand] = []
    previous = net
    for band in rules.height.bands:
        if not band.modelled or (cap is not None and band.above_m >= cap):
            continue
        if band.setback_m is None:
            raise ValueError(f"the band {band_key(band.above_m, band.up_to_m)} is modelled but "
                             "has no setback")
        inset = net.buffer(-band.setback_m, join_style="mitre").intersection(previous)
        buildable = inset if excluded is None else inset.difference(excluded)
        lands.append(BandLand(band, band_key(band.above_m, band.up_to_m), inset, buildable))
        previous = inset
        if buildable.is_empty:
            break
    return lands
