"""The full search round a locked block lays only what the validator counts (2026-10-18). On
Dhulapally, with T1 locked at Stilt + 10, eight of the fifteen layouts the search judged were
refused for too little countable tot-lot, and five for a road under a block:

- the generator sized its setback zone from the configuration's own blocks (Stilt + 8 or 9) when
  the validator's is as deep as the deepest setback any block standing needs, the locked one's,
  so the open space laid in the difference did not count;
- a street between two columns ran on through the locked block.

Both are fixed in the generator; the validator is unchanged. Made-up land: the search's 200 x 120 m
rectangle (`search_support.rectangle`), where Stilt + 10 keeps a 10 m setback zone and Stilt + 8
an 8 m one under the reading that leaves the stilt out of the height."""

from functools import cache

from search_support import rectangle, strategy
from shapely import affinity

from siteplan import validator as independent
from siteplan.contracts.candidate import PlacedTower
from siteplan.contracts.common import Shape
from siteplan.contracts.validation import LegalVerdict
from siteplan.optimizer.guard import STUDY_NOT_LAID, held_to
from siteplan.optimizer.interfaces import Budget, SearchContext
from siteplan.optimizer.search import Limits
from siteplan.optimizer.search.land import erode
from siteplan.optimizer.search.layout import (
    Config,
    Failure,
    Frame,
    evaluate,
    locked_standing,
    make_run,
    placement_of,
)
from siteplan.optimizer.search.readings import profiles

TEST_CLASS = "normative"

LARGE = "two-core-large-12"  # the made-up kit's two-core block, 24.13 m deep
OVERLAP_SQM = 0.5  # more than a sliver: a road over a block, not a touch
# A little wider than the quick limits, so layouts with blocks lower than the lock are judged
WIDER = Limits(offsets=3, heights=3, laid_per_profile=8, attempts_per_profile=40,
               judged_per_profile=6, per_profile_proposed=4)


def _locked(prototype_id: str, floors: int, x: float, y: float) -> PlacedTower:
    prototype = next(p for p in rectangle().kit if p.id == prototype_id)
    footprint = affinity.translate(prototype.footprint.to_shapely(), x, y)
    return PlacedTower(name="T1", prototype_id=prototype_id, x=x, y=y, floors_above_stilt=floors,
                       footprint=Shape.from_shapely(footprint))


def _run(tower: PlacedTower):
    made = rectangle()
    found = profiles(made.rules, made.brief, list(made.kit))
    return made, found, make_run(made.site, made.rules, made.brief, made.envelope, made.kit,
                                 found, locked=[tower])


def _configs(profile, floors):
    """Both directions, four column starts, one cluster or more."""
    return [Config(profile, angle, offset, most, more_clusters=more)
            for angle in (0.0, 90.0) for offset in (0.0, 4.0, 8.0, 12.0) for most in floors
            for more in (False, True)]


def test_the_setback_zone_is_as_deep_as_the_locked_block_needs():
    """T1 locked at Stilt + 10 (a 10 m zone), the rest at most Stilt + 8 (8 m): the land the
    configuration lays its open space on starts 10 m in, where the validator's count starts. The
    old generator started it 8 m in."""
    made, found, run = _run(_locked(LARGE, 10, 52.02, 62.35))
    profile = next(p for p in found if p.key == "not_counted-allowed")
    locked, _ = locked_standing(run, profile)
    assert locked[0].choice.cls.zone_m == 10.0
    assert max(c.zone_m for c in run.classes[profile.key][LARGE] if c.floors <= 8) == 8.0
    laid = 0
    for config in _configs(profile, (8, 9)):
        ev = evaluate(run, config)
        if isinstance(ev, Failure):
            continue
        laid += 1
        beyond = ev.land.interior.difference(erode(run.plot.net, 10.0))
        assert beyond.area < 0.01, (config.key, f"{beyond.area:.1f} m² inside the 10 m zone")
    assert laid, "some configuration lays a layout round the lock"


def test_no_street_or_link_runs_through_a_locked_block():
    """A Stilt + 8 block locked between where two columns stand: the old generator drew street-1
    across 328 m² of it at 4 m offset; now every configuration either keeps its roads off the
    block or is not offered, with that reason."""
    made, found, run = _run(_locked(LARGE, 8, 139.02, 56.785))
    profile = next(p for p in found if p.key == "ALL-ALL")
    locked, _ = locked_standing(run, profile)
    feet = placement_of(locked[0], "T1", Frame(0.0)).footprint
    reasons, laid = [], 0
    for config in _configs(profile, (8, 9)):
        ev = evaluate(run, config)
        if isinstance(ev, Failure):
            reasons.append(ev.reason)
            continue
        laid += 1
        for road in [*ev.streets, *ev.links]:
            assert road.ground.intersection(feet).area <= OVERLAP_SQM, (config.key, road.id)
    assert laid, "some configuration still lays a layout round the lock"
    assert "street-1 would run through a locked block" in reasons


@cache
def _judged_round_a_taller_lock():
    """The quick search round T1 locked at Stilt + 10, every report the validator made."""
    made = rectangle()
    seen = []

    class Spy:
        @staticmethod
        def validate(site, rules, brief, candidate, envelope=None):
            report = independent.validate(site, rules, brief, candidate, envelope)
            seen.append((candidate, report))
            return report

    context = SearchContext(made.site, made.rules, made.brief, made.envelope, made.kit, 0,
                            Budget(), (_locked(LARGE, 10, 52.02, 62.35),))
    strategy(WIDER, validator=Spy()).propose(context)
    return made, seen


def test_the_search_round_a_taller_lock_lays_only_tot_lot_the_validator_counts():
    made, seen = _judged_round_a_taller_lock()
    assert any(t.floors_above_stilt < 10 for c, _ in seen for t in c.towers if t.name != "T1")
    for candidate, report in seen:
        tot_lot = next(c for c in report.legal if c.finding.rule == STUDY_NOT_LAID)
        assert (tot_lot.selected_status or tot_lot.finding.status).value != "FAIL", (
            candidate.candidate_id, tot_lot.finding.measured)
        assert held_to(report, made.brief.objectives.study) is not LegalVerdict.FAIL, (
            candidate.candidate_id)
