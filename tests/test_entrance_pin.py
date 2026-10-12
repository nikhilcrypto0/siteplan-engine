"""The pinned entrance (2026-10-12): where the survey or the architect fixes the gate, that stretch
of the net plot's edge is the only access zone, so no layout moves the entrance to suit itself;
where nothing is pinned, every stretch facing the access side stays open, as before. Found on
Dhulapally, where the search slid the gate 48 to 57 m along a 213 m west side away from the
survey's GATE on the main road. Made-up plots only."""

TEST_CLASS = "normative"

from legal_fixtures import make_site  # noqa: E402
from shapely.geometry import LineString, box  # noqa: E402

from siteplan.adapters import legacy_site  # noqa: E402
from siteplan.contracts.common import digest  # noqa: E402
from siteplan.contracts.site_model import CanonicalSiteModel  # noqa: E402
from siteplan.legal.envelope import envelope  # noqa: E402
from siteplan.legal.resolve import resolve  # noqa: E402

NET = box(0, 0, 150, 100)
GATE = [(0.0, 40.0), (0.0, 54.0)]  # 14 m of the west side
SOUTH_GATE = [(120.0, 0.0), (134.0, 0.0)]  # 14 m of a 200 m south side, off its middle
ON_STRETCH_M = 1e-6  # the gate touches the pinned stretch itself
GATE_DEPTH_M = 2.0  # and lies within the depth a gate is drawn to beside it


def _pinned(site: CanonicalSiteModel) -> CanonicalSiteModel:
    gate = {"value": {"points": GATE}, "status": "USER_CONFIRMED", "source_kind": "ARCHITECT",
            "source": "the survey's GATE on the main road"}
    dumped = site.model_dump()
    return CanonicalSiteModel.model_validate({**dumped, "access": {**dumped["access"],
                                                                   "gate": gate}})


def test_a_pinned_gate_is_the_only_access_zone():
    site = make_site(NET, side="W")
    open_zones = envelope(site, resolve(site)).circulation.access_zones
    assert sum(z.length_m for z in open_zones) == 100  # the whole west side, as before
    pinned = _pinned(site)
    zone, = envelope(pinned, resolve(pinned)).circulation.access_zones
    assert LineString(zone.frontage.points).equals(LineString(GATE))
    assert zone.length_m == 14 and "the survey's GATE" in zone.note


def test_a_site_model_without_a_gate_is_stored_as_before():
    site = make_site(NET, side="W")
    assert "gate" not in site.model_dump()["access"]
    assert digest(site) == digest(CanonicalSiteModel.model_validate(site.model_dump()))
    stored = _pinned(site).model_dump(mode="json")["access"]["gate"]
    assert stored["value"]["points"] == [list(p) for p in GATE]


def test_the_project_carries_the_gate_to_the_site_model_and_back():
    from siteplan.project import Project

    site = _pinned(make_site(NET, side="W"))
    fields, sources, status, _ = legacy_site._site_fields(site)
    project = Project.model_validate({"name": "Made-up", "site": {
        "abutting_road_m": 18.0, "access_side": "W", "gate_m": GATE,
        "net_plot_m": [list(p) for p in NET.exterior.coords[:-1]]},
        "sources": {"gate_m": "the survey's GATE on the main road"},
        "status": {"gate_m": "USER_CONFIRMED"}})
    back = legacy_site.site_model(project, site_id="made-up", boundary=NET)
    assert back.access.gate.value.points == site.access.gate.value.points
    assert back.access.gate.source == "the survey's GATE on the main road"
    assert fields["gate_m"] == [list(p) for p in GATE] and status["gate_m"] == "USER_CONFIRMED"
    assert sources["gate_m"] == "the survey's GATE on the main road"


def test_the_full_search_keeps_every_layouts_gate_on_the_pinned_stretch():
    """The quick search on a made-up 200 x 120 m plot whose 60 ft road runs along the south side,
    with the gate pinned to 14 m of it off the middle: every layout proposed comes in there (left
    to itself the search takes the middle, x 96 to 105)."""
    from search_support import Made, made_up, strategy

    made = made_up(box(0, 0, 200, 120))
    site = _pinned_to(made.site, SOUTH_GATE)
    rules = resolve(site)
    proposal = strategy().propose(Made(site, rules, made.brief, envelope(site, rules),
                                       made.kit).context())
    assert proposal.candidates
    stretch = LineString(SOUTH_GATE)
    for candidate in proposal.candidates:
        gate, = candidate.circulation.gates
        shape = gate.shape.to_shapely()
        assert shape.distance(stretch) <= ON_STRETCH_M, candidate.candidate_id
        assert stretch.buffer(GATE_DEPTH_M).contains(shape), candidate.candidate_id


def _pinned_to(site: CanonicalSiteModel, points) -> CanonicalSiteModel:
    dumped = site.model_dump()
    gate = {"value": {"points": points}, "status": "USER_CONFIRMED", "source_kind": "ARCHITECT",
            "source": "made-up pinned gate"}
    return CanonicalSiteModel.model_validate({**dumped, "access": {**dumped["access"],
                                                                   "gate": gate}})
