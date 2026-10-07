"""What the service's full search proposes on made-up land, which three it shows, what the
architect is asked and what the model is answered: pinned on main (0e2ffa2) before a run kept
every proposal, so that keeping them is shown to change none of it; re-pinned on contracts 1.3
(2026-10-06), where the search keeps its cellar out from under blocks below 21 m, so the same
twelve are proposed and the model is answered as on main; only the digests move
(docs/behaviour-changes.md). Re-pinned on C4-01a, where the generator's ledger takes its claims one
union at a time: the same twelve, the same three and the same answer; only the digests move.
Re-pinned on C4-01, where every road is drawn from its centre line: the same ground to 0.01 m², but
where two open-space pockets are the same size or two layouts score the same, the last digits
still choose, so `full-not_counted-ALL-61` is proposed for `-62` (the same blocks, flats and
saleable area) and `full-ALL-ALL-6` is shown for `-5` (the same blocks, flats, saleable area and
open space). Re-pinned on C4-02, where every configuration is also tried with further clusters:
768 evaluated where 384 were, and the same twelve proposed, the same three shown. Re-pinned on
C4-05, where the fringe tries each kind of block in turn and the plot's own directions: four
proposals of the lower profiles are others, none smaller (one 224-flat layout is now 232 flats),
and the open-space option shown is `full-not_counted-ALL-63` (4 x S+9, 252 flats), not
`full-ALL-ALL-6` (4 x S+8, 224 flats). Only 1 of the 12 holds under every reading where 3 did: the
3 x S+7 layout that does is still judged, the same, but an S+8, S+8, S+5 layout of the same flats
and saleable area is proposed in its place; the selector has no robustness objective yet (C4-09).
Re-pinned on C4-06, where the layouts built for every reading take no block below 21 m that NBC's
own 15 m line holds to its fire access: 3 of the 12 hold under every reading again (3 x S+7, an
S+8, S+8, S+3 of 309,320 sft and 4 x S+8), and the open-space option shown is the 4 x S+8 one,
which holds under every reading, as on C4-04. Re-pinned on C4-07, where the club house stands on
its own band's ground and the layouts laid out are repaired: 116 laid out where 112 were (four of
the repair's), 10 proposed, 3 of them holding under every reading; the club house leaves room for
more configurations to lay out, which fill each profile's quota before some laid on C4-06 are
reached, and the judge's six of each profile by yield take more layouts of equal value (four of
3 x S+9). The balanced option shown is the repair's S+9, S+9, S+5, S+5, S+5 (371,440 sft) where
it was 4 x S+10 (440,800, laid out but no longer among the six judged), and the open-space one
4 x S+9 (335,880), which rests on a reading, where it was the 4 x S+8 that holds under every
reading (the selector weighs no robustness yet, C4-09). Re-pinned on C4-08, where a facility the
brief prefers is a preference, not a failure of the program: the same proposals and the same three
shown; only the program verdicts in the model's answer move. Re-pinned on C4-09, where each
profile's judged six are its front and different ideas before copies, and a fourth alternative is
shown, ROBUST, the layout resting on the fewest open readings: 15 proposed where 10 were; shown
the 4 x S+10 balanced one again (440,800 sft), and for the open space the S+8 x 4 + S+3 and for
ROBUST the 3 x S+7, both holding under every reading (ROBUST ranks by the readings and the
yield, not the front of the other axes, which the 3 x S+7 does not reach).

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
        "FULL: 768 configurations evaluated, 116 laid out, 24 judged by the validator, 15 proposed",
        "FULL: 3 of 15 proposed hold under every reading of the open questions; the others each "
        "name the readings they rest on",
        "FULL: every layout leaves the height above sea level and the 45 t loading of the paving "
        "UNVERIFIED",
    ],
    "proposed": [
        "full-not_counted-allowed-86",
        "full-ALL-allowed-29",
        "full-ALL-allowed-31",
        "full-not_counted-allowed-87",
        "full-not_counted-ALL-58",
        "full-not_counted-ALL-116",
        "full-ALL-allowed-33",
        "full-not_counted-ALL-115",
        "full-ALL-ALL-1",
        "full-not_counted-ALL-61",
        "full-not_counted-allowed-111",
        "full-not_counted-allowed-112",
        "full-ALL-ALL-7",
        "full-ALL-allowed-55",
        "full-ALL-ALL-114",
    ],
    "proposed_sha256": "6600dfffbef1b234bc3a3b151e6a32f951389799ae846aa5fff142d2f053f3f7",
    "shown": [
        ["full-not_counted-allowed-87", "BALANCED"],
        ["full-not_counted-allowed-86", "MAX_YIELD"],
        ["full-ALL-ALL-114", "CONVENTIONAL_OPEN_SPACE"],
        ["full-ALL-ALL-1", "ROBUST"],
    ],
    "shown_digests": ["f221bdd69a4af9be", "159177f104623eb7", "cfae9011d83df020",
                      "e81bd7dba6563362"],
    "answer_sha256": "6eda374e1b32925fea8be94d7cf1fcd779bddc2bcfdc6a48564825f361ee97dd",
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
