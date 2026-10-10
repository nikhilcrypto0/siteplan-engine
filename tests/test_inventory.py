import ast
import inspect
import re
from pathlib import Path

import pytest

import siteplan
from siteplan import rules
from siteplan.cli import main
from siteplan.inventory import INVENTORY, Reading, Where, render_markdown, render_text

SRC = Path(siteplan.__file__).parent


def _modules(root: Path) -> list[str]:
    """Every module under a folder, in every package however deep, as 'legal/resolve'."""
    return sorted(p.relative_to(root).with_suffix("").as_posix() for p in root.rglob("*.py"))


MODULES = _modules(SRC)
# Modules the scan for rules marked not applied leaves out, each with the reason. Every other
# module is scanned, so one added later, in any package, is covered without being named.
EXEMPT = {
    "rules": "defines every value and clause the inventory reports on",
    "inventory": "the inventory itself: it reads every value from rules.py to list it",
    "constraints": "the number audit: it reads every rule value to classify it",
}
SCANNED = [m for m in MODULES if m not in EXEMPT]
TEXT = {m: (SRC / f"{m}.py").read_text() for m in MODULES}
WHERE = {  # the modules each place in the inventory is
    Where.CHECKER: ("checks", "access_checks", "parking_checks"),
    # runner.py builds the land the layout keeps off (water buffers)
    Where.LAYOUT: ("layout", "towers", "grounds", "access", "parking", "heights", "runner"),
    Where.FLOORS: ("max_floors",),
    Where.RESOLVER: tuple(m for m in MODULES if m.startswith("legal/")),
    Where.STEPS: tuple(m for m in MODULES if m.startswith("steps/")),
}
SOURCES = {where: "".join(TEXT[m] for m in modules) for where, modules in WHERE.items()}
SOURCES[Where.LOOKUP] = inspect.getsource(rules.height_rules)


def _bound(node: ast.stmt) -> list[str]:
    targets = (node.targets if isinstance(node, ast.Assign)
               else [node.target] if isinstance(node, ast.AnnAssign) else [])
    return [n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)]


# What rules.py binds that is no rule, with the reason: no inventory entry is asked of it.
NOT_A_RULE = {"RULES_SOURCE": "the name of the base text the values were read from"}
# The values and clauses rules.py binds itself, not the names it imports.
RULE_NAMES = sorted({name for node in ast.parse(TEXT["rules"]).body for name in _bound(node)
                     if name.isupper()} - set(NOT_A_RULE))


def _mentions(source: str, name: str) -> bool:
    return re.search(rf"\b{name}\b", source) is not None


def _package(module: str) -> str:
    """The package a module's relative imports start from: 'legal/resolve' is siteplan.legal."""
    return ".".join(["siteplan", *module.split("/")[:-1]])


def _imports_rules(source: str, package: str) -> bool:
    """Whether a module imports rules.py, however it does it: an alias, a relative import, a
    name taken from it, inside a function."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(a.name == "siteplan.rules" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*parent, base]) if base else ".".join(parent)
            if base == "siteplan.rules" or (base == "siteplan"
                                            and any(a.name == "rules" for a in node.names)):
                return True
    return False


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
def test_a_rule_marked_not_applied_is_used_nowhere_but_where_it_is_carried(entry):
    """Every module but the exempt ones is scanned, in every package. A rule its entry marks not
    applied may be named only where the entry says it is carried as data, and is named there."""
    carried = {m for where in entry.carried_in for m in WHERE[where]}
    for name in entry.uses:
        named = [m for m in SCANNED if m not in carried and _mentions(TEXT[m], name)]
        assert named == [], f"{name} is used in {named}: say what the code does with it"
        assert len(re.findall(rf"\b{name}\b", TEXT["rules"])) == 1, name
    for where in entry.carried_in:
        assert any(_mentions(SOURCES[where], name) for name in entry.uses), where


def test_only_what_is_not_modelled_is_applied_nowhere():
    for entry in INVENTORY:
        assert (entry.reading is Reading.NOT_MODELLED) == (not entry.applied_in), entry.rule
        assert not (entry.carried_in and entry.applied_in), entry.rule  # carried means unused


def test_every_module_is_scanned_or_exempt_with_a_reason():
    assert all(reason.strip() for reason in EXEMPT.values())
    assert [m for m in EXEMPT if m not in MODULES] == [], "no such module"
    assert {"legal/resolve", "validator/blocks", "optimizer/search/network"} <= set(SCANNED)
    assert all(m in MODULES for modules in WHERE.values() for m in modules)


def test_a_module_added_in_any_package_is_scanned_without_being_named(tmp_path):
    for name in ("new_rules.py", "legal/new_rules.py", "new_package/deep/new_rules.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("from siteplan import rules\n")
    found = _modules(tmp_path)
    assert found == ["legal/new_rules", "new_package/deep/new_rules", "new_rules"]
    assert not set(found) & set(EXEMPT)  # so each would be scanned


def test_the_scan_sees_every_way_of_importing_the_rules():
    for source, package in (("from siteplan import rules", "siteplan"),
                            ("from siteplan import rules as law", "siteplan.validator"),
                            ("from siteplan import (\n    parking,\n    rules,\n)", "siteplan"),
                            ("from siteplan.rules import PARKING_CLAUSE", "siteplan.legal"),
                            ("import siteplan.rules", "siteplan"),
                            ("from .. import rules", "siteplan.legal"),
                            ("from ..rules import TABLE_IV", "siteplan.optimizer"),
                            ("def f():\n    from siteplan import rules", "siteplan.service")):
        assert _imports_rules(source, package), source
    for source, package in (("from siteplan.contracts import resolved_rules", "siteplan"),
                            ("from siteplan.legal.resolve import resolve", "siteplan"),
                            ("from . import rules", "siteplan.legal")):  # siteplan.legal.rules
        assert not _imports_rules(source, package), source


def test_no_module_that_names_a_rule_escapes_the_inventory():
    """A rule module added under any package cannot escape the inventory: every module that
    imports rules.py is scanned (but the exempt ones, which list or classify every rule), and
    every value or clause of rules.py that any other module names has an inventory entry."""
    importers = set()
    for path in SRC.rglob("*.py"):  # walked here, not taken from MODULES
        module = path.relative_to(SRC).with_suffix("").as_posix()
        if _imports_rules(path.read_text(), _package(module)):
            importers.add(module)
    assert {"legal/resolve", "legal/facts", "validator/blocks", "optimizer/floors"} <= importers
    assert sorted(importers - set(SCANNED)) == sorted(importers & set(EXEMPT))
    covered = {name for entry in INVENTORY for name in entry.uses}
    loose = sorted({(m, name) for m in MODULES if m != "rules" for name in RULE_NAMES
                    if name not in covered and _mentions(TEXT[m], name)})
    assert loose == [], "give these an inventory entry"
    assert "PARKING_CLAUSE" in RULE_NAMES and "M_PER_FT" not in RULE_NAMES  # its own, not units'
    assert all(hasattr(rules, name) and reason.strip() for name, reason in NOT_A_RULE.items())


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
