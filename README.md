# siteplan-engine

An offline "survey to site plan" assistant for group housing in Telangana, built for an architecture firm in Hyderabad.

It reads a surveyor's drawing, checks a proposed development against the state's building rules, prints the area statement, searches tower layouts, and exports a layered DXF the architect can open in CAD. A locally served language model can drive the same tools through a chat, but it never produces a number.

## The one rule that shapes everything

**The language model never produces a number.** Areas, scales, setbacks, heights and rule verdicts all come from deterministic code. The model can ask the architect questions, call the tools and explain what they returned. Nothing is drawn until the architect approves the interpreted brief on a page the model cannot click.

## What it does

- **Reads a survey** (PDF or DXF) into a site model where every fact records how far it can be trusted: verified against a document, confirmed by the architect, or assumed.
- **Resolves the rules** from the orders themselves (G.O.168 of 2012 and the later orders that amend it). Every rule value carries its clause, and each one is inventoried as read as written, interpreted, assumed or not modelled.
- **Finds the legal envelope**: the land a building may stand on, before any tower or road is placed.
- **Searches layouts** across heights and tower arrangements, then validates each candidate with an independent checker. When no layout passes, it says which rule stops it at each height.
- **Prints the area statement** in the firm's format and **exports DXF**.
- **Exposes the same tools to a model** over MCP, behind an approval step that is written to an audit log before anything it allows runs.

## Pipeline

```
raw survey -> site model -> resolved rules -> buildable envelope
                                                   |
design brief + tower library -> optimizer -> candidate layouts -> independent validation
                                                   |
                                          approval -> area statement, DXF
```

The architecture is described in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Site facts, law and design intent are kept in separate contracts and never share a type. The contract schemas are generated into `docs/contracts/`.

## Status

This is working engineering software, not a finished product.

- The rule engine and checker run on real surveys and on made-up land used in tests.
- Several rules are still **interpretations** of the orders. Where a reading is open, the engine evaluates every reading and reports a result that holds under only some of them as unverified, not as a pass. `siteplan inventory` lists every rule and how it was read.
- It has not yet been checked against the firm's sanctioned plans, which is the real test of the rule readings. Until then, treat its verdicts as decision support for the architect, not as a compliance certificate.

## Run it

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
```

Some commands, using the made-up project in `examples/`:

```bash
uv run siteplan check examples/example.project.json          # rule check, exits 1 on any FAIL
uv run siteplan area-statement examples/example.project.json
uv run siteplan layout examples/example.project.json --library examples/flat_library.example.json
uv run siteplan inventory                                     # every rule and how it was read
uv run siteplan rules "is a ramp allowed in the setback"      # search the order, print the passage
```

`AGENTS.md` lists the full command set, including the survey reader, the acceptance run, the MCP server and the agent loop.

## Client data

Client drawings and anything derived from them live in `fixtures/` and `out/`, which are gitignored and never committed. The examples and tests use made-up geometry, and the tests that need a client drawing skip themselves when `fixtures/` is empty.

## Layout

| Path | What is in it |
|---|---|
| `src/siteplan/` | the engine: survey readers, rules, checks, optimizer, service, MCP server, agent loop |
| `src/siteplan/contracts/` | the typed contracts between stages |
| `docs/` | architecture, behaviour changes, generated contract schemas |
| `examples/` | made-up projects and libraries for trying the commands |
| `tests/` | normative and characterization tests |
