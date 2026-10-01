"""Every number generation uses is classified, and the classification cannot drift from the code."""

import ast
import dataclasses
import re
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

import siteplan
from siteplan import intake, layout, library, parking, rules
from siteplan.cli import main
from siteplan.constraints import REGISTRY, Basis, open_items, render_markdown, render_text

SRC = Path(siteplan.__file__).parent
# The modules whose numbers shape a generated layout or accept and reject one.
GENERATION_MODULES = ("rules", "access", "towers", "grounds", "parking", "layout", "heights",
                      "site_amenities", "runner", "checks", "access_checks", "parking_checks",
                      "max_floors", "intake", "library")
# The request and standards models whose numeric defaults stand in for the firm's choices.
MODELS = (layout.LayoutRequest, intake.WorkspaceDefaults, library.FlatLibrary,
          parking.ParkingStandards)
CONSTANT = re.compile(r"_?[A-Z][A-Z0-9_]*")


def _numeric(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, (tuple, list)):
        return any(_numeric(v) for v in value)
    if isinstance(value, dict):
        return any(_numeric(v) for v in value.values())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return any(_numeric(getattr(value, f.name)) for f in dataclasses.fields(value))
    return False


def _numeric_constants(module_name: str) -> list[str]:
    """Names a module itself binds to numbers at top level, found in its source so an import
    of another module's number is not counted twice."""
    module = __import__(f"siteplan.{module_name}", fromlist=[module_name])
    tree = ast.parse((SRC / f"{module_name}.py").read_text())
    names = []
    for node in tree.body:
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        for target in targets:
            if (isinstance(target, ast.Name) and CONSTANT.fullmatch(target.id)
                    and _numeric(getattr(module, target.id))):
                names.append(f"{module_name}.{target.id}")
    return names


def _numeric_defaults(model) -> list[str]:
    stem = f"{model.__module__.split('.')[-1]}.{model.__name__}"
    if isinstance(model, type) and issubclass(model, BaseModel):
        return [f"{stem}.{name}" for name, field in model.model_fields.items()
                if field.default is not PydanticUndefined and _numeric(field.default)]
    return [f"{stem}.{f.name}" for f in dataclasses.fields(model)
            if f.default is not dataclasses.MISSING and _numeric(f.default)]


REGISTERED = {symbol for c in REGISTRY for symbol in c.symbols}


@pytest.mark.parametrize("module_name", GENERATION_MODULES)
def test_every_numeric_constant_in_a_generation_module_is_classified(module_name):
    missing = [name for name in _numeric_constants(module_name) if name not in REGISTERED]
    assert missing == [], f"classify these in constraints.py: {missing}"


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_numeric_default_on_a_request_or_standards_model_is_classified(model):
    missing = [name for name in _numeric_defaults(model) if name not in REGISTERED]
    assert missing == [], f"classify these in constraints.py: {missing}"


def test_every_symbol_an_entry_names_exists_and_is_a_number():
    for c in REGISTRY:
        for symbol in c.symbols:
            module_name, *path = symbol.split(".")
            value = __import__(f"siteplan.{module_name}", fromlist=[module_name])
            for step in path:
                value = (value.model_fields[step].default
                         if isinstance(value, type) and issubclass(value, BaseModel)
                         else next(f.default for f in dataclasses.fields(value) if f.name == step)
                         if isinstance(value, type) and dataclasses.is_dataclass(value)
                         else getattr(value, step))
            assert _numeric(value), symbol


def test_what_is_not_law_says_what_would_settle_it():
    for c in REGISTRY:
        if c.basis in (Basis.UNRESOLVED_INTERPRETATION, Basis.ENGINE_DESIGN_ASSUMPTION):
            assert c.settles, c.what
        if c.basis is Basis.LEGAL_RULE:
            assert "G.O." in c.source or "NBC" in c.source, c.what
        if c.basis is Basis.FIRM_STANDARD:
            assert "firm" in c.source, c.what


def test_the_three_findings_the_review_named_are_not_presented_as_law():
    by_what = {c.what: c for c in REGISTRY}
    amenity = next(c for c in REGISTRY if "amenities (club house) area" in c.what)
    assert amenity.basis is Basis.UNRESOLVED_INTERPRETATION
    assert f"{rules.AMENITY_CAP_SQFT_2016:,.0f}" in amenity.value
    turn = next(c for c in REGISTRY if "Where the 9 m turning radius is measured" in c.what)
    assert turn.basis is Basis.UNRESOLVED_INTERPRETATION and "6.88" in turn.value
    bays = next(c for c in REGISTRY if "size of a parking bay" in c.what)
    assert bays.basis is Basis.ENGINE_DESIGN_ASSUMPTION and "2.5 x 5 m" in bays.value
    assert "ENGINE_DESIGN_ASSUMPTION" in parking.BAY_BASIS
    assert by_what  # every entry has its own sentence
    assert len(by_what) == len(REGISTRY)


def test_values_are_read_from_the_code_not_written_by_hand():
    text = render_text()
    assert f"{rules.HIGH_RISE_THRESHOLD_M:g} m" in text
    assert f"{parking.BAY_WIDTH_M:g} x {parking.BAY_DEPTH_M:g} m bays" in text
    assert "SITE_INPUT" in text and text.endswith(".")
    rows = [line for line in render_markdown().splitlines() if line.startswith("| ")]
    assert len(rows) == len(REGISTRY) + 1


def test_open_items_are_the_readings_and_the_engines_own_assumptions():
    items = open_items()
    assert items and all(c.basis in (Basis.UNRESOLVED_INTERPRETATION,
                                     Basis.ENGINE_DESIGN_ASSUMPTION) for c in items)
    assert any("3%" in c.value for c in items)  # the amenities share is open


def test_the_command_prints_the_audit(capsys):
    assert main(["constraints"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("LEGAL_RULE") and "UNRESOLVED_INTERPRETATION" in out
    assert main(["constraints", "--basis", "ENGINE_DESIGN_ASSUMPTION"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("ENGINE_DESIGN_ASSUMPTION") and "LEGAL_RULE\n" not in out
