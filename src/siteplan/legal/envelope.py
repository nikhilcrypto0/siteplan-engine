"""BuildableEnvelope: the legal land picture of one site, before any tower or road exists.

`envelope(site, rules)` takes the net plot and the law resolved for it and gives: the statutory
exclusions fixed in place; for each high-rise band up to the legal height, the setback envelope
and the buildable land; the width profile of the net plot and of every band's land, reported and
never judged; the circulation the law will ask for, as requirements and never as drawn roads; the
quantities asked, as pointers into ResolvedRules; the rule layers with what each permits; and the
facts, with every input still unknown said plainly.

It places no tower and draws no road. It reads the law only from the ResolvedRules it is given,
so an envelope follows the rules it was resolved with, not the ones in rules.py today.
"""

from __future__ import annotations

from siteplan.contracts.common import digest, shapes_from
from siteplan.contracts.envelope import (
    BandEnvelope,
    BuildableEnvelope,
    CirculationRequirements,
    Obligation,
)
from siteplan.contracts.resolved_rules import Eligibility, ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.legal.bands import band_key, band_lands, height_cap
from siteplan.legal.exclusions import exclusions
from siteplan.legal.facts import facts, requirements
from siteplan.legal.frontage import access_zones
from siteplan.legal.layers import rule_layers
from siteplan.legal.widths import width_profile

NOT_MODELLED_NOTE = ("Table III (rule 5) is not encoded yet: stream A2 reads it from the order; "
                     "a block of this height has no envelope here")
NET_PLOT = "net plot"


class NetPlotUnknown(ValueError):
    """The net plot cannot be placed, so there is no envelope to draw. The message names what
    the architect has to give."""


def envelope(site: CanonicalSiteModel, rules: ResolvedRules) -> BuildableEnvelope:
    if rules.site_ref != digest(site):
        raise ValueError("These rules were resolved for a different site model: resolve them "
                         "again for this one.")
    net = _net_plot(site)
    found = exclusions(site, rules, net)
    lands = band_lands(rules, net, found.union)
    cap, cap_note = height_cap(rules)
    return BuildableEnvelope(
        site_ref=rules.site_ref, rules_ref=digest(rules), exclusions=found.items,
        bands=_bands(rules, lands, cap_note),
        width_profiles=[width_profile(NET_PLOT, net),
                        *(width_profile(land.key, land.buildable) for land in lands)],
        circulation=CirculationRequirements(access_zones=access_zones(site, net, found.union),
                                            obligations=_obligations(rules, cap)),
        requirements=requirements(rules),
        rule_layers=rule_layers(rules, net, lands, found.water, site.access.side.value),
        facts=facts(site, rules, cap, lands, found.findings))


def _net_plot(site: CanonicalSiteModel):
    """The net plot as a shapely polygon, or a stop that says what to give."""
    if site.net_plot is None:
        raise NetPlotUnknown(_what_is_missing(site))
    return site.net_plot.value.to_shapely()


def _what_is_missing(site: CanonicalSiteModel) -> str:
    unplaced = [d for d in site.ownership.deductions if d.location.how.value == "UNKNOWN"]
    if not unplaced:
        return ("The site model has no net plot outline. Give the net plot outline "
                "(net_plot_m), or a survey that draws the plot.")
    lines = []
    for d in unplaced:
        side = d.location.side
        named = (f"the {side} side is named, but not the strip's width or outline" if side
                 else "neither its side, its width nor its outline is given")
        lines.append(f"{d.area_sqm.value:,.0f} m² of {d.kind.value.lower()} ({d.purpose}): "
                     f"{named}")
    return ("The net plot cannot be placed. " + "; ".join(lines) + ". The setbacks are measured "
            "on the land that is left, so give the side and the width of the strip "
            "(road_strip_side and road_strip_width_m), its outline (road_strip_m), or the net "
            "plot outline (net_plot_m). The engine does not guess a strip's location.")


def _bands(rules: ResolvedRules, lands, cap_note: str) -> list[BandEnvelope]:
    """Every band the rules carry, in order: the unmodelled ones as such, the others with their
    land up to the legal height (a band with no land after the first empty one is left out)."""
    by_key = {land.key: land for land in lands}
    out = []
    for band in rules.height.bands:
        common = {"above_m": band.above_m, "up_to_m": band.up_to_m, "kind": band.kind}
        if not band.modelled:
            out.append(BandEnvelope(**common, modelled=False, note=NOT_MODELLED_NOTE))
        elif (land := by_key.get(band_key(band.above_m, band.up_to_m))) is not None:
            out.append(BandEnvelope(
                **common, setback_m=band.setback_m, setback_envelope=shapes_from(land.inset),
                buildable=shapes_from(land.buildable), area_sqm=land.buildable.area,
                green_strip_applies=band.setback_m >= rules.green_strip.where_setback_from_m.value,
                note=_band_note(land.buildable.is_empty, cap_note)))
    return out


def _band_note(empty: bool, cap_note: str) -> str:
    notes = ["the setback and the exclusions leave no land at this height" if empty else "",
             f"no height limit is known from the road: {cap_note}" if cap_note else ""]
    return "; ".join(note for note in notes if note)


def _obligations(rules: ResolvedRules, cap: float | None) -> list[Obligation]:
    """What the law will ask of the circulation, each pointing at the value in ResolvedRules."""
    group = rules.circulation.applies.value
    high_rise = rules.height.high_rise.eligibility is not Eligibility.PROHIBITED and (
        cap is None or cap >= rules.height.high_rise_from_m.value)
    return [
        Obligation(id="gate", applies=True, rule_ref="fire.entrance_width_m",
                   note="the entrance a fire tender can use"),
        Obligation(id="internal roads", applies=group, rule_ref="circulation.internal_road_m",
                   note="rule 8(m): only in a Group Development Scheme"),
        Obligation(id="main approach", applies=group, rule_ref="circulation.approach_m",
                   note="only in a Group Development Scheme"),
        Obligation(id="fire lanes", applies=high_rise, rule_ref="fire.clear_width_m",
                   note="round every high-rise, with the turning radius in fire.turning_radius_m"),
        Obligation(id="no dead end above the physical limit", applies=True,
                   rule_ref="fire.dead_end_max_physical_m",
                   note="binds only if the access road ends at the plot")]

