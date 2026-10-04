"""The full search against LEGACY on the firm's two real sites, side by side (client data).

    uv run python tests/search_compare.py            # both sites
    uv run python tests/search_compare.py dhulapally # one

Dhulapally is the pinned debug run (the firm's net outline fitted onto its survey, tagged
FIRM_FINISHED_PLAN, so a DEBUG run and never evidence for a rule); Suchitra is its survey with the
nala's buffer kept clear. Both strategies are given the same site model, rules, brief, envelope and
the same independent validator, through `optimize`. LEGACY is run once for each reading of the stilt
and of circulation inside the setback (its four configurations), the full search once with the
prototype kit composed from the firm's own flat library. What is printed is what each strategy
proposes, every alternative the guard let through, and how long it took.

Everything this writes lives on the screen; nothing here is committed with client data.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"
WORKSPACE = FIXTURES / "workspace"
EXAMPLES = Path(__file__).parent.parent / "examples"


def dhulapally():
    """The pinned debug run's inputs, the stilt and circulation left open (ALL)."""
    from client_baseline import ANSWERS, SURVEY, profile_path

    from siteplan.adapters import brief
    from siteplan.intake import build_project, extract, load_defaults
    from siteplan.legal.envelope import envelope
    from siteplan.legal.resolve import resolve
    from siteplan.legal.site import readings_of, site_from_project
    from siteplan.profiles import apply_profile, load_profile
    from siteplan.project import Project
    from siteplan.provenance import Provenance
    from siteplan.site_amenities import AmenityLibrary

    defaults = load_defaults(WORKSPACE)
    built = build_project(extract(SURVEY), json.loads(ANSWERS.read_text()), defaults)
    built["layout"]["conservative_parking"] = True
    built["sources"]["conservative_parking"] = "run in the conservative test mode"
    built["status"]["conservative_parking"] = Provenance.ASSUMED_FOR_TEST
    built = apply_profile(built, load_profile(profile_path("counted")))
    project = Project.model_validate(built)
    site = site_from_project(project, SURVEY)
    selections, when_open = readings_of(project)
    rules = resolve(site, selections=selections, when_open=when_open)
    stated = AmenityLibrary.model_validate_json((EXAMPLES / "amenities.hyderabad.json").read_text())
    return _inputs(site, rules, brief(project, defaults, amenities=stated), defaults, envelope)


def suchitra():
    from siteplan.adapters import brief, site_model
    from siteplan.contracts.common import Line
    from siteplan.intake import load_defaults
    from siteplan.legal.envelope import envelope
    from siteplan.legal.resolve import resolve
    from siteplan.legal.site import readings_of
    from siteplan.project import Project
    from siteplan.runner import load_plot, read_survey
    from siteplan.site_amenities import AmenityLibrary

    survey = WORKSPACE / "suchitra_survey.pdf"
    project = Project.model_validate_json((WORKSPACE / "suchitra.project.json").read_text())
    project = project.model_copy(update={"layout": project.layout.model_copy(update={
        "conservative_parking": True, "maximise": True})})
    plot, _ = load_plot(project, survey)
    ring = [list(p) for p in list(plot.exterior.coords)[:-1]]
    project = project.model_copy(update={"site": project.site.model_copy(
        update={"net_plot_m": ring})})
    site = site_model(project, site_id="suchitra", boundary=read_survey(survey).boundary)
    drawn = list(read_survey(survey, project.site.water[0]).water)
    site.water[0].lines = [Line(points=[tuple(c) for c in line.coords]) for line in drawn]
    defaults = load_defaults(WORKSPACE)
    stated = AmenityLibrary.model_validate_json((EXAMPLES / "amenities.hyderabad.json").read_text())
    selections, when_open = readings_of(project)
    rules = resolve(site, selections=selections, when_open=when_open)
    return _inputs(site, rules, brief(project, defaults, amenities=stated), defaults, envelope)


