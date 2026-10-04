"""Marks every test normative or characterization, and refuses a test file nobody has
classified. A file is classified in tests/manifest.py, or by declaring its own class at the top
(`TEST_CLASS = "normative"`), so parallel streams need not all edit one file. Run one class with
`uv run pytest -m normative` (or `-m characterization`)."""

import pytest
from manifest import CHARACTERIZATION, NORMATIVE, kind_of


def pytest_collection_modifyitems(config, items):
    unlisted = set()
    for item in items:
        declared = getattr(item.module, "TEST_CLASS", None) if item.module else None
        kind = kind_of(item.path.name, getattr(item, "originalname", None) or item.name)
        if declared is not None:
            if declared not in (NORMATIVE, CHARACTERIZATION):
                raise pytest.UsageError(f"{item.path.name}: TEST_CLASS is {declared!r}")
            kind = kind or declared
        if kind is None:
            unlisted.add(item.path.name)
            continue
        item.add_marker(getattr(pytest.mark, kind))
    if unlisted:
        raise pytest.UsageError("Classify these test files (TEST_CLASS at the top, or "
                                f"tests/manifest.py): {sorted(unlisted)}")
