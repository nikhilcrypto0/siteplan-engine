"""Command line: survey, check, area-statement, layout, rules, inventory, constraints, floors,
cases, assist."""

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
from siteplan.intake import WORKSPACE_FILE, load_defaults
from siteplan.library import FlatLibrary
from siteplan.llm import AssistantConfig
from siteplan.project import Project
from siteplan.runner import (
    LAYOUT_CAVEAT,
    NoLayout,
    load_plot,
    load_water,
    read_survey,
    run_layout,
)
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
    tried = summaries[0].get("heights_tried") if summaries else None
    if tried:
        print("Heights, top down:")
        for t in tried:
            print(f"  stilt + {t['floors_above_stilt']} ({t['height_m']:g} m): {t['verdict']}")
            for reason in t["reasons"]:
                print(f"    - {reason}")
        print()
    for summary in summaries:
        open_ = [rule for rule, status in summary["rule_findings"].items()
                 if status in ("UNVERIFIED", "NOT_CHECKED")]
        parking = summary.get("parking", {})
        print(
            f"Option {summary['option']}: stilt + {summary['floors_above_stilt']}, "
            f"{_count(summary['towers'], 'tower')}, {summary['total_flats']} flats, "
            f"{summary['saleable_sqft']:,} sft saleable (flats), {summary['tower_floor_sqft']:,} "
            f"sft tower floor, tot-lot {summary['open_space_share_pct']}%, mix "
            f"{summary['unit_mix_achieved']}, {parking.get('cellar_levels', 0)} cellar level(s)"
        )
        print(f"          every rule passes; open: {', '.join(open_) or 'none'}")


def _cmd_layout(args: argparse.Namespace) -> int:
    project = _load_project(args.project)
    if project.layout is None:
        print("The project file has no layout section.", file=sys.stderr)
        return 2
    library_file, amenities_file = _library_files(args)
    if library_file is None:
        print(f"Give --library, or name a flat_library in {WORKSPACE_FILE} next to the project "
              "or the survey.", file=sys.stderr)
        return 2
    library = FlatLibrary.model_validate_json(library_file.read_text())
    amenities = (
        AmenityLibrary.model_validate_json(amenities_file.read_text()) if amenities_file else None
    )
    if args.conservative_parking:
        project = project.model_copy(update={"layout": project.layout.model_copy(
            update={"conservative_parking": True})})
    plot, basis = load_plot(project, args.survey)
    keep_out, water = load_water(project, args.survey)
    print(f"Layout: {project.name}\nPlot: {plot.area:,.0f} m², {basis}")
    print("\n".join(_site_facts(project, project.site.road_dead_end)) + "\n")
    if water:
        print(f"Water: {water}; {plot.intersection(keep_out).area:,.0f} m² of the plot\n")
    out = Path(args.out)
    try:
        summaries = run_layout(project, library, plot, project.layout, out, amenities, keep_out)
    except NoLayout as exc:
        print(exc)
        return 1
    _print_options(summaries)
    print(f"\nWrote option_1..{len(summaries)} (.dxf, .svg, .json) to {out}/")
    if library.note:
        print(f"Flat library: {library.note}")
    print(LAYOUT_CAVEAT)
    return 0


