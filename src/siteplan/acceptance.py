"""Acceptance: the whole flow on a real site, with the firm's own plan kept out until the end.

raw survey -> extract -> the architect's answers -> project -> every height from above the legal
limit down, each laid out with every requirement active -> the layouts that pass the checker ->
compared with the firm's plan. `generate` is given the survey, the answers and the firm's standard
libraries, never its plan for this site; `compare` reads the plan (a case traced from the firm's
drawing, and its area statement) only once the layouts exist, so the expected answer cannot leak
into them. Setbacks and gaps are measured from the DXF each option is delivered as, the file the
firm would open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import ezdxf
from shapely.geometry import Point, Polygon

from siteplan import rules
from siteplan.area_statement import AreaStatement
from siteplan.cases import Case
from siteplan.constraints import Basis, by_basis
from siteplan.findings import Status
from siteplan.heights import HeightSearch
from siteplan.intake import Draft, build_project, extract, load_defaults, save
from siteplan.intake import render as render_draft
from siteplan.layout import LayoutOption
from siteplan.library import FlatLibrary
from siteplan.max_floors import FloorLimit, max_floors
from siteplan.project import Project
from siteplan.provenance import Provenance
from siteplan.runner import load_plot, load_water, run_search, write_options
from siteplan.site_amenities import AmenityLibrary

BUILDING_LAYER = "Building Plan"  # the BuildNow layer the towers are delivered on
TOWER_NAME = re.compile(r"T\d+")


@dataclass(frozen=True)
class Generated:
    draft: Draft
    project: dict
    plot: Polygon
    basis: str
    limit: FloorLimit
    found: HeightSearch
    options: list[dict]  # the summaries written beside each option's drawings
    out: Path
    library_note: str = ""
    standards: dict | None = None  # the workspace standards the run used


def generate(survey: Path, answers: dict, out: Path, workspace: Path | None = None,
             conservative_parking: bool = False) -> Generated:
    """Everything the engine produces from the raw survey and the answers alone. With
    conservative_parking, an unestablished jurisdiction plans the GHMC column (a labelled test
    mode) instead of stopping to ask."""
    workspace = workspace or survey.parent
    defaults = load_defaults(workspace)
    if not defaults.flat_library:
        raise ValueError(f"Set the firm's flat_library in {workspace}/siteplan.workspace.json.")
    draft = extract(survey)
    project_dict = build_project(draft, answers, defaults)
    if conservative_parking:
        project_dict["layout"]["conservative_parking"] = True
        project_dict["sources"]["conservative_parking"] = "run in the conservative test mode"
        project_dict["status"]["conservative_parking"] = Provenance.ASSUMED_FOR_TEST
    save(project_dict, out / "project.json")
    project = Project.model_validate(project_dict)
    plot, basis = load_plot(project, survey)
    keep_out, _ = load_water(project, survey)
    site = project.to_site()
    limit = max_floors(plot.area, site.abutting_road_m, project.layout.floor_height_m,
                       project.layout.stilt_height_m, project.site.road_dead_end)
    library = FlatLibrary.model_validate_json((workspace / defaults.flat_library).read_text())
    amenities = (AmenityLibrary.model_validate_json((workspace / defaults.amenities).read_text())
                 if defaults.amenities else None)
    found = run_search(project, library, plot, project.layout, amenities, keep_out)
    options = write_options(found, project, library, plot, project.layout, out)
    return Generated(draft, project_dict, plot, basis, limit, found, options, out, library.note,
                     defaults.model_dump(exclude={"status"}))


def towers_in(dxf: Path) -> list[Polygon]:
    """The tower outlines an option was delivered with: the club house shares their layer, so
    a tower is an outline holding a tower's name (T1, T2 ...)."""
    msp = ezdxf.readfile(dxf).modelspace()
    names = [Point(t.dxf.insert.x, t.dxf.insert.y) for t in msp.query("TEXT")
             if TOWER_NAME.fullmatch(t.dxf.text.strip())]
    outlines = [Polygon([(x, y) for x, y, *_ in e.get_points()])
                for e in msp.query("LWPOLYLINE") if e.dxf.layer == BUILDING_LAYER]
    return [o for o in outlines if any(o.buffer(0.01).contains(p) for p in names)]


def spacing(plot: Polygon, towers: list[Polygon]) -> tuple[float, float | None]:
    """The least setback from the plot line, and the least gap between two towers."""
    setback = min(plot.exterior.distance(t) for t in towers)
    gaps = [a.distance(b) for a, b in combinations(towers, 2)]
    return setback, (min(gaps) if gaps else None)


