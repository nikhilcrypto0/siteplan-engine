"""The Dhulapally debug regression baseline: how it is made, summarised and pinned.

Blind acceptance on Dhulapally cannot run until the architect says where the 1,160 m² road strip
lies (the survey marks none), so the regression load is carried by a DEBUG run: the firm's
site-plan outline, fitted onto the survey's frame (registration.py) and tagged
FIRM_FINISHED_PLAN, stands in as the net plot; everything else is generated. It is run under both
readings of whether the stilt counts toward the Table IV height, and the results are pinned.

    uv run python tests/client_baseline.py     # rebuild the profiles and re-pin (client data)

Client data: everything this writes lives in gitignored fixtures/.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"
WORKSPACE = FIXTURES / "workspace"
SURVEY = WORKSPACE / "dhulapally_survey.pdf"
SITE_PLAN = WORKSPACE / "DULAPALLY_SITE_PLANS.dxf"
ANSWERS = FIXTURES / "acceptance" / "dhulapally.answers.json"
FIRM_CASE = FIXTURES / "cases" / "dhulapally.case.json"
FIRM_PROJECT = WORKSPACE / "dhulapally.project.json"
PROFILES = FIXTURES / "profiles"
BASELINE = FIXTURES / "baseline" / "dhulapally-debug-2026-10-02"
PINNED = BASELINE / "baseline.json"
# The two readings of stilt_in_rule_height, and what each sets in the debug profile. Under
# "not counted" a 30 m rule height is 10 floors, so the search starts one above that.
READINGS = {"counted": {},
            "not_counted": {"stilt_in_rule_height": False, "floors": 10}}
OPEN_FACTS = ["where the 1,160 m² road strip lies (the architect's answer; the outline here is "
              "the firm's finished plan)", "whether the stilt counts toward the Table IV height",
              "whether the access road ends at the plot", "whether it joins a 12 m street",
              "whose rules apply (the survey names Bhadurpalle, the answers CMC)"]


def profile_path(reading: str) -> Path:
    return PROFILES / f"dhulapally.debug.{reading.replace('_', '-')}.profile.json"


def debug_profile(reading: str) -> dict:
    from siteplan.registration import register
    from siteplan.runner import read_survey

    fit = register(read_survey(SITE_PLAN).boundary, read_survey(SURVEY).boundary)
    ring = [list(point) for point in list(fit.polygon.exterior.coords)[:-1]]
    layout = {key: {"value": value, "source": f"debug run under the '{reading}' reading of "
                    "stilt_in_rule_height"} for key, value in READINGS[reading].items()}
    return {"name": f"dhulapally-debug-{reading.replace('_', '-')}", "debug_fixture": True,
            "purpose": "Regression baseline while the strip's location is unknown: the firm's "
                       "net outline stands in as the net plot; nothing else is taken from its "
                       "plan.",
            "site": {"net_plot_m": {
                "value": ring, "status": "ASSUMED_FOR_TEST", "source_kind": "FIRM_FINISHED_PLAN",
                "source": f"the firm's site plan {SITE_PLAN.name}, outline registered onto the "
                          f"survey: {fit.describe()}"}},
            "layout": layout, "open_facts": OPEN_FACTS}


def run(reading: str, out: Path):
    from siteplan.acceptance import generate
    from siteplan.profiles import load_profile

    return generate(SURVEY, json.loads(ANSWERS.read_text()), out, WORKSPACE,
                    conservative_parking=True, profile=load_profile(profile_path(reading)),
                    mode="debug")


def summarise(generated) -> dict:
    """What the baseline pins: every height tried with its verdict and reasons, and every
    option's headline numbers."""
    found = generated.found
    return {
        "heights": [{"floors_above_stilt": r.floors, "height_m": round(r.height_m, 2),
                     "verdict": r.verdict, "reasons": list(r.reasons())} for r in found.results],
        "max_legal_floors": found.max_legal_floors,
        "max_feasible_floors": found.max_feasible_floors,
        "options": [{"strategy": o["strategy"], "floors_above_stilt": o["floors_above_stilt"],
                     "towers": o["towers"], "total_flats": o["total_flats"],
                     "saleable_sqft": o["saleable_sqft"], "tower_floor_sqft": o["tower_floor_sqft"],
                     "statuses": dict(sorted(Counter(o["rule_findings"].values()).items()))}
                    for o in generated.options],
        "rejected": sum(len(r.search.rejected) for r in found.results if r.search),
    }


def main() -> None:
    from siteplan.acceptance import compare, report
    from siteplan.cases import Case
    from siteplan.project import Project

    PROFILES.mkdir(parents=True, exist_ok=True)
    pinned = {"pinned": "2026-10-02", "readings": {}}
    for reading in READINGS:
        profile = debug_profile(reading)
        profile_path(reading).write_text(json.dumps(profile, indent=1) + "\n")
        out = BASELINE / reading
        generated = run(reading, out)
        rows = compare(generated, Case.model_validate_json(FIRM_CASE.read_text()),
                       Project.model_validate_json(FIRM_PROJECT.read_text()).area_statement
                       ) if generated.options else [("No layout passed", "-", "-")]
        (out / "acceptance.txt").write_text(report(generated, rows) + "\n")
        pinned["readings"][reading] = summarise(generated)
        pinned["registration"] = profile["site"]["net_plot_m"]["source"]
        heights = pinned["readings"][reading]["heights"]
        print(f"{reading}: {len(generated.options)} options; heights "
              f"{[(h['floors_above_stilt'], h['verdict']) for h in heights]}")
    PINNED.write_text(json.dumps(pinned, indent=1) + "\n")
    print(f"pinned {PINNED}")


if __name__ == "__main__":
    main()
