"""Every number generation uses is classified, and the classification cannot drift from the code.

Every module under src/siteplan is either audited or exempt with its reason. An audited module's
named numbers (at its top level and in its classes, tuples, dicts and sets of numbers included)
and the numeric defaults of its models each need an entry in constraints.py, or a line in
NOT_DOMAIN saying why they are no domain number. A module in an audited package is audited
without being named, so a new one cannot slip past; a new module anywhere else fails until
someone audits or exempts it.
"""

import ast
import dataclasses
import importlib
import re
from enum import Enum
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

import siteplan
from siteplan import area_statement, assistant, intake, layout, library, parking, rules
from siteplan.cli import main
from siteplan.constraints import REGISTRY, Basis, open_items, render_markdown, render_text
from siteplan.contracts import design_brief
from siteplan.optimizer.search import strategy

SRC = Path(siteplan.__file__).parent
# Packages every module of which is audited, modules added later included. `service` is named
# before it exists, so its first module is held to the audit like the rest.
AUDITED_PACKAGES = ("adapters", "contracts", "legal", "optimizer", "prototypes", "service",
                    "validator")
# Top-level modules whose numbers shape a generated layout, size it, or accept or reject one.
AUDITED_MODULES = (
    "access", "access_checks", "acceptance", "area_statement", "assistant", "basis", "blind",
    "cases", "checks", "findings", "flat_import", "geometry", "grounds", "heights", "intake",
    "layout", "library", "max_floors", "parking", "parking_checks", "profiles", "project",
    "provenance", "rules", "runner", "site_amenities", "towers",
)
# Modules no number of which reaches a layout or a verdict, each with the reason.
EXEMPT = {
    "__init__": "the package's marker",
    "approval": "the MCP approval page: HTTP plumbing (a form's size limit)",
    "cli": "command-line plumbing",
    "constraints": "this audit itself: it reads every value from the modules it classifies",
    "dxf_entities": "drawing reading: a DXF's declared unit and its blocks opened out",
    "dxf_export": "rendering only: BuildNow layer names and colours",
    "dxf_survey": "survey reading: what a drawing settles is a SITE_INPUT, EXTRACTED",
    "guards": "the model's guards: cleaning a brief, checking the numbers the model quotes",
    "inventory": "the rule inventory: it lists rules.py, which this audit classifies",
    "layout_export": "rendering only: an option as DXF",
    "llm": "the model's transport: token budgets, timeouts and retries",
    "mcp_server": "MCP plumbing: listing and brief limits, the approval's timeout",
    "pdf_survey": "survey reading: what a sheet settles is a SITE_INPUT, EXTRACTED",
    "registration": "debug and regression runs only: fits the firm's finished outline to the "
                    "survey, which a blind run never does",
    "result_page": "rendering only: the MCP result page",
    "roads": "survey reading: drawn road widths, reported and never used by the rules",
    "rulebook": "rule questions: a search over the order's text, no number of a layout",
    "sheet": "rendering only: the A1 sheet",
    "survey": "survey reading: the sheet in metres, its scale and levels (SITE_INPUT)",
    "units": "unit conversions, fixed by definition",
    "wizard": "command-line questions for `siteplan new`",
    "legal/debug_drawing": "rendering only: the envelope's debug drawing",
    "prototypes/__main__": "command-line plumbing for the prototype kit",
    "prototypes/draw": "rendering only: prototypes as DXF blocks",
    "service/render": "rendering only: a candidate as DXF, sheet notes and SVG",
    # The model-facing transport and the model process's sandbox: no number of a layout.
    "agent/__init__": "the model-facing package's marker",
    "agent/server": "transport plumbing: MCP over stdio around the ToolHost",
    "agent/harness": "transport plumbing: the model's side of the MCP stream",
    "agent/launch": "process plumbing: starting the host and the sandboxed agent, and waiting",
    "agent/sandbox": "sandbox plumbing: the model process's policy, a link limit, a timeout",
    "agent/standin": "a scripted stand-in model that proves the transport and the sandbox",
}
# Named numbers in audited modules that are no domain number: an ordering, a unit, a bearing, a
# message's length. A new number belongs in constraints.py unless it is plainly one of these.
NOT_DOMAIN = {
    "contracts.resolved_rules.ELIGIBILITY_RANK": "the order of the Eligibility labels",
    "geometry.COMPASS_DEG": "the bearing each compass label names",
    "flat_import.MM_M": "a unit: room sizes are written in millimetres",
    "flat_import.SQM_SQFT": "a unit: square feet in a square metre",
    "prototypes.compose.COORD_DIGITS": "the decimals a composed prototype is saved to",
    "optimizer.search.network.STREET_REACH_M": "a stand-in for infinity, far beyond any plot",
    "validator.refusals.SHOWN": "how many offending numbers a refusal names",
    "validator.refusals.LIBRARY_MESSAGE_CHARS": "how much of a library's error a report keeps",
    "assistant.MAX_UNCLEAR": "how many unclear points of a brief the reply lists",
    "assistant.EXPLAIN_MAX_TOKENS": "the model's token allowance for an explanation",
    # The service's requests: bounds on what a caller may send, never a figure of a layout.
    "service.models.MAX_NAME_CHARS": "the longest file name a request may carry",
    "service.models.MAX_BRIEF_CHARS": "the longest brief a request may carry, as the MCP caps it",
    "service.models.MAX_ITEM_CHARS": "the longest acknowledged UNVERIFIED item",
    "service.models.MAX_ITEMS": "how many UNVERIFIED items one export may acknowledge",
    "service.models.MAX_COMPARED": "how many candidates one comparison takes",
    "service.models.MAX_MIX_CATEGORIES": "how many flat categories a unit mix may name",
    "service.models.MAX_FLOORS_ABOVE_STILT": "a sanity bound on a requested count, far above "
                                             "the search's ceiling: the rules decide the height",
    "service.models.RUN_ID_CHARS": "the length of a run's id",
    "service.models.MAX_TEXT_CHARS": "how much text read off a drawing a reply returns",
    "service.approvers.PAGE_TIMEOUT_S": "how long the architect has to answer the approval "
                                        "page; an unanswered page is a no",
}
# The request, standards and config models: each numeric default stands in for a choice, so
# every one is classified, a 0 or a 1 included.
MODELS = (layout.LayoutRequest, intake.WorkspaceDefaults, intake.WorkspaceMargins,
          library.FlatLibrary, parking.ParkingStandards, area_statement.TowerGroup,
          design_brief.FirmStandards, design_brief.DesignMargins, design_brief.Program,
          design_brief.Objectives, strategy.Limits)
