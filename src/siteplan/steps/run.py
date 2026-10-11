"""`siteplan steps`: run the steps built so far on one project and write each one's report,
picture and facts in a folder of its own, with an index that says which steps are done, which
stopped and what they need, and which come in a later stage."""

from __future__ import annotations

import json
from pathlib import Path

from siteplan.steps import road_widening_report, survey_copy_report
from siteplan.steps.drawing import Picture
from siteplan.steps.inputs import Inputs
from siteplan.steps.report import StepReport
from siteplan.steps.road_widening import take_off
from siteplan.steps.survey_copy import copy_survey

LATER = {  # the architect's steps not built yet, each in a later stage
    2: "The main road and the height it allows",
    4: "Setbacks from every side",
    5: "The open space (tot-lot)",
    6: "Buildings, roads, parking and site works",
    7: "The final check of the whole plan",
}


def run_steps(inputs: Inputs, out: Path) -> list[StepReport]:
    copy = copy_survey(inputs)
    first = survey_copy_report.report(copy)
    _write(out / "step1", "step1", first, survey_copy_report.picture(copy),
           survey_copy_report.facts(copy))
    widening = take_off(inputs, copy)
    third = road_widening_report.report(widening)
    _write(out / "step3", "step3", third,
           None if widening.stopped else road_widening_report.picture(widening),
           road_widening_report.facts(widening))
    _index(out, inputs, [first, third])
    return [first, third]


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
