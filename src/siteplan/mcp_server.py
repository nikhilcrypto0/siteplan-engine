"""The engine as an MCP server, so an agent harness (Hermes Agent, or any MCP client) can use it.

The harness's model decides which tool to call and fills in the arguments; every number in a
reply is computed here. Two rules carry over from the assistant:

- Nothing is solved until the architect approves the request, and that approval is asked of
  the person through MCP elicitation, never of the model. A client that cannot ask, a
  timeout, or any answer other than "accept" stops the call with nothing drawn.
- The model only reaches files inside the workspace, and replies carry computed numbers
  and fixed wording, never text copied out of a drawing.
"""

from __future__ import annotations

import argparse
import json
import logging
import uuid
from pathlib import Path
from typing import Annotated, Any

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError

from siteplan.area_statement import render
from siteplan.assistant import Assistant, BriefExtraction, compare_options
from siteplan.checks import check_site
from siteplan.guards import sanitize_brief
from siteplan.layout import LayoutRequest
from siteplan.library import FlatLibrary
from siteplan.project import Project
from siteplan.runner import LAYOUT_CAVEAT, load_plot, read_survey, run_layout

log = logging.getLogger("siteplan.mcp")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITES_FILES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
SURVEY_TYPES = {".pdf", ".dxf"}
MAX_LISTED = 200
MAX_BRIEF_CHARS = 2000
OPTION_KEYS = ("option", "towers", "total_flats", "saleable_sqft", "open_space_share_pct",
               "unit_mix_achieved", "mix_error", "rule_findings")

INSTRUCTIONS = (
    "Site-planning tools for Telangana group housing. Every number these tools return is "
    "computed; quote them as given and never estimate areas, setbacks or flat counts yourself. "
    "Call list_files first to find project, survey and flat-library files. propose_layouts asks "
    "the architect to approve before it draws anything; if it reports that the architect did "
    "not approve, do not call it again unless the architect asks."
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
        try:
            return Project.model_validate_json(self.file(name, {".json"}).read_text())
        except ValidationError as exc:
            raise ToolError(f"'{name}' is not a valid project file ({_fields(exc)}).") from None

    def library(self, name: str) -> FlatLibrary:
        try:
            return FlatLibrary.model_validate_json(self.file(name, {".json"}).read_text())
        except ValidationError as exc:
            raise ToolError(f"'{name}' is not a valid flat library ({_fields(exc)}).") from None

    def listing(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {"projects": [], "flat_libraries": [], "surveys": []}
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
        return found


def _fields(exc: ValidationError) -> str:
    return ", ".join(sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})) or "format"


def _json_kind(path: Path) -> str | None:
    text = path.read_text(errors="replace")
    for kind, model in (("projects", Project), ("flat_libraries", FlatLibrary)):
        try:
            model.model_validate_json(text)
            return kind
        except ValidationError:
            continue
    return None


def approval_message(project: str, plot: str, request: LayoutRequest, reading: dict) -> str:
    mix = ", ".join(f"{k} {v * 100:.0f}%" for k, v in sorted(request.unit_mix.items()))
    lines = [
        f"Generate layout options for {project} ({plot}) with:",
        f"  floors above the stilt: {request.floors} (height {request.height_m:g} m)",
        f"  unit mix: {mix}",
        f"  stilt {request.stilt_height_m:g} m, floor-to-floor {request.floor_height_m:g} m, "
        f"common area {request.common_area_pct:g}%",
    ]
    lines += [f"  default: {a}" for a in reading["assumptions"]]
    if reading["flagged"]:
        lines.append(f"CHECK: the brief never states {', '.join(reading['flagged'])}.")
    lines.append("Nothing is drawn unless you approve.")
    return "\n".join(lines)


def build_server(workspace: Path, out_dir: Path) -> FastMCP:
    ws = Workspace(workspace, out_dir)
    server = FastMCP("siteplan", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def list_files() -> dict[str, list[str]]:
        """List the project files, survey drawings (PDF/DXF) and flat libraries available."""
        return ws.listing()

    @server.tool(annotations=READ_ONLY)
    def read_survey_drawing(survey_file: str) -> dict[str, Any]:
        """Read a survey drawing (vector PDF or DXF): plot area, how well it agrees with the
        stated area, the drawing scale, spot levels and slope, and any warnings."""
        try:
            return read_survey(ws.file(survey_file, SURVEY_TYPES)).summary()
        except ValueError as exc:
            raise ToolError(str(exc)) from None

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

    @server.tool(annotations=WRITES_FILES)
    async def propose_layouts(
        ctx: Context,
        project_file: str,
        library_file: str,
        brief: Annotated[str, Field(description="The architect's own words, copied exactly")],
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
    ) -> dict[str, Any]:
        """Draw tower layout options (DXF for ZWCAD plus an SVG preview) from a brief. Pass
        only values the architect stated; leave the rest null. The architect is asked to
        approve the values before anything is drawn."""
        project = ws.project(project_file)
        library = ws.library(library_file)
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
        if reading["missing"]:
            return {"solved": False, "missing": reading["missing"],
                    "next": "Ask the architect for these values. Do not guess them."}
        try:
            request = LayoutRequest.model_validate(reading["request"])
        except ValidationError as exc:
            raise ToolError(f"The request is invalid ({_fields(exc)}).") from None
        survey = ws.file(survey_file, SURVEY_TYPES) if survey_file else None
        try:
            plot, basis = load_plot(project, survey)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

        plot_text = f"plot {plot.area:,.0f} m², {basis}"
        refusal = await _refusal(ctx, approval_message(project.name, plot_text, request, reading))
        if refusal:
            return {"solved": False, "next": refusal}

        run = uuid.uuid4().hex[:8]
        out = ws.out / run
        try:
            options = await anyio.to_thread.run_sync(
                run_layout, project, library, plot, request, out
            )
        except ValueError as exc:
            return {"solved": False, "next": f"The solver refused the request: {exc}"}
        if not options:
            return {"solved": False,
                    "next": "No tower fits inside the setbacks with the required open space."}
        facts = [{k: o[k] for k in OPTION_KEYS} for o in options]
        record = {"project": project.name, "brief": clean.text, "plot": plot_text,
                  "approved_request": request.model_dump(), "options": facts}
        (out / "run.json").write_text(json.dumps(record, indent=2))
        log.info("run %s: approved and solved, %d options", run, len(options))
        return {
            "solved": True,
            "folder": str(out),
            "comparison": compare_options(facts),
            "options": [
                f | {"dxf": str(out / f"option_{f['option']}.dxf"),
                     "preview_svg": str(out / f"option_{f['option']}.svg")}
                for f in facts
            ],
            "flat_library_note": library.note,
            "caveat": LAYOUT_CAVEAT,
        }

    return server


async def _refusal(ctx: Context, message: str) -> str | None:
    """Ask the person, not the model. None means approved; anything but an explicit accept
    comes back as the reason nothing was drawn."""
    try:
        answer = await ctx.elicit(message, Approval)
    except Exception as exc:  # the client cannot ask, or answered outside the form
        log.warning("approval could not be asked: %s", exc)
        return ("This app could not show the architect the approval prompt, so nothing was "
                "drawn. It needs an MCP client that supports approval prompts (elicitation).")
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
    args = parser.parse_args(argv)
    Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(  # stdout carries the protocol, so logs go to a file
        filename=args.log_file, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    build_server(Path(args.workspace), Path(args.out)).run("stdio")


if __name__ == "__main__":
    main()
