"""Marks every test normative or characterization from tests/manifest.py, and refuses a test
file nobody has classified. Run one class with `uv run pytest -m normative` (or
`-m characterization`)."""

import pytest
from manifest import kind_of


def pytest_collection_modifyitems(config, items):
    unlisted = set()
    for item in items:
        kind = kind_of(item.path.name, getattr(item, "originalname", None) or item.name)
        if kind is None:
            unlisted.add(item.path.name)
            continue
        item.add_marker(getattr(pytest.mark, kind))
    if unlisted:
        raise pytest.UsageError("Classify these test files in tests/manifest.py (normative or "
                                f"characterization): {sorted(unlisted)}")