def compare(generated: Generated, case: Case,
            statement: AreaStatement | None = None) -> list[tuple[str, str, str]]:
    """The engine's first option against the firm's plan, measure by measure."""
    best = generated.options[0]
    towers = towers_in(generated.out / "option_1.dxf")
    setback, gap = spacing(generated.plot, towers)
    firm_plot = Polygon(case.net_plot)
    firm_towers = [Polygon(b.outline) for b in case.buildings]
    firm_setback, firm_gap = spacing(firm_plot, firm_towers)
    firm_floors = ", ".join(f"{b.name} stilt + {b.floors}" for b in case.buildings)
    stilt, floor_h = (generated.project["layout"][k] for k in ("stilt_height_m",
                                                                "floor_height_m"))
    rows = [
        ("Net plot", f"{generated.plot.area:,.0f} m²", f"{firm_plot.area:,.0f} m²"),
        ("Towers", str(best["towers"]), str(len(case.buildings))),
        ("Floors above the stilt", f"stilt + {best['floors_above_stilt']} (every tower)",
         firm_floors),
        ("Height, stilt counted", f"{stilt + best['floors_above_stilt'] * floor_h:g} m",
         ", ".join(sorted({f"{stilt + b.floors * floor_h:g} m" for b in case.buildings}))),
        ("Least setback from the plot line", f"{setback:.2f} m", f"{firm_setback:.2f} m"),
        ("Least gap between towers", f"{gap:.2f} m" if gap else "one tower",
         f"{firm_gap:.2f} m" if firm_gap else "one tower"),
        ("Organised open space", f"{best['open_space_sqm']:,.0f} m²",
         f"{case.open_space_sqm:,.0f} m²" if case.open_space_sqm else "not given"),
        ("Flats", str(best["total_flats"]), "not in the area statement"),
    ]
    if statement is not None:
        ours = best["tower_floor_sqft"]
        firm_area = sum(g.subtotal_sqft for g in statement.groups)
        loading = statement.groups[0].common_area_pct
        rows += [
            ("Tower floor area, all floors, no loading", f"{ours:,} sft",
             f"{firm_area:,.0f} sft (engine {(ours / firm_area - 1) * 100:+.1f}%)"),
            (f"The same with the firm's {loading:g}% loading (its statement's total)",
             f"{ours * (1 + loading / 100):,.0f} sft", f"{statement.total_sqft:,} sft"),
            ("Saleable from the flats' own sale areas", f"{best['saleable_sqft']:,} sft",
             "not in the area statement"),
        ]
    fails = [rule for rule, status in best["rule_findings"].items() if status == "FAIL"]
    rows.append(("Rule FAILs (engine's checker)", ", ".join(fails) or "none",
                 f"{len(case.known_disagreements)} known, as the case records"))
    return rows


def report(generated: Generated, rows: list[tuple[str, str, str]]) -> str:
    """Plain text for the terminal and the report file."""
    project = generated.project
    lines = [
        f"ACCEPTANCE: {project['name']}",
        "The generator saw the raw survey, the answers and the firm's standard libraries; the "
        "firm's plan for this site was read only for the comparison at the end.",
        "",
        "1. EXTRACTED FROM THE SURVEY",
        *("  " + line.strip() for line in render_draft(generated.draft).splitlines()[1:]),
        f"  plot planned on: {generated.plot.area:,.0f} m², {generated.basis}",
        "",
        "2. INPUTS AND HOW FAR EACH IS TRUSTED",
        *_inputs(project, generated.standards or {}),
        "",
        "3. UNRESOLVED FACTS AND ASSUMPTIONS",
        *_unresolved(project),
        "  UNRESOLVED_INTERPRETATION: the engine's readings of what the orders leave open, each "
        "taken for this test (siteplan constraints lists what would settle each):",
        *(f"    - {c.what} {c.value}." for c in by_basis(Basis.UNRESOLVED_INTERPRETATION)),
        "  ENGINE_DESIGN_ASSUMPTION: the engine's own numbers, neither law nor the firm's "
        "standards:",
        *(f"    - {c.what} {c.value}." for c in by_basis(Basis.ENGINE_DESIGN_ASSUMPTION)),
        "",
        "4. HEIGHT",
        *_heights(generated),
        "",
        "5. LAYOUTS THAT PASS",
    ]
    if not generated.found.options:
        lines.append("  None: no height has a layout that passes every rule.")
    gross = generated.project["site"].get("gross_area_sqm") or generated.plot.area
    for summary, option in zip(generated.options, generated.found.options, strict=True):
        lines += _option(summary, option, generated.plot, gross)
    lines += ["", "6. REJECTED CANDIDATES", *_rejected(generated.found)]
    width = max(len(r[0]) for r in rows)
    lines += ["", "7. COMPARED WITH THE FIRM'S PLAN (read only now)",
              f"  {'':<{width}}  Engine  |  Firm"]
    lines += [f"  {name:<{width}}  {ours}  |  {theirs}" for name, ours, theirs in rows]
    return "\n".join(lines)


