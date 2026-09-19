# siteplan-engine: Agent Instructions

> Last verified: 2026-09-18

Stage 1 of an offline "survey to site plan" assistant for a Hyderabad architecture firm (agency client). It reads a surveyor's drawing, checks a proposal against Telangana building rules, prints the firm's area statement, and writes DXF using BuildNow plugin layer names. It is client-facing software: tests, lint and review apply.

## Commands

- Install: `uv sync`
- Tests: `uv run pytest -q` (client-drawing tests skip when `fixtures/` is empty)
- Lint: `uv run ruff check src tests`
- Read a survey: `uv run siteplan survey <survey.pdf|survey.dxf> --out out/`
- Rule check: `uv run siteplan check examples/example.project.json` (exit 1 if any rule FAILs)
- Area statement: `uv run siteplan area-statement examples/example.project.json`

## Rules

- **Client data never enters git.** Drawings and anything derived from them live in `fixtures/` and `out/`, both gitignored. Examples and tests use made-up geometry.
- **The language model never produces a number.** Areas, scales, setbacks and rule verdicts come from this code. A later LLM layer may fill a `Project` file from a brief and explain findings; it does not compute.
- **Every rule value carries its clause** (`src/siteplan/rules.py`). Change a value only with the primary source in hand, and update the test in `tests/test_rules.py`. Values known only from news (G.O.Ms.No.95 of 2026) are not the defaults.
- **A missing input is reported, not guessed.** Checks return `NEEDS_INPUT` rather than assuming.
- **No AGPL dependencies.** PyMuPDF is AGPL, so PDFs are read with pdfplumber (MIT). Check the licence of anything new before adding it.
- **The printed scale on a survey sheet is not trusted.** Scale comes from the dimension labels, then snaps to a standard plot scale only when within 0.5%.
- The BuildNow layer names in `dxf_export.py` are from the plugin's layer index; whether the plugin accepts pre-named layers is untested (needs Windows, ZWCAD 2025 and the plugin).
- Lines stay at 100 characters or fewer (ruff).