# One number kept in several modules (the validator imports no generator module, so it keeps its
# own copies). The entry that lists a group prints one of them, so the group holds one value.
COPIES = (
    ("grounds.CLEARANCE_M", "site_amenities.CLEARANCE_M", "optimizer.search.ground.CLEARANCE_M"),
    ("grounds.CLUB_ASPECT", "optimizer.search.ground.CLUB_ASPECT"),
    ("grounds.TRIM_ABOVE", "optimizer.search.fit.TRIM_ABOVE"),
    ("grounds.TRIM_MARGIN", "optimizer.search.fit.TRIM_MARGIN"),
    ("site_amenities.SCAN_STEP_M", "optimizer.search.fit.SCAN_STEP_M"),
    ("layout.SAME_IDEA_OVERLAP", "optimizer.pareto.SAME_IDEA_OVERLAP"),
    ("layout.ANGLE_FAMILY_DEG", "optimizer.pareto.ANGLE_FAMILY_DEG"),
    ("access.SECTOR_STEPS", "optimizer.search.turns.ARC_STEPS", "validator.turning.ARC_STEPS"),
    ("access.MIN_TURN_DEG", "optimizer.search.turns.MIN_TURN_DEG",
     "validator.turning.MIN_TURN_DEG"),
    ("towers.TOUCH_M", "access_checks.TOUCH_M", "optimizer.search.layout.TOUCH_M",
     "optimizer.search.network.TOUCH_M", "validator.network.TOUCH_M",
     "validator.parking.RAMP_TOUCH_M", "validator.fire.GATE_TOUCH_M"),
    ("optimizer.search.parking_plan.OFFSETS_ALONG", "validator.cars.OFFSETS_ALONG"),
    ("optimizer.search.parking_plan.OFFSETS_ACROSS", "validator.cars.OFFSETS_ACROSS"),
    ("parking_checks.AREA_SLACK_SQM", "validator.parking.AREA_SLACK_SQM"),
    ("checks.WATER_OVERLAP_SQM", "validator.land_checks.WATER_OVERLAP_SQM"),
    ("contracts.design_brief.MIX_SUM_TOLERANCE", "prototypes.compose.MIX_SUM_TOLERANCE"),
    ("validator.accounting.PLAY_SHARE", "optimizer.search.build.ON_POCKET_SHARE",
     "adapters.legacy_layout.ON_GROUND_SHARE"),
    ("layout.LayoutRequest.club_house_floors", "optimizer.search.layout.CLUB_FLOORS"),
    ("layout.LayoutRequest.options", "contracts.design_brief.Objectives.options"),
    ("intake.WorkspaceDefaults.floor_height_m", "layout.LayoutRequest.floor_height_m"),
    ("intake.WorkspaceDefaults.stilt_height_m", "layout.LayoutRequest.stilt_height_m"),
    ("intake.WorkspaceDefaults.common_area_pct", "layout.LayoutRequest.common_area_pct",
     "area_statement.TowerGroup.common_area_pct"),
    ("intake.WorkspaceDefaults.cellar_floor_height_m", "layout.LayoutRequest.cellar_floor_height_m",
     "parking.ParkingStandards.cellar_floor_height_m"),
    ("intake.WorkspaceDefaults.max_cellars", "layout.LayoutRequest.max_cellars",
     "parking.ParkingStandards.max_cellars"),
)
CONSTANT = re.compile(r"_?[A-Z][A-Z0-9_]*")
STRUCTURAL = (0, 1, -1)  # a count's start, an identity, a neutral weight

