"""No prototype is made from a site's own plan.

A library sized from a site's own area statement hands the generator the answer it is later
marked against (AGENTS.md: acceptance keeps the firm's plan out of the generator). So the
prototype package, its tests and the example library are made from the made-up example flats and
from nothing under the client's fixtures folder. The names below are what must never appear in
them; this file is the one place that may say them, so it is not scanned.
"""

import ast
import re
from pathlib import Path

from prototype_helpers import EXAMPLE_FLATS, EXAMPLES, ROOT

from siteplan.library import FlatLibrary
from siteplan.prototypes import compose_library, dumps

TEST_CLASS = "normative"

SITE_NAMES = re.compile(r"dhulapally|dulapally|bhadurpalle|calibrated", re.IGNORECASE)
CLIENT_FOLDER = re.compile(r"(?<![A-Za-z_])fixtures/")  # not tests/contract_fixtures/
OWNED = [*sorted((ROOT / "src" / "siteplan" / "prototypes").glob("*.py")),
         *sorted(p for p in (ROOT / "tests").glob("test_prototypes*.py") if p != Path(__file__)),
         ROOT / "tests" / "prototype_helpers.py", EXAMPLES / "prototypes.example.json"]


def _strings(path: Path) -> list[str]:
    """Every string a Python file holds (docstrings and paths included), or a JSON file whole."""
    text = path.read_text()
    if path.suffix != ".py":
        return [text]
    return [node.value for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_nothing_the_prototype_work_holds_or_reads_comes_from_a_site_plan():
    assert len(OWNED) >= 9, "the scan found too few files to mean anything"
    for path in OWNED:
        for text in _strings(path):
            assert not SITE_NAMES.search(text), f"{path.name} names a site's own plan"
            assert not CLIENT_FOLDER.search(text), f"{path.name} reads the client's fixtures"


def test_the_example_library_is_made_from_the_example_flats_alone():
    """Rebuilt here from examples/flat_library.example.json, it is the committed file to the
    letter, so no other library (and no site's plan) went into it."""
    kit = compose_library(FlatLibrary.model_validate_json(EXAMPLE_FLATS.read_text()),
                          {"2BHK": 0.7, "3BHK": 0.3})
    assert dumps(kit) == (EXAMPLES / "prototypes.example.json").read_text()
    assert all("EXAMPLE sizes only" in p.source for p in kit)  # and it says so itself
