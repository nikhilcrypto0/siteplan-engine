"""Check a proposed site against the encoded Telangana rules.

Each finding says what was measured, what the rule requires and which clause says so.
When an input is missing the finding says so (NEEDS_INPUT) rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from math import hypot

from shapely.geometry import Polygon

from siteplan import rules
from siteplan.geometry import opening


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_INPUT = "NEEDS_INPUT"
    NOT_CHECKED = "NOT_CHECKED"
    INFO = "INFO"  # a classification that drives other checks, not a verdict


@dataclass(frozen=True)
class Finding:
    rule: str
    status: Status
    measured: str
    required: str
    clause: str
    note: str = ""


@dataclass(frozen=True)
class Building:
    name: str
    height_m: float | None = None
    stilt_height_m: float | None = None
    floors: int | None = None
    floor_height_m: float | None = None
    footprint: Polygon | None = None

    def resolved_height(self) -> float | None:
        """Height including the stilt, as rule 2(f) counts it."""
        if self.height_m is not None:
            return self.height_m
        if None in (self.stilt_height_m, self.floors, self.floor_height_m):
            return None
        return self.stilt_height_m + self.floors * self.floor_height_m  # type: ignore[operator]


@dataclass(frozen=True)
class Site:
    gross_area_sqm: float | None = None  # as per documents / survey
    net_area_sqm: float | None = None  # after road widening and other deductions
    abutting_road_m: float | None = None  # existing width
    master_plan_road_m: float | None = None  # proposed width, if the road is to be widened
    open_space_sqm: float | None = None
    net_plot: Polygon | None = None
    open_space_pockets: tuple[Polygon, ...] = ()
    buildings: tuple[Building, ...] = field(default_factory=tuple)
    club_house: Polygon | None = None  # footprint
    club_house_built_up_sqm: float | None = None  # all its floors
    driveway: Polygon | None = None
    built_up_sqm: float | None = None  # all floors of all blocks
    surface_parking_sqm: float = 0.0
    units: int | None = None
    authority: str | None = None  # GHMC, HMDA, DTCP...; Table V differs by authority


def _m(value: float) -> str:
    return f"{value:.2f} m"


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def check_site(site: Site) -> list[Finding]:
    findings: list[Finding] = [_height_finding(b) for b in site.buildings]
    all_high_rise = [
        b for b in site.buildings if (b.resolved_height() or 0) >= rules.HIGH_RISE_THRESHOLD_M
    ]
    bands = {b.name: rules.band_for_height(b.resolved_height() or 0) for b in all_high_rise}
    encoded = [b for b in all_high_rise if bands[b.name] is not None]
    beyond_table = [b for b in all_high_rise if bands[b.name] is None]

    if all_high_rise:
        findings.append(_plot_size_finding(site))
        tallest = max(all_high_rise, key=lambda b: b.resolved_height() or 0)
        if bands[tallest.name] is not None:
            findings.append(_road_finding(site, tallest.name, bands[tallest.name]))
        else:
            findings.append(_beyond_table(f"Abutting road width (for {tallest.name})", tallest))
    for b in beyond_table:
        findings.append(_beyond_table(f"Setbacks and block gaps: {b.name}", b))
    if encoded:
        findings += _setback_findings(site, encoded, bands)
        findings += _spacing_findings(encoded, bands)
    findings += _open_space_findings(site)
    findings.append(_green_strip_finding(site, encoded, bands))
    findings.append(_driveway_finding(site))
    findings.append(_amenity_finding(site))
    findings.append(_parking_finding(site))
    return findings


def _green_strip_finding(site: Site, high_rise, bands) -> Finding:
    """The 2 m planting strip, which since 2016 is asked for only where the setback is 9 m+."""
    from_m = rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M
    required = (f">= {rules.PERIPHERAL_GREEN_STRIP_M:g} m on sides with a setback of "
                f"{from_m:g} m or more")
    setbacks = [_needed_setback(b, bands[b.name]) for b in high_rise] if high_rise else []
    if setbacks and max(setbacks) < from_m:
        return Finding(
            "Peripheral green strip", Status.INFO,
            f"deepest setback here is {max(setbacks):.2f} m", required,
            rules.PERIPHERAL_GREEN_STRIP_CLAUSE,
            f"The strip is required only where the setback reaches {from_m:g} m.",
        )
    return Finding(
        "Peripheral green strip", Status.NOT_CHECKED, "not modelled yet", required,
        rules.PERIPHERAL_GREEN_STRIP_CLAUSE,
        "Needs the landscape layer from the site-plan DWG.",
    )


def _driveway_finding(site: Site) -> Finding:
    required = f">= {rules.DRIVEWAY_MIN_WIDTH_M:g} m wide"
    if site.driveway is None:
        return Finding("Driveway", Status.NOT_CHECKED, "no driveway in this layout", required,
                       rules.DRIVEWAY_CLAUSE, "Give the layout a driveway width to check it.")
    narrow = _narrower_than(site.driveway, rules.DRIVEWAY_MIN_WIDTH_M)
    measured = f"{site.driveway.area:,.0f} m²"
    if narrow:
        measured += ", narrower than the minimum in places"
    return Finding(
        "Driveway",
        Status.FAIL if narrow else Status.PASS,
        measured,
        required,
        rules.DRIVEWAY_CLAUSE,
        "Ramps are not counted here; rule 13(vii) keeps those out of the mandatory setbacks.",
    )


def _amenity_finding(site: Site) -> Finding:
    required = f">= {rules.AMENITY_MIN_BUILT_UP_FRACTION:.0%} of built-up area"
    if site.built_up_sqm is None or site.units is None:
        return Finding("Amenities (club house)", Status.NOT_CHECKED,
                       "built-up area or unit count unknown", required, rules.AMENITY_CLAUSE)
    if site.units < rules.AMENITY_MIN_UNITS:
        return Finding(
            "Amenities (club house)", Status.INFO, f"{site.units} units",
            required, rules.AMENITY_CLAUSE,
            f"The clause applies from {rules.AMENITY_MIN_UNITS} units.",
        )
    provided = site.club_house_built_up_sqm
    if provided is None:
        provided = site.club_house.area if site.club_house is not None else 0.0
    need = rules.AMENITY_MIN_BUILT_UP_FRACTION * site.built_up_sqm
    short = provided + 0.5 < need
    return Finding(
        "Amenities (club house)",
        Status.FAIL if short else Status.PASS,
        f"{provided:,.0f} m² ({_pct(provided / site.built_up_sqm)} of built-up)",
        f"{required} = {need:,.0f} m²",
        rules.AMENITY_CLAUSE,
        "The amenities block is separate from the residential blocks, as the clause requires.",
    )


def _parking_finding(site: Site) -> Finding:
    percent = rules.parking_percent(site.authority)
    required = f">= {percent:g}% of built-up area"
    if site.built_up_sqm is None:
        return Finding("Parking", Status.NOT_CHECKED, "built-up area unknown", required,
                       rules.PARKING_CLAUSE)
    need = percent / 100 * site.built_up_sqm
    stilt = sum(b.footprint.area for b in site.buildings if b.footprint is not None)
    provided = stilt + site.surface_parking_sqm
    measured = f"stilt {stilt:,.0f} m² + surface {site.surface_parking_sqm:,.0f} m²"
    note = "Cellars and podium parking are not modelled."
    if site.authority is None:
        note += " Authority not given, so the 20% column is used; inside GHMC it is 30%."
    if provided + 0.5 >= need:
        return Finding("Parking", Status.PASS, measured, f"{required} = {need:,.0f} m²",
                       rules.PARKING_CLAUSE, note)
    return Finding(
        "Parking",
        Status.NEEDS_INPUT,
        f"{measured}, short by {need - provided:,.0f} m²",
        f"{required} = {need:,.0f} m²",
        rules.PARKING_CLAUSE,
        f"{note} Say where the rest goes (cellar or podium) to settle this.",
    )


def _height_finding(b: Building) -> Finding:
    height = b.resolved_height()
    if height is None:
        return Finding(
            f"Height class: {b.name}",
            Status.NEEDS_INPUT,
            "unknown",
            "total height including stilt",
            rules.HIGH_RISE_CLAUSE,
            "Give height_m, or stilt height + floors + floor-to-floor height.",
        )
    if height < rules.HIGH_RISE_THRESHOLD_M:
        return Finding(
            f"Height class: {b.name}",
            Status.NOT_CHECKED,
            _m(height),
            f"high-rise from {rules.HIGH_RISE_THRESHOLD_M:g} m",
            rules.HIGH_RISE_CLAUSE,
            "Not high-rise: Table III (plot-size setbacks) applies and is not encoded yet.",
        )
    band = rules.band_for_height(height)
    if band is None:
        return Finding(
            f"Height class: {b.name}",
            Status.NOT_CHECKED,
            _m(height),
            "up to 55 m encoded",
            rules.TABLE_IV_CLAUSE,
            "Above 55 m: 0.5 m extra setback per 5 m; not encoded yet.",
        )
    span = (
        f"up to {band.up_to_m:g} m"
        if band.above_m == 0
        else f"above {band.above_m:g} m, up to {band.up_to_m:g} m"
    )
    return Finding(
        f"Height class: {b.name}",
        Status.INFO,
        _m(height),
        f"high-rise band {span}",
        rules.TABLE_IV_CLAUSE,
        f"Needs a road at least {band.min_road_m:g} m wide "
        f"and {band.min_open_space_m:g} m open all round.",
    )


def _beyond_table(rule: str, b: Building) -> Finding:
    return Finding(
        rule,
        Status.NOT_CHECKED,
        _m(b.resolved_height() or 0),
        "Table IV rows up to 55 m are encoded",
        rules.TABLE_IV_CLAUSE,
        "Above 55 m the requirement is not encoded yet. Check it by hand.",
    )


def _road_finding(site: Site, tallest: str, band: rules.HeightBand) -> Finding:
    rule = f"Abutting road width (for {tallest})"
    required = f">= {band.min_road_m:g} m"
    if site.master_plan_road_m is not None:
        ok = site.master_plan_road_m >= band.min_road_m
        return Finding(
            rule,
            Status.PASS if ok else Status.FAIL,
            f"{_m(site.master_plan_road_m)} (master plan)",
            required,
            f"{rules.TABLE_IV_CLAUSE}; {rules.ROAD_WIDENING_CLAUSE}",
            "Counts only if the road-widening strip is surrendered.",
        )
    if site.abutting_road_m is None:
        return Finding(rule, Status.NEEDS_INPUT, "unknown", required, rules.TABLE_IV_CLAUSE)
    ok = site.abutting_road_m >= band.min_road_m
    return Finding(
        rule,
        Status.PASS if ok else Status.FAIL,
        f"{_m(site.abutting_road_m)} (existing)",
        required,
        rules.TABLE_IV_CLAUSE,
        "" if ok else "If the master plan widens this road, re-run with master_plan_road_m.",
    )


def _plot_size_finding(site: Site) -> Finding:
    area = site.net_area_sqm or site.gross_area_sqm
    required = f">= {rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m²"
    if area is None:
        return Finding(
            "Plot size for high-rise",
            Status.NEEDS_INPUT,
            "unknown",
            required,
            rules.MIN_HIGH_RISE_PLOT_CLAUSE,
        )
    ok = area >= rules.MIN_HIGH_RISE_PLOT_SQM
    return Finding(
        "Plot size for high-rise",
        Status.PASS if ok else Status.FAIL,
        f"{area:,.0f} m²",
        required,
        rules.MIN_HIGH_RISE_PLOT_CLAUSE,
    )


def _no_geometry(rule: str, required: str, clause: str, count: int) -> Finding:
    return Finding(
        rule,
        Status.NEEDS_INPUT,
        f"no footprint geometry ({count} to check)",
        required,
        clause,
        "Needs building footprints and the net plot boundary (DWG).",
    )


def _longest_side_m(building: Building) -> float | None:
    """How long the building is, which decides whether the 40 m note applies.

    Measured on the building's own axes, not the drawing's: a block turned to suit the site
    is no longer for it, and its bounding box would charge it setback it does not owe.
    """
    if building.footprint is None or building.footprint.is_empty:
        return None
    hull = building.footprint.convex_hull
    if not hasattr(hull, "exterior"):  # degenerate footprint: a line or a point
        x0, y0, x1, y1 = hull.bounds
        return max(x1 - x0, y1 - y0)
    x, y = hull.exterior.coords.xy
    return max(hypot(x[i + 1] - x[i], y[i + 1] - y[i]) for i in range(len(x) - 1))


def _needed_setback(building: Building, band) -> float:
    return rules.setback_for(band, _longest_side_m(building))


def _setback_findings(site, high_rise, bands) -> list[Finding]:
    if site.net_plot is None or all(b.footprint is None for b in high_rise):
        need = ", ".join(sorted({f"{bands[b.name].min_open_space_m:g} m" for b in high_rise}))
        required = f">= {need} to the net plot line (by height)"
        return [_no_geometry("All-round setbacks", required, rules.TABLE_IV_CLAUSE, len(high_rise))]
    findings = []
    for b in high_rise:
        need = _needed_setback(b, bands[b.name])
        long_note = ""
        if need > bands[b.name].min_open_space_m:
            long_note = (f" ({bands[b.name].min_open_space_m:g} m from the table plus "
                         f"{need - bands[b.name].min_open_space_m:.2f} m for a building "
                         f"{_longest_side_m(b):.0f} m long)")
        required = f">= {need:.2f} m to the net plot line{long_note}"
        if b.footprint is None or site.net_plot is None:
            findings.append(
                Finding(
                    f"All-round setback: {b.name}",
                    Status.NEEDS_INPUT,
                    "no footprint geometry",
                    required,
                    rules.TABLE_IV_CLAUSE,
                    "Needs the building footprint and net plot boundary (DWG).",
                )
            )
            continue
        gap = site.net_plot.exterior.distance(b.footprint)
        if not site.net_plot.contains(b.footprint):
            gap = 0.0
        ok = gap + 1e-6 >= need
        findings.append(
            Finding(
                f"All-round setback: {b.name}",
                Status.PASS if ok else Status.FAIL,
                _m(gap),
                required,
                rules.LONG_BUILDING_CLAUSE if long_note else rules.TABLE_IV_CLAUSE,
                "Front setback may also be governed by the Table III building line (not encoded).",
            )
        )
    return findings


def _spacing_findings(high_rise, bands) -> list[Finding]:
    pairs = list(combinations(high_rise, 2))
    if pairs and all(b.footprint is None for b in high_rise):
        need = max(bands[b.name].min_open_space_m for b in high_rise)
        return [
            _no_geometry(
                "Gaps between blocks",
                f">= the taller block's all-round open space (up to {need:g} m here)",
                rules.BLOCK_SPACING_CLAUSE,
                len(pairs),
            )
        ]
    findings = []
    for a, b in pairs:
        need = max(_needed_setback(a, bands[a.name]), _needed_setback(b, bands[b.name]))
        rule = f"Gap between blocks: {a.name} / {b.name}"
        if a.footprint is None or b.footprint is None:
            findings.append(
                Finding(
                    rule,
                    Status.NEEDS_INPUT,
                    "no footprint geometry",
                    f">= {need:.2f} m",
                    rules.BLOCK_SPACING_CLAUSE,
                    "Needs both footprints (DWG).",
                )
            )
            continue
        gap = a.footprint.distance(b.footprint)
        findings.append(
            Finding(
                rule,
                Status.PASS if gap >= need else Status.FAIL,
                _m(gap),
                f">= {need:g} m",
                rules.BLOCK_SPACING_CLAUSE,
                "This gap does not count towards the tot-lot.",
            )
        )
    return findings


def _narrower_than(shape: Polygon, width_m: float) -> bool:
    """True if any part of the shape is narrower than width_m (a noticeable share of its
    area disappears when every part thinner than the width is removed)."""
    return opening(shape, width_m).area < shape.area * 0.98


def _open_space_findings(site: Site) -> list[Finding]:
    rule = "Organized open space (tot-lot)"
    required = f">= {rules.OPEN_SPACE_MIN_FRACTION:.0%} of site area, over and above setbacks"
    if site.open_space_sqm is None:
        return [Finding(rule, Status.NEEDS_INPUT, "unknown", required, rules.OPEN_SPACE_CLAUSE)]
    shares = {
        name: site.open_space_sqm / area
        for name, area in (("net", site.net_area_sqm), ("gross", site.gross_area_sqm))
        if area
    }
    if not shares:
        clause = rules.OPEN_SPACE_CLAUSE
        return [Finding(rule, Status.NEEDS_INPUT, "no site area", required, clause)]
    measured = ", ".join(f"{_pct(v)} of {k}" for k, v in shares.items())
    passing = [v >= rules.OPEN_SPACE_MIN_FRACTION for v in shares.values()]
    if all(passing):
        status, note = Status.PASS, ""
    elif not any(passing):
        status, note = Status.FAIL, ""
    else:
        status = Status.NEEDS_INPUT
        note = "Passes on one site-area basis only. Confirm whether the rule uses net or gross."
    findings = [Finding(rule, status, measured, required, rules.OPEN_SPACE_CLAUSE, note)]

    for i, pocket in enumerate(site.open_space_pockets, 1):
        too_small = pocket.area < rules.OPEN_SPACE_MIN_POCKET_SQM
        too_narrow = _narrower_than(pocket, rules.OPEN_SPACE_MIN_WIDTH_M)
        findings.append(
            Finding(
                f"Open-space pocket {i}",
                Status.FAIL if too_small or too_narrow else Status.PASS,
                f"{pocket.area:,.1f} m²" + (", narrower than 3 m" if too_narrow else ""),
                f">= {rules.OPEN_SPACE_MIN_POCKET_SQM:g} m² and >= "
                f"{rules.OPEN_SPACE_MIN_WIDTH_M:g} m wide",
                rules.OPEN_SPACE_CLAUSE,
            )
        )
    return findings