MODULES = sorted(p.relative_to(SRC).with_suffix("").as_posix() for p in SRC.rglob("*.py"))


def _audited(module: str) -> bool:
    if module in EXEMPT:
        return False
    return module in AUDITED_MODULES or (
        "/" in module and module.split("/")[0] in AUDITED_PACKAGES)


AUDITED = [m for m in MODULES if _audited(m)]


def _dotted(module: str) -> str:
    """A module's name below siteplan, as constraints.py names its symbols."""
    return module.removesuffix("/__init__").replace("/", ".")


def _numeric(value) -> bool:
    if isinstance(value, bool | Enum):
        return False
    if isinstance(value, int | float):
        return True
    if isinstance(value, tuple | list | set | frozenset | range):
        return any(_numeric(v) for v in value)
    if isinstance(value, dict):
        return any(_numeric(k) or _numeric(v) for k, v in value.items())
    if isinstance(value, BaseModel):
        return any(_numeric(getattr(value, name)) for name in type(value).model_fields)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return any(_numeric(getattr(value, f.name)) for f in dataclasses.fields(value))
    return False


def _structural(value) -> bool:
    if isinstance(value, int | float):
        return value in STRUCTURAL
    if isinstance(value, tuple | list | set | frozenset):
        return all(_structural(v) for v in value)
    return False


def _bound(node: ast.stmt) -> list[str]:
    """The constant-style names a statement binds, tuple unpacking included."""
    targets = (node.targets if isinstance(node, ast.Assign)
               else [node.target] if isinstance(node, ast.AnnAssign) else [])
    return [n.id for target in targets for n in ast.walk(target)
            if isinstance(n, ast.Name) and CONSTANT.fullmatch(n.id)]


def _named_numbers(module: str) -> list[str]:
    """The names a module itself binds to numbers, at its top level and in its classes' bodies,
    found in its source so an import of another module's number is not counted twice. Enum
    members are labels, not numbers."""
    dotted = _dotted(module)
    loaded = importlib.import_module(f"siteplan.{dotted}")
    found = []
    for node in ast.parse((SRC / f"{module}.py").read_text()).body:
        found += [f"{dotted}.{name}" for name in _bound(node)
                  if _numeric(getattr(loaded, name, None))]
        cls = getattr(loaded, node.name, None) if isinstance(node, ast.ClassDef) else None
        if isinstance(cls, type) and not issubclass(cls, Enum):
            found += [f"{dotted}.{node.name}.{name}" for statement in node.body
                      for name in _bound(statement) if _numeric(getattr(cls, name, None))]
    return found


def _models(module: str) -> list[type]:
    """The pydantic models and dataclasses a module defines."""
    loaded = importlib.import_module(f"siteplan.{_dotted(module)}")
    return [cls for cls in vars(loaded).values()
            if isinstance(cls, type) and cls.__module__ == loaded.__name__
            and (issubclass(cls, BaseModel) or dataclasses.is_dataclass(cls))]


