"""The engine as an MCP server, so an agent harness (Hermes Agent, or any MCP client) can use it.

The harness's model decides which tool to call and fills in the arguments; every number in a
reply is computed here. Two rules carry over from the assistant:

- Nothing is solved until the architect approves the request, and that approval is asked of
  the person, never of the model: through MCP elicitation (`--approval elicit`) or on a page
  served on this machine (`--approval page`, for clients that cannot show a prompt). The
  channel is fixed at startup and never falls back to the other one, because a failure in
  one must not be retried in a channel that might answer differently. A client that cannot
  ask, a timeout, or any answer other than an approval stops the call with nothing drawn.
- The model only reaches files inside the workspace, and replies carry computed numbers
  and fixed wording, never text copied out of a drawing.

`propose_layouts` and `check_rules` are LEGACY (the prototype generator and its checker), not for
production generation by a language model: they stay for the Hermes profile already wired to
them and for regression comparison. The production surface is `siteplan.service`, on the full
search and the independent validator. The tools' own docstrings are left as they were, because
they are the descriptions Hermes's model reads.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import uuid
import webbrowser
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated, Any

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError

from siteplan import rules
from siteplan.approval import ApprovalDesk
from siteplan.area_statement import render
from siteplan.assistant import Assistant, BriefExtraction, compare_options
from siteplan.checks import check_site
from siteplan.guards import sanitize_brief
from siteplan.heights import heights_to_try
from siteplan.intake import WORKSPACE_FILE, build_project, extract, load_defaults, questions, save
from siteplan.layout import LayoutRequest
from siteplan.library import FlatLibrary
from siteplan.max_floors import max_floors as floor_limit
from siteplan.project import Project
from siteplan.result_page import write_result_page
from siteplan.rulebook import RuleBook
from siteplan.runner import (
    LAYOUT_CAVEAT,
    NoLayout,
    load_plot,
    load_water,
    read_survey,
    run_layout,
    stop_reason,
)
from siteplan.site_amenities import AmenityLibrary

log = logging.getLogger("siteplan.mcp")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITES_FILES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
SURVEY_TYPES = {".pdf", ".dxf"}
PROJECTS = "projects"  # where finish_project writes, inside the runs folder
MAX_LISTED = 200
MAX_BRIEF_CHARS = 2000
APPROVAL_TIMEOUT_S = 300
OPTION_KEYS = ("option", "floors_above_stilt", "towers", "total_flats", "flats_by_type",
               "saleable_sqft", "tower_floor_sqft", "common_core_sqft", "built_up_sqft",
               "open_space_share_pct", "unit_mix_achieved", "mix_error", "parking", "roads",
               "amenities", "amenities_with_no_room", "surface_parking_bays", "rule_findings")

INSTRUCTIONS = (
    "Site-planning tools for Telangana group housing. Every number these tools return is "
    "computed; quote them as given and never estimate areas, setbacks or flat counts yourself. "
    "Call list_files first to find project, survey and flat-library files. To start a new "
    "project from a raw survey, call start_project: it returns what the survey settles and the "
    "questions it cannot. Ask the architect those questions, showing each default, and pass "
    "their answers in their own words to finish_project; never answer one yourself. "
    "propose_layouts asks "
    "the architect to approve before it draws anything; if it reports that the architect did "
    "not approve, do not call it again unless the architect asks. "
    "For any question about the building rules, call rules_for_height or search_rules and "
    "answer from what they return, quoting the clause and page: never answer a rule question "
    "from memory, and say so plainly when the tools find nothing."
)


class Approval(BaseModel):
    """The approval form. Hermes answers "accept" with an empty form, so the field defaults to
    true; a client that shows the checkbox lets the architect untick it."""

    approve: bool = Field(True, description="Generate the layouts with these values")


class Workspace:
    """The only folder the model can read from, and the folder runs are written to."""

    def __init__(self, root: Path, out: Path) -> None:
        self.root = root.resolve()
        self.out = out.resolve()

    def file(self, name: str, suffixes: set[str]) -> Path:
        path = (self.root / name).resolve()
        if (
            not path.is_relative_to(self.root)
            or path.suffix.lower() not in suffixes
            or not path.is_file()
        ):
            log.warning("file refused: %r", name)  # the reason stays in the log
            raise ToolError(f"'{name}' is not a readable file in the workspace. Call list_files.")
        return path

    def project(self, name: str) -> Project:
        """A project file from the workspace, or one finish_project wrote to the runs folder."""
        made = (self.out / name).resolve()
        path = (made if made.is_relative_to(self.out / PROJECTS) and made.suffix == ".json"
                and made.is_file() else self.file(name, {".json"}))
        try:
            return Project.model_validate_json(path.read_text())
        except ValidationError as exc:
            raise ToolError(f"'{name}' is not a valid project file ({_fields(exc)}).") from None

    def amenities(self, name: str) -> AmenityLibrary:
        try:
            return AmenityLibrary.model_validate_json(self.file(name, {".json"}).read_text())
        except ValidationError as exc:
            raise ToolError(f"'{name}' is not a valid amenity library ({_fields(exc)}).") from None

    def library(self, name: str) -> FlatLibrary:
        try:
            return FlatLibrary.model_validate_json(self.file(name, {".json"}).read_text())
        except ValidationError as exc:
            raise ToolError(f"'{name}' is not a valid flat library ({_fields(exc)}).") from None

    def listing(self) -> dict[str, Any]:
        """What is in the workspace. Projects carry their names: a workspace holds several,
        and the architect asks for one by its name, not by its file name."""
        found: dict[str, Any] = {"projects": [], "flat_libraries": [],
                                 "amenity_libraries": [], "surveys": [], "project_names": {}}
        files = sorted(
            p for p in self.root.rglob("*")
            if p.is_file() and not p.is_relative_to(self.out)
            and not any(part.startswith(".") for part in p.relative_to(self.root).parts)
        )
        for path in files[:MAX_LISTED]:
            name = str(path.relative_to(self.root))
            if path.suffix.lower() in SURVEY_TYPES:
                found["surveys"].append(name)
            elif path.suffix.lower() == ".json":
                kind = _json_kind(path)
                if kind:
                    found[kind].append(name)
                    if kind == "projects":
                        found["project_names"][name] = Project.model_validate_json(
                            path.read_text()
                        ).name
        # Projects finish_project wrote live in the runs folder, not the workspace; list them
        # too, so a new chat can find the project an earlier one made.
        for path in sorted((self.out / PROJECTS).glob("*.project.json"))[:MAX_LISTED]:
            name = f"{PROJECTS}/{path.name}"
            try:
                found["project_names"][name] = Project.model_validate_json(path.read_text()).name
            except ValidationError:
                continue
            found["projects"].append(name)
        return found


def _fields(exc: ValidationError) -> str:
    return ", ".join(sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})) or "format"


def _json_kind(path: Path) -> str | None:
    text = path.read_text(errors="replace")
    for kind, model in (("projects", Project), ("flat_libraries", FlatLibrary),
                        ("amenity_libraries", AmenityLibrary)):
        try:
            model.model_validate_json(text)
            return kind
        except ValidationError:
            continue
    return None


def approval_request(project: str, plot: str, request: LayoutRequest, reading: dict) -> tuple:
    """What the architect is shown before anything is drawn: a title and one line per value."""
    mix = ", ".join(f"{k} {v * 100:.0f}%" for k, v in sorted(request.unit_mix.items()))
    floors = f"Floors above the stilt: {request.floors} (height {request.height_m:g} m)"
    if request.maximise:
        tried = heights_to_try(request)
        floors = (f"Floors above the stilt: the most the rules allow, {request.floors} (height "
                  f"{request.height_m:g} m); tests every height from stilt + {tried[0]} down to "
                  f"stilt + {tried[-1]} and keeps the layouts that pass")
    lines = [
        f"Plot: {plot}",
        floors,
        f"Unit mix: {mix}",
        f"Stilt {request.stilt_height_m:g} m, floor-to-floor {request.floor_height_m:g} m, "
        f"common area {request.common_area_pct:g}%",
    ]
    lines += [f"Default: {a}" for a in reading["assumptions"]]
    if reading["flagged"]:
        lines.append(f"CHECK: the brief never states {', '.join(reading['flagged'])}.")
    return f"Generate layout options for {project}", lines


def build_server(workspace: Path, out_dir: Path, approval: str = "elicit",
                 desk: ApprovalDesk | None = None,
                 approval_timeout: float = APPROVAL_TIMEOUT_S,
                 open_result: Callable[[str], object] | None = webbrowser.open,
                 book: RuleBook | None = None) -> FastMCP:
    ws = Workspace(workspace, out_dir)
    desk = desk or (ApprovalDesk() if approval == "page" else None)
    server = FastMCP("siteplan", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def list_files() -> dict[str, Any]:
        """List the project files, survey drawings (PDF/DXF) and flat libraries available.
        `project_names` gives each project file's name: match the architect's words to a
        name, never to a file name, and say which project you picked."""
        return ws.listing()

    @server.tool(annotations=READ_ONLY)
    def read_survey_drawing(survey_file: str) -> dict[str, Any]:
        """Read a survey drawing (vector PDF or DXF): plot area, how well it agrees with the
        stated area, the drawing scale, spot levels and slope, the roads next to the plot with
        their drawn widths, and any warnings. A road's width is as drawn (it may be the
        carriageway alone): quote it as that, and ask the architect for the legal width."""
        try:
            return read_survey(ws.file(survey_file, SURVEY_TYPES)).summary()
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    @server.tool(annotations=READ_ONLY)
    def start_project(survey_file: str) -> dict[str, Any]:
        """Start a project from a raw survey (PDF or DXF). Returns what the survey settles by
        itself (the plot and its areas, the roads measured across themselves, marks such as
        ROAD WIDENING or NALA, the village and mandal) and the questions it cannot settle. Ask
        the architect every question, showing its default, and pass their answers to
        finish_project. Never answer a question yourself, and never pick a nala's colour from
        the lines listed near it: they are offered, not chosen."""
        try:
            draft = extract(ws.file(survey_file, SURVEY_TYPES))
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        asked = [{"key": q.key, "question": q.prompt, "default": q.default,
                  "example": q.example} | (
                     {"asked_only_if": "road_row is a width, not 'as drawn'"}
                     if q.when is not None else {}) for q in questions(draft)]
        return {"survey": draft.as_dict(), "questions": asked,
                "next": "Ask the architect these questions, then call finish_project with "
                        "survey_file and their answers, keyed as asked."}

    @server.tool(annotations=WRITES_FILES)
    def finish_project(survey_file: str, answers: dict[str, str]) -> dict[str, Any]:
        """Write the project from the survey and the architect's answers to start_project's
        questions (keyed as asked; one left out takes the default shown). Returns the
        project_file to pass to propose_layouts. 'max' floors is worked out here, from the
        rules, not by you."""
        survey = ws.file(survey_file, SURVEY_TYPES)
        try:
            project = build_project(extract(survey), answers, load_defaults(ws.root))
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        slug = re.sub(r"[^a-z0-9]+", "-", project["name"].lower()).strip("-") or "project"
        name = f"{PROJECTS}/{slug}.project.json"
        save(project, ws.out / name)
        return {"project_file": name, "project": project,
                "next": f"Call propose_layouts with project_file '{name}' and survey_file "
                        f"'{survey_file}'; the flat and amenity libraries are the firm's "
                        "defaults."}

    @server.tool(annotations=READ_ONLY)
    def check_rules(project_file: str) -> list[dict]:
        """Check a project against Telangana G.O.Ms.No.168: plot size, road width, setbacks,
        gaps between blocks and organized open space. Each result cites its clause."""
        findings = check_site(ws.project(project_file).to_site())
        return [f.__dict__ | {"status": f.status.value} for f in findings]

    @server.tool(annotations=READ_ONLY)
    def area_statement(project_file: str) -> str:
        """The project's area statement in the firm's format."""
        statement = ws.project(project_file).area_statement
        if statement is None:
            raise ToolError("The project file has no area_statement section.")
        return render(statement)

    @server.tool(annotations=READ_ONLY)
    def rules_for_height(height_m: float) -> dict[str, Any]:
        """What the Telangana rules require of a building of this height: the minimum abutting
        road, the all-round setback and the gap between blocks, each with its clause. Exact
        values from the encoded Table IV, not a search."""
        if height_m <= 0:
            raise ToolError("Give the building height in metres, stilt included.")
        return rules.height_rules(height_m)

    @server.tool(annotations=READ_ONLY)
    def max_floors(plot_area_sqm: float, road_width_m: float, floor_height_m: float = 3.0,
                   stilt_height_m: float = 3.0,
                   road_is_dead_end: bool | None = None) -> dict[str, Any]:
        """The most floors the rules allow on a plot: whether it can be high-rise, the maximum
        height and the rule that stops it there, the floors above the stilt both ways the stilt
        may be counted, and the extra floors TDR could buy, each with its clause. road_width_m
        must be the LEGAL width of the road the site takes its access from, which the
        architect confirms: a width from read_survey_drawing is as drawn and may be the
        carriageway alone. road_is_dead_end is whether that road ends at the plot, only as the
        architect says (a survey does not show where a road leads); leave it out when not
        known. Quote both stilt answers and the notes; never choose between them."""
        try:
            return floor_limit(plot_area_sqm, road_width_m, floor_height_m,
                               stilt_height_m, road_is_dead_end).as_dict()
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    @server.tool(annotations=READ_ONLY)
    def search_rules(question: str, limit: int = 3) -> dict[str, Any]:
        """Search the building rules document itself and return the passages that answer the
        question, each with its page number, so the answer can be quoted rather than recalled."""
        if book is None:
            raise ToolError("No rules document is loaded; start the server with --rules <pdf>.")
        hits = book.search(question, limit=max(1, min(limit, 8)))
        repealed = [hit for hit in hits if hit.superseded_by]
        warning = ""
        if repealed:
            warning = ("WARNING: " + " ".join(sorted({hit.superseded_by for hit in repealed}))
                       + " Do not quote the superseded passage as the rule in force.")
        return {
            "source": book.source,
            "warning": warning,
            "passages": [hit.as_dict() for hit in hits],
            "next": ("Quote the passage and its page. A passage whose still_in_force is false "
                     "has been replaced by a later order: say so and give the replacement "
                     "instead. If this is empty, say the document does not answer it rather "
                     "than answering from memory."),
        }

    @server.tool(annotations=WRITES_FILES)
    async def propose_layouts(
        ctx: Context,
        project_file: str,
        brief: Annotated[str, Field(description="The architect's own words, copied exactly")],
        library_file: Annotated[str | None, Field(
            description=f"Flat library; left out, the firm's default in {WORKSPACE_FILE}"
        )] = None,
        floors_above_stilt: Annotated[int | None, Field(
            description="Floors above the stilt: 'stilt + 8' means 8. Null if not stated"
        )] = None,
        unit_mix_percent: Annotated[dict[str, float] | None, Field(
            description="Percent of flats per category, e.g. {'2BHK': 70, '3BHK': 30}"
        )] = None,
        stilt_height_m: float | None = None,
        floor_height_m: float | None = None,
        common_area_pct: float | None = None,
        survey_file: str | None = None,
        amenities_file: Annotated[str | None, Field(
            description="Amenity library (pool, courts, play area, security cabin); left out, "
            "the firm's default"
        )] = None,
    ) -> dict[str, Any]:
        """Draw tower layout options (DXF for ZWCAD, an A1 drawing sheet and an SVG preview) from
        a brief. Pass only values the architect stated; leave the rest null: a project made by
        finish_project already holds the floors and the mix. The architect is asked to approve
        the values before anything is drawn."""
        project = ws.project(project_file)
        defaults = load_defaults(ws.root)
        if not (library_file or defaults.flat_library):
            raise ToolError(f"No flat library given, and none set in {WORKSPACE_FILE}.")
        library = ws.library(library_file or defaults.flat_library)
        amenities_file = amenities_file or defaults.amenities
        amenities = ws.amenities(amenities_file) if amenities_file else None
        unknown = set(unit_mix_percent or {}) - set(library.categories)
        if unknown:
            raise ToolError(f"Unknown flat categories {sorted(unknown)}; the library has "
                            f"{sorted(library.categories)}.")
        clean = sanitize_brief(brief, MAX_BRIEF_CHARS)
        if clean.removed:
            log.info("brief sanitised: %s", "; ".join(clean.removed))
        reading = Assistant.interpret(
            BriefExtraction(
                floors_above_stilt=floors_above_stilt,
                unit_mix_percent=unit_mix_percent or {},
                stilt_height_m=stilt_height_m,
                floor_height_m=floor_height_m,
                common_area_pct=common_area_pct,
            ),
            clean.text,
        )
        if project.sources and project.layout is not None:
            # made by finish_project: the architect's own answers already set these
            reading["missing"] = [m for m in reading["missing"]
                                  if m not in ("floors above the stilt", "unit mix")]
        if "floors" in reading["request"]:  # a height the architect names is not a maximum
            reading["request"]["maximise"] = False
        if reading["missing"]:
            return {"solved": False, "missing": reading["missing"],
                    "next": "Ask the architect for these values. Do not guess them."}
        # The project's own layout section carries site-level settings (tower length cap,
        # amenities); the brief decides the rest.
        settings = project.layout.model_dump(exclude_unset=True) if project.layout else {}
        try:
            request = LayoutRequest.model_validate(settings | reading["request"])
        except ValidationError as exc:
            raise ToolError(f"The request is invalid ({_fields(exc)}).") from None
        survey = ws.file(survey_file, SURVEY_TYPES) if survey_file else None
        try:
            plot, basis = load_plot(project, survey)
            keep_out, water = load_water(project, survey)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

        stop = stop_reason(project, plot, request, keep_out)
        if stop:  # nothing can be tried: say why before asking anyone to approve
            return {"solved": False, "next": f"Nothing was tried: {stop}."}
        plot_text = f"plot {plot.area:,.0f} m², {basis}"
        if water:
            plot_text += f"; {water}"
        title, lines = approval_request(project.name, plot_text, request, reading)
        refusal = await _refusal(ctx, approval, desk, title, lines, approval_timeout)
        if refusal:
            return {"solved": False, "next": refusal}

        run = uuid.uuid4().hex[:8]
        out = ws.out / run
        try:
            options = await anyio.to_thread.run_sync(
                run_layout, project, library, plot, request, out, amenities, keep_out
            )
        except NoLayout as exc:
            return {"solved": False, "next": str(exc)}
        except ValueError as exc:
            return {"solved": False, "next": f"The solver refused the request: {exc}"}
        facts = [{k: o[k] for k in OPTION_KEYS} for o in options]
        comparison = compare_options(facts)
        record = {"project": project.name, "brief": clean.text, "plot": plot_text,
                  "approved_request": request.model_dump(), "options": facts,
                  "caveat": LAYOUT_CAVEAT, "flat_library_note": library.note}
        (out / "run.json").write_text(json.dumps(record, indent=2))
        page = write_result_page(record, comparison, out)
        if open_result is not None:
            try:  # the drawings are ready: put them in front of the architect
                open_result(page.as_uri())
            except Exception as exc:
                log.warning("could not open the results page: %s", exc)
        log.info("run %s: approved and solved, %d options", run, len(options))
        return {
            "solved": True,
            "folder": str(out),
            "results_page": str(page),
            "comparison": comparison,
            "options": [
                f | {"dxf": str(out / f"option_{f['option']}.dxf"),
                     "preview_svg": str(out / f"option_{f['option']}.svg")}
                for f in facts
            ],
            "flat_library_note": library.note,
            "caveat": LAYOUT_CAVEAT,
        }

    return server


async def _refusal(ctx: Context, channel: str, desk: ApprovalDesk | None,
                   title: str, lines: list[str], timeout: float) -> str | None:
    """Ask the person, not the model. None means approved; anything else comes back as the
    reason nothing was drawn. The channel is chosen at startup, never by the model, and a
    failure in one channel is never retried in the other: that would let a real no through."""
    if channel == "page":
        assert desk is not None
        approved = await anyio.to_thread.run_sync(partial(desk.ask, title, lines, timeout))
        if approved:
            return None
        return ("The architect did not approve on the approval page (or did not answer in "
                f"{timeout / 60:.0f} minutes), so nothing was drawn. Ask what to change.")
    message = f"{title}:\n" + "\n".join(f"  {line}" for line in lines) + \
              "\nNothing is drawn unless you approve."
    try:
        answer = await ctx.elicit(message, Approval)
    except Exception as exc:  # the client cannot ask, or answered outside the form
        log.warning("approval could not be asked: %s", exc)
        return ("This app could not show the architect the approval prompt, so nothing was "
                "drawn. It needs an MCP client that supports approval prompts (elicitation), "
                "or this server started with --approval page.")
    approved = answer.action == "accept" and answer.data.approve is True
    log.info("approval answer: %s%s", answer.action,
             "" if answer.action != "accept" else f" (approve={answer.data.approve})")
    if approved:
        return None
    return ("The architect did not approve, so nothing was drawn. Do not call "
            "propose_layouts again unless the architect asks.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="siteplan-mcp", description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True, help="Folder the tools may read from")
    parser.add_argument("--out", default="out/mcp", help="Folder runs are written to")
    parser.add_argument("--log-file", default="out/logs/mcp.log")
    parser.add_argument("--rules",
                        help="The building rules PDF that rule questions are answered from")
    parser.add_argument(
        "--approval", choices=("elicit", "page"), default="elicit",
        help="Where the architect approves: 'elicit' asks through the chat app (needs a client "
             "that shows MCP approval prompts), 'page' opens a page on this machine.",
    )
    parser.add_argument("--no-open-result", action="store_true",
                        help="Do not open the drawings in a browser when a run finishes.")
    args = parser.parse_args(argv)
    Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(  # stdout carries the protocol, so logs go to a file
        filename=args.log_file, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    book = RuleBook.load(args.rules) if args.rules else None
    build_server(Path(args.workspace), Path(args.out), args.approval,
                 open_result=None if args.no_open_result else webbrowser.open,
                 book=book).run("stdio")


if __name__ == "__main__":
    main()
