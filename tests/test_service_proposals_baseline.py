"""What the service's full search proposes on made-up land, which three it shows, what the
architect is asked and what the model is answered: pinned on main (0e2ffa2) before a run kept
every proposal, so that keeping them is shown to change none of it.

The values pin exact output on the locked dependencies (uv.lock). They move only with a normative
replacement and an entry in docs/behaviour-changes.md.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from test_service import Approver, _propose, make_workspace

from siteplan.contracts import digest
from siteplan.optimizer.search import FullSearchStrategy
from siteplan.service import Service
from siteplan.service import service as service_module

TEST_CLASS = "characterization"

PINNED = {
    "notes": [
        "FULL: 384 configurations evaluated, 112 laid out, 24 judged by the validator, "
        "12 proposed",
        "FULL: 3 of 12 proposed hold under every reading of the open questions; the others each "
        "name the readings they rest on",
        "FULL: every layout leaves the height above sea level and the 45 t loading of the paving "
        "UNVERIFIED"],
    "proposed": [
        "full-not_counted-allowed-85", "full-ALL-allowed-29", "full-not_counted-allowed-89",
        "full-not_counted-allowed-87", "full-ALL-allowed-33", "full-not_counted-ALL-57",
        "full-ALL-allowed-31", "full-not_counted-ALL-62", "full-ALL-ALL-1",
        "full-not_counted-ALL-59", "full-ALL-ALL-5", "full-ALL-ALL-6"],
    "proposed_sha256": "801476b84ec192df374318599ba79b12c7b2fe3e6d4b8fe63055dfabbdef3bcc",
    "shown": [["full-not_counted-allowed-87", "BALANCED"],
              ["full-not_counted-allowed-85", "MAX_YIELD"],
              ["full-ALL-ALL-5", "CONVENTIONAL_OPEN_SPACE"]],
    "shown_digests": ["f89b0195cb713a18", "85d6f0e86816fa0f", "8960cf4bc4d27c49"],
    "answer_sha256": "73c8a93310bdf108b43acd99987b14fe184fe004589b789bffbfc1f694e2aa54",
    "approval_page_sha256": "cd3ebee2af46849756df643999df9b16d2cbc91d92c45101983782cff1eb0181",
}
PROPOSALS: list = []


class Recording(FullSearchStrategy):
    """The full search unchanged; what it proposes is also kept."""

    def propose(self, context):
        proposal = super().propose(context)
        PROPOSALS.append(proposal)
        return proposal


def _sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def observe(folder) -> dict:
    """The search's proposals, the three shown, the run's digests of them, the answer the model
    gets (without the run's random id) and the approval page, for the module's made-up land."""
    ws = make_workspace(folder)
    approver = Approver()
    service = Service(ws, ws / "out", approver)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service_module, "FullSearchStrategy", Recording)
        result = _propose(service)
    proposal = PROPOSALS[-1]
    record = json.loads((ws / "out" / result.run_id / "run.json").read_text())
    return {
        "notes": result.notes,
        "proposed": [c.candidate_id for c in proposal.candidates],
        "proposed_sha256": _sha256([[c.candidate_id, digest(c)] for c in proposal.candidates]),
        "shown": [[c.candidate_id, c.pareto_point] for c in result.candidates],
        "shown_digests": [c["digest"] for c in record["candidates"]],
        "answer_sha256": _sha256(result.model_dump(mode="json", exclude={"run_id"})),
        "approval_page_sha256": _sha256(approver.asked),
    }


@pytest.fixture(scope="module")
def observed(tmp_path_factory) -> dict:
    return observe(tmp_path_factory.mktemp("baseline"))


def test_the_search_proposes_the_same_layouts_as_before(observed):
    assert observed["notes"] == PINNED["notes"]
    assert observed["proposed"] == PINNED["proposed"]
    assert observed["proposed_sha256"] == PINNED["proposed_sha256"]


def test_select_shows_the_same_three_and_the_model_gets_the_same_answer(observed):
    assert observed["shown"] == PINNED["shown"]
    assert observed["shown_digests"] == PINNED["shown_digests"]
    assert observed["answer_sha256"] == PINNED["answer_sha256"]


def test_the_architect_is_asked_the_same_approval(observed):
    assert observed["approval_page_sha256"] == PINNED["approval_page_sha256"]