def _inputs(site, rules, design, defaults, make_envelope):
    from siteplan.library import FlatLibrary
    from siteplan.site_amenities import AmenityLibrary

    library = FlatLibrary.model_validate_json((WORKSPACE / defaults.flat_library).read_text())
    amenities = AmenityLibrary.model_validate_json(
        (WORKSPACE / defaults.amenities).read_text()) if defaults.amenities else None
    return site, rules, design, make_envelope(site, rules), library, amenities


def _row(label, candidate, report, seconds=None):
    m = candidate.metrics
    floors = sorted({t.floors_above_stilt for t in candidate.towers})
    return (f"| {label} | {len(candidate.towers)} | {'/'.join(map(str, floors))} | "
            f"{m.total_flats} | {m.saleable_sqft:,.0f} | {m.open_space_sqm:,.0f} | "
            f"{report.verdict.legal.value} | {report.verdict.program.value} |")


def compare(name: str, loader) -> None:
    from siteplan import validator
    from siteplan.contracts.common import SourceKind
    from siteplan.optimizer import LegacyStrategy, optimize
    from siteplan.optimizer.search import FullSearchStrategy
    from siteplan.optimizer.search.verdicts import rests_on
    from siteplan.prototypes import compose_library

    site, rules, design, envelope, library, amenities = loader()
    print(f"\n## {name}\n")
    print("| strategy / alternative | towers | floors | flats | saleable sft | open space m² | "
          "legal | program |")
    print("|---|---|---|---|---|---|---|---|")
    started = time.time()
    legacy = optimize(site, rules, design, LegacyStrategy.for_readings(rules, library, amenities),
                      envelope=envelope)
    legacy_s = time.time() - started
    for a in legacy.alternatives:
        print(_row(f"LEGACY {a.point.value if a.point else 'extra'}", a.candidate, a.report))
    print(f"\nLEGACY: {len(legacy.alternatives)} alternatives passed the guard, "
          f"{len(legacy.rejected)} candidates refused, {legacy_s:.0f} s")
    kit = compose_library(library, design.program.unit_mix.value,
                          source_kind=SourceKind.FIRM_STANDARD)
    started = time.time()
    full_strategy = FullSearchStrategy()
    proposal = full_strategy.propose(_context(site, rules, design, envelope, kit))
    full_s = time.time() - started
    result = optimize(site, rules, design, [FullSearchStrategy()], envelope=envelope,
                      prototypes=kit)
    print()
    print("| strategy / alternative | towers | floors | flats | saleable sft | open space m² | "
          "legal | program |")
    print("|---|---|---|---|---|---|---|---|")
    for a in result.alternatives:
        holds = rests_on(a.report).holds_under_every_reading
        print(_row(f"FULL {a.point.value if a.point else 'extra'}"
                   f"{' (every reading)' if holds else ''}", a.candidate, a.report))
    print("\nEvery proposal of the full search:\n")
    print("| proposal | towers | floors | flats | saleable sft | open space m² | legal | program |")
    print("|---|---|---|---|---|---|---|---|")
    for c in proposal.candidates:
        report = validator.validate(site, rules, design, c, envelope)
        holds = rests_on(report).holds_under_every_reading
        print(_row(f"{c.candidate_id}{' (every reading)' if holds else ''}", c, report))
    print(f"\nFULL: {len(proposal.candidates)} proposed, {len(result.alternatives)} alternatives "
          f"through the guard ({len(result.rejected)} refused), {full_s:.0f} s per proposal")
    for note in proposal.notes:
        print(f"- {note}")


def _context(site, rules, design, envelope, kit):
    from siteplan.optimizer import SearchContext

    return SearchContext(site, rules, design, envelope, tuple(kit), 0)


def main(argv: list[str]) -> None:
    sites = {"dhulapally": dhulapally, "suchitra": suchitra}
    for name in argv or list(sites):
        compare(name, sites[name])


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main(sys.argv[1:])
