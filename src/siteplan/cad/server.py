"""`siteplan-cad-mcp`: the live CAD session as MCP tools over stdio, for Claude Code.

Claude reads a request ("show Dhulapally's setbacks", "move tower T1 three metres east") and calls
these tools; the engine computes and checks, and the drawing changes in the running FreeCAD.
Every number in a reply comes from the engine or is measured back from FreeCAD. There is no tool
that runs code, and FreeCAD's end listens on 127.0.0.1 only.

    uv run siteplan-cad-mcp --sites fixtures/cad_sites.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from siteplan.cad.bridge import NoBridge
from siteplan.cad.live import Session, load_sites

INSTRUCTIONS = (
    "Draws the site-plan engine's own geometry in a running FreeCAD and checks changes against "
    "the engine's rules. Open FreeCAD with cad/siteplan_live.FCMacro first. Coordinates are "
    "metres in the survey's frame (x east, y north); FreeCAD shows millimetres. A site run in "
    "debug mode may use the firm's finished plan and is never acceptance evidence."
)


def build(session: Session) -> FastMCP:
    server = FastMCP("siteplan-cad", instructions=INSTRUCTIONS)

    def guard(call):
        try:
            return call()
        except (KeyError, ValueError, NoBridge) as problem:
            raise ToolError(str(problem)) from problem

    @server.tool()
    def cad_status() -> dict:
        """Whether FreeCAD's live link answers, and the sites this server knows."""
        return guard(lambda: {"freecad": session.bridge.ping(), "sites": sorted(session.specs),
                              "open": sorted(session.sites)})

    @server.tool()
    def show_site(site: str, what: str = "setbacks") -> dict:
        """Draw a site in FreeCAD, or update what is drawn: 'survey' (the survey's property
        boundary and roads), 'net' (plus the net plot, land given up and the gate), 'setbacks'
        (plus the setback zone, the buildable area, the green strip, the fire lane, water
        buffers and each side's setback as a dimension) or 'all'."""
        return guard(lambda: session.show(site, what))

    @server.tool()
    def site_summary(site: str) -> dict:
        """The engine's numbers for a site: areas, setbacks, the buildable area's bounds, a point
        well inside it, the firm's block sizes and the test towers placed."""
        return guard(lambda: session.summary(site))

    @server.tool()
    def place_tower(site: str, tower: str, length_m: float, depth_m: float,
                    x: float | None = None, y: float | None = None, bearing_deg: float = 0.0,
                    floors: int | None = None) -> dict:
        """Place a test tower footprint centred on (x, y) metres, length_m along bearing_deg
        (clockwise from north: 0 runs north-south) and depth_m across; without x and y, in the
        middle of the buildable area. floors defaults to the most step 2 allows. Returns the
        engine's checks and the buildable area left."""
        return guard(lambda: session.place_tower(site, tower, length_m, depth_m, x, y,
                                                 bearing_deg, floors))

    @server.tool()
    def move_tower(site: str, tower: str, east_m: float = 0.0, north_m: float = 0.0) -> dict:
        """Move a test tower by east_m and north_m metres (negative for west or south) and check
        it again."""
        return guard(lambda: session.move_tower(site, tower, east_m, north_m))

    @server.tool()
    def delete_tower(site: str, tower: str) -> dict:
        """Remove a test tower from the engine and from FreeCAD, and work out the buildable area
        left again."""
        return guard(lambda: session.delete_tower(site, tower))

    @server.tool()
    def read_tower_from_cad(site: str, tower: str) -> dict:
        """Take a tower as it now stands in FreeCAD (after it was dragged or edited there) into
        the engine, and check it."""
        return guard(lambda: session.read_back(site, tower))

    @server.tool()
    def validate_towers(site: str) -> dict:
        """The engine's checks on every test tower: inside its height's setbacks, out of water
        buffers, the taller one's setback from every other tower."""
        return guard(lambda: session.validate(site))

    @server.tool()
    def compare_cad_with_engine(site: str) -> dict:
        """Read every drawn shape back from FreeCAD and measure it against the engine's: the
        largest distance between them and the difference in area, within the stated
        tolerance."""
        return guard(lambda: session.compare(site))

    @server.tool()
    def measure_setbacks_in_cad(site: str) -> dict:
        """How far the buildable outline, as FreeCAD holds it, lies from each side of the net
        plot, beside the setback the engine asked of that side."""
        return guard(lambda: session.setback_distances(site))

    @server.tool()
    def show_layout(site: str, run_id: str, layout_id: str) -> dict:
        """Draw a layout of a service run (one shown, one proposed, or a version saved of one)
        in the site's FreeCAD document, judged again by the independent validator, its sheet
        saying DEBUG or STUDY where they apply, its verdict and PRELIMINARY for floor plates.
        The run is read from the 'runs' folder the sites file names for the site."""
        return guard(lambda: session.show_layout(site, run_id, layout_id))

    @server.tool()
    def keep_layout(site: str, run_id: str, layout_id: str, note: str = "") -> dict:
        """Save a layout of a run, unchanged, as a version of its own in the run's folder, its
        parent's digest recorded; the validator judges it now and whenever it is used."""
        return guard(lambda: session.keep_layout(site, run_id, layout_id, note))

    @server.tool()
    def save_drawing(site: str, file_name: str) -> str:
        """Save the site's FreeCAD document as file_name (a bare name ending .FCStd) in the
        live link's folder."""
        return guard(lambda: session.save(site, file_name))

    @server.tool()
    def reopen_drawing(site: str, file_name: str) -> str:
        """Close the saved drawing and open it again from its file; the site carries on in it."""
        return guard(lambda: session.reopen(site, file_name))

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="siteplan-cad-mcp", description=__doc__.splitlines()[0])
    parser.add_argument("--sites", required=True, help="the sites file (JSON)")
    args = parser.parse_args(argv)
    build(Session(load_sites(Path(args.sites)))).run("stdio")


if __name__ == "__main__":
    main()
