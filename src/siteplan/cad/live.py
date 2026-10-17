"""A live CAD session: a site's steps run by the engine, drawn in FreeCAD, and test objects (a
tower footprint) placed, moved, read back after an edit in FreeCAD, or removed, each change
checked by the engine's own rules. FreeCAD shows and edits; the engine decides.

A site is named in a sites file (JSON, client paths, kept in gitignored fixtures/ or out/):
{"dhulapally": {"survey": ..., "answers": ..., "profile": ..., "mode": "debug", "workspace": ...},
 "suchitra": {"survey": ..., "project": ..., "mode": "blind", ...}}. A blind site never reads the
firm's finished plan (`blind.py` holds it); a debug site says DEBUG in every answer."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import polylabel, unary_union

from siteplan.cad import scene
from siteplan.cad.bridge import Bridge, from_cad, to_cad
from siteplan.profiles import load_profile
from siteplan.prototypes.plates import PLATE_SOURCE
from siteplan.service import describe, edits, judge, render, store, versions
from siteplan.service.models import Mode
from siteplan.service.store import RunRecord
from siteplan.steps.inputs import Inputs, from_answers, from_project
from siteplan.steps.main_road_height import height_for
from siteplan.steps.road_widening import take_off
from siteplan.steps.setbacks import Setbacks, land_left_at, set_back
from siteplan.steps.survey_copy import copy_survey
from siteplan.steps.tot_lot import firm_blocks

FIT_M = 0.01  # a footprint this far past a line still keeps it (drawing noise)
MATCH_M = 0.001  # CAD and engine agree when no vertex is further apart than this
MATCH_SHARE = 1e-6  # ... and their areas differ by less than this share
POLE_M = 0.1  # how finely the middle of the buildable area is looked for
SAME_SQM = 1e-4  # a shape read back from CAD differing by less than this area did not change
TURN_DEG = 0.01  # a block read back turned by less than this was only moved
SHOT_PX = (1600, 1200)  # a screenshot's width and height in pixels


@dataclass
class TestTower:
    """A footprint placed to try the rules: where it stands, how tall (for its setbacks)."""

    ident: str
    polygon: Polygon
    floors: int


@dataclass
class Site:
    name: str
    mode: str
    inputs: Inputs
    setbacks: Setbacks
    towers: dict[str, TestTower] = field(default_factory=dict)
    document: str = ""  # its FreeCAD document; a reopened file brings its own name

    def __post_init__(self) -> None:
        self.document = self.document or f"Siteplan_{self.name}"

    @property
    def debug(self) -> bool:
        return self.mode != "blind"


def load_sites(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text())


def run_steps(spec: dict) -> tuple[Inputs, Setbacks]:
    """Steps 1 to 4 for a site, the engine's own functions, nothing redone here."""
    survey = Path(spec["survey"])
    workspace = Path(spec["workspace"]) if spec.get("workspace") else None
    mode = spec.get("mode", "blind")
    if spec.get("project"):
        inputs = from_project(survey, Path(spec["project"]), workspace, mode)
    else:
        profile = load_profile(spec["profile"]) if spec.get("profile") else None
        inputs = from_answers(survey, json.loads(Path(spec["answers"]).read_text()), workspace,
                              profile, mode)
    copy = copy_survey(inputs)
    return inputs, set_back(inputs, copy, height_for(inputs, copy), take_off(inputs, copy))