def _inputs(project: dict, standards: dict) -> list[str]:
    site, layout = project["site"], project["layout"]
    values = {**standards, **site, **layout,
              "water": ", ".join(f"{w['kind']} in {w.get('survey_colour') or w.get('survey_layer')}"
                                 for w in site.get("water", [])) or "none",
              "road_strip": (f"{site['road_strip_width_m']:g} m off the "
                             f"{site.get('road_strip_side', '?')} side"
                             if site.get("road_strip_width_m") else ""),
              "conservative_parking": "GHMC column planned while the jurisdiction is open"
              if layout.get("conservative_parking") else "",
              "abutting_road": (f"{site['abutting_road_ft']:g} ft" if "abutting_road_ft" in site
                                else f"{site.get('abutting_road_m', 0):g} m")
              + f" ({site.get('abutting_road_status', '')})",
              "floors": ("max: stilt + " if layout.get("maximise") else "stilt + ")
              + str(layout["floors"])}
    out = []
    for key, status in project.get("status", {}).items():
        value = values.get(key, "")
        if isinstance(value, dict):
            value = ", ".join(f"{k} {v:.0%}" if isinstance(v, float) else f"{k} {v}"
                              for k, v in value.items())
        if value in (None, ""):
            value = "not known" if status == Provenance.UNVERIFIED else "-"
        source = project.get("sources", {}).get(key, "")
        out.append(f"  {key}: {value}  [{status}]  {source}")
    return out


def _unresolved(project: dict) -> list[str]:
    weak = [(k, s) for k, s in project.get("status", {}).items()
            if s in (Provenance.UNVERIFIED, Provenance.ASSUMED_FOR_TEST)]
    if not weak:
        return ["  Every input is confirmed."]
    return [f"  - {key}: {status}" for key, status in weak]


def _heights(generated: Generated) -> list[str]:
    found, limit = generated.found, generated.limit
    legal, feasible = found.max_legal_floors, found.max_feasible_floors
    stilt = generated.project["layout"]["stilt_height_m"]
    floor_h = generated.project["layout"]["floor_height_m"]

    def height(floors: int | None) -> str:
        return "none" if floors is None else f"stilt + {floors} ({stilt + floors * floor_h:g} m)"

    road_status = generated.project.get("status", {}).get("abutting_road", "not recorded")
    lines = [f"  Maximum legally allowed: {height(legal)}, resting on the abutting road's width "
             f"[{road_status}]; the floors calculator: stilt + "
             f"{limit.floors_stilt_counted} if the stilt counts, stilt + "
             f"{limit.floors_stilt_not_counted} if not, stopped by {limit.limited_by}",
             f"  Maximum geometrically feasible: {height(feasible)}",
             "  Height by height, top down:"]
    for r in found.results:
        lines.append(f"    stilt + {r.floors} ({r.height_m:g} m): {r.verdict}"
                     + (f", {len(r.options)} passing layout{'s' if len(r.options) != 1 else ''}"
                        if r.options else ""))
        lines += [f"      - {reason}" for reason in r.reasons()]
    return lines