def _defaults(model: type) -> dict[str, object]:
    """A model's numeric defaults, by the symbol constraints.py names them with. A default that
    is itself a model is left to that model, whose own defaults are audited where it is made."""
    stem = f"{model.__module__.removeprefix('siteplan.')}.{model.__name__}"
    if issubclass(model, BaseModel):
        given = {name: field.default for name, field in model.model_fields.items()
                 if field.default is not PydanticUndefined}
    else:
        given = {f.name: f.default for f in dataclasses.fields(model)
                 if f.default is not dataclasses.MISSING}
    return {f"{stem}.{name}": value for name, value in given.items()
            if _numeric(value) and not isinstance(value, BaseModel)
            and not dataclasses.is_dataclass(value)}


def _step(value, name: str):
    if isinstance(value, type) and issubclass(value, BaseModel) and name in value.model_fields:
        return value.model_fields[name].default
    if isinstance(value, type) and dataclasses.is_dataclass(value):
        fields = {f.name: f for f in dataclasses.fields(value)}
        if name in fields:
            return fields[name].default
    return getattr(value, name)


def _resolve(symbol: str):
    """What a symbol names: module.NAME, module.Class.NAME or module.Model.field (its default),
    the module being the longest prefix that imports."""
    parts = symbol.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            value = importlib.import_module("siteplan." + ".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for name in parts[cut:]:
            value = _step(value, name)
        return value
    raise AssertionError(f"no module in {symbol}")


REGISTERED = {symbol for c in REGISTRY for symbol in c.symbols}


def test_every_module_is_audited_or_exempt_with_a_reason():
    unplaced = [m for m in MODULES if not _audited(m) and m not in EXEMPT]
    assert unplaced == [], ("audit these (AUDITED_MODULES, or an audited package) or exempt "
                            f"them in EXEMPT with the reason: {unplaced}")
    assert not set(AUDITED_MODULES) & set(EXEMPT)
    assert all("/" not in m for m in AUDITED_MODULES)
    stale = [m for m in (*AUDITED_MODULES, *EXEMPT) if m not in MODULES]
    assert stale == [], f"no such module: {stale}"
    assert all(reason.strip() for reason in EXEMPT.values())


def test_a_new_module_in_an_audited_package_is_audited_without_being_named():
    assert _audited("legal/anything_new") and _audited("service/api")
    assert not _audited("anything_new") and not _audited("new_package/module")
    assert not _audited("legal/debug_drawing")  # exempt by name, with its reason


@pytest.mark.parametrize("module", AUDITED)
def test_every_named_number_in_an_audited_module_is_classified(module):
    missing = [n for n in _named_numbers(module) if n not in REGISTERED and n not in NOT_DOMAIN]
    assert missing == [], f"classify these in constraints.py: {missing}"


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_numeric_default_on_a_request_standards_or_config_model_is_classified(model):
    missing = [name for name in _defaults(model) if name not in REGISTERED]
    assert missing == [], f"classify these in constraints.py: {missing}"


@pytest.mark.parametrize("module", AUDITED)
def test_a_model_default_that_is_a_domain_number_is_classified_wherever_the_model_is(module):
    """Not only the models MODELS names: a settings model added to an audited module is held to
    the audit. On a record that is not a request, standards or config model a default of 0, 1
    or -1 is where a count starts or a neutral value, not a choice."""
    missing = [name for model in _models(module) for name, value in _defaults(model).items()
               if not _structural(value) and name not in REGISTERED and name not in NOT_DOMAIN]
    assert missing == [], f"classify these in constraints.py: {missing}"


def test_what_is_set_aside_as_no_domain_number_exists_and_is_not_classified_too():
    for symbol, reason in NOT_DOMAIN.items():
        assert _numeric(_resolve(symbol)) and reason.strip(), symbol
        assert symbol not in REGISTERED, symbol


def test_every_symbol_an_entry_names_exists_and_is_a_number():
    for c in REGISTRY:
        for symbol in c.symbols:
            assert _numeric(_resolve(symbol)), symbol


@pytest.mark.parametrize("group", COPIES, ids=lambda group: group[0])
def test_the_copies_an_entry_counts_as_one_number_hold_one_value(group):
    assert all(symbol in REGISTERED for symbol in group), group
    values = {symbol: _resolve(symbol) for symbol in group}
    first = values[group[0]]
    assert all(value == first for value in values.values()), values


def test_the_assistant_names_the_defaults_the_request_uses():
    for name, (default, _, _) in assistant.DEFAULTS.items():
        assert default == layout.LayoutRequest.model_fields[name].default, name


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
    assert main(["constraints", "--markdown"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("| Basis |") and f"{len(REGISTRY)} constraints:" in out
