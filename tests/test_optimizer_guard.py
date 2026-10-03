"""The hard-constraint guard and the interim validator (C1): a candidate whose legal verdict is
FAIL is never returned, whatever its score; the interim validator says what it is and never
claims a PASS. Made-up land and candidates only."""

import random

import pytest
from optimizer_support import (
    Fixed,
    Scripted,
    candidate,
    fixture,
    module_prototype,
    refs_of,
    rules_with_dead_end,
    tower,
)

from siteplan.contracts import digest
from siteplan.contracts.common import Finding, Status
from siteplan.contracts.design_brief import Objectives
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT
from siteplan.contracts.validation import (
    Check,
    Discrepancy,
    Family,
    LegalVerdict,
    ProgramVerdict,
    ValidationReport,
    Verdict,
)
from siteplan.optimizer import InterimValidator, optimize
from siteplan.optimizer.guard import guard, inputs_of, why_refused
from siteplan.optimizer.interim import STANDING, VERSION, family_of
from siteplan.optimizer.objective import measure
from siteplan.optimizer.pareto import Scored, select

TEST_CLASS = "normative"

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


# --- the interim validator ---------------------------------------------------------------------


def _report(cand, site=SITE, rules=RULES, brief=BRIEF):
    return InterimValidator().validate(site, rules, brief, cand)


def test_the_interim_validator_says_what_it_is_and_never_claims_a_pass():
    report = _report(_slab("a"))
    assert report.validator_version == VERSION and "INTERIM" in VERSION
    assert "not an independent validation" in VERSION
    assert report.verdict.legal is LegalVerdict.UNVERIFIED  # not PASS: nobody independent looked
    assert STANDING in report.legal
    assert any("Independent validation" in reason for reason in report.verdict.reasons)
    assert report.candidate_ref == digest(_slab("a"))
    assert (report.site_ref, report.rules_ref, report.brief_ref) == REFS
    assert report.envelope_ref is None  # it cross-checks nothing against an envelope


def test_the_interim_validator_restates_the_generators_findings_by_family():
    claims = [Finding("Cellar setback", Status.PASS, "3 m", "3 m", "13(c)(x)"),
              Finding("Fire access: dead-end road", Status.PASS, "27 m", "30 m", "NBC 4.6(b)"),
              Finding("Gap between blocks: T1 / T2", Status.PASS, "9 m", "9 m", "7(a)(xii)"),
              Finding("INTERNAL_EGRESS", Status.NOT_CHECKED, "72 m", "-", "NBC")]
    report = _report(_slab("a", claims=claims))
    families = {c.finding.rule: c.family for c in report.legal}
    assert families["Cellar setback"] is Family.PARKING  # not the setback of the towers
    assert families["Fire access: dead-end road"] is Family.DEAD_END
    assert families["Gap between blocks: T1 / T2"] is Family.SPACING
    assert families["INTERNAL_EGRESS"] is Family.EGRESS
    assert "INTERNAL_EGRESS" in report.not_checked
    assert family_of("Something nobody has met") is Family.OTHER


def test_a_generator_fail_is_a_fail():
    report = _report(_slab("a", claims=[SETBACK_FAIL]))
    assert report.verdict.legal is LegalVerdict.FAIL
    assert "All-round setback: T1: FAIL" in report.verdict.reasons


def test_a_candidate_made_for_another_brief_is_a_fail():
    stale = candidate("stale", [tower("T1", P2, 40, 20, 8)], [P2],
                      refs=(REFS[0], REFS[1], "an earlier brief"))
    check = next(c for c in _report(stale).legal if c.family is Family.CONSISTENCY)
    assert check.finding.status is Status.FAIL and "brief" in check.finding.measured
    assert _report(stale).verdict.legal is LegalVerdict.FAIL
    fresh = next(c for c in _report(_slab("a")).legal if c.family is Family.CONSISTENCY)
    assert fresh.finding.status is Status.PASS


def _height_check(cand, site=SITE, rules=RULES):
    report = _report(cand, site, rules)
    return next(c for c in report.legal if c.family is Family.HEIGHT and c.subject == "T1")


def _one_tower(floors):
    return _made("h", [tower("T1", P2, 40, 20, floors)], [P2])


def test_a_tower_within_the_limits_passes_under_every_reading():
    check = _height_check(_one_tower(9))  # 30 m both ways, the road runs on
    assert check.finding.status is Status.PASS
    assert check.by_reading[STILT_IN_RULE_HEIGHT] == {"counted": Status.PASS,
                                                      "not_counted": Status.PASS}


def test_a_tower_above_the_limit_fails_with_no_claim_from_the_generator_at_all():
    check = _height_check(_one_tower(11))  # 33 m rule height either way: over the road's 30 m
    assert check.finding.status is Status.FAIL
    assert check.by_reading[STILT_IN_RULE_HEIGHT] == {"counted": Status.FAIL,
                                                      "not_counted": Status.FAIL}
    assert _report(_one_tower(11)).verdict.legal is LegalVerdict.FAIL


def test_a_height_that_holds_under_only_one_reading_is_unverified_naming_it():
    check = _height_check(_one_tower(10))  # 30 m if the stilt is not counted, 33 m if it is
    assert check.by_reading[STILT_IN_RULE_HEIGHT] == {"counted": Status.FAIL,
                                                      "not_counted": Status.PASS}
    assert check.finding.status is Status.UNVERIFIED
    assert "counted:" in check.finding.note  # the reading it fails under is named
    assert _report(_one_tower(10)).verdict.legal is LegalVerdict.UNVERIFIED


def test_the_dead_end_fact_decides_the_33_m_tower():
    """10 floors with the stilt not counted is 30 m of rule height but 33 m physical, so only
    the dead end decides it; counted, it fails the road's 30 m outright."""
    for ends_at_plot, expected in ((True, Status.FAIL), (None, Status.UNVERIFIED),
                                   (False, Status.PASS)):
        site, rules = rules_with_dead_end(ends_at_plot)
        made = candidate("h", [tower("T1", P2, 40, 20, 10)], [P2],
                         refs=refs_of(site, rules, BRIEF))
        check = _height_check(made, site, rules)
        assert check.by_reading[STILT_IN_RULE_HEIGHT]["not_counted"] is expected
        assert check.by_reading[STILT_IN_RULE_HEIGHT]["counted"] is Status.FAIL


def test_the_programs_mix_is_judged_apart_from_the_law():
    report = _report(_slab("a"))  # 50/50 blocks against a 70/30 brief
    (mix,) = report.program
    assert mix.finding.status is Status.FAIL and mix.family is Family.PROGRAM
    assert report.verdict.program is ProgramVerdict.NOT_MET
    assert report.verdict.legal is LegalVerdict.UNVERIFIED  # never changed by the mix


def test_an_unevaluable_limit_is_listed_not_passed():
    report = _report(_slab("a"))
    assert any("airport" in item.lower() for item in report.not_checked)
