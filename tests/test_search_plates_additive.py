"""Floor plates are searched beside the firm's families, never in their place (2026-10-13, the
regulatory audit's phase 6). The families' search runs exactly as it does without plates, on its
own quotas; the plates have a bounded pass of their own whose every layout uses a plate; what
both judged is ranked together, so a plate is proposed where its layout is better and only there.

The expectations here are a families-only run of the same search, made independently: whatever
it judges must still be judged, unchanged, once plates are added. Made-up land and the made-up
flat library of test_plates.py only."""

from dataclasses import dataclass, field
from functools import cache

from search_support import FAST, Made, made_up, strategy
from shapely.geometry import box
from test_plates import LIBRARY, LOADING_PCT, MIX

from siteplan import validator as independent
from siteplan.contracts import digest
from siteplan.optimizer.interfaces import Budget
from siteplan.optimizer.search import FullSearchStrategy
from siteplan.optimizer.search.strategy import Judged, Tally
from siteplan.prototypes import compose_library
from siteplan.prototypes.plates import PLATE_SOURCE, kit_for

TEST_CLASS = "normative"

# 200 x 60 m with its road along the south side: a plate lays more flats here than the families
# (found by running both kits; the expectation below compares the two runs, not a pinned figure).
LAND = box(0, 0, 200, 60)


@dataclass
class Spy:
    """The independent validator, recording every candidate it is asked to judge."""

    judged: dict[str, object] = field(default_factory=dict)

    def validate(self, site, rules, brief, candidate, envelope):
        self.judged[digest(candidate)] = candidate
        return independent.validate(site, rules, brief, candidate, envelope)


@cache
def _kits():
    base = made_up(LAND)
    _, plates = kit_for(LIBRARY, MIX, base.envelope, loading_pct=LOADING_PCT)
    return base, tuple(compose_library(LIBRARY, MIX)), tuple(p.prototype for p in plates)


@cache
def _run(with_plates: bool):
    base, families, plates = _kits()
    kit = (*families, *plates) if with_plates else families
    spy = Spy()
    made = Made(base.site, base.rules, base.brief, base.envelope, kit)
    return strategy(FAST, validator=spy).propose(made.context()), spy.judged


def _uses_a_plate(candidate) -> bool:
    plates = {p.id for p in candidate.prototypes_used if p.source.startswith(PLATE_SOURCE)}
    return bool(plates & {t.prototype_id for t in candidate.towers})


def test_the_plates_are_a_shortlist_on_this_land():
    assert _kits()[2], "the made-up land must take plates for these tests to say anything"


def test_adding_plates_takes_no_family_layout_out_of_the_search():
    _, alone = _run(False)
    _, together = _run(True)
    assert alone
    missing = set(alone) - set(together)
    assert not missing, [alone[d].candidate_id for d in missing]


def test_every_layout_the_plates_add_is_the_plates_pass_and_some_use_a_plate():
    """The plates' pass lays out only configurations with a plate; a repair or a raise of one
    may give the plate up and is kept all the same, so not every layout it adds keeps one."""
    _, alone = _run(False)
    _, together = _run(True)
    added = [c for d, c in together.items() if d not in alone]
    assert added and any(_uses_a_plate(c) for c in added)
    assert all(c.candidate_id.startswith("full-plates-") for c in added)


def _judged(candidate, new_id: str | None = None) -> Judged:
    if new_id:
        candidate = candidate.model_copy(update={"candidate_id": new_id})
    return Judged(candidate, None, None, None, None)


def test_the_plates_pass_keeps_a_layout_only_it_found_and_drops_a_copy_of_a_familys(
        monkeypatch):
    """Whatever the plates' pass judged is kept unless the families' search judged the same
    blocks: a layout without a plate that only this pass reached is never lost (the old filter
    dropped it), and the families' own is not offered twice."""
    base, families, plates = _kits()
    _, alone = _run(False)
    first, second = list(alone.values())[:2]
    found_by_plates = [_judged(first, "full-plates-copy"), _judged(second, "full-plates-only")]
    monkeypatch.setattr(FullSearchStrategy, "_pass",
                        lambda self, *a, **k: (object(), found_by_plates, Tally()))
    made = Made(base.site, base.rules, base.brief, base.envelope, (*families, *plates))
    plating = strategy(FAST)._plate_pass(made.context(), families, plates, base.envelope, False,
                                         [_judged(first)])
    assert [j.candidate.candidate_id for j in plating.found] == ["full-plates-only"]


def test_a_plate_is_proposed_where_its_layout_is_genuinely_better():
    _, alone = _run(False)
    proposal, _ = _run(True)
    best_family = max(c.metrics.saleable_sqft for c in alone.values())
    best = max(proposal.candidates, key=lambda c: c.metrics.saleable_sqft)
    assert _uses_a_plate(best)
    assert best.metrics.saleable_sqft > best_family


def test_a_family_layout_proposed_without_plates_is_kept_unless_a_better_one_is_found():
    """Ranking is the only way a family layout leaves the proposal: one proposed alone is either
    still proposed, or something at least as saleable is."""
    alone, _ = _run(False)
    together, _ = _run(True)
    kept = {digest(c) for c in together.candidates}
    top = max(c.metrics.saleable_sqft for c in together.candidates)
    for c in alone.candidates:
        assert digest(c) in kept or top >= c.metrics.saleable_sqft, c.candidate_id


def test_the_notes_say_what_the_plates_pass_did():
    proposal, _ = _run(True)
    [said] = [n for n in proposal.notes if n.startswith("floor plates:")]
    assert "50% of each quota" in said and "judged" in said


def test_without_plates_the_search_says_nothing_of_them():
    proposal, _ = _run(False)
    assert not any(n.startswith("floor plates:") for n in proposal.notes)


def test_the_plates_pass_is_bounded():
    """At most its share of each profile's judging quota is judged in the plates' pass."""
    _, alone = _run(False)
    _, together = _run(True)
    added = [c for d, c in together.items() if d not in alone]
    profiles = {tuple(sorted(c.interpretation_basis.items())) for c in added}
    assert len(added) <= len(profiles) * FAST.for_plates().judged_per_profile


def test_a_spent_budget_leaves_the_plates_unsearched_and_says_so():
    base, families, plates = _kits()
    made = Made(base.site, base.rules, base.brief, base.envelope, (*families, *plates))
    ticks = iter(range(0, 10**9))
    budget = Budget(0.0, clock=lambda: float(next(ticks)))
    proposal = strategy(FAST).propose(made.context(budget=budget))
    assert any(n.startswith("floor plates: not searched") for n in proposal.notes)
    assert proposal.budget_exhausted
    assert not any(_uses_a_plate(c) for c in proposal.candidates)