def _library_files(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    """The libraries asked for, else the firm's defaults in the project's or survey's folder."""
    folders = [Path(args.project).parent] + ([Path(args.survey).parent] if args.survey else [])
    folder = next((f for f in folders if (f / WORKSPACE_FILE).exists()), folders[0])
    defaults = load_defaults(folder)
    library = Path(args.library) if args.library else (
        folder / defaults.flat_library if defaults.flat_library else None)
    amenities = Path(args.amenities) if args.amenities else (
        folder / defaults.amenities if defaults.amenities else None)
    return library, amenities


def _cmd_extract(args: argparse.Namespace) -> int:
    """What the survey settles by itself, and what will still be asked."""
    from siteplan.intake import extract, questions, render

    draft = extract(Path(args.survey))
    if args.json:
        print(json.dumps(draft.as_dict(), indent=2))
        return 0
    print(render(draft) + "\n\nStill to answer:")
    for question in questions(draft):
        default = f" [{question.default}]" if question.default else ""
        print(f"  - {question.prompt.splitlines()[0]}{default}")
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    """Raw survey -> what it settles -> ask only the rest -> the project file."""
    from siteplan.intake import build_project, extract, questions, render, save

    survey = Path(args.survey)
    draft = extract(survey)
    print(render(draft) + "\n")
    if args.answers:
        answers = json.loads(Path(args.answers).read_text())
    else:
        print("Only what the survey cannot settle. Press enter to take the value in brackets.\n")
        answers = collect(input, questions=questions(draft))
    workspace = Path(args.workspace) if args.workspace else survey.parent
    project = build_project(draft, answers, load_defaults(workspace))
    out = Path(args.out or workspace / f"{_slug(project['name'])}.project.json")
    if out.exists() and not args.force and (
            args.answers or input(f"\n{out} exists. Overwrite? [y/N]: ").strip().lower() != "y"):
        print(f"{out} exists; left it alone (--force to replace it).", file=sys.stderr)
        return 1
    save(project, out)
    print(f"Wrote {out}")
    if project["layout"].get("maximise"):
        print(f"The most floors the rules allow here: stilt + {project['layout']['floors']}. "
              "Layouts try every height from one above it down, and keep those that pass.")
    print(f"\nNext: uv run siteplan layout {out} --survey {survey}")
    return 0


def _cmd_acceptance(args: argparse.Namespace) -> int:
    """Raw survey and answers -> layouts; only then is the firm's plan read, to compare."""
    from siteplan.acceptance import compare, generate, report
    from siteplan.cases import Case

    out = Path(args.out)
    from siteplan.profiles import load_profile

    profile = load_profile(args.profile) if args.profile else None
    generated = generate(Path(args.survey), json.loads(Path(args.answers).read_text()), out,
                         Path(args.workspace) if args.workspace else None,
                         conservative_parking=args.conservative_parking, profile=profile,
                         mode="debug" if args.debug else "blind")
    rows = []
    if generated.options:
        case = Case.model_validate_json(Path(args.firm_case).read_text())  # read only now
        statement = (Project.model_validate_json(Path(args.firm_project).read_text())
                     .area_statement if args.firm_project else None)
        rows = compare(generated, case, statement)
    text = report(generated, rows or [("No layout passed", "-", "-")])
    out.mkdir(parents=True, exist_ok=True)
    (out / "acceptance.txt").write_text(text + "\n")
    print(text + f"\n\nWrote the options and acceptance.txt to {out}/")
    return 0 if generated.options else 1


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


def _cmd_inventory(args: argparse.Namespace) -> int:
    from siteplan.inventory import render_markdown, render_text

    print(render_markdown() if args.markdown else render_text())
    return 0


def _cmd_constraints(args: argparse.Namespace) -> int:
    from siteplan.constraints import Basis, render_markdown, render_text

    only = Basis(args.basis) if args.basis else None
    print(render_markdown() if args.markdown else render_text(only=only))
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    from siteplan.contracts import export_schemas

    for path in export_schemas(args.out):
        print(path)
    return 0


def _cmd_floors(args: argparse.Namespace) -> int:
    from siteplan.max_floors import describe, max_floors
    from siteplan.roads import roads_near
    from siteplan.units import ft_to_m, sqyd_to_sqm

    road_m = ft_to_m(args.road_ft) if args.road_ft else args.road_m
    dead_end = {"yes": True, "no": False}.get(args.dead_end)
    if args.project:
        project = _load_project(args.project)
        plot_sqm = project.site.net_sqm()
        if plot_sqm is None:
            raise ValueError("The project states no net area (net_area_sqyd or net_area_sqm).")
        if road_m is None:
            road_m = project.to_site().abutting_road_m
        if args.dead_end is None:
            dead_end = project.site.road_dead_end
        print("\n".join(_site_facts(project, dead_end)) + "\n")
    elif args.survey:
        survey = read_survey(Path(args.survey))
        plot_sqm = survey.stated_area_sqm or survey.area_sqm
        print(f"Plot from {args.survey}: {plot_sqm:,.0f} m²")
        for road in roads_near(survey):
            limit = max_floors(plot_sqm, road.width_m, args.floor_m, args.stilt_m)
            reach = f"up to {limit.max_height_m:g} m" if limit.max_height_m else (
                "no road limit" if limit.high_rise else "no high-rise")
            print(f"  road to the {road.side}, {road.distance_m:.1f} m off: drawn "
                  f"{road.width_m:.2f} m ({road.width_ft:.0f} ft) -> {reach}")
        if road_m is None:
            print("\nDrawn widths may be the carriageway alone. Give the legal width with "
                  "--road-m or --road-ft for the full answer.")
            return 0
        print()
    else:
        plot_sqm = sqyd_to_sqm(args.plot_sqyd) if args.plot_sqyd else args.plot_sqm
    if road_m is None:
        raise ValueError("Give the road width with --road-m or --road-ft.")
    limit = max_floors(plot_sqm, road_m, args.floor_m, args.stilt_m, dead_end)
    print(describe(limit))
    proposed = project.site.proposed_floors if args.project else None
    if proposed and limit.floors_stilt_counted is not None:
        print("\n" + _against_proposal(proposed, limit))
    return 0


def _against_proposal(proposed: int, limit) -> str:
    """The floors the firm's drawings propose, held against the most this road allows."""
    most = max(limit.floors_stilt_counted, limit.floors_stilt_not_counted)
    if proposed <= most:
        return f"Proposed on the drawings: stilt + {proposed}, within what this road allows."
    line = (f"Proposed on the drawings: stilt + {proposed}, more than the stilt + {most} this "
            "road allows")
    if limit.tdr_extra_floors and proposed <= most + limit.tdr_extra_floors:
        line += f"; the {limit.tdr_extra_floors} TDR floors could cover it"
    return line + "."


def _site_facts(project: Project, dead_end: bool | None) -> list[str]:
    """What the project knows about the site, and what it does not: printed before an answer."""
    s, road_m = project.site, project.to_site().abutting_road_m
    lines = []
    if road_m is not None:
        road = f"Road: {road_m:.2f} m declared ({s.abutting_road_status or 'status not given'})"
        if s.measured_carriageway_m is not None:
            road += (f"; the survey measures {s.measured_carriageway_m:.2f} m of carriageway, "
                     "not used by the rules")
        lines.append(road)
    lines.append(f"Road ends at the plot: {_TRISTATE[dead_end]}")
    cure = {True: "inside CURE", False: "outside CURE", None: "CURE not known"}[s.inside_cure]
    lines.append(f"Jurisdiction: {s.authority or 'not given'}, {cure}")
    floors = {n: f"stilt + {n}" for n in (s.proposed_floors, s.sanctioned_floors) if n}
    lines.append(f"Floors: proposed {floors.get(s.proposed_floors, 'UNKNOWN')} (drawing), "
                 f"sanctioned {floors.get(s.sanctioned_floors, 'UNKNOWN')}")
    lines.append("Airport and Air Force height: UNVERIFIED, " + (
        "no site coordinates" if s.site_coordinates is None
        else f"not computed; read the maps at {s.site_coordinates[0]:.5f}, "
             f"{s.site_coordinates[1]:.5f}"))
    return lines


_TRISTATE = {True: "yes", False: "no", None: "UNKNOWN"}


def _cmd_cases(args: argparse.Namespace) -> int:
    from siteplan.cases import load_cases, render, review

    folder = Path(args.folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"no case folder at {folder}")
    reviews = [review(case) for case in load_cases(folder)]
    if not reviews:
        print(f"No *.case.json files in {folder}.")
        return 1
    print(render(reviews))
    return 0 if all(r.settled for r in reviews) else 1


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
    keep_out, _ = load_water(project, args.survey)
    brief = args.brief if args.brief else Path(args.brief_file).read_text()
    out = Path(args.out)
    assistant = Assistant(OpenAICompatibleModel(config), config, project, library, plot, out,
                          keep_out)
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


_CONSERVATIVE_HELP = ("Test mode: when whose rules apply is not established, plan the stricter "
                      "GHMC parking column (labelled CONSERVATIVE_ASSUMPTION) instead of stopping "
                      "to ask")


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

    p = sub.add_parser("extract", help="What a raw survey settles, and what it leaves to ask.")
    p.add_argument("survey")
    p.add_argument("--json", action="store_true", help="The facts as JSON")
    p.set_defaults(run=_cmd_extract)

    p = sub.add_parser("start", help="Start a project from a raw survey: ask only what is open.")
    p.add_argument("survey")
    p.add_argument("--answers", help="Answers as JSON instead of asking (scripted runs)")
    p.add_argument("--workspace", help=f"Folder with {WORKSPACE_FILE} (default: the survey's)")
    p.add_argument("--out", help="Where to write the project (default: the workspace)")
    p.add_argument("--force", action="store_true", help="Replace an existing project file")
    p.set_defaults(run=_cmd_start)

    p = sub.add_parser("acceptance", help="Raw survey + answers -> layouts, then compared with "
                       "the firm's own plan, which is read only after they are drawn.")
    p.add_argument("survey")
    p.add_argument("--answers", required=True, help="The architect's answers, as JSON")
    p.add_argument("--firm-case", required=True, help="The firm's plan, as a case file")
    p.add_argument("--firm-project", help="A project file holding the firm's area statement")
    p.add_argument("--workspace", help=f"Folder with {WORKSPACE_FILE} (default: the survey's)")
    p.add_argument("--out", default="out/acceptance")
    p.add_argument("--conservative-parking", action="store_true", help=_CONSERVATIVE_HELP)
    p.add_argument("--profile", help="A site's temporary test assumptions (JSON, kept in "
                   "fixtures/): each value it sets is ASSUMED_FOR_TEST and listed in the report")
    p.add_argument("--debug", action="store_true", help="A debug run, which may use the "
                   "firm's finished plan (a debug profile, a value taken from it); a blind run, "
                   "the default, refuses them")
    p.set_defaults(run=_cmd_acceptance)

    p = sub.add_parser("layout", help="Generate tower layout options for a project.")
    p.add_argument("project")
    p.add_argument("--library", help=f"Flat library JSON (default: {WORKSPACE_FILE}'s)")
    p.add_argument("--survey", help="Survey or site-plan PDF/DXF (a site plan's outline is the "
                   "net plot), used when the project has no net_plot_m")
    p.add_argument("--amenities", help="Amenity library JSON: pool, courts, play area, cabin")
    p.add_argument("--out", default="out/layout")
    p.add_argument("--conservative-parking", action="store_true", help=_CONSERVATIVE_HELP)
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

    p = sub.add_parser("inventory", help="Every rule the engine applies, and how it was read.")
    p.add_argument("--markdown", action="store_true", help="A table to share with the firm")
    p.set_defaults(run=_cmd_inventory)

    p = sub.add_parser("constraints", help="Every number generation uses, and what kind of fact "
                       "each is: law, the firm's standard, an engine assumption, an unresolved "
                       "reading, or a site input.")
    p.add_argument("--markdown", action="store_true", help="A table to share with the firm")
    p.add_argument("--basis", choices=["LEGAL_RULE", "FIRM_STANDARD", "ENGINE_DESIGN_ASSUMPTION",
                                       "UNRESOLVED_INTERPRETATION", "SITE_INPUT"],
                   help="Only this class")
    p.set_defaults(run=_cmd_constraints)

    p = sub.add_parser("schema", help="Write the JSON Schema of every permanent contract "
                       "(src/siteplan/contracts) into a folder.")
    p.add_argument("--out", default="docs/contracts")
    p.set_defaults(run=_cmd_schema)

    p = sub.add_parser("floors", help="The most floors a plot can take, from its area and road.")
    plot = p.add_mutually_exclusive_group(required=True)
    plot.add_argument("--plot-sqm", type=float, help="Net plot area in m²")
    plot.add_argument("--plot-sqyd", type=float, help="Net plot area in square yards")
    plot.add_argument("--survey", help="Take the area, and list the roads, from a survey")
    plot.add_argument("--project", help="Take the plot, declared road and site facts from a "
                      "project file")
    road = p.add_mutually_exclusive_group()
    road.add_argument("--road-m", type=float, help="Legal width of the abutting road, metres")
    road.add_argument("--road-ft", type=float, help="Legal width of the abutting road, feet")
    p.add_argument("--floor-m", type=float, default=3.0, help="Floor-to-floor height")
    p.add_argument("--stilt-m", type=float, default=3.0, help="Stilt height")
    p.add_argument("--dead-end", choices=("yes", "no"),
                   help="Does the access road end at the plot? Above 30 m it must not")
    p.set_defaults(run=_cmd_floors)

    p = sub.add_parser("cases", help="Check the rules against real schemes (sanctioned plans).")
    p.add_argument("folder", nargs="?", default="fixtures/cases", help="Folder of *.case.json")
    p.set_defaults(run=_cmd_cases)

    p = sub.add_parser("assist", help="Plain-English brief -> approved request -> layouts.")
    p.add_argument("project")
    p.add_argument("--library", required=True, help="Flat library JSON")
    brief = p.add_mutually_exclusive_group(required=True)
    brief.add_argument("--brief", help="The brief, in plain English")
    brief.add_argument("--brief-file", help="A text file holding the brief")
    p.add_argument("--survey", help="Survey or site-plan PDF/DXF (a site plan's outline is the "
                   "net plot), used when the project has no net_plot_m")
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
