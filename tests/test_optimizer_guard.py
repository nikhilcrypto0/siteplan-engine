"""The hard-constraint guard (C1): a candidate whose legal verdict is FAIL is never returned,
whatever its score. The verdict is stream D's independent validator's, the optimizer's default.
Made-up land and candidates only."""

import random

import pytest
from contract_fixtures import load
from optimizer_support import (
    Claims,
    Fixed,
    Scripted,
    candidate,
    fixture,
    module_prototype,
    refs_of,
    tower,
)

from siteplan import validator as independent
from siteplan.contracts import digest
from siteplan.contracts.common import Finding, Status
from siteplan.contracts.design_brief import Objectives
from siteplan.contracts.validation import (
    Check,
    Discrepancy,
    Family,
    LegalVerdict,
    ProgramVerdict,
    ValidationReport,
    Verdict,
)
from siteplan.optimizer import optimize as real_optimize
from siteplan.optimizer.guard import guard, inputs_of, why_refused
from siteplan.optimizer.objective import measure
from siteplan.optimizer.pareto import Scored, select

TEST_CLASS = "normative"


def optimize(*args, **kwargs):
    """The optimizer, judged by the made-up candidates' own claims unless a test gives a
    validator: these tests are of the guard's mechanics, not of the law (see Claims)."""
    kwargs.setdefault("validator", Claims())
    return real_optimize(*args, **kwargs)

P1, P2 = module_prototype(1), module_prototype(2)
SITE, RULES, BRIEF = fixture()  # a 60 ft road: up to 30 m; the road runs on past the plot
REFS = refs_of(SITE, RULES, BRIEF)
SETBACK_FAIL = Finding("All-round setback: T1", Status.FAIL, "6.1 m", ">= 9 m",
                       "G.O.168 rule 7(a)(x), Table IV")


def _made(candidate_id, towers, protos, *, claims=None, **kwargs):
    return candidate(candidate_id, towers, protos, claims=claims, refs=REFS, **kwargs)


def _slab(candidate_id, floors=9, open_space=300, *, claims=None):
    return _made(candidate_id, [tower("T1", P2, 40, 20, floors), tower("T2", P2, 110, 75, floors)],
                 [P2], open_space_sqm=open_space, claims=claims)


def _singles(candidate_id, count=5, floors=5, open_space=2400):
    return _made(candidate_id, [tower(f"T{i}", P1, 25 + 25 * i, 20, floors) for i in range(count)],
                 [P1], open_space_sqm=open_space)


def _mid(candidate_id):
    return _made(candidate_id, [tower("T1", P2, 40, 20, 8), tower("T2", P1, 100, 20, 8),
                                tower("T3", P1, 60, 75, 8)], [P1, P2], open_space_sqm=1200)


def _brief_with(**objectives):
    return BRIEF.model_copy(update={"objectives": Objectives(**objectives)})


# --- the guard ---------------------------------------------------------------------------------


def test_a_higher_scoring_candidate_that_fails_is_never_returned():
    planted = _slab("planted", floors=9, claims=[SETBACK_FAIL])  # the most saleable area of all
    honest = [_slab("honest-slabs", floors=8), _mid("honest-mid"), _singles("honest-singles")]
    pool = [*honest, planted]
    # It would have been the maximum-yield alternative: the test has teeth.
    unguarded = select([Scored(c, measure(c, BRIEF)) for c in pool], BRIEF)
    assert unguarded.picks[0].scored.candidate.candidate_id == "planted"

    result = optimize(SITE, RULES, BRIEF, [Fixed(pool)])
    returned = {a.candidate.candidate_id for a in result.alternatives}
    assert "planted" not in returned and "planted" not in result.front
    assert result.alternatives  # the honest ones are still offered
    assert [r.candidate_id for r in result.rejected] == ["planted"]
    assert any("All-round setback" in reason and "needs >= 9 m" in reason
               for reason in result.rejected[0].reasons)
    assert all(a.report.verdict.legal is not LegalVerdict.FAIL for a in result.alternatives)


def test_an_open_question_is_not_a_failure():
    open_question = Finding("Fire access: the street joins a 12 m street", Status.UNVERIFIED,
                            "not known", "joins a street of 12 m or more", "NBC 4.6(a)")
    result = optimize(SITE, RULES, BRIEF, [Fixed([_slab("open", claims=[open_question])])])
    (best,) = result.alternatives
    assert best.candidate.candidate_id == "open"
    assert best.report.verdict.legal is LegalVerdict.UNVERIFIED


@pytest.mark.parametrize("seed", range(25))
def test_whatever_the_pool_no_alternative_has_a_fail_verdict(seed):
    rng = random.Random(seed)
    pool, failing = [], set()
    for i in range(8):
        towers = [tower(f"T{n}", rng.choice([P1, P2]), rng.uniform(20, 130), rng.uniform(15, 85),
                        rng.randint(1, 9), rng.choice([0.0, 90.0, 33.0]))
                  for n in range(rng.randint(1, 4))]
        broken = rng.random() < 0.4
        claims = [SETBACK_FAIL] if broken else []
        if broken:
            failing.add(f"c{i}")
        pool.append(_made(f"c{i}", towers, [P1, P2], open_space_sqm=rng.uniform(0, 3000),
                          claims=claims))
    result = optimize(SITE, RULES, BRIEF, [Fixed(pool)], seed=seed)
    returned = {a.candidate.candidate_id for a in result.alternatives}
    assert not returned & failing
    assert {r.candidate_id for r in result.rejected} == failing
    assert not set(result.front) & failing
    assert all(a.report.verdict.legal is not LegalVerdict.FAIL for a in result.alternatives)


