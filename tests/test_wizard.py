"""Starting a project by answering questions, for someone who will never edit JSON."""

import pytest

from siteplan.project import Project
from siteplan.wizard import QUESTIONS, build_project, collect, parse_length, parse_mix

GOOD = {
    "name": "Kompally towers",
    "client": "A builder",
    "architect": "",
    "road": "40 ft",
    "master_road": "60 ft",
    "authority": "hmda",
    "floors": "8",
    "mix": "70% 2BHK, 30% 3BHK",
    "floor_height": "3",
    "stilt_height": "3",
    "common_area": "22",
}


@pytest.mark.parametrize(("text", "expected"), [
    ("70% 2BHK, 30% 3BHK", {"2BHK": 0.7, "3BHK": 0.3}),
    ("2BHK 70, 3BHK 30", {"2BHK": 0.7, "3BHK": 0.3}),
    ("50% 2 BHK and 50% 3 BHK", {"2BHK": 0.5, "3BHK": 0.5}),
    ("100% 3BHK", {"3BHK": 1.0}),
])
def test_a_mix_can_be_written_the_way_people_say_it(text, expected):
    assert parse_mix(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["70% 2BHK, 20% 3BHK", "mostly 2BHK", ""])
def test_a_mix_that_does_not_add_up_is_refused(text):
    with pytest.raises(ValueError):
        parse_mix(text)


@pytest.mark.parametrize(("text", "unit", "value"), [
    ("40 ft", "ft", 40.0), ("40", "ft", 40.0), ("12 m", "m", 12.0), ("18.5 metres", "m", 18.5),
])
def test_a_road_width_can_be_feet_or_metres(text, unit, value):
    assert parse_length(text) == (unit, value)


def test_the_answers_become_a_file_the_tool_can_read():
    project = Project.model_validate(build_project(GOOD))
    assert project.name == "Kompally towers"
    assert project.site.abutting_road_ft == 40 and project.site.master_plan_road_ft == 60
    assert project.site.authority == "HMDA"
    assert project.layout.floors == 8
    assert project.layout.unit_mix == pytest.approx({"2BHK": 0.7, "3BHK": 0.3})
    assert project.sheet.client == "A builder"


def test_what_was_skipped_is_left_out_rather_than_invented():
    answers = GOOD | {"client": "", "architect": "", "master_road": ""}
    built = build_project(answers)
    assert "sheet" not in built
    assert "master_plan_road_ft" not in built["site"]


def test_a_wrong_answer_is_asked_again_with_the_reason():
    replies = iter(["Kompally towers", "", "", "wide-ish", "40 ft", "", "HMDA",
                    "eight", "8", "70% 2BHK, 30% 3BHK", "3", "3", "22"])
    said: list[str] = []
    answers = collect(lambda prompt: next(replies), said.append)
    assert answers["road"] == "40 ft" and answers["floors"] == "8"
    assert any("40 ft" in line for line in said)        # the road question explained itself
    assert any("number" in line for line in said)       # so did the floors question


def test_a_required_answer_is_not_skippable():
    replies = iter(["", "Kompally towers", "", "", "40 ft", "", "HMDA", "8",
                    "70% 2BHK, 30% 3BHK", "3", "3", "22"])
    said: list[str] = []
    answers = collect(lambda prompt: next(replies), said.append)
    assert answers["name"] == "Kompally towers"
    assert any("needed" in line for line in said)


def test_pressing_enter_takes_the_default():
    replies = iter(["Kompally towers", "", "", "40 ft", "", "", "8", "", "", "", ""])
    answers = collect(lambda prompt: next(replies), lambda line: None)
    assert answers["authority"] == "HMDA"
    assert answers["mix"] == "70% 2BHK, 30% 3BHK"
    assert answers["common_area"] == "22"


def test_every_question_a_person_must_answer_carries_an_example():
    for question in QUESTIONS:
        if not question.optional and not question.default:
            assert question.example, f"{question.key} has no example to show"
