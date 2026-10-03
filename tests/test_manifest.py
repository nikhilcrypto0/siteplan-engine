"""The test manifest stays true: every test file is classified, and every exception it names is
a test that exists (a renamed test would otherwise lose its class silently)."""

import ast
from pathlib import Path

from manifest import FILES

HERE = Path(__file__).parent


def _tests_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}


def test_every_test_file_is_classified():
    files = {p.name for p in HERE.glob("test_*.py")}
    assert files == set(FILES), {"unlisted": sorted(files - set(FILES)),
                                 "listed but missing": sorted(set(FILES) - files)}


def test_every_exception_names_a_real_test():
    for name, (_, exceptions) in FILES.items():
        missing = set(exceptions) - _tests_in(HERE / name)
        assert not missing, f"{name}: no such test(s) {sorted(missing)}"
