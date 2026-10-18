"""Alternatives round locked blocks (2026-10-17, Stage D of the architect's roadmap): the blocks the
architect locked in a layout stay exactly where they stand, to the millimetre and at their own
height; the full search places the rest round them and lays the roads, the club house, the tot-lot
and the parking again; up to N genuinely different alternatives (pareto.same_idea, as Stage A)
are judged by the independent validator and each saved as a version of the chosen layout
(service.versions), with what it broke beside the chosen one. A lock that leaves no room says why:
the search's own reasons, never an empty answer.

The search runs on the run's stored inputs (site, rules, brief, envelope), so every alternative is
made for exactly them; the number asked shapes only which are chosen. Its kit is every block the
firm's flat library in the site's workspace gives the stored brief, composed as the service
composed the run's own search (`service.search_kit`), with the chosen layout's blocks beside them
(2026-10-18, the architect: every block type in the firm's library, not only those the run used).
An alternative that does not keep every locked block where it stood is never offered (it cannot
arise; it is checked all the same).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from siteplan import validator
from siteplan.contracts import CandidateLayout, TowerPrototype, ValidationReport
from siteplan.intake import WORKSPACE_FILE, load_defaults
from siteplan.library import FlatLibrary
from siteplan.optimizer.core import _rests
from siteplan.optimizer.guard import guard
from siteplan.optimizer.interfaces import Budget, SearchContext
from siteplan.optimizer.objective import measure
from siteplan.optimizer.pareto import Scored, select, shortfall
from siteplan.optimizer.search import FullSearchStrategy, Limits
from siteplan.optimizer.search.layout import LOCK_EXACT_M
from siteplan.service import judge, versions
from siteplan.service.edits import EditRefused, locks
from siteplan.service.service import search_kit
from siteplan.service.store import Inputs, RunRecord

OVERLAP_SQM = 0.01  # two locked blocks sharing more ground than this overlap


@dataclass(frozen=True)
class Alternative:
    version: versions.LayoutVersion
    candidate: CandidateLayout
    report: ValidationReport


@dataclass(frozen=True)
class Around:
    parent_id: str
    locked: tuple[str, ...]
    alternatives: tuple[Alternative, ...]
    why_none: str  # when no alternative could be laid: the reasons, in the search's words
    notes: tuple[str, ...]  # what the search said of its run
    seconds: float
    short: str = ""  # when fewer than asked: how many passed, how many were copies (Stage A)


def alternatives(out: Path, workspace: Path, record: RunRecord, layout_id: str, n: int,
                 limits: Limits | None = None, seed: int = 0) -> Around:
    """Up to `n` different alternatives round the blocks locked in `layout_id`, each a version."""
    started = time.monotonic()
    parent = judge.judge_again(out, record, layout_id)
    if parent.references:
        raise EditRefused(f"{layout_id} cannot be used: " + "; ".join(parent.references))
    names = locks(out, record, layout_id)
    if not names:
        raise EditRefused(f"{layout_id} has no locked block: lock the blocks to keep first "
                          "(lock_blocks), and the search places the rest round them")
    locked = [t for t in parent.candidate.towers if t.name in names]
    inputs = parent.inputs
    why = _cannot_hold(parent.candidate, locked, inputs.site.net_plot.value.to_shapely())
    if why:
        return Around(layout_id, tuple(names), (), why, (), time.monotonic() - started)
    context = SearchContext(inputs.site, inputs.rules, inputs.brief, inputs.envelope,
                            tuple(_kit(workspace, inputs, parent.candidate)), seed,
                            Budget(inputs.brief.objectives.search_budget_s), tuple(locked))
    proposal = FullSearchStrategy(limits=(limits or Limits()).for_options(n)).propose(context)
    kept = [c for c in proposal.candidates if _keeps(c, parent.candidate, locked)]
    passed = guard(kept, validator, inputs.site, inputs.rules, inputs.brief,
                   inputs.envelope).passed
    pool = [Scored(v.candidate, measure(v.candidate, inputs.brief), _rests(v.report))
            for v in passed]
    asked = inputs.brief.model_copy(update={"objectives": inputs.brief.objectives.model_copy(
        update={"options": n})})  # chooses only: every alternative is made for the stored brief
    selection = select(pool, asked) if pool else None
    picks = selection.picks[:n] if selection else ()
    short = (shortfall(selection, pool, asked) or "") if selection else ""
    failed = next((note for note in proposal.notes if note.startswith("the validator failed")),
                  "")
    if short and failed:
        short += f"; {failed.split(':', 1)[0]} the search judged round them"
    made = []
    for k, pick in enumerate(picks, 1):
        version, candidate, report = versions.make_version(
            out, record, layout_id, pick.scored.candidate,
            [f"laid again round the locked {', '.join(names)}: alternative {k} of {len(picks)}"],
            locked=names, before=parent.report)
        made.append(Alternative(version, candidate, report))
    why_none = "" if made else _why_none(proposal.notes, len(proposal.candidates), len(kept),
                                         len(passed))
    return Around(layout_id, tuple(names), tuple(made), why_none, tuple(proposal.notes),
                  time.monotonic() - started, short)


def _cannot_hold(candidate: CandidateLayout, locked, net) -> str:
    """Why the locked blocks cannot stand at all, before any search: off the net plot, or on
    each other."""
    feet = {t.name: candidate.placed_footprint(t) for t in locked}
    off = [n for n, f in feet.items() if f.difference(net).area > OVERLAP_SQM]
    if off:
        return f"the locked {', '.join(off)} stand{'s' if len(off) == 1 else ''} off the net plot"
    names = sorted(feet)
    on = [f"{a} and {b}" for i, a in enumerate(names) for b in names[i + 1:]
          if feet[a].intersection(feet[b]).area > OVERLAP_SQM]
    return f"the locked blocks stand on each other: {'; '.join(on)}" if on else ""


def _keeps(candidate: CandidateLayout, parent: CandidateLayout, locked) -> bool:
    """Whether every locked block stands in the candidate exactly where and as high as it does in
    the chosen layout."""
    by_name = {t.name: t for t in candidate.towers}
    for t in locked:
        got = by_name.get(t.name)
        if got is None or got.prototype_id != t.prototype_id \
                or got.floors_above_stilt != t.floors_above_stilt:
            return False
        if candidate.placed_footprint(got).hausdorff_distance(
                parent.placed_footprint(t)) > LOCK_EXACT_M:
            return False
    return True


def library_of(workspace: Path) -> FlatLibrary:
    """The firm's flat library: the file the workspace's settings name, inside the workspace."""
    root = Path(workspace).resolve()
    name = load_defaults(root).flat_library
    if not name:
        raise EditRefused(f"the workspace's {WORKSPACE_FILE} names no flat_library: the "
                          "alternatives are laid with the firm's blocks")
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise EditRefused(f"the workspace's flat library {name} is not a file in it")
    return FlatLibrary.model_validate_json(path.read_text())


def _kit(workspace: Path, inputs: Inputs, parent: CandidateLayout) -> list[TowerPrototype]:
    """Every block the firm's library gives the stored brief, composed as the run's own search
    was given them (the families for its mix and the floor plates its land takes, within the
    firm's longest block), and the chosen layout's blocks, which win on an id they share, so a
    locked block is placed as it is even when the library has changed since."""
    found = {p.id: p for p in parent.prototypes_used}
    kit, _ = search_kit(library_of(workspace), inputs.brief, inputs.envelope)
    for p in kit:
        found.setdefault(p.id, p)
    return list(found.values())


def _why_none(notes, proposed: int, kept: int, passed: int) -> str:
    said = "; ".join(notes)
    if proposed and not kept:
        return "no layout the search laid kept every locked block where it stood"
    if kept and not passed:
        return "every layout laid round the locked blocks fails the law: " + said
    return "no layout can be laid round the locked blocks: " + said
