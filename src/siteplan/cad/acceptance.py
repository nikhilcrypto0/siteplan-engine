"""The Step 4 acceptance in FreeCAD, run against a live FreeCAD (cad/siteplan_live.FCMacro).

Every change goes through the MCP server, as Claude Code's calls would; every check reads the
geometry back from FreeCAD over its own connection and measures it against the engine's numbers,
so nothing is taken on the server's word and a screenshot is never the proof. Writes
`acceptance-<site>.json` and `.md` beside the drawings.

    uv run python -m siteplan.cad.acceptance --sites out/cad/sites.json \\
        --site dhulapally-debug --blind dhulapally-blind
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from siteplan.cad.bridge import MM_PER_M, Bridge
from siteplan.cad.live import MATCH_M, Session, load_sites

KIT_BLOCK = "two-core-medium"  # the firm's kit block placed as the test tower, when it has one
EAST_M, SOUTH_M = 3.0, 2.0  # the engine's move, and the move made in FreeCAD itself


def _body(result) -> object:
    if result.structuredContent is not None:
        body = result.structuredContent
        return body.get("result", body) if isinstance(body, dict) and len(body) == 1 else body
    texts = [c.text for c in result.content]
    try:
        return json.loads(texts[0]) if len(texts) == 1 else texts
    except json.JSONDecodeError:
        return texts


async def _run(sites: Path, site: str, blind: str | None, bridge: Bridge) -> dict:
    record: dict = {"site": site, "blind_site": blind, "calls": [], "checks": {}}
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "siteplan.cad.server", "--sites", str(sites)])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as mcp:
        await mcp.initialize()

        async def call(tool: str, **arguments) -> object:
            result = await mcp.call_tool(tool, arguments)
            body = _body(result)
            record["calls"].append({"tool": tool, "arguments": arguments,
                                    "error": bool(result.isError)})
            if result.isError:
                raise RuntimeError(f"{tool} failed: {body}")
            return body

        if blind:
            shown = await call("show_site", site=blind, what="setbacks")
            record["blind"] = {"drawn": shown["drawn"], "stopped": shown["stopped"]}
        shown = await call("show_site", site=site, what="setbacks")
        record["shown"] = {k: shown[k] for k in ("mode", "debug", "drawn", "created",
                                                  "updated", "stopped")}
        again = await call("show_site", site=site, what="setbacks")  # no copies on a redraw
        record["redrawn"] = {"created": again["created"], "updated": again["updated"]}
        compared = await call("compare_cad_with_engine", site=site)
        rows = compared["objects"]
        record["checks"]["1 survey boundary"] = rows["survey-boundary"]
        sides = await call("measure_setbacks_in_cad", site=site)
        dims = {}
        for number, side in sides["sides"].items():
            got = bridge.read(f"setback-side-{number}")
            if got:
                dims[number] = {"setback_m": side["setback_m"],
                                "dimension_m": got["measured"] / MM_PER_M}
        record["checks"]["2 setbacks"] = {
            "dimensions": dims,
            "dimensions_exact": all(abs(d["dimension_m"] - d["setback_m"]) <= MATCH_M
                                    for d in dims.values()),
            "buildable_outline_from_each_side": sides["sides"]}
        record["checks"]["3 buildable area"] = rows["buildable"]
        record["checks"]["all drawn shapes agree"] = compared["all_agree"]

        summary = await call("site_summary", site=site)
        block = next((b for b in summary["firm_blocks_m"] if KIT_BLOCK in b["what"]),
                     summary["firm_blocks_m"][0])
        placed = await call("place_tower", site=site, tower="T1", length_m=block["length_m"],
                            depth_m=block["depth_m"])
        before = bridge.read("tower-T1")
        bridge.snapshot(f"acceptance-{site}-1-placed.png", 1600, 1200)
        moved = await call("move_tower", site=site, tower="T1", east_m=EAST_M)
        after = bridge.read("tower-T1")
        shift = [round((a[0] - b[0]) / MM_PER_M, 6) for a, b in zip(after["rings"][0],
                                                                    before["rings"][0],
                                                                    strict=True)]
        bridge.snapshot(f"acceptance-{site}-2-moved.png", 1600, 1200)
        record["checks"]["5 modified through MCP"] = {
            "tower": block, "placed_holds": placed["checks"]["T1"]["holds"],
            "moved_east_m_per_vertex_in_freecad": shift,
            "moved_holds": moved["checks"]["T1"]["holds"]}
        bridge.move("tower-T1", 0.0, -SOUTH_M)  # as a person dragging it in FreeCAD
        taken = await call("read_tower_from_cad", site=site, tower="T1")
        engine_y = [p[1] for p in taken["towers"]["T1"]]
        record["checks"]["4 editable and measurable"] = {
            "tower_type": after["type"], "points_editable": after["points_editable"],
            "tower_area_sqm": after["area"] / MM_PER_M ** 2,
            "buildable_type": bridge.read("buildable")["type"],
            "moved_in_freecad_south_m": SOUTH_M,
            "engine_reads_it_back_y_m": engine_y,
            "engine_checks_after": taken["checks"]["T1"]}
        await call("place_tower", site=site, tower="T2", length_m=block["length_m"],
                   depth_m=block["depth_m"], x=summary["a_point_well_inside_m"][0],
                   y=summary["a_point_well_inside_m"][1] + 60.0)
        listed_with = sorted(o["id"] for o in bridge.listing() if o["id"].startswith("tower"))
        deleted = await call("delete_tower", site=site, tower="T2")
        listed_without = sorted(o["id"] for o in bridge.listing()
                                if o["id"].startswith("tower"))
        record["checks"]["6 drawing updates"] = {
            "objects_with_T2": listed_with, "objects_after_delete": listed_without,
            "removed_objects": deleted["removed_objects"],
            "remaining_sqm_after_delete": deleted["remaining_sqm"],
            "snapshots": [f"acceptance-{site}-1-placed.png", f"acceptance-{site}-2-moved.png"]}
        file_name = f"acceptance-{site}.FCStd"
        saved = await call("save_drawing", site=site, file_name=file_name)
        reopened = await call("reopen_drawing", site=site, file_name=file_name)
        after_reopen = await call("compare_cad_with_engine", site=site)
        record["checks"]["7 saved and reopened"] = {
            "file": saved, "document": reopened, "all_agree": after_reopen["all_agree"],
            "objects": sorted(after_reopen["objects"])}
    return record


def verdicts(record: dict) -> dict[str, bool]:
    c = record["checks"]
    moved = c["5 modified through MCP"]["moved_east_m_per_vertex_in_freecad"]
    return {
        "1 survey boundary": bool(c["1 survey boundary"].get("agrees")),
        "2 setbacks": c["2 setbacks"]["dimensions_exact"],
        "3 buildable area": bool(c["3 buildable area"].get("agrees")),
        "4 editable and measurable": c["4 editable and measurable"]["points_editable"],
        "5 modified through MCP": all(abs(m - EAST_M) <= MATCH_M for m in moved),
        "6 drawing updates": ("tower-T2" in c["6 drawing updates"]["objects_with_T2"]
                              and "tower-T2" not in c["6 drawing updates"]
                              ["objects_after_delete"]),
        "7 saved and reopened": c["7 saved and reopened"]["all_agree"],
    }


def markdown(record: dict, passed: dict[str, bool]) -> str:
    lines = [f"# Step 4 in FreeCAD: {record['site']}", ""]
    if record["shown"]["debug"]:
        lines += ["**DEBUG RUN**: the net plot comes from the firm's finished plan, so this is a "
                  "test of the CAD link, not acceptance evidence for the engine.", ""]
    if record.get("blind"):
        lines += [f"Blind run ({record['blind_site']}): {record['blind']['drawn']} objects drawn; "
                  f"it stops at: {record['blind']['stopped']}", ""]
    lines += ["| Check | Result |", "|---|---|"]
    lines += [f"| {name} | {'PASS' if ok else 'FAIL'} |" for name, ok in passed.items()]
    lines += ["", f"Tolerance: {MATCH_M * 1000:g} mm on any vertex, area to one part in a "
              "million.", "", "Every MCP call: " + ", ".join(c["tool"] for c in record["calls"])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m siteplan.cad.acceptance")
    parser.add_argument("--sites", required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--blind", help="the same site's blind run, shown first")
    args = parser.parse_args(argv)
    sites = Path(args.sites).resolve()
    load_sites(sites)  # a bad file stops here, before FreeCAD is touched
    bridge = Bridge()
    Session({}, bridge).bridge.ping()
    record = asyncio.run(_run(sites, args.site, args.blind, bridge))
    passed = verdicts(record)
    record["passed"] = passed
    out = bridge.folder
    (out / f"acceptance-{args.site}.json").write_text(json.dumps(record, indent=1) + "\n")
    (out / f"acceptance-{args.site}.md").write_text(markdown(record, passed))
    for name, ok in passed.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(passed.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
