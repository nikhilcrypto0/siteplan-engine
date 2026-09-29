import inspect
import re
from pathlib import Path

import pytest

import siteplan
from siteplan import rules
from siteplan.cli import main
from siteplan.inventory import INVENTORY, Reading, Where, render_markdown, render_text

SRC = Path(siteplan.__file__).parent
SOURCES = {
    Where.CHECKER: (SRC / "checks.py").read_text(),
    Where.LAYOUT: "".join(
        (SRC / name).read_text() for name in ("layout.py", "amenities.py", "parking.py")
    ),
    Where.LOOKUP: inspect.getsource(rules.height_rules),
    Where.FLOORS: (SRC / "max_floors.py").read_text(),
}


def _mentions(source: str, name: str) -> bool:
    return re.search(rf"\b{name}\b", source) is not None


def test_every_clause_in_rules_is_inventoried():
    clauses = {name for name in vars(rules) if name.endswith("_CLAUSE")}
    covered = {name for entry in INVENTORY for name in entry.uses}
    assert clauses - covered == set()


def test_every_name_an_entry_reports_on_exists():
    missing = [(e.rule, n) for e in INVENTORY for n in e.uses if not hasattr(rules, n)]
    assert missing == []


@pytest.mark.parametrize("entry", [e for e in INVENTORY if e.uses and e.applied_in],
                         ids=lambda e: e.rule[:40])
def test_an_entry_is_applied_where_it_says(entry):
    for where in entry.applied_in:
        assert any(_mentions(SOURCES[where], name) for name in entry.uses), where


@pytest.mark.parametrize("entry", [e for e in INVENTORY if e.uses and not e.applied_in],
                         ids=lambda e: e.rule[:40])
def test_a_rule_marked_not_applied_is_used_nowhere(entry):
    others = [p.read_text() for p in SRC.glob("*.py") if p.name not in ("rules.py", "inventory.py")]
    for name in entry.uses:
        assert not any(_mentions(text, name) for text in others), name
        assert len(re.findall(rf"\b{name}\b", (SRC / "rules.py").read_text())) == 1, name


def test_only_what_is_not_modelled_is_applied_nowhere():
    for entry in INVENTORY:
        assert (entry.reading is Reading.NOT_MODELLED) == (not entry.applied_in), entry.rule


def test_every_reading_that_is_not_the_text_says_what_we_chose_and_what_settles_it():
    for entry in INVENTORY:
        if entry.reading is not Reading.AS_WRITTEN:
            assert entry.choice, entry.rule
        if entry.reading in (Reading.INTERPRETED, Reading.ASSUMED):
            assert entry.settles, entry.rule


def test_the_setback_line_is_built_from_every_row_of_table_iv():
    entry = next(e for e in INVENTORY if e.rule.startswith("Open space to be left"))
    assert entry.value.count(" m up to ") == len(rules.TABLE_IV) - 1
    assert entry.value.endswith(f"{rules.TABLE_IV[-1].min_open_space_m:g} m above 120 m")


def test_the_stilt_is_flagged_as_our_reading_not_the_text():
    stilt = next(e for e in INVENTORY if "stilt floor counts" in e.rule)
    assert stilt.reading is Reading.INTERPRETED


def test_both_renderings_carry_every_rule_and_the_tally():
    text, table = render_text(), render_markdown()
    tally = f"{len(INVENTORY)} rules: "
    assert tally in text and tally in table
    rows = [line for line in table.splitlines() if line.startswith("| ")]
    assert len(rows) == len(INVENTORY) + 1  # the header row plus one per rule


def test_the_command_prints_the_inventory(capsys):
    assert main(["inventory"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("HEIGHT") and "not modelled" in out
