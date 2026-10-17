"""Edits of a layout (2026-10-16, Stage C of the architect's roadmap): a block locked, moved or
turned, the club house or a tot-lot piece moved. Each edit is saved as a version of its own
(service.versions) and judged by the independent validator; nothing else is laid again. The
roads, the fire lanes and the parking stay as drawn, and what the edit broke is named: every
legal check that held before it and holds no more (`what_broke`). Laying the rest again round
blocks the architect has locked is Stage D's.

An edited layout keeps its blocks' prototypes, heights and flats, so its counts stand; it drops
what the generator worked out from where things stood (its ledger of the ground, its rule layers,
its own claims and its scores), which an edit makes stale and the validator would otherwise
report as a discrepancy, and says so in a caveat. Every figure reported of it is the validator's.

A block is rigid: moved or turned whole (read back from FreeCAD, an outline that is not its
prototype's outline moved and turned is refused); the club house and a tot-lot piece may be
moved or redrawn. A block locked in a version stays locked in every version made from it, and an
edit that would move it is refused.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon

from siteplan import validator
from siteplan.contracts import CandidateLayout, ValidationReport
from siteplan.contracts.common import Shape
from siteplan.service import judge, versions
from siteplan.service.store import RunRecord, StoreError
from siteplan.validator.open_space import STUDY_COUNTING

COUNTING = "open_space_counting_sqm"  # the validator's name for what counts, by reading

EDITED_CAVEAT = ("EDITED BY HAND: the blocks, the club house and the tot-lot stand where the "
                 "architect put them; the roads, fire lanes and parking are as the search drew "
                 "them, and the generator's own ledger and claims are dropped (every figure is "
                 "the validator's)")
RIGID_TOL_M = 0.01  # a block read back from CAD is its own outline moved and turned within this


class EditRefused(StoreError):
    """An edit the layout cannot take: a locked block, a block reshaped, a name not in it."""


@dataclass(frozen=True)
class Edited:
    version: versions.LayoutVersion
    candidate: CandidateLayout
    report: ValidationReport
    broke: tuple[str, ...]  # what held before the edit and holds no more
    refusals: tuple[str, ...]  # why it could not be exported as it stands


# --- the edits themselves: a new candidate, the old one untouched ------------------------------


def moved_block(candidate: CandidateLayout, name: str, east_m: float, north_m: float
                ) -> CandidateLayout:
    tower = _tower(candidate, name)
    return _with_tower(candidate, tower.model_copy(update={"x": tower.x + east_m,
                                                            "y": tower.y + north_m}))


def turned_block(candidate: CandidateLayout, name: str, degrees: float) -> CandidateLayout:
    """The block turned `degrees` anticlockwise about the middle of its footprint."""
    tower = _tower(candidate, name)
    cx, cy = candidate.placed_footprint(tower).centroid.coords[0]
    a = math.radians(degrees)
    dx, dy = tower.x - cx, tower.y - cy
    return _with_tower(candidate, tower.model_copy(update={
        "x": cx + dx * math.cos(a) - dy * math.sin(a),
        "y": cy + dx * math.sin(a) + dy * math.cos(a),
        "rotation_deg": (tower.rotation_deg + degrees) % 360}))


def block_from_outline(candidate: CandidateLayout, name: str, outline: Polygon
                       ) -> CandidateLayout:
    """The block where its outline now stands (dragged or turned in FreeCAD): its own footprint
    moved and turned, found from the outline's corners; any other shape is refused."""
    tower = _tower(candidate, name)
    placed = candidate.placed_footprint(tower)
    fit = _rigid_fit(placed, outline)
    if fit is None:
        raise EditRefused(f"{name}'s outline in CAD is not its block moved or turned: a block "
                          "keeps its prototype's shape (move or turn it; do not reshape it)")
    degrees, (tx, ty) = fit
    turned = turned_block(candidate, name, degrees)
    return moved_block(turned, name, tx, ty)


def moved_club(candidate: CandidateLayout, east_m: float, north_m: float) -> CandidateLayout:
    club = candidate.program.club_house
    if club is None:
        raise EditRefused("the layout has no club house")
    return club_from_outline(candidate, affinity.translate(club.shape.to_shapely(),
                                                           east_m, north_m))


def club_from_outline(candidate: CandidateLayout, outline: Polygon) -> CandidateLayout:
    club = candidate.program.club_house
    if club is None:
        raise EditRefused("the layout has no club house")
    program = candidate.program.model_copy(update={"club_house": club.model_copy(
        update={"shape": Shape.from_shapely(outline)})})
    return _edited(candidate, program=program)


def moved_piece(candidate: CandidateLayout, piece: int, east_m: float, north_m: float
                ) -> CandidateLayout:
    """Tot-lot piece `piece` (counted from 1, as CAD names them: layout-open-<piece>) moved."""
    shape = _piece(candidate, piece)
    return piece_from_outline(candidate, piece, affinity.translate(shape, east_m, north_m))


def piece_from_outline(candidate: CandidateLayout, piece: int, outline: Polygon
                       ) -> CandidateLayout:
    _piece(candidate, piece)
    pockets = list(candidate.program.open_space)
    pockets[piece - 1] = Shape.from_shapely(outline)
    return _edited(candidate, program=candidate.program.model_copy(
        update={"open_space": pockets}))


# --- saved as a version and judged ---------------------------------------------------------------


