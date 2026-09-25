"""Command line: survey, check, area-statement, layout, assist."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from siteplan import rules
from siteplan.area_statement import render
from siteplan.checks import Status, check_site
from siteplan.dxf_export import write_survey_dxf
from siteplan.library import FlatLibrary
from siteplan.llm import AssistantConfig
from siteplan.project import Project
from siteplan.runner import LAYOUT_CAVEAT, load_plot, read_survey, run_layout
from siteplan.site_amenities import AmenityLibrary
from siteplan.wizard import build_project, collect


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


def _print_options(summaries: list[dict]) -> None:
    for summary in summaries:
        fails = [rule for rule, status in summary["rule_findings"].items() if status == "FAIL"]
        print(
            f"Option {summary['option']}: {_count(summary['towers'], 'tower')}, "
            f"{summary['total_flats']} flats, {summary['saleable_sqft']:,} sft saleable, "
            f"open space {summary['open_space_share_pct']}%, mix {summary['unit_mix_achieved']}"
        )
        print(f"          rule FAILs: {', '.join(fails) or 'none'}")


def _cmd_layout(args: argparse.Namespace) -> int:
    project = _load_project(args.project)
    if project.layout is None:
        print("The project file has no layout section.", file=sys.stderr)
        return 2
    library = FlatLibrary.model_validate_json(Path(args.library).read_text())
    amenities = (
        AmenityLibrary.model_validate_json(Path(args.amenities).read_text())
        if args.amenities else None
    )
    plot, basis = load_plot(project, args.survey)
    print(f"Layout: {project.name}\nPlot: {plot.area:,.0f} m², {basis}\n")
    out = Path(args.out)
    summaries = run_layout(project, library, plot, project.layout, out, amenities)
    if not summaries:
        print("No tower fits inside the setbacks with the required open space.")
        return 1
    _print_options(summaries)
    print(f"\nWrote option_1..{len(summaries)} (.dxf, .svg, .json) to {out}/")
    if library.note:
        print(f"Flat library: {library.note}")
    print(LAYOUT_CAVEAT)
    return 0


def _cmd_new(args: argparse.Namespace) -> int:
    """Ask a few questions and write the project file the other commands read."""
    print("A few questions about the site. Press enter to take the value in brackets.\n")
    project = build_project(collect(input))
    out = Path(args.out or f"{_slug(project['name'])}.project.json")
    if out.exists() and (input(f"\n{out} exists. Overwrite? [y/N]: ").strip().lower() != "y"):
        print("Left it alone.")
        return 1
    Project.model_validate(project)  # refuse to write a file the tool cannot read back
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(project, indent=2) + "\n")
    print(f"\nWrote {out}")
    print("\nNext, to draw layouts:")
    print(f"  uv run siteplan layout {out} --library <flat library>.json \\")
    print("      --survey <survey>.pdf --amenities examples/amenities.example.json")
    return 0


def _slug(name: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", name.lower())) or "project"


def _cmd_rules(args: argparse.Namespace) -> int:
    if args.height:
        for key, value in rules.height_rules(args.height).items():
            print(f"{key}: {value}")
        return 0
    from siteplan.rulebook import RuleBook  # only a document search pays for pdfplumber

    hits = RuleBook.load(args.document).search(args.question, limit=args.limit)
    if not hits:
        print("The document does not answer that. Try other words, or ask the firm.")
        return 1
    for hit in hits:
        print(f"\n--- page {hit.page} ---\n{hit.text}")
        if hit.superseded_by:
            print(f"\n!! SUPERSEDED: {hit.superseded_by}")
    return 0


def _ask_architect(question: dict) -> dict:
    """Show the interpreted request and get an explicit decision. There is no skip flag."""
    print("\nThe assistant read the brief as:")
    print(json.dumps(question["request"], indent=2))
    for title, key in (("Defaults it will use", "assumptions"), ("Still missing", "missing"),
                       ("Values the brief never stated (check these)", "flagged"),
                       ("Parts of the brief it could not use", "unclear")):
        if question.get(key):
            print(f"{title}:")
            for item in question[key]:
                print(f"  - {item}")
    while True:
        answer = input("\nApprove? [y]es / [e]dit / [n]o: ").strip().lower()
        if answer in {"y", "yes"}:
            return {"approve": True}
        if answer in {"n", "no"}:
            return {"approve": False}
        if answer in {"e", "edit"}:
            example = '{"floors": 8, "unit_mix": {"2BHK": 0.7, "3BHK": 0.3}}'
            raw = input(f"Edits as JSON, e.g. {example}: ")
            try:
                return {"approve": True, "edits": json.loads(raw)}
            except json.JSONDecodeError:
                print("That was not valid JSON; try again.")


def _cmd_assist(args: argparse.Namespace) -> int:
    from siteplan.assistant import Assistant  # keeps LangGraph off the plain CLI paths
    from siteplan.llm import OpenAICompatibleModel

    config = (
        AssistantConfig.model_validate_json(Path(args.config).read_text())
        if args.config
        else AssistantConfig()
    )
    Path(config.log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(config.log_file)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger("siteplan.assistant").addHandler(handler)
    logging.getLogger("siteplan.assistant").setLevel(logging.INFO)

    project = _load_project(args.project)
    library = FlatLibrary.model_validate_json(Path(args.library).read_text())
    plot, basis = load_plot(project, args.survey)
    brief = args.brief if args.brief else Path(args.brief_file).read_text()
    out = Path(args.out)
    assistant = Assistant(OpenAICompatibleModel(config), config, project, library, plot, out)
    print(f"Assistant: {project.name} | plot {plot.area:,.0f} m², {basis} | model {config.model}")

    result = assistant.start(brief)
    while (question := Assistant.pending_question(result)) is not None:
        result = assistant.resume(_ask_architect(question))

    record = {k: v for k, v in result.items() if not k.startswith("__")}
    record["tokens_used"] = assistant.meter.run_used
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps(record, indent=2, default=str))
    if result.get("options"):
        print()
        _print_options(result["options"])
    if result.get("status"):
        print(f"\n{result['status']}")
        return 1
    labels = {"code": "computed", "code + model commentary": "computed, plus model commentary"}
    print(f"\nComparison ({labels[result['explanation_source']]}):\n{result['explanation']}")
    print(f"\nFiles and run record in {out}/ | tokens used: {assistant.meter.run_used:,}")
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
    p.add_argument("--amenities", help="Amenity library JSON: pool, courts, play area, cabin")
    p.add_argument("--out", default="out/layout")
    p.set_defaults(run=_cmd_layout)

    p = sub.add_parser("new", help="Answer a few questions; write the project file.")
    p.add_argument("--out", help="Where to write it (default: from the project name)")
    p.set_defaults(run=_cmd_new)

    p = sub.add_parser("rules", help="Answer a rule question from the order, with its page.")
    p.add_argument("question", nargs="?", default="", help="The question, in plain English")
    p.add_argument("--height", type=float, help="Skip the search: the Table IV row for a height")
    p.add_argument("--document", default="fixtures/rules/go168-2012.pdf")
    p.add_argument("--limit", type=int, default=3)
    p.set_defaults(run=_cmd_rules)

    p = sub.add_parser("assist", help="Plain-English brief -> approved request -> layouts.")
    p.add_argument("project")
    p.add_argument("--library", required=True, help="Flat library JSON")
    brief = p.add_mutually_exclusive_group(required=True)
    brief.add_argument("--brief", help="The brief, in plain English")
    brief.add_argument("--brief-file", help="A text file holding the brief")
    p.add_argument("--survey", help="Survey PDF/DXF, used when the project has no net_plot_m")
    p.add_argument("--config", help="Assistant config JSON (model endpoint, budgets)")
    p.add_argument("--out", default="out/assist")
    p.set_defaults(run=_cmd_assist)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (ValueError, ValidationError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
