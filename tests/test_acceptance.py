"""The acceptance flow: raw survey and answers in, layouts out, the firm's plan read only after.

Made-up geometry; the real run (Dhulapally's survey against the firm's plan) is by command:
`siteplan acceptance <survey> --answers <json> --firm-case <case> --workspace <folder>`.
"""

import json
from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import box

from siteplan.acceptance import compare, generate, report, spacing, towers_in
from siteplan.cases import Case

EXAMPLES = Path(__file__).parent.parent / "examples"
ANSWERS = {"main_road": "W", "road_row": "60 ft", "road_row_source": "2", "surrender": "no",
           "authority": "HMDA", "name": "Acceptance test", "mix": "70% 2BHK, 30% 3BHK",
           "floors": "max"}


def _workspace(tmp_path) -> Path:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.modelspace().add_lwpolyline([(0, 0), (150, 0), (150, 120), (0, 120)], close=True,
                                    dxfattribs={"layer": "SITE-BOUNDARY"})
    doc.modelspace().add_text("AREA: 18000 SQ.MTS", height=2).set_placement((10, -10))
    doc.saveas(tmp_path / "survey.dxf")
    (tmp_path / "siteplan.workspace.json").write_text(json.dumps(
        {"flat_library": str(EXAMPLES / "flat_library.example.json")}))
    return tmp_path


def _firm_case() -> Case:
    """A made-up 'firm plan' for the same plot: two towers, 8 m from the line and apart."""
    towers = [box(8, 8, 58, 30), box(8, 38, 58, 60)]
    return Case(name="Made-up firm plan", evidence="firm_drawing", sources=["test"],
                net_plot=list(box(0, 0, 150, 120).exterior.coords)[:-1], open_space_sqm=1800,
                buildings=[{"name": f"T{i}", "floors": 8,
                            "outline": list(t.exterior.coords)[:-1]}
                           for i, t in enumerate(towers, 1)])


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    ws = _workspace(tmp_path_factory.mktemp("ws"))
    return generate(ws / "survey.dxf", ANSWERS, ws / "out")


def test_generation_needs_only_the_survey_the_answers_and_the_firms_libraries(generated):
    assert generated.options and generated.limit.floors_stilt_counted == 9  # a 60 ft road
    assert generated.options[0]["heights_tried"][0]["floors_above_stilt"] == 9
    assert (generated.out / "project.json").exists()


def test_the_comparison_reads_the_firms_plan_only_now_and_measures_both_the_same_way(generated):
    rows = dict((name, (ours, theirs)) for name, ours, theirs in
                compare(generated, _firm_case()))
    assert rows["Towers"][1] == "2" and rows["Least gap between towers"][1] == "8.00 m"
    assert rows["Least setback from the plot line"][1] == "8.00 m"
    ours = float(rows["Least setback from the plot line"][0].split()[0])
    assert ours >= 9.99  # 30 m of building asks 10 m (Table IV), measured off the DXF
    assert "Compared with the firm" in report(generated, compare(generated, _firm_case()))


def test_towers_are_read_back_from_the_delivered_dxf(generated):
    towers = towers_in(generated.out / "option_1.dxf")
    assert len(towers) == generated.options[0]["towers"]
    setback, gap = spacing(generated.plot, towers)
    assert setback > 0 and (gap is None or gap > 0)