def edit(out: Path, record: RunRecord, parent_id: str,
         change: Callable[[CandidateLayout], CandidateLayout], words: list[str],
         moves: Iterable[str] = (), note: str = "") -> Edited:
    """Make the change to `parent_id`, save it as a version and judge it: refused when it moves a
    block the parent has locked (`moves`: the blocks it moves or turns)."""
    parent = judge.judge_again(out, record, parent_id)
    locked = locks(out, record, parent_id)
    held = sorted(set(moves) & set(locked))
    if held:
        raise EditRefused(f"{', '.join(held)} {'is' if len(held) == 1 else 'are'} locked in "
                          f"{parent_id}; unlock it first, or edit another block")
    changed = _open_space_as_measured(change(parent.candidate), parent.inputs)
    version, candidate, report = versions.make_version(out, record, parent_id, changed, words,
                                                       note, locked=locked, before=parent.report)
    return Edited(version, candidate, report, tuple(version.broke),
                  tuple(judge.refusals(judge.judge_again(out, record, version.version_id))))


def lock(out: Path, record: RunRecord, parent_id: str, names: list[str], note: str = ""
         ) -> Edited:
    """A version of `parent_id` with these blocks locked, nothing moved."""
    parent = judge.judge_again(out, record, parent_id)
    known = {t.name for t in parent.candidate.towers}
    unknown = sorted(set(names) - known)
    if unknown:
        raise EditRefused(f"{parent_id} has no block {', '.join(unknown)}; it has "
                          f"{', '.join(sorted(known))}")
    locked = sorted(set(locks(out, record, parent_id)) | set(names))
    version, candidate, report = versions.make_version(
        out, record, parent_id, None, [f"{', '.join(sorted(names))} locked"], note, locked=locked)
    return Edited(version, candidate, report, (),
                  tuple(judge.refusals(judge.judge_again(out, record, version.version_id))))


def locks(out: Path, record: RunRecord, layout_id: str) -> list[str]:
    """The blocks locked in a layout: none in one the run made, a version's own otherwise."""
    if not versions.exists(out, record, layout_id):
        return []
    version, _, _ = versions.load(out, record, layout_id)
    return list(version.locked)


# --- helpers -------------------------------------------------------------------------------------


def _tower(candidate: CandidateLayout, name: str):
    found = next((t for t in candidate.towers if t.name == name), None)
    if found is None:
        raise EditRefused(f"the layout has no block {name}; it has "
                          f"{', '.join(t.name for t in candidate.towers)}")
    return found


def _piece(candidate: CandidateLayout, piece: int) -> Polygon:
    pockets = candidate.program.open_space
    if not 1 <= piece <= len(pockets):
        raise EditRefused(f"the layout has tot-lot pieces 1 to {len(pockets)}, not {piece}")
    return pockets[piece - 1].to_shapely()


def _with_tower(candidate: CandidateLayout, tower) -> CandidateLayout:
    tower = tower.model_copy(update={"footprint": Shape.from_shapely(
        candidate.placed_footprint(tower))})
    return _edited(candidate, towers=[tower if t.name == tower.name else t
                                      for t in candidate.towers])


def _open_space_as_measured(candidate: CandidateLayout, inputs) -> CandidateLayout:
    """The edited layout's open-space figure as the validator counts it, not the generator's
    (which an edit makes stale, and the validator would report as claiming more than counts):
    what counts under the study's selected readings, else under the strictest one."""
    m = candidate.metrics
    if m is None:
        return candidate
    found = validator.validate(inputs.site, inputs.rules, inputs.brief, candidate,
                               inputs.envelope).recomputed.quantities
    counting = found.get(STUDY_COUNTING, min(
        (v for k, v in found.items() if k.startswith(COUNTING)), default=0.0))
    share = m.open_space_share_pct * counting / m.open_space_sqm if m.open_space_sqm else 0.0
    return candidate.model_copy(update={"metrics": m.model_copy(update={
        "open_space_sqm": counting, "open_space_share_pct": share})})


def _edited(candidate: CandidateLayout, **update) -> CandidateLayout:
    caveats = [c for c in candidate.caveats if c != EDITED_CAVEAT]
    return candidate.model_copy(update={**update, "partition": None, "rule_layers": None,
                                        "generator_claims": [], "scores": {},
                                        "pareto_tag": None, "caveats": [*caveats, EDITED_CAVEAT]})


def _rigid_fit(placed: Polygon, outline: Polygon) -> tuple[float, tuple[float, float]] | None:
    """The turn (degrees anticlockwise about the footprint's middle) and the move that take the
    footprint onto the outline, corner for corner within RIGID_TOL_M; None when none does."""
    a = np.array(placed.exterior.coords[:-1])
    b = np.array(outline.exterior.coords[:-1])
    if len(a) != len(b):
        return None
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    best = None
    for order in (b, b[::-1]):
        for shift in range(len(order)):
            target = np.roll(order, shift, axis=0)
            h = (a - ca).T @ (target - cb)
            u, _, vt = np.linalg.svd(h)
            r = vt.T @ u.T
            if np.linalg.det(r) < 0:  # a mirror image is not a block moved
                continue
            error = np.abs((a - ca) @ r.T + cb - target).max()
            if best is None or error < best[0]:
                best = (error, math.degrees(math.atan2(r[1, 0], r[0, 0])))
    if best is None or best[0] > RIGID_TOL_M:
        return None
    degrees = best[1]
    turned = affinity.rotate(placed, degrees, origin=placed.centroid)
    return degrees, (outline.centroid.x - turned.centroid.x, outline.centroid.y - turned.centroid.y)