def _option(summary: dict, option: LayoutOption, plot: Polygon, gross_sqm: float) -> list[str]:
    parking = summary["parking"]
    tot_lot_need = rules.OPEN_SPACE_MIN_FRACTION * max(plot.area, gross_sqm)
    club_need = (rules.AMENITY_MIN_BUILT_UP_FRACTION * option.built_up_sqm
                 if option.total_flats >= rules.AMENITY_MIN_UNITS else 0.0)
    towers = ", ".join(f"{t.name} {t.length_m:.0f} m" for t in option.towers)
    by_type = ", ".join(f"{k} {n}" for k, n in summary["flats_by_type"].items())
    asked = ", ".join(f"{k} {v:.0%}" for k, v in sorted(option.unit_mix_target.items()))
    got = ", ".join(f"{k} {v:.1%}" for k, v in summary["unit_mix_achieved"].items())
    setback, gap = spacing(plot, [t.footprint for t in option.towers])
    roads = summary["roads"]
    kinds = {}
    for road in roads:
        kinds.setdefault(road["kind"], []).append(road)
    road_line = "; ".join(f"{kind} {rs[0]['width_m']:g} m" + (f" x {len(rs)}" if len(rs) > 1
                                                              else "")
                          for kind, rs in kinds.items())
    fire = [f for f in option.findings if f.rule.startswith("Fire access")]
    counts = {s: sum(f.status is s for f in option.findings) for s in Status}
    lines = [
        "",
        f"  Option {summary['option']}: stilt + {option.floors} ({option.height_m:g} m), "
        f"{summary['towers']} towers ({towers})",
        f"    Flats: {summary['total_flats']} ({by_type}); mix {got} against {asked}",
        f"    Areas: tower floor {summary['tower_floor_sqft']:,} sft = flats' own "
        f"{summary['flats_own_sqft']:,} + common and core {summary['common_core_sqft']:,} "
        f"({summary['core_share_pct']}%); saleable {summary['saleable_sqft']:,} sft "
        f"({summary['saleable_basis']}); club house {summary['amenity_sqft']:,} sft; parking "
        f"{summary['parking_sqft']:,} sft",
        f"    Roads: {road_line}; entrance {option.entrance.note if option.entrance else '-'}",
        f"    Fire access: {sum(f.status is Status.PASS for f in fire)} of {len(fire)} checks "
        "pass; " + "; ".join(f"{f.rule.removeprefix('Fire access: ')} {f.status.value}"
                            for f in fire if f.status is not Status.PASS),
        f"    Parking: required {parking.get('required_sqm', 0):,} m² "
        f"({parking.get('percent', 0):g}%, {parking.get('basis', '')}); provided "
        f"{parking.get('provided_sqm', 0):,} m² of floor = stilt {parking.get('stilt_sqm', 0):,} + "
        f"surface {parking.get('surface_sqm', 0):,} + {parking.get('cellar_levels', 0)} cellar "
        f"level(s) x {parking.get('cellar_sqm_per_level', 0):,}; {parking.get('total_cars', 0):,} "
        f"cars laid out in bays and aisles = {parking.get('laid_out_sqm', 0):,} m² "
        f"{parking.get('cars', {})}; ramp {parking.get('ramp', 'none')}; "
        f"{parking.get('bay_standard', '')}",
        f"    Tot-lot: required {tot_lot_need:,.0f} m² (10% of the larger of the net and gross "
        f"site); provided {summary['open_space_sqm']:,.0f} m² in {len(option.open_space)} "
        f"pocket(s), {summary['open_space_share_pct']}% of the net plot",
        f"    Club house: required {club_need:,.0f} m² "
        f"({rules.AMENITY_MIN_BUILT_UP_FRACTION:.0%} of the built-up area from "
        f"{rules.AMENITY_MIN_UNITS} units: the planning minimum ASSUMED_FOR_TEST, an "
        "UNRESOLVED_INTERPRETATION of the 2016 wording); "
        f"provided {summary['club_house_sqm']:,.0f} m² built-up on "
        f"{summary['club_house_footprint_sqm']:,.0f} m²; facilities placed: "
        f"{', '.join(a['name'] for a in summary['amenities']) or 'none'}"
        + (f"; no room for: {', '.join(summary['amenities_with_no_room'])}"
           if summary["amenities_with_no_room"] else ""),
        f"    Setbacks and spacing: least setback {setback:.2f} m, least gap "
        + (f"{gap:.2f} m" if gap is not None else "- (one tower)"),
        f"    Rules: {counts[Status.PASS]} PASS, {counts[Status.FAIL]} FAIL, "
        f"{counts[Status.UNVERIFIED] + counts[Status.NOT_CHECKED]} UNVERIFIED",
    ]
    for f in option.findings:
        if f.status is Status.INFO:
            continue
        shown = "UNVERIFIED" if f.status is Status.NOT_CHECKED else f.status.value
        lines.append(f"      {shown:<10} {f.rule}: {f.measured} (needs {f.required})")
    return lines


def _rejected(found: HeightSearch) -> list[str]:
    lines = []
    for r in found.results:
        if r.search is None or not r.search.rejected:
            continue
        lines.append(f"  stilt + {r.floors}: {len(r.search.rejected)} candidate"
                     f"{'s' if len(r.search.rejected) != 1 else ''} drawn and failed")
        for rejected in r.search.rejected[:3]:
            sale = (f", {rejected.saleable_sqft:,.0f} sft saleable" if rejected.saleable_sqft
                    else "")
            lines.append(f"    {rejected.towers} towers at {rejected.orientation_deg:.0f}°"
                         f"{sale}: " + "; ".join(rejected.reasons[:3]))
    return lines or ["  None: every candidate drawn exactly passed the checker."]
