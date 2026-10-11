"""`siteplan steps`: run the steps built so far on one project and write each one's report,
picture and facts in a folder of its own, with an index that says which steps are done, which
stopped and what they need, and which come in a later stage."""

from __future__ import annotations

import json
from pathlib import Path

from siteplan.steps import (
    main_road_height_report,
    road_widening_report,
    setbacks_report,
    survey_copy_report,
    tot_lot_report,
)
from siteplan.steps.drawing import Picture
from siteplan.steps.inputs import Inputs
from siteplan.steps.main_road_height import height_for
from siteplan.steps.report import StepReport
from siteplan.steps.road_widening import take_off
from siteplan.steps.setbacks import set_back
from siteplan.steps.survey_copy import copy_survey
from siteplan.steps.tot_lot import lay_out

LATER = {  # the architect's steps not built yet, each in a later stage
    6: "Buildings, roads, parking and site works",
    7: "The final check of the whole plan",
}


def run_steps(inputs: Inputs, out: Path) -> list[StepReport]:
    copy = copy_survey(inputs)
    first = survey_copy_report.report(copy)
    _write(out / "step1", "step1", first, survey_copy_report.picture(copy),
           survey_copy_report.facts(copy))
    height = height_for(inputs, copy)
    second = main_road_height_report.report(height)
    _write(out / "step2", "step2", second,
           None if height.stopped else main_road_height_report.picture(height),
           main_road_height_report.facts(height))
    side = None if height.stopped else main_road_height_report.section(height)
    if side is not None:
        side.write(out / "step2", "step2-section")
    widening = take_off(inputs, copy)
    third = road_widening_report.report(widening)
    _write(out / "step3", "step3", third,
           None if widening.stopped else road_widening_report.picture(widening),
           road_widening_report.facts(widening))
    setbacks = set_back(inputs, copy, height, widening)
    fourth = setbacks_report.report(setbacks)
    _write(out / "step4", "step4", fourth,
           None if setbacks.stopped else setbacks_report.picture(setbacks),
           setbacks_report.facts(setbacks))
    tot_lot = lay_out(inputs, copy, setbacks)
    fifth = tot_lot_report.report(tot_lot)
    _write(out / "step5", "step5", fifth,
           None if fifth.picture is None else tot_lot_report.picture(tot_lot),
           tot_lot_report.facts(tot_lot))
    _index(out, inputs, [first, second, third, fourth, fifth])
    return [first, second, third, fourth, fifth]


def _write(folder: Path, stem: str, report: StepReport, picture: Picture | None,
           facts: dict) -> None:
    report.write(folder)
    if picture is not None:
        picture.write(folder, stem)
    (folder / f"{stem}.json").write_text(json.dumps(facts, indent=1, ensure_ascii=False) + "\n")


def _index(out: Path, inputs: Inputs, done: list[StepReport]) -> None:
    rows = {r.number: (r.title, "STOPPED: it needs an answer" if r.stopped else "done",
                       f"[report](step{r.number}/REPORT.md)") for r in done}
    rows.update({n: (title, "a later stage", "-") for n, title in LATER.items()})
    lines = [f"# The steps for {inputs.project.name}", "", f"**Site:** {inputs.site}", "",
             "Each step says what it did, what it looked at, which rules it used and where "
             "each comes from, what the engine decided by itself, and what came out.", "",
             "| Step | What it does | State | Report |", "|---|---|---|---|"]
    lines += [f"| {n} | {title} | {state} | {link} |"
              for n, (title, state, link) in sorted(rows.items())]
    questions = [(r.number, q) for r in done for q in r.questions]
    if questions:
        lines += ["", "## Questions for you, from every step", ""]
        lines += [f"{i}. (step {n}) {q}" for i, (n, q) in enumerate(questions, 1)]
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("\n".join(lines) + "\n")
