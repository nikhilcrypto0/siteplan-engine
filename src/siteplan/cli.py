"""Command line: `siteplan survey`, `siteplan check`, `siteplan area-statement`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from siteplan.area_statement import render
from siteplan.checks import Status, check_site
from siteplan.dxf_export import write_survey_dxf
from siteplan.dxf_survey import read_dxf_survey
from siteplan.pdf_survey import read_pdf_survey
from siteplan.project import Project
from siteplan.survey import Survey


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

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (ValueError, ValidationError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
