# Test classes

Every test is **normative** (must stay true whatever the implementation: law with its clause,
contract and geometry invariants, approval and security properties, how inputs are read, facts
of a real drawing) or **characterization** (what the prototype produces today: exact numbers, the
legacy generator's own choices, one reading of an open question).

- A test file is classified in `tests/manifest.py` (the files that predate P0, with their
  exceptions), or declares its own class at the top: `TEST_CLASS = "normative"` (new files, so
  parallel streams need not edit one shared file). `tests/conftest.py` marks every test and
  refuses an unclassified file; `tests/test_manifest.py` checks that every exception names a
  real test.
- Run one class: `uv run pytest -m normative` or `uv run pytest -m characterization`; count one
  with `uv run pytest --collect-only -q -m characterization | tail -1`.
- A characterization test changes only with a normative replacement test and an entry in
  `docs/behaviour-changes.md`.
- Client-data tests (`test_client_fixtures.py`) skip cleanly without `fixtures/`; the Dhulapally
  debug baseline is rebuilt with `uv run python tests/client_baseline.py`.
