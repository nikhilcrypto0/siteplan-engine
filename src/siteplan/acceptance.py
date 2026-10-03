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
from siteplan.access import FIRE_BAND_M
from siteplan.area_statement import AreaStatement
from siteplan.blind import BLIND, DEBUG, BlindLeak, finished_values
from siteplan.blind import check as check_blind
from siteplan.cases import Case
from siteplan.constraints import Basis, by_basis
from siteplan.findings import Status
from siteplan.heights import HeightSearch
from siteplan.intake import Draft, build_project, extract, load_defaults, save
from siteplan.intake import render as render_draft
from siteplan.layout import LayoutOption, missing_strategies
from siteplan.library import FlatLibrary
from siteplan.max_floors import FloorLimit, max_floors
from siteplan.profiles import AssumptionProfile, apply_profile, describe
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
    profile: AssumptionProfile | None = None  # a site's temporary test assumptions, if any
    mode: str = BLIND  # 'debug' when the run may use the firm's finished plan


def generate(survey: Path, answers: dict, out: Path, workspace: Path | None = None,
             conservative_parking: bool = False,
             profile: AssumptionProfile | None = None, mode: str = BLIND) -> Generated:
    """Everything the engine produces from the raw survey and the answers alone. With
    conservative_parking, an unestablished jurisdiction plans the GHMC column (a labelled test
    mode) instead of stopping to ask. A profile sets one site's temporary test assumptions on
    top of the answers, each recorded ASSUMED_FOR_TEST and listed in the report. A blind run
    (the default) refuses anything taken from the firm's finished plan (blind.py); a debug run
    may use it and says so in the report."""
    workspace = workspace or survey.parent
    defaults = load_defaults(workspace)
    check_blind(mode, survey, answers, profile, defaults.finished_plans)
    if not defaults.flat_library:
        raise ValueError(f"Set the firm's flat_library in {workspace}/siteplan.workspace.json.")
    draft = extract(survey)
    project_dict = build_project(draft, answers, defaults)
    if conservative_parking:
        project_dict["layout"]["conservative_parking"] = True
        project_dict["sources"]["conservative_parking"] = "run in the conservative test mode"
        project_dict["status"]["conservative_parking"] = Provenance.ASSUMED_FOR_TEST
    if profile is not None:
        project_dict = apply_profile(project_dict, profile)
    leaked = finished_values(project_dict)
    if mode == BLIND and leaked:
        raise BlindLeak(f"A blind acceptance run may not use the firm's finished plan: {leaked}")
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
                     defaults.model_dump(exclude={"status"}), profile, mode)


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
    profile = generated.profile
    debug = generated.mode == DEBUG or (profile is not None and profile.debug_fixture)
    lines = [
        f"{'DEBUG RUN (test fixture, not blind acceptance)' if debug else 'ACCEPTANCE'}: "
        f"{project['name']}",
        "The plot outline comes from the firm's finished plan; the towers, roads and everything "
        "else were generated, and the firm's plan was read again only for the comparison."
        if debug else
        "The generator saw the raw survey, the answers and the firm's standard libraries; the "
        "firm's plan for this site was read only for the comparison at the end.",
        "",
        *(["0. TEST PROFILE: TEMPORARY ASSUMPTIONS FOR THIS SITE ONLY", *describe(profile), ""]
          if profile is not None else []),
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
    lines += [f"  {missing}" for missing in missing_strategies(generated.found.options)]
    gross = generated.project["site"].get("gross_area_sqm") or generated.plot.area
    assumed = sorted(k for k, s in project.get("status", {}).items()
                     if s == Provenance.ASSUMED_FOR_TEST)
    for summary, option in zip(generated.options, generated.found.options, strict=True):
        lines += _option(summary, option, generated.plot, gross, assumed)
    if generated.found.options:
        lines += ["", "5a. COMPARISON", *_comparison(generated.options, generated.plot)]
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
    layout = generated.project["layout"]
    stilt, floor_h = layout["stilt_height_m"], layout["floor_height_m"]
    counted = layout.get("stilt_in_rule_height", True)

    def height(floors: int | None) -> str:
        if floors is None:
            return "none"
        physical = stilt + floors * floor_h
        if counted:
            return f"stilt + {floors} ({physical:g} m)"
        return f"stilt + {floors} ({floors * floor_h:g} m for the rules, {physical:g} m physical)"

    road_status = generated.project.get("status", {}).get("abutting_road", "not recorded")
    lines = [f"  Maximum legally allowed: {height(legal)}, resting on the abutting road's width "
             f"[{road_status}]; the floors calculator: stilt + "
             f"{limit.floors_stilt_counted} if the stilt counts, stilt + "
             f"{limit.floors_stilt_not_counted} if not, stopped by {limit.limited_by}",
             f"  Maximum geometrically feasible: {height(feasible)}",
             "  Height by height, top down:"]
    for r in found.results:
        physical = (f", {r.physical_height_m:g} m physical" if r.physical_height_m
                    and abs(r.physical_height_m - r.height_m) > 1e-6 else "")
        lines.append(f"    stilt + {r.floors} ({r.height_m:g} m for the rules{physical}): "
                     f"{r.verdict}"
                     + (f", {len(r.options)} passing layout{'s' if len(r.options) != 1 else ''}"
                        if r.options else ""))
        lines += [f"      - {reason}" for reason in r.reasons()]
    return lines


def _option(summary: dict, option: LayoutOption, plot: Polygon, gross_sqm: float,
            assumed: list[str] | None = None) -> list[str]:
    parking = summary["parking"]
    tot_lot_need = rules.OPEN_SPACE_MIN_FRACTION * max(plot.area, gross_sqm)
    club_need = (rules.AMENITY_MIN_BUILT_UP_FRACTION * option.built_up_sqm
                 if option.total_flats >= rules.AMENITY_MIN_UNITS else 0.0)
    total = summary["total_flats"] or 1
    by_type = ", ".join(f"{k} {n} ({n / total:.1%})" for k, n in summary["flats_by_type"].items())
    asked = ", ".join(f"{k} {v:.0%}" for k, v in sorted(option.unit_mix_target.items()))
    setback, gap = spacing(plot, [t.footprint for t in option.towers])
    band = rules.band_for_height(option.height_m)
    need = band.min_open_space_m if band else None
    kinds: dict[str, list] = {}
    for road in summary["roads"]:
        kinds.setdefault(road["kind"], []).append(road)
    road_line = "; ".join(f"{kind} {rs[0]['width_m']:g} m" + (f" x {len(rs)}" if len(rs) > 1
                                                              else "")
                          for kind, rs in kinds.items() if kind != "perimeter")
    lane = kinds.get("perimeter")
    lane_line = (f"perimeter lane {lane[0]['width_m']:g} m inside the setback "
                 "(ASSUMED_FOR_TEST; not counted as a rule 8(m) road); " if lane else "")
    fire = [f for f in option.findings if f.rule.startswith("Fire access")]
    counts = {s: sum(f.status is s for f in option.findings) for s in Status}
    physical = summary.get("physical_height_m", option.height_m)
    title = summary.get("strategy") or f"Option {summary['option']}"
    lines = [
        "",
        f"  {title}: {summary['towers']} tower{'s' if summary['towers'] != 1 else ''}, "
        f"stilt + {option.floors}; height used for the rules {option.height_m:g} m "
        f"({physical:g} m physical, stilt included)",
        "    Towers:",
        *(f"      {d['name']}: {d['length_m']:g} x {d['width_m']:g} m, {d['flats_per_floor']} "
          f"flats per floor ({_by_type(d['flats_per_floor_by_type'])}), "
          f"{d['cores']} core{'s' if d['cores'] != 1 else ''}, "
          f"{d['flats_per_core_per_floor']:g} flats per core per floor, {d['flats']} flats"
          for d in summary.get("towers_detail", [])),
        f"    Flats: {summary['total_flats']}: {by_type}; asked {asked}",
        f"    Areas: built-up {summary['built_up_sqft']:,} sft (towers "
        f"{summary['tower_floor_sqft']:,} + club house {summary['amenity_sqft']:,}); saleable "
        f"{summary['saleable_sqft']:,} sft "
        f"({summary['saleable_basis']}); common and core {summary['core_share_pct']}% of the "
        "tower floor",
        f"    Parking: required {parking.get('required_sqm', 0):,} m² "
        f"({parking.get('percent', 0):g}%, {parking.get('basis', '')}); provided "
        f"{parking.get('provided_sqm', 0):,} m² of floor = stilt {parking.get('stilt_sqm', 0):,} + "
        f"surface {parking.get('surface_sqm', 0):,} + {parking.get('cellar_levels', 0)} cellar "
        f"level(s) x {parking.get('cellar_sqm_per_level', 0):,}; {parking.get('total_cars', 0):,} "
        f"cars laid out = {parking.get('laid_out_sqm', 0):,} m² {parking.get('cars', {})}; ramp "
        f"{parking.get('ramp', 'none')}; {parking.get('bay_standard', '')}",
        f"    Club house: required {club_need:,.0f} m² "
        f"({rules.AMENITY_MIN_BUILT_UP_FRACTION:.0%} of the built-up area from "
        f"{rules.AMENITY_MIN_UNITS} units: the planning minimum ASSUMED_FOR_TEST, an "
        "UNRESOLVED_INTERPRETATION of the 2016 wording); "
        f"provided {summary['club_house_sqm']:,.0f} m² built-up on "
        f"{summary['club_house_footprint_sqm']:,.0f} m²",
        f"    Amenities: placed {', '.join(a['name'] for a in summary['amenities']) or 'none'}"
        + (f"; no room for {', '.join(summary['amenities_with_no_room'])}"
           if summary["amenities_with_no_room"] else ""),
        f"    Tot-lot: required {tot_lot_need:,.0f} m² (10% of the larger of the net and gross "
        f"site); provided {summary['open_space_sqm']:,.0f} m² in {len(option.open_space)} "
        f"pocket(s), {summary['open_space_share_pct']}% of the net plot",
        f"    Setback: required {need:g} m (Table IV at {option.height_m:g} m); least actual "
        f"{setback:.2f} m" if need is not None else f"    Setback: least actual {setback:.2f} m",
        (f"    Tower spacing: required {need:g} m; least actual {gap:.2f} m" if gap is not None
         else "    Tower spacing: one tower"),
        f"    Internal roads (rule 8(m)): {road_line}; entrance "
        f"{option.entrance.note if option.entrance else '-'}",
        f"    Fire lanes: {lane_line}clear motorable band round every tower at least "
        f"{FIRE_BAND_M:.2f} m (derived from the 9 m turning radius on our reading, "
        f"UNRESOLVED_INTERPRETATION); {summary['fire_lanes_sqm']:,.0f} m² of fire lane",
        f"    Fire access: {sum(f.status is Status.PASS for f in fire)} of {len(fire)} checks "
        "pass; " + "; ".join(f"{f.rule.removeprefix('Fire access: ')} {f.status.value}"
                            for f in fire if f.status is not Status.PASS),
        f"    Rules: {counts[Status.PASS]} PASS, {counts[Status.FAIL]} FAIL, "
        f"{counts[Status.UNVERIFIED]} UNVERIFIED, {counts[Status.NOT_CHECKED]} NOT_CHECKED",
    ]
    for f in option.findings:
        if f.status is Status.INFO:
            continue
        lines.append(f"      {f.status.value:<11} {f.rule}: {f.measured} (needs {f.required})")
    if assumed:
        lines.append(f"    ASSUMED_FOR_TEST in this run: {', '.join(assumed)}")
    return lines


def _by_type(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {n}" for k, n in counts.items())


def _comparison(summaries: list[dict], plot: Polygon) -> list[str]:
    """The options side by side, one measure per row."""
    def cell(s: dict, key: str) -> str:
        p = s.get("parking", {})
        d = s.get("towers_detail", [])
        values = {
            "Towers": str(s["towers"]),
            "Floors": f"stilt + {s['floors_above_stilt']}",
            "Height for the rules": f"{s['rule_height_m']:g} m",
            "Flats": str(s["total_flats"]),
            "2BHK / 3BHK": " / ".join(str(s["flats_by_type"].get(k, 0)) for k in ("2BHK", "3BHK")),
            "Flats per floor per tower": ", ".join(str(t["flats_per_floor"]) for t in d),
            "Cores per tower": ", ".join(str(t["cores"]) for t in d),
            "Longest tower": f"{max((t['length_m'] for t in d), default=0):g} m",
            "Built-up": f"{s['built_up_sqft']:,} sft",
            "Saleable": f"{s['saleable_sqft']:,} sft",
            "Parking req / prov": f"{p.get('required_sqm', 0):,} / "
                                  f"{min(p.get('provided_sqm', 0), p.get('laid_out_sqm', 0)):,} m²",
            "Cars": f"{p.get('total_cars', 0):,}",
            "Tot-lot": f"{s['open_space_share_pct']}%",
            "Club house": f"{s['club_house_sqm']:,.0f} m²",
            "Facilities missed": str(len(s["amenities_with_no_room"])),
            "Internal roads": ", ".join(sorted({f"{r['kind']} {r['width_m']:g} m"
                                                for r in s["roads"]
                                                if r["kind"] != "perimeter"})),
            "Fire lane": ", ".join(sorted({f"{r['width_m']:g} m perimeter"
                                           for r in s["roads"] if r["kind"] == "perimeter"}))
            or "loop road",
            "PASS/FAIL/UNVERIFIED/NOT_CHECKED": " / ".join(
                str(list(s["rule_findings"].values()).count(k))
                for k in ("PASS", "FAIL", "UNVERIFIED", "NOT_CHECKED")),
        }
        return values[key]

    keys = ["Towers", "Floors", "Height for the rules", "Flats", "2BHK / 3BHK",
            "Flats per floor per tower", "Cores per tower", "Longest tower", "Built-up",
            "Saleable", "Parking req / prov", "Cars", "Tot-lot", "Club house",
            "Facilities missed", "Internal roads", "Fire lane",
            "PASS/FAIL/UNVERIFIED/NOT_CHECKED"]
    names = [(s.get("strategy") or f"Option {s['option']}").split(":")[0] for s in summaries]
    width = max(len(k) for k in keys)
    lines = [f"  {'':<{width}}  " + "  |  ".join(names)]
    lines += [f"  {k:<{width}}  " + "  |  ".join(cell(s, k) for s in summaries) for k in keys]
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
