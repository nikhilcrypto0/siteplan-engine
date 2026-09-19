"""Command line: `siteplan survey`, `siteplan check`, `siteplan area-statement`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError
from shapely.geometry import Polygon

from siteplan.area_statement import render
from siteplan.checks import Status, check_site
from siteplan.dxf_export import write_survey_dxf
from siteplan.dxf_survey import read_dxf_survey
from siteplan.layout import area_statement, solve
from siteplan.layout_export import write_layout_dxf, write_layout_svg
from siteplan.library import FlatLibrary
from siteplan.pdf_survey import read_pdf_survey
from siteplan.project import Project
from siteplan.survey import Survey

LAYOUT_CAVEAT = (
    "Layouts are first drafts for an architect: v0 ignores the club house, amenities, "
    "parking ramps and driveway connections, and uses whatever flat library it is given."
)


def read_survey(path: Path) -> Survey:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_survey(path)
    if suffix == ".dxf":
        return read_dxf_survey(path)
    if suffix == ".dwg":
        raise ValueError("DWG is not read directly. Save it as DXF in ZWCAD first.")
    raise ValueError(f"Unsupported survey file type: {path.suffix}")


def _cmd_survey(args: argparse.Namespace) -> int:
    path = Path(args.file)
    survey = read_survey(path)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = survey.summary()
    (out_dir / f"{path.stem}.survey.json").write_text(json.dumps(summary, indent=2))
    dxf = write_survey_dxf(survey, out_dir / f"{path.stem}.buildnow.dxf")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {out_dir / (path.stem + '.survey.json')} and {dxf}")
    return 0


def _load_project(file: str) -> Project:
    return Project.model_validate_json(Path(file).read_text())


def _cmd_check(args: argparse.Namespace) -> int:
    project = _load_project(args.project)
    findings = check_site(project.to_site())
    if args.json:
        rows = [f.__dict__ | {"status": f.status.value} for f in findings]
        print(json.dumps(rows, indent=2))
    else:
        print(f"Rule check: {project.name}\n")
        for f in findings:
            print(f"[{f.status.value:<11}] {f.rule}")
            print(f"              measured {f.measured} | required {f.required}")
            print(f"              {f.clause}" + (f"\n              {f.note}" if f.note else ""))
    return 1 if any(f.status is Status.FAIL for f in findings) else 0


def _cmd_area_statement(args: argparse.Namespace) -> int:
    project = _load_project(args.project)
    if project.area_statement is None:
        print("The project file has no area_statement section.", file=sys.stderr)
        return 2
    print(render(project.area_statement))
    return 0


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _cmd_layout(args: argparse.Namespace) -> int:
    project = _load_project(args.project)
    if project.layout is None:
        print("The project file has no layout section.", file=sys.stderr)
        return 2
    library = FlatLibrary.model_validate_json(Path(args.library).read_text())
    if project.site.net_plot_m:
        plot = Polygon(project.site.net_plot_m)
        basis = "net plot from the project file"
    elif args.survey:
        plot = read_survey(Path(args.survey)).boundary
        basis = "surveyed boundary (road-widening strip, if any, NOT deducted)"
    else:
        print("Give --survey, or net_plot_m in the project file.", file=sys.stderr)
        return 2

    site = project.to_site()
    options = solve(
        plot,
        library,
        project.layout,
        gross_area_sqm=site.gross_area_sqm,
        abutting_road_m=site.abutting_road_m,
        master_plan_road_m=site.master_plan_road_m,
    )
    print(f"Layout: {project.name}\nPlot: {plot.area:,.0f} m², {basis}\n")
    if not options:
        print("No tower fits inside the setbacks with the required open space.")
        return 1
    out = Path(args.out)
    for i, option in enumerate(options, 1):
        stem = out / f"option_{i}"
        write_layout_dxf(option, plot, stem.with_suffix(".dxf"))
        write_layout_svg(option, plot, stem.with_suffix(".svg"), f"{project.name}: option {i}")
        summary = option.summary() | {
            "area_statement": render(area_statement(option, project.layout)),
            "flat_library_note": library.note,
            "caveat": LAYOUT_CAVEAT,
        }
        stem.with_suffix(".json").write_text(json.dumps(summary, indent=2))
        fails = [rule for rule, status in summary["rule_findings"].items() if status == "FAIL"]
        print(
            f"Option {i}: {_count(summary['towers'], 'tower')}, {summary['total_flats']} flats, "
            f"{summary['saleable_sqft']:,} sft saleable, open space "
            f"{summary['open_space_share_pct']}%, mix {summary['unit_mix_achieved']}"
        )
        print(f"          rule FAILs: {', '.join(fails) or 'none'}")
    print(f"\nWrote option_1..{len(options)} (.dxf, .svg, .json) to {out}/")
    if library.note:
        print(f"Flat library: {library.note}")
    print(LAYOUT_CAVEAT)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="siteplan", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("survey", help="Read a survey (vector PDF or DXF); write JSON + DXF.")
    p.add_argument("file")
    p.add_argument("--out", default="out")
    p.set_defaults(run=_cmd_survey)

    p = sub.add_parser("check", help="Check a project file against the Telangana rules.")
    p.add_argument("project")
    p.add_argument("--json", action="store_true")
    p.set_defaults(run=_cmd_check)

    p = sub.add_parser("area-statement", help="Print the area statement for a project file.")
    p.add_argument("project")
    p.set_defaults(run=_cmd_area_statement)

    p = sub.add_parser("layout", help="Generate tower layout options for a project.")
    p.add_argument("project")
    p.add_argument("--library", required=True, help="Flat library JSON")
    p.add_argument("--survey", help="Survey PDF/DXF, used when the project has no net_plot_m")
    p.add_argument("--out", default="out/layout")
    p.set_defaults(run=_cmd_layout)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (ValueError, ValidationError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
