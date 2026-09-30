"""Acceptance: the whole flow on a real site, with the firm's own plan kept out until the end.

raw survey -> extract -> the architect's answers -> project -> the most floors -> layouts, each
re-checked -> compared with the firm's plan. `generate` is given the survey, the answers and
the firm's standard libraries, never its plan for this site; `compare` reads the plan (a case
traced from the firm's drawing, and its area statement) only once the layouts exist, so the
expected answer cannot leak into them. Setbacks and gaps are measured from the DXF each option
is delivered as, the file the firm would open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import ezdxf
from shapely.geometry import Point, Polygon

from siteplan.area_statement import AreaStatement
from siteplan.cases import Case
from siteplan.intake import build_project, extract, load_defaults, save
from siteplan.library import FlatLibrary
from siteplan.max_floors import FloorLimit, max_floors
from siteplan.project import Project
from siteplan.runner import load_plot, load_water, run_layout
from siteplan.site_amenities import AmenityLibrary

BUILDING_LAYER = "Building Plan"  # the BuildNow layer the towers are delivered on
TOWER_NAME = re.compile(r"T\d+")


@dataclass(frozen=True)
class Generated:
    project: dict
    plot: Polygon
    basis: str
    limit: FloorLimit
    options: list[dict]
    out: Path


def generate(survey: Path, answers: dict[str, str], out: Path,
             workspace: Path | None = None) -> Generated:
    """Everything the engine produces from the raw survey and the answers alone."""
    workspace = workspace or survey.parent
    defaults = load_defaults(workspace)
    if not defaults.flat_library:
        raise ValueError(f"Set the firm's flat_library in {workspace}/siteplan.workspace.json.")
    project_dict = build_project(extract(survey), answers, defaults)
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
    options = run_layout(project, library, plot, project.layout, out, amenities, keep_out)
    return Generated(project_dict, plot, basis, limit, options, out)


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
        ours = best["saleable_sqft"]  # the plates: every square foot of tower floor
        firm_area = sum(g.subtotal_sqft for g in statement.groups)
        loading = statement.groups[0].common_area_pct
        rows += [
            ("Tower floor area, all floors, no loading", f"{ours:,} sft",
             f"{firm_area:,.0f} sft (engine {(ours / firm_area - 1) * 100:+.1f}%)"),
            (f"The same with the firm's {loading:g}% loading",
             f"{ours * (1 + loading / 100):,.0f} sft", f"{statement.total_sqft:,} sft"),
        ]
    fails = [rule for rule, status in best["rule_findings"].items() if status == "FAIL"]
    rows.append(("Rule FAILs (engine's checker)", ", ".join(fails) or "none",
                 f"{len(case.known_disagreements)} known, as the case records"))
    return rows


def report(generated: Generated, rows: list[tuple[str, str, str]]) -> str:
    """Plain text for the terminal and the report file."""
    limit = generated.limit
    tried = generated.options[0].get("heights_tried", [])
    lines = [
        f"Plot: {generated.plot.area:,.0f} m², {generated.basis}",
        f"Most floors: stilt + {limit.floors_stilt_counted} if the stilt counts, stilt + "
        f"{limit.floors_stilt_not_counted} if not; stopped by {limit.limited_by}",
    ]
    if tried:
        lines.append("Heights tried: " + "; ".join(
            f"stilt + {t['floors_above_stilt']}: best {t['best_saleable_sqft']:,} sft"
            for t in tried))
    lines.append("")
    for option in generated.options:
        fails = [r for r, s in option["rule_findings"].items() if s == "FAIL"]
        lines.append(f"Option {option['option']}: {option['towers']} towers at stilt + "
                     f"{option['floors_above_stilt']}, {option['total_flats']} flats, "
                     f"{option['saleable_sqft']:,} sft of tower floor, mix "
                     f"{option['unit_mix_achieved']}, FAILs: {', '.join(fails) or 'none'}")
    width = max(len(r[0]) for r in rows)
    lines += ["", f"{'Compared with the firm (read only now)':<{width}}  Engine  |  Firm"]
    lines += [f"{name:<{width}}  {ours}  |  {theirs}" for name, ours, theirs in rows]
    return "\n".join(lines)