def tower_polygon(x: float, y: float, length_m: float, depth_m: float,
                  bearing_deg: float) -> Polygon:
    """A rectangle centred on (x, y), `length_m` along the bearing (clockwise from north, so 0
    runs north to south) and `depth_m` across it."""
    a = math.radians(bearing_deg)
    ux, uy = math.sin(a), math.cos(a)  # along
    vx, vy = uy, -ux  # across
    hl, hd = length_m / 2, depth_m / 2
    return Polygon([(x + ux * sl * hl + vx * sd * hd, y + uy * sl * hl + vy * sd * hd)
                    for sl, sd in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


def _moved(what: str, east_m: float, north_m: float) -> str:
    east_m, north_m = round(east_m, 2) + 0.0, round(north_m, 2) + 0.0  # no '-0.00 m'
    return (f"{what} moved {abs(east_m):.2f} m {'east' if east_m >= 0 else 'west'}, "
            f"{abs(north_m):.2f} m {'north' if north_m >= 0 else 'south'}")


def _shift_words(old, new, before: Polygon, after: Polygon) -> str:
    """How a block read back from CAD moved: turned, and how far its middle went."""
    turn = (new.rotation_deg - old.rotation_deg + 180) % 360 - 180
    east, north = after.centroid.x - before.centroid.x, after.centroid.y - before.centroid.y
    moved = _moved(old.name, east, north)
    return (f"{old.name} turned {turn:.2f} degrees anticlockwise and {moved.split(' ', 1)[1]}"
            if abs(turn) >= TURN_DEG else moved)


class Session:
    """Sites opened by name, each drawn in its own FreeCAD document."""

    def __init__(self, sites: dict[str, dict], bridge: Bridge | None = None):
        self.specs = sites
        self.sites: dict[str, Site] = {}
        self._bridge = bridge

    @property
    def bridge(self) -> Bridge:
        if self._bridge is None:
            self._bridge = Bridge()
        return self._bridge

    # --- sites and what is drawn of them ------------------------------------------------------

    def site(self, name: str) -> Site:
        if name not in self.sites:
            if name not in self.specs:
                raise KeyError(f"no site named {name!r}; known: {', '.join(sorted(self.specs))}")
            spec = self.specs[name]
            inputs, setbacks = run_steps(spec)
            self.sites[name] = Site(name, spec.get("mode", "blind"), inputs, setbacks)
        return self.sites[name]

    def show(self, name: str, what: str) -> dict:
        """Draw a site's step in FreeCAD, or update what is already drawn: 'survey' (step 1),
        'net' (step 3), 'setbacks' (step 4, with the buildable area) or 'all'."""
        if what not in ("survey", "net", "setbacks", "all"):
            raise ValueError("show 'survey', 'net', 'setbacks' or 'all'")
        s = self.site(name)
        b = s.setbacks
        items: list[dict] = []
        items += scene.survey_items(b)
        stopped = None
        if what in ("net", "setbacks", "all"):
            if b.widening.stopped:
                stopped = f"step 3 stopped: {b.widening.stopped} ({b.widening.ask})"
            else:
                items += scene.net_items(b)
        if what in ("setbacks", "all") and stopped is None:
            if b.stopped:
                stopped = f"step 4 stopped: {b.stopped} ({b.ask})"
            else:
                items += scene.setback_items(b)
        self.bridge.document(s.document)
        done = self.bridge.upsert(items, scene.styles())
        self.bridge.view(True)
        return {"site": name, "mode": s.mode, "debug": s.debug, "drawn": len(done),
                "created": sum(1 for d in done if d["created"]),
                "updated": sum(1 for d in done if not d["created"]),
                "stopped": stopped, "summary": self.summary(name)}

    def summary(self, name: str) -> dict:
        s = self.site(name)
        b = s.setbacks
        out = {"site": name, "mode": s.mode,
               "survey_sqm": round(b.copy.plot.area, 2),
               "net_sqm": round(b.widening.net.area, 2) if b.widening.net is not None else None}
        if b.stopped:
            return {**out, "stopped": b.stopped, "question": b.ask}
        x0, y0, x1, y1 = b.left.bounds
        inside = polylabel(max(scene.parts(b.left), key=lambda p: p.area), tolerance=POLE_M)
        blocks = firm_blocks(s.inputs.workspace)
        return {**out, "floors": b.floors, "high_rise": b.high_rise,
                "buildable_sqm": round(b.left.area, 2),
                "buildable_bounds_m": [round(v, 3) for v in (x0, y0, x1, y1)],
                "a_point_well_inside_m": [round(inside.x, 3), round(inside.y, 3)],
                "setbacks_m": sorted({side.metres for side in b.sides}),
                "firm_blocks_m": [{"what": what, "length_m": round(length, 2),
                                   "depth_m": round(depth, 2)}
                                  for what, length, depth in blocks.footprints] if blocks else [],
                "towers": sorted(s.towers)}

    # --- test towers ---------------------------------------------------------------------------

    def place_tower(self, name: str, ident: str, length_m: float, depth_m: float,
                    x: float | None = None, y: float | None = None, bearing_deg: float = 0.0,
                    floors: int | None = None) -> dict:
        s = self.site(name)
        if s.setbacks.stopped:
            raise ValueError(f"no setbacks yet: {s.setbacks.stopped}")
        if x is None or y is None:
            middle = polylabel(max(scene.parts(s.setbacks.left), key=lambda p: p.area),
                               tolerance=POLE_M)
            x, y = middle.x, middle.y
        s.towers[ident] = TestTower(ident, tower_polygon(x, y, length_m, depth_m, bearing_deg),
                                    floors or s.setbacks.floors)
        return self._redraw(s, [ident])

    def move_tower(self, name: str, ident: str, east_m: float = 0.0,
                   north_m: float = 0.0) -> dict:
        s = self.site(name)
        tower = self._tower(s, ident)
        moved = Polygon([(px + east_m, py + north_m) for px, py in tower.polygon.exterior.coords])
        s.towers[ident] = TestTower(ident, moved, tower.floors)
        return self._redraw(s, [ident])

    def delete_tower(self, name: str, ident: str) -> dict:
        s = self.site(name)
        self._tower(s, ident)
        del s.towers[ident]
        self.bridge.document(s.document)
        gone = self.bridge.remove([f"tower-{ident}", f"tower-{ident}-label"])
        return {**self._redraw(s, []), "removed_objects": gone}

    def read_back(self, name: str, ident: str) -> dict:
        """Take a tower as it now stands in FreeCAD (dragged or edited there) into the engine,
        and check it."""
        s = self.site(name)
        tower = self._tower(s, ident)
        self.bridge.document(s.document)
        got = self.bridge.read(f"tower-{ident}")
        if not got or not got.get("rings"):
            raise ValueError(f"tower {ident} is not in FreeCAD")
        s.towers[ident] = TestTower(ident, Polygon([from_cad(p) for p in got["rings"][0]]),
                                    tower.floors)
        return self._redraw(s, [ident])

    def _tower(self, s: Site, ident: str) -> TestTower:
        if ident not in s.towers:
            raise KeyError(f"no tower {ident!r} on {s.name}; placed: {sorted(s.towers)}")
        return s.towers[ident]

    def _redraw(self, s: Site, idents: list[str]) -> dict:
        items = []
        for ident in idents:
            t = s.towers[ident]
            items += scene.polygon_items(f"tower-{ident}", f"Tower {ident} (Stilt + {t.floors})",
                                         scene.TOWERS, t.polygon, "outline")
            c = t.polygon.centroid
            items.append({"id": f"tower-{ident}-label", "label": f"Tower {ident} label",
                          "layer": scene.NOTES, "kind": "text", "at": to_cad((c.x, c.y)),
                          "text": f"{ident}\nS+{t.floors}"})
        remaining = self.remaining(s)
        items += scene.polygon_items("remaining", "Buildable area left after the towers",
                                     scene.FOOTPRINTS, remaining, "area")
        self.bridge.document(s.document)
        if remaining.is_empty:
            self.bridge.remove(["remaining"])
        self.bridge.upsert(items, scene.styles())
        return {"site": s.name, "mode": s.mode, "checks": self.validate(s.name),
                "remaining_sqm": round(remaining.area, 2),
                "towers": {k: [[round(px, 3), round(py, 3)]
                               for px, py in t.polygon.exterior.coords[:-1]]
                           for k, t in s.towers.items()}}

    # --- the engine's checks --------------------------------------------------------------------

    def validate(self, name: str) -> dict:
        """Each tower against the engine's rules: wholly inside the land its own height's
        setbacks leave (step 4's rules, `land_left_at`), out of every water body's buffer, and
        the taller one's setback from every other tower (rule 7(a)(xii))."""
        s = self.site(name)
        b = s.setbacks
        water = unary_union([w.kept_free for w in b.widening.water if w.buffer_m is not None]) \
            if b.widening.water else Polygon()
        out = {}
        towers = list(s.towers.values())
        for t in towers:
            land, setback = land_left_at(b, t.floors)
            outside = t.polygon.difference(land).area
            checks = {"setback_m": setback,
                      "inside_setbacks": outside <= FIT_M * t.polygon.length,
                      "outside_sqm": round(outside, 3),
                      "in_water_buffer_sqm": round(t.polygon.intersection(water).area, 3)}
            gaps = {}
            for other in towers:
                if other is t:
                    continue
                need = max(setback, land_left_at(b, other.floors)[1])
                apart = t.polygon.distance(other.polygon)
                gaps[other.ident] = {"apart_m": round(apart, 3), "needs_m": need,
                                     "holds": apart >= need - FIT_M}
            checks["gaps"] = gaps
            checks["holds"] = (checks["inside_setbacks"]
                               and checks["in_water_buffer_sqm"] <= FIT_M * t.polygon.length
                               and all(g["holds"] for g in gaps.values()))
            out[t.ident] = checks
        return out

    def remaining(self, s: Site) -> Polygon:
        """The buildable area less each tower and the setback it keeps round itself."""
        if s.setbacks.stopped:
            return Polygon()
        kept = [t.polygon.buffer(land_left_at(s.setbacks, t.floors)[1], join_style="mitre")
                for t in s.towers.values()]
        return s.setbacks.left.difference(unary_union(kept)) if kept else s.setbacks.left

    # --- proof: what FreeCAD holds against what the engine made ---------------------------------

    def compare(self, name: str) -> dict:
        """Read every drawn outline and zone back from FreeCAD and measure it against the
        engine's own shape: the largest distance between them (Hausdorff, metres) and the area
        (FreeCAD's mm² over 1,000,000 against the engine's m²)."""
        s = self.site(name)
        b = s.setbacks
        engine = {"survey-boundary": b.copy.plot}
        if b.widening.net is not None:
            engine["net-plot"] = b.widening.net
        if not b.stopped:
            engine.update({"setback-zone": b.band, "buildable": b.left,
                           "green-strip": b.green, "fire-lane": b.fire_lane})
        engine.update({f"tower-{k}": t.polygon for k, t in s.towers.items()})
        self.bridge.document(s.document)
        rows = {}
        for ident, shape in engine.items():
            if shape is None or shape.is_empty:
                continue
            pieces = scene.parts(shape)
            for n, piece in enumerate(sorted(pieces, key=lambda p: -p.area), 1):
                key = ident if n == 1 else f"{ident}#{n}"
                got = self.bridge.read(key)
                if not got or not got.get("rings"):
                    rows[key] = {"found": False}
                    continue
                rings = [[from_cad(p) for p in r] for r in got["rings"]]
                cad = Polygon(rings[0], rings[1:])
                engine_piece = piece if got["kind"] == "area" else Polygon(piece.exterior)
                hausdorff = cad.exterior.hausdorff_distance(engine_piece.exterior)
                cad_area = got["area"] / 1e6
                share = abs(cad_area - engine_piece.area) / engine_piece.area
                rows[key] = {"found": True, "kind": got["kind"],
                             "engine_sqm": round(engine_piece.area, 4),
                             "freecad_sqm": round(cad_area, 4),
                             "area_difference_share": share,
                             "largest_distance_m": hausdorff,
                             "vertices": [len(engine_piece.exterior.coords) - 1,
                                          len(rings[0])],
                             "agrees": hausdorff <= MATCH_M and share <= MATCH_SHARE}
        return {"site": name, "mode": s.mode, "tolerance_m": MATCH_M,
                "tolerance_area_share": MATCH_SHARE, "objects": rows,
                "all_agree": all(r.get("agrees") for r in rows.values())}

    def setback_distances(self, name: str) -> dict:
        """Each side of the net plot against the buildable outline as FreeCAD holds it: how far
        in the outline lies from that side, beside the setback the engine asked of it."""
        s = self.site(name)
        b = s.setbacks
        self.bridge.document(s.document)
        got = self.bridge.read("buildable")
        cad = Polygon([from_cad(p) for p in got["rings"][0]])
        out = {}
        for side in b.sides:
            distance = side.line.distance(cad)
            out[str(side.number)] = {"faces": side.faces, "length_m": round(side.length_m, 2),
                                     "setback_m": side.metres, "measured_m": round(distance, 4),
                                     "kept": distance >= side.metres - MATCH_M}
        return {"site": name, "sides": out, "all_kept": all(v["kept"] for v in out.values())}

    # --- a layout a service run made (Stage B, 2026-10-16) -----------------------------------

    def show_layout(self, name: str, run_id: str, layout_id: str) -> dict:
        """Draw a layout a run showed or proposed, or a version saved of one, in the site's
        document: judged again by the independent validator from the run's stored contracts
        (service.judge), labelled on the sheet (DEBUG or STUDY where they apply, its verdict,
        PRELIMINARY for floor plates), the previous layout's objects removed."""
        out, record = self._run(name, run_id)
        judged = judge.judge_again(out, record, layout_id)
        candidate, report = judged.candidate, judged.report
        plan = render.plan_of(judged.inputs.site, candidate)
        plates = {t.name for t in candidate.towers
                  if candidate.prototype(t.prototype_id).source.startswith(PLATE_SOURCE)}
        items = [i for _, group in scene.candidate_layers(plan, None, "") for i in group]
        for item in items:  # each plate tower's own label says so
            if item["kind"] == "text" and item["label"].removesuffix(" label") in plates:
                item["text"] += "\nPRELIMINARY floor plate"
        refusals = judge.refusals(judged)
        lines = self._labels(out, record, judged, layout_id, sorted(plates), refusals)
        items.append(scene.sheet_label(plan.plot, lines))
        items.append(scene.sheet_note(plan.plot, self._note(report, refusals)))
        drawn = {i["id"] for i in items}
        self.bridge.document(self._document(name))
        stale = [o["id"] for o in self.bridge.listing() if o["id"].startswith(scene.LAYOUT)
                 and o["id"].split("#")[0] not in drawn]
        removed = self.bridge.remove(stale) if stale else 0
        done = self.bridge.upsert(items, scene.styles())
        self.bridge.view(True)
        return {"site": name, "run": run_id, "layout": layout_id, "labels": lines,
                "verdict": report.verdict.legal.value, "refusals": refusals,
                "drawn": len(done), "removed": removed}

    def keep_layout(self, name: str, run_id: str, layout_id: str, note: str = "") -> dict:
        """Save a layout of a run, unchanged, as a version of its own in the run's folder
        (service.versions): its parent's digest recorded, judged by the validator now."""
        out, record = self._run(name, run_id)
        version, _, _ = versions.make_version(out, record, layout_id, None, [], note)
        judged = judge.judge_again(out, record, version.version_id)
        return {"site": name, "run": run_id, "version": version.version_id,
                "parent": version.parent_id, "verdict": judged.report.verdict.legal.value,
                "refusals": judge.refusals(judged)}

    # --- edits of a layout (Stage C, 2026-10-16) ----------------------------------------------

    def move_block(self, name: str, run_id: str, layout_id: str, block: str, east_m: float,
                   north_m: float) -> dict:
        return self._edit(name, run_id, layout_id,
                          lambda c: edits.moved_block(c, block, east_m, north_m),
                          [_moved(block, east_m, north_m)], [block])

    def turn_block(self, name: str, run_id: str, layout_id: str, block: str,
                   degrees: float) -> dict:
        return self._edit(name, run_id, layout_id,
                          lambda c: edits.turned_block(c, block, degrees),
                          [f"{block} turned {degrees:g} degrees anticlockwise"], [block])

    def move_club_house(self, name: str, run_id: str, layout_id: str, east_m: float,
                        north_m: float) -> dict:
        return self._edit(name, run_id, layout_id,
                          lambda c: edits.moved_club(c, east_m, north_m),
                          [_moved("club house", east_m, north_m)])

    def move_tot_lot_piece(self, name: str, run_id: str, layout_id: str, piece: int,
                           east_m: float, north_m: float) -> dict:
        return self._edit(name, run_id, layout_id,
                          lambda c: edits.moved_piece(c, piece, east_m, north_m),
                          [_moved(f"tot-lot piece {piece}", east_m, north_m)])

    def lock_blocks(self, name: str, run_id: str, layout_id: str, blocks: list[str]) -> dict:
        out, record = self._run(name, run_id)
        done = edits.lock(out, record, layout_id, blocks)
        return self._after(name, run_id, done)

    def read_layout_from_cad(self, name: str, run_id: str, layout_id: str) -> dict:
        """Take a layout as it now stands in FreeCAD (blocks dragged or turned, the club house or
        a tot-lot piece redrawn) into a version of its own, judged by the validator; nothing is
        saved when nothing changed. A block reshaped in CAD is refused."""
        out, record = self._run(name, run_id)
        candidate = judge.judge_again(out, record, layout_id).candidate
        self.bridge.document(self._document(name))
        changed, words, moved = candidate, [], []
        for tower in candidate.towers:
            outline = self._outline(f"{scene.LAYOUT}{tower.name.lower()}")
            placed = candidate.placed_footprint(tower)
            if outline is None or outline.symmetric_difference(placed).area < SAME_SQM:
                continue
            changed = edits.block_from_outline(changed, tower.name, outline)
            new = next(t for t in changed.towers if t.name == tower.name)
            words.append(_shift_words(tower, new, placed, changed.placed_footprint(new)))
            moved.append(tower.name)
        club = candidate.program.club_house
        outline = self._outline(f"{scene.LAYOUT}club-1")
        if club is not None and outline is not None and outline.symmetric_difference(
                club.shape.to_shapely()).area >= SAME_SQM:
            changed = edits.club_from_outline(changed, outline)
            words.append("club house redrawn in CAD")
        for k, pocket in enumerate(candidate.program.open_space, 1):
            outline = self._outline(f"{scene.LAYOUT}open-{k}")
            if outline is not None and outline.symmetric_difference(
                    pocket.to_shapely()).area >= SAME_SQM:
                changed = edits.piece_from_outline(changed, k, outline)
                words.append(f"tot-lot piece {k} redrawn in CAD")
        if not words:
            return {"site": name, "run": run_id, "layout": layout_id, "version": None,
                    "edits": [], "said": "nothing in FreeCAD differs from the layout"}
        final = changed
        return self._edit(name, run_id, layout_id, lambda _: final, words, moved)

    def _edit(self, name: str, run_id: str, layout_id: str, change, words: list[str],
              moves: list[str] = ()) -> dict:
        out, record = self._run(name, run_id)
        done = edits.edit(out, record, layout_id, change, words, moves)
        return self._after(name, run_id, done)

    def _after(self, name: str, run_id: str, done) -> dict:
        """The version an edit made, drawn in FreeCAD, and what it broke."""
        shown = self.show_layout(name, run_id, done.version.version_id)
        return {"site": name, "run": run_id, "version": done.version.version_id,
                "parent": done.version.parent_id, "edits": list(done.version.edits),
                "locked": list(done.version.locked), "broke": list(done.broke),
                "verdict": done.report.verdict.legal.value, "refusals": list(done.refusals),
                "labels": shown["labels"]}

    def _outline(self, ident: str) -> Polygon | None:
        got = self.bridge.read(ident)
        if not got or not got.get("rings"):
            return None
        return Polygon([from_cad(p) for p in got["rings"][0]])

    def _run(self, name: str, run_id: str) -> tuple[Path, RunRecord]:
        """A run of the service for this site: in the folder the sites file names as 'runs' (the
        service's out); a blind site never reads a DEBUG run (the firm's finished plan)."""
        if name not in self.specs:
            raise KeyError(f"no site named {name!r}; known: {', '.join(sorted(self.specs))}")
        spec = self.specs[name]
        if not spec.get("runs"):
            raise ValueError(f"the sites file names no 'runs' folder (the service's out) for "
                             f"{name}")
        out = Path(spec["runs"])
        record = store.read_record(out, run_id)
        if record.mode is Mode.DEBUG and spec.get("mode", "blind") == "blind":
            raise ValueError("that run used the firm's finished plan; a blind site does not "
                             "read it")
        return out, record

    def _document(self, name: str) -> str:
        return self.sites[name].document if name in self.sites else f"Siteplan_{name}"

    @staticmethod
    def _labels(out: Path, record: RunRecord, judged: judge.Judged, layout_id: str,
                plates: list[str], refusals: list[str]) -> list[str]:
        candidate, report = judged.candidate, judged.report
        point = f", {candidate.pareto_tag}" if candidate.pareto_tag else ""
        lines = [f"{layout_id} (run {record.run_id}{point})"]
        if versions.exists(out, record, layout_id):
            version, _, _ = versions.load(out, record, layout_id)
            lines.append(f"a version of {version.parent_id}: "
                         + ("; ".join(version.edits) if version.edits else "unchanged"))
        if record.mode is Mode.DEBUG:
            lines.append("DEBUG RUN: drawn on the firm's finished plan, not an acceptance")
        if judged.inputs.brief.objectives.study:
            lines.append("STUDY, NOT A LEGAL LAYOUT")
        detail = report.verdict.legal.value != "PASS"
        lines.append(describe.verdict_short(report)
                     + (" (listed in the note below the plot)" if detail else ""))
        if plates:
            lines.append(f"PRELIMINARY: floor plates sized to the land, not the firm's drawing "
                         f"({', '.join(plates)})")
        if refusals:
            lines.append(f"NOT EXPORTABLE: {len(refusals)} reason"
                         f"{'s' if len(refusals) != 1 else ''} (in the note)")
        return lines

    @staticmethod
    def _note(report, refusals: list[str]) -> list[str]:
        """The verdict in full, and why the layout could not be exported as it stands."""
        lines = [f"Verdict in full: {describe.verdict_line(report)}"]
        if refusals:
            lines += ["Not exportable as it stands:", *(f"- {r}" for r in refusals)]
        return lines

    def screenshot(self, name: str, file_name: str, width: int = SHOT_PX[0],
                   height: int = SHOT_PX[1]) -> str:
        """A picture of the site's FreeCAD document framed on the plot and its short label: the
        note of the verdict in full (its own layer) is hidden for the shot and shown again."""
        self.bridge.document(self._document(name))
        note = any(layer["layer"] == scene.DETAIL for layer in self.bridge.layers())
        if note:
            self.bridge.show_layer(scene.DETAIL, False)
        try:
            return self.bridge.snapshot(file_name, width, height)
        finally:
            if note:
                self.bridge.show_layer(scene.DETAIL, True)

    def save(self, name: str, file_name: str) -> str:
        self.bridge.document(self.site(name).document)
        return self.bridge.save(file_name)

    def reopen(self, name: str, file_name: str) -> str:
        """Close the saved drawing and open it again from the file; the site carries on in the
        reopened document."""
        s = self.site(name)
        s.document = self.bridge.reopen(file_name)
        return s.document