def _guarded(verdicts, candidates, validator=None):
    validator = validator or Scripted(verdicts)
    return guard(candidates, validator, SITE, RULES, BRIEF, None), validator


def test_a_fail_is_refused_and_an_open_or_passed_candidate_is_kept():
    pool = [_slab("a"), _slab("b"), _slab("c")]
    done, validator = _guarded({"a": Status.FAIL, "b": Status.UNVERIFIED, "c": Status.PASS}, pool)
    assert [v.candidate.candidate_id for v in done.passed] == ["b", "c"]
    assert [r.candidate_id for r in done.rejected] == ["a"]
    assert done.rejected[0].reasons == ("Scripted check: scripted (needs scripted)",)
    assert validator.calls == ["a", "b", "c"]  # every candidate is judged, none skipped


def test_a_report_about_another_candidate_does_not_clear_this_one():
    class Mixes:
        def validate(self, site, rules, brief, cand, envelope=None):
            return Scripted().validate(site, rules, brief, _slab("someone-else"))

    done, _ = _guarded({}, [_slab("a")], Mixes())
    assert not done.passed and "another candidate" in done.rejected[0].reasons[0]


def test_a_report_about_other_inputs_does_not_clear_this_one():
    class OtherBrief:
        def validate(self, site, rules, brief, cand, envelope=None):
            return Scripted().validate(site, rules, brief.model_copy(update={"brief_id": "x"}),
                                       cand)

    done, _ = _guarded({}, [_slab("a")], OtherBrief())
    assert not done.passed and "other inputs" in done.rejected[0].reasons[0]


def test_a_report_whose_verdict_does_not_follow_from_its_checks_is_refused():
    """The contract refuses to build one; a report put together some other way is not trusted."""

    failing = Check(family=Family.OTHER, finding=Finding(
        "A rule", Status.FAIL, "5 m", "9 m", "clause"))
    report = ValidationReport.model_construct(
        candidate_ref=digest(_slab("a")), site_ref=REFS[0], rules_ref=REFS[1], brief_ref=REFS[2],
        legal=[failing], cross_checks=[],
        verdict=Verdict(legal=LegalVerdict.PASS, program=ProgramVerdict.MET))
    reasons = why_refused(_slab("a"), report, inputs_of(SITE, RULES, BRIEF))
    assert any("does not follow from its checks" in r for r in reasons)
    assert any("A rule: 5 m (needs 9 m)" in r for r in reasons)  # the real verdict is FAIL


def test_a_discrepancy_that_blocks_a_pass_refuses_the_candidate():
    class Blocking:
        def validate(self, site, rules, brief, cand, envelope=None):
            ours = Discrepancy(item="tower height", source="generator", theirs="27 m",
                               ours="33 m", blocks_pass=True)
            return ValidationReport(
                candidate_ref=digest(cand), site_ref=digest(site), rules_ref=digest(rules),
                brief_ref=digest(brief), validator_version="test", cross_checks=[ours],
                verdict={"legal": LegalVerdict.FAIL, "program": ProgramVerdict.MET})

    done, _ = _guarded({}, [_slab("a")], Blocking())
    assert not done.passed
    assert "tower height: the generator says 27 m, the validator found 33 m" in (
        done.rejected[0].reasons)


# --- the optimizer's validator is stream D's -----------------------------------------------------


def test_the_guard_refuses_what_the_independent_validator_fails_with_no_claim_needed():
    """The generator's own layout of the rectangle passes the guard; the same layout with its
    towers raised to 11 floors (33 m of rule height either way, over the road's 30 m) is refused,
    though the generator's claims say nothing about it: the validator works it out."""
    drawn = load("rectangle", "CandidateLayout")
    raised = drawn.model_copy(deep=True)
    raised.candidate_id = "raised"
    for placed in raised.towers:
        placed.floors_above_stilt = 11
    done = guard([drawn, raised], independent, SITE, RULES, BRIEF, None)
    assert [v.candidate.candidate_id for v in done.passed] == [drawn.candidate_id]
    (refused,) = done.rejected
    assert refused.candidate_id == "raised"
    assert any("Rule-height limit" in reason for reason in refused.reasons)


def test_a_candidate_made_for_another_brief_is_refused():
    stale = candidate("stale", [tower("T1", P2, 40, 20, 8)], [P2],
                      refs=(REFS[0], REFS[1], "an earlier brief"))
    report = independent.validate(SITE, RULES, BRIEF, stale)
    assert report.verdict.legal is LegalVerdict.FAIL
    done = guard([stale], independent, SITE, RULES, BRIEF, None)
    assert not done.passed and done.rejected


def test_the_programs_mix_is_judged_apart_from_the_law():
    report = independent.validate(SITE, RULES, BRIEF, _slab("a"))  # 50/50 against 70/30
    assert report.verdict.program is not ProgramVerdict.MET
    assert all(c.family is not Family.PROGRAM for c in report.legal)
