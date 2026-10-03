"""The validator must not lean on the generator: it imports none of its modules, directly or
through anything it imports, so an error in the generator's geometry cannot pass silently."""

import ast
from pathlib import Path

TEST_CLASS = "normative"

SRC = Path(__file__).parent.parent / "src"
VALIDATOR = SRC / "siteplan" / "validator"
# What stream D may import from the package (docs/ARCHITECTURE.md, section 6).
ALLOWED = {"contracts", "rules", "findings", "provenance", "basis", "geometry", "units",
           "validator"}
BANNED = {"layout", "grounds", "towers", "access", "heights", "runner", "adapters", "optimizer",
          "legal", "prototypes", "max_floors", "intake", "acceptance"}


def _file_of(module: str) -> Path | None:
    path = SRC.joinpath(*module.split("."))
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    return path / "__init__.py" if (path / "__init__.py").is_file() else None


def imported_modules(source: str, package: str = "siteplan.validator") -> set[str]:
    """Every module a source file imports, as dotted names, wherever the import stands
    (inside a function too). `from siteplan import rules` is the module siteplan.rules."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*parent, base]) if base else ".".join(parent)
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names
                         if _file_of(f"{base}.{alias.name}"))
    return found


def _siteplan_part(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if parts[0] == "siteplan" and len(parts) > 1 else None


def test_the_scanner_sees_every_way_of_importing_a_generator_module():
    for source in ("import siteplan.access", "from siteplan.access import around_block",
                   "from siteplan import access", "def f():\n    from siteplan.layout import x"):
        assert {_siteplan_part(m) for m in imported_modules(source)} & BANNED, source


def test_the_validator_imports_no_generator_module():
    offenders = {}
    for path in sorted(VALIDATOR.glob("*.py")):
        names = {_siteplan_part(m) for m in imported_modules(path.read_text())} - {None}
        wrong = names & BANNED
        if wrong:
            offenders[path.name] = sorted(wrong)
    assert not offenders, offenders


def test_the_validator_imports_only_what_stream_d_may():
    offenders = {}
    for path in sorted(VALIDATOR.glob("*.py")):
        names = {_siteplan_part(m) for m in imported_modules(path.read_text())} - {None}
        if names - ALLOWED:
            offenders[path.name] = sorted(names - ALLOWED)
    assert not offenders, offenders


def test_nothing_the_validator_imports_reaches_a_generator_module_either():
    """checks.py and access_checks.py would pass the direct test and still bring access.py in."""
    seen: set[str] = set()
    pending = [m for p in VALIDATOR.glob("*.py") for m in imported_modules(p.read_text())
               if _siteplan_part(m)]
    while pending:
        module = pending.pop()
        if module in seen or not (path := _file_of(module)):
            continue
        seen.add(module)
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        pending += [m for m in imported_modules(path.read_text(), package) if _siteplan_part(m)]
    reached = {_siteplan_part(m) for m in seen}
    assert not reached & BANNED, sorted(reached & BANNED)
    assert not {"checks", "access_checks", "parking_checks", "parking"} & reached
    assert "validator" in reached and "contracts" in reached  # the walk really walked


def test_the_measuring_geometry_is_rebuilt_inside_the_validator():
    """The pieces today's checker borrows from access.py have their own versions here."""
    from siteplan.validator import shapes, turning

    assert callable(shapes.opening) and callable(shapes.healed)
    assert callable(turning.round_block) and callable(turning.road_bends)
    assert callable(turning.sector) and callable(turning.along_wall)
