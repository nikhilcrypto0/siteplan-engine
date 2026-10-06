"""A run keeps every layout its search proposed, and validate_candidate and export_candidate
reach one the run did not show only through that run's own record (siteplan.service.store and
judge).

On made-up land: the search runs once for the module and is watched (what the strategy proposed,
what the optimizer's guard judged); the tests that tamper with a run copy it first. That keeping
the proposals changes nothing the search finds, the three shown, the answer the model gets or the
approval page is pinned against main in test_service_proposals_baseline.py.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_service import Approver, _propose, make_workspace

import siteplan.optimizer.core as core
import siteplan.validator
from siteplan.contracts import CandidateLayout, DesignBrief, ValidationReport, digest
from siteplan.optimizer.objective import measure
from siteplan.optimizer.pareto import Scored, select
from siteplan.optimizer.search import FullSearchStrategy
from siteplan.optimizer.search.verdicts import rests_on
from siteplan.service import (
    Asked,
    CompareCandidates,
    Decision,
    ExportCandidate,
    ExportStatus,
    Service,
    ServiceError,
    ValidateCandidate,
    store,
)
from siteplan.service import service as service_module

TEST_CLASS = "normative"

EXPORTED = (".dxf", ".sheet.dxf", ".svg", ".report.txt", ".validation.json")


@dataclass
class Ran:
    ws: Path
    service: Service
    approver: Approver
    proposed: object  # the answer to propose_layouts
    proposals: tuple  # the candidates the search proposed, in order
    guarded: object  # what the optimizer's guard made of them


@pytest.fixture(scope="module")
def ran(tmp_path_factory) -> Ran:
    ws = make_workspace(tmp_path_factory.mktemp("proposals"))
    approver = Approver()
    service = Service(ws, ws / "out", approver)
    proposals, guarded = [], []
    real_guard = core.guard

    class Recording(FullSearchStrategy):
        def propose(self, context):
            proposal = super().propose(context)
            proposals.append(proposal)
            return proposal

    def watch_guard(*args, **kwargs):
        result = real_guard(*args, **kwargs)
        guarded.append(result)
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service_module, "FullSearchStrategy", Recording)
        patch.setattr(core, "guard", watch_guard)
        proposed = _propose(service)
    return Ran(ws, service, approver, proposed, proposals[-1].candidates, guarded[-1])


def _out(ran: Ran) -> Path:
    return ran.ws / "out"


def _record(ran: Ran) -> store.RunRecord:
    return store.read_record(_out(ran), ran.proposed.run_id)


def _hidden(ran: Ran, n: int = 0) -> store.ProposedCandidate:
    return [p for p in _record(ran).proposed_candidates if not p.shown][n]


def _validate(service: Service, run_id: str, candidate_id: str):
    return service.validate_candidate(ValidateCandidate(run_id=run_id,
                                                        candidate_id=candidate_id))


def _copy(ran: Ran, approved: bool = True) -> str:
    """A copy of the module's run under a new id, nothing exported. Approved, its record's
    approvals name the copy, as if the person had approved a run of that id, so a test can reach
    past that gate; otherwise they still name the run the copy was made from."""
    out, new = _out(ran), uuid.uuid4().hex[:12]
    shutil.copytree(out / ran.proposed.run_id, out / new)
    shutil.rmtree(out / new / "exports", ignore_errors=True)

    def rename(record: dict) -> None:
        record["run_id"] = new
        for entry in record["approvals"] if approved else ():
            entry["run_id"] = new

    _edit(out / new / "run.json", rename)
    return new


def _edit(path: Path, change) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def _proposed_file(ran: Ran, run_id: str, kind: str, candidate_id: str) -> Path:
    return _out(ran) / run_id / store.PROPOSED / kind / f"{candidate_id}.json"


# --- 1. The run keeps every proposal, and shows the same three ---------------------------------


def test_every_layout_the_search_proposed_is_kept_with_the_report_the_guard_made(ran):
    record = _record(ran)
    assert not ran.guarded.rejected and len(ran.guarded.passed) == len(ran.proposals)
    guard_reports = {v.candidate.candidate_id: v.report for v in ran.guarded.passed}
    shown = {c.candidate_id for c in record.candidates}
    assert [p.candidate_id for p in record.proposed_candidates] == [
        c.candidate_id for c in ran.proposals]
    for entry, proposal in zip(record.proposed_candidates, ran.proposals, strict=True):
        candidate = CandidateLayout.model_validate_json(_proposed_file(
            ran, ran.proposed.run_id, "candidates", entry.candidate_id).read_text())
        report = ValidationReport.model_validate_json(_proposed_file(
            ran, ran.proposed.run_id, "reports", entry.candidate_id).read_text())
        assert digest(candidate) == entry.digest == digest(proposal)
        assert digest(report) == entry.report_digest == digest(guard_reports[entry.candidate_id])
        assert report.candidate_ref == entry.digest
        assert entry.basis == candidate.interpretation_basis != {}
        assert entry.holds_under_every_reading is rests_on(report).holds_under_every_reading
        assert entry.shown is (entry.candidate_id in shown)
    assert sum(p.shown for p in record.proposed_candidates) == len(record.candidates) == 3
    assert len(record.proposed_candidates) > len(record.candidates)  # some were not shown
    held = sum(p.holds_under_every_reading for p in record.proposed_candidates)
    assert any(f"{held} of {len(ran.proposals)} proposed hold under every reading" in note
               for note in record.notes)  # what the search said of them


def test_the_three_shown_are_what_select_chooses_from_the_proposals_kept(ran):
    """Choosing again over the kept proposals gives the alternatives the run shows, each at its
    point, and the model is answered with those three and no other."""
    record = _record(ran)
    folder = _out(ran) / ran.proposed.run_id
    brief = DesignBrief.model_validate_json((folder / "brief.json").read_text())
    kept = [CandidateLayout.model_validate_json(_proposed_file(
        ran, ran.proposed.run_id, "candidates", p.candidate_id).read_text())
        for p in record.proposed_candidates]
    picks = select([Scored(c, measure(c, brief)) for c in kept], brief).picks
    chosen = {p.scored.candidate.candidate_id: p.point.value for p in picks}
    assert chosen == {c.candidate_id: c.point for c in record.candidates}
    assert {c.candidate_id: c.pareto_point for c in ran.proposed.candidates} == chosen


# --- 2. Run C reaches a proposal the run did not show ------------------------------------------


def test_validate_candidate_judges_a_proposal_the_run_did_not_show_again(ran, monkeypatch):
    hidden = _hidden(ran)
    calls = []
    real = siteplan.validator.validate

    def watch(site, rules, brief, candidate, envelope=None):
        calls.append(digest(candidate))
        return real(site, rules, brief, candidate, envelope)

    monkeypatch.setattr(siteplan.validator, "validate", watch)
    checked = _validate(ran.service, ran.proposed.run_id, hidden.candidate_id)
    stored = ValidationReport.model_validate_json(_proposed_file(
        ran, ran.proposed.run_id, "reports", hidden.candidate_id).read_text())
    assert calls == [hidden.digest]  # judged now, the stored report is not its verdict
    assert checked.candidate_id == hidden.candidate_id and checked.refusals == []
    assert checked.legal_verdict is stored.verdict.legal
    assert checked.unverified  # what an export of it would need acknowledged


def test_exporting_a_proposal_the_run_did_not_show_still_needs_the_architects_approval(ran):
    run_id, hidden = _copy(ran), _hidden(ran)
    out, exports = _out(ran), _out(ran) / run_id / "exports"
    items = [i.item for i in _validate(ran.service, run_id, hidden.candidate_id).unverified]
    assert items  # the made-up land leaves items open, so the person has to be asked

    asked = len(ran.approver.asked)
    unacknowledged = ran.service.export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=hidden.candidate_id))
    assert unacknowledged.status is ExportStatus.REFUSED
    assert len(ran.approver.asked) == asked and not exports.exists()

    refusing = Approver(answer=False)
    declined = Service(ran.ws, out, refusing).export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=hidden.candidate_id, acknowledged_unresolved=items))
    assert declined.status is ExportStatus.NOT_APPROVED and len(refusing.asked) == 1
    assert not exports.exists()

    approving = Approver()
    done = Service(ran.ws, out, approving).export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=hidden.candidate_id, acknowledged_unresolved=items))
    assert done.status is ExportStatus.EXPORTED and len(approving.asked) == 1
    title, lines = approving.asked[0]
    assert hidden.candidate_id in title
    assert all(any(line.startswith(f"UNVERIFIED {item}:") for line in lines) for item in items)
    assert sorted(Path(f).name for f in done.files) == sorted(
        f"{hidden.candidate_id}{suffix}" for suffix in EXPORTED)
    recorded = [(a.decision, a.candidate_id, list(a.acknowledged))
                for a in store.read_record(out, run_id).approvals if a.asked is Asked.EXPORT]
    assert recorded == [(Decision.REJECTED, hidden.candidate_id, items),
                        (Decision.APPROVED, hidden.candidate_id, items)]


# --- 3. Nothing else is reached ----------------------------------------------------------------


def test_a_candidate_the_run_never_proposed_is_refused_however_it_got_there(ran):
    run_id, hidden = _copy(ran), _hidden(ran)
    folder = _out(ran) / run_id
    planted = "full-planted-1"  # copied in by hand under a name of its own, beside the others
    copy = json.loads(_proposed_file(ran, run_id, "candidates", hidden.candidate_id).read_text())
    copy["candidate_id"] = planted
    for kind in ("candidates", f"{store.PROPOSED}/candidates"):
        (folder / kind / f"{planted}.json").write_text(json.dumps(copy))
    for kind in ("reports", f"{store.PROPOSED}/reports"):
        shutil.copy(_proposed_file(ran, run_id, "reports", hidden.candidate_id),
                    folder / kind / f"{planted}.json")
    asked = len(ran.approver.asked)
    for candidate_id in (planted, "full-ALL-ALL-999"):
        with pytest.raises(ServiceError, match="has no candidate"):
            _validate(ran.service, run_id, candidate_id)
        with pytest.raises(ServiceError, match="has no candidate"):
            ran.service.export_candidate(ExportCandidate(run_id=run_id,
                                                         candidate_id=candidate_id))
    assert len(ran.approver.asked) == asked and not (folder / "exports").exists()


def test_a_proposal_of_another_run_is_refused_though_its_files_are_here(ran):
    """Its files are in this run's folder; this run's record does not list it."""
    run_id, hidden = _copy(ran), _hidden(ran)
    _edit(_out(ran) / run_id / "run.json", lambda r: r.update(proposed_candidates=[
        p for p in r["proposed_candidates"] if p["candidate_id"] != hidden.candidate_id]))
    assert _proposed_file(ran, run_id, "candidates", hidden.candidate_id).is_file()
    with pytest.raises(ServiceError, match="has no candidate"):
        _validate(ran.service, run_id, hidden.candidate_id)


def test_a_candidate_is_asked_for_by_its_id_and_never_by_a_path(ran):
    hidden = _hidden(ran)
    for candidate_id in (f"../{hidden.candidate_id}", f"proposed/candidates/{hidden.candidate_id}",
                         "/tmp/replay/candidates/full-ALL-ALL-1.json"):
        with pytest.raises(ValidationError):
            ValidateCandidate(run_id=ran.proposed.run_id, candidate_id=candidate_id)


@pytest.mark.parametrize("how", ["copied under a new id", "approvals removed",
                                 "proposal rejected"])
def test_a_run_whose_record_holds_no_approved_proposal_reaches_none_of_its_proposals(ran, how):
    hidden = _hidden(ran)
    run_id = _copy(ran, approved=how != "copied under a new id")
    if how == "approvals removed":
        _edit(_out(ran) / run_id / "run.json", lambda r: r.update(approvals=[]))
    if how == "proposal rejected":
        _edit(_out(ran) / run_id / "run.json", lambda r: [
            a.update(decision=Decision.REJECTED.value) for a in r["approvals"]])
    with pytest.raises(ServiceError, match="holds no approved proposal"):
        _validate(ran.service, run_id, hidden.candidate_id)


def _shift_first_tower(candidate: dict) -> None:
    tower = candidate["towers"][0]
    tower["x"] += 1.0
    tower["footprint"]["outer"] = [[x + 1.0, y] for x, y in tower["footprint"]["outer"]]


def _into_a_pass(report: dict) -> None:
    report["legal"] = [c for c in report["legal"] if c["finding"]["status"] == "PASS"]
    report["cross_checks"] = []
    report["verdict"] = {**report["verdict"], "legal": "PASS", "reasons": []}


def _tamper(ran: Ran, run_id: str, how: str) -> None:
    hidden, other = _hidden(ran), _hidden(ran, 1)
    if how == "candidate changed":
        _edit(_proposed_file(ran, run_id, "candidates", hidden.candidate_id), _shift_first_tower)
    elif how == "report changed":
        _edit(_proposed_file(ran, run_id, "reports", hidden.candidate_id), _into_a_pass)
    elif how == "another proposal in its place":
        shutil.copy(_proposed_file(ran, run_id, "candidates", other.candidate_id),
                    _proposed_file(ran, run_id, "candidates", hidden.candidate_id))
    else:  # the digest recorded for it changed
        _edit(_out(ran) / run_id / "run.json", lambda r: [
            p.update(digest="0" * len(p["digest"])) for p in r["proposed_candidates"]
            if p["candidate_id"] == hidden.candidate_id])


@pytest.mark.parametrize(("how", "reason"), [
    ("candidate changed", "the stored candidate changed since the run was made"),
    ("report changed", "the stored report of the proposal changed since the run was made"),
    ("another proposal in its place", "the stored candidate changed since the run was made"),
    ("digest recorded changed", "the stored candidate changed since the run was made")])
def test_a_tampered_proposal_or_report_is_refused_and_never_exported(ran, how, reason):
    run_id, hidden = _copy(ran), _hidden(ran)
    _tamper(ran, run_id, how)
    checked = _validate(ran.service, run_id, hidden.candidate_id)
    assert any(r.startswith(reason) for r in checked.refusals), checked.refusals
    asked = len(ran.approver.asked)
    items = [i.item for i in checked.unverified]
    result = ran.service.export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=hidden.candidate_id, acknowledged_unresolved=items))
    assert result.status is ExportStatus.REFUSED
    assert any(r.startswith(reason) for r in result.reasons), result.reasons
    assert len(ran.approver.asked) == asked  # never put to the person
    assert not (_out(ran) / run_id / "exports").exists()


def test_an_alternative_shown_is_held_to_its_own_digest_not_the_file_it_was_swapped_with(ran):
    """A shown candidate's file replaced by another shown candidate's: the file is intact, but
    it is not the candidate recorded under the id asked for."""
    run_id = _copy(ran)
    first, second = (c.candidate_id for c in _record(ran).candidates[:2])
    folder = _out(ran) / run_id / "candidates"
    shutil.copy(folder / f"{second}.json", folder / f"{first}.json")
    checked = _validate(ran.service, run_id, first)
    assert any(r.startswith("the stored candidate changed since the run was made")
               for r in checked.refusals), checked.refusals


# --- 4. A run made before the proposals were kept ----------------------------------------------


def test_a_run_kept_before_the_proposals_were_behaves_as_it_did(ran):
    run_id, hidden = _copy(ran), _hidden(ran)
    folder = _out(ran) / run_id
    _edit(folder / "run.json", lambda r: r.pop("proposed_candidates"))
    shutil.rmtree(folder / store.PROPOSED)
    shown = _record(ran).candidates[0].candidate_id
    before = _validate(ran.service, ran.proposed.run_id, shown)
    after = _validate(ran.service, run_id, shown)
    assert after.refusals == [] and after.legal_verdict is before.legal_verdict
    items = [i.item for i in after.unverified]
    assert items == [i.item for i in before.unverified]
    assert ran.service.compare_candidates(CompareCandidates(
        run_id=run_id, candidate_ids=[shown])).rows[0].candidate_id == shown
    exported = ran.service.export_candidate(ExportCandidate(
        run_id=run_id, candidate_id=shown, acknowledged_unresolved=items))
    assert exported.status is ExportStatus.EXPORTED
    with pytest.raises(ServiceError, match="has no candidate"):
        _validate(ran.service, run_id, hidden.candidate_id)


# --- 5. A request that repeats an approved run --------------------------------------------------


def test_a_request_that_repeats_an_approved_run_says_so_before_it_is_approved(tmp_path):
    """D1 (KNOWN_QWEN_DEFECTS.md): a model searched again "to get a clean run id", the person
    approved a second, identical page, and the second run was reported as if it were the only
    one. A request on exactly the inputs of an approved run now says so on its page, before it is
    approved, and in its notes; a rejected request was never a run and is not named."""
    ws = make_workspace(tmp_path)
    rejected = _propose(Service(ws, ws / "out", Approver(answer=False)))
    approver = Approver()
    service = Service(ws, ws / "out", approver)
    first, second = _propose(service), _propose(service)
    assert rejected.run_id is None and first.run_id and second.run_id != first.run_id
    (_, first_lines), (_, second_lines) = approver.asked
    said = [line for line in second_lines if line.startswith("The same request as run")]
    assert [line for line in first_lines if line.startswith("The same request")] == []
    assert len(said) == 1 and re.fullmatch(
        rf"The same request as run {first.run_id}, approved \d{{4}}-\d\d-\d\d \d\d:\d\d UTC: "
        "approving this searches the same inputs again", said[0]), said
    assert said[0] in second.notes and not any(n.startswith("The same request")
                                               for n in first.notes)
