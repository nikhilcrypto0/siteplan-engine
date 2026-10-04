"""The test manifest stays true: every test file is classified (in tests/manifest.py, or by its
own TEST_CLASS), and every exception the manifest names is a test that exists (a renamed test
would otherwise lose its class silently)."""

import ast
from pathlib import Path

from manifest import CHARACTERIZATION, FILES, NORMATIVE

HERE = Path(__file__).parent


def _tests_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}


def _declared(path: Path) -> str | None:
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "TEST_CLASS" for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def test_every_test_file_is_classified():
    files = sorted(HERE.rglob("test_*.py"))
    unclassified = [p.name for p in files if p.name not in FILES and _declared(p) is None]
    assert not unclassified, f"classify: {unclassified}"
    assert all(_declared(p) in (None, NORMATIVE, CHARACTERIZATION) for p in files)
    listed_missing = set(FILES) - {p.name for p in files}
    assert not listed_missing, f"listed but missing: {sorted(listed_missing)}"


def test_every_exception_names_a_real_test():
    for name, (_, exceptions) in FILES.items():
        missing = set(exceptions) - _tests_in(HERE / name)
        assert not missing, f"{name}: no such test(s) {sorted(missing)}"
