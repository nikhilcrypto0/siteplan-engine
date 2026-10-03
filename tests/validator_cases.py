"""A case (a real scheme described from a firm's drawing: its plot and its buildings, nothing
else) as the validator's inputs, so the validator can be held to the same known FAILs as
`siteplan cases`. A case draws no roads, no open space, no bays, no cellars: only buildings.

Each building becomes a one-module prototype (the validator needs a prototype's footprint and
heights, not its flats) placed where it stands. The rules are the contract fixtures' resolver
for this site; the stilt is read as counting by default, as `siteplan cases` reads it.
"""

from __future__ import annotations

import re

from contract_fixtures.rules_and_envelope import resolved_rules
from shapely import affinity
from shapely.geometry import Polygon
from validator_helpers import Inputs, fixture, select

from siteplan.cases import Case, CaseBuilding
from siteplan.contracts import CandidateLayout, CanonicalSiteModel, TowerPrototype, digest
from siteplan.contracts.accounting import DeductionKind, LocationHow
from siteplan.contracts.common import Provenance, Shape, SourceKind
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT

CASE_KIND = SourceKind.FIRM_FINISHED_PLAN  # never blind input


def _sourced(value, status=Provenance.EXTRACTED):
    return {"value": value, "status": status, "source_kind": CASE_KIND,
            "source": "a case traced from the firm's drawing"}


def site_of(case: Case) -> CanonicalSiteModel:
    plot = Polygon(case.net_plot)
    net = plot.area  # the outline is what the case traced; net_area_sqm is the statement's
    gross = case.gross_area_sqm or net
    deductions = []
    if gross - net > 1.0:
        deductions.append({"kind": DeductionKind.SURRENDER, "purpose": "road widening",
                           "area_sqm": _sourced(gross - net),
                           "location": {"how": LocationHow.UNKNOWN}})
    road = {"id": 1, "drawn_width_m": case.measured_carriageway_m,
            "row_status": case.abutting_road_status}
    if case.abutting_road_m is not None:
        road["legal_row_m"] = _sourced(case.abutting_road_m)
    if case.master_plan_road_m is not None:
        road["master_plan_row_m"] = _sourced(case.master_plan_road_m)
    unknown = _sourced(None, Provenance.UNVERIFIED)
    return CanonicalSiteModel(
        site_id=re.sub(r"[^a-z0-9]+", "-", case.name.lower()).strip("-"), name=case.name,
        ownership={"gross_sqm": _sourced(gross), "deductions": deductions,
                   "net_sqm": _sourced(net)},
        net_plot=_sourced(Shape.from_shapely(plot)), roads=[road],
        access={"road_id": _sourced(1), "side": unknown, "dead_end": unknown,
                "joins_12m_street": unknown},
        jurisdiction={"authority": _sourced(case.authority, Provenance.USER_CONFIRMED
                                            if case.authority else Provenance.UNVERIFIED),
                      "inside_cure": _sourced(case.inside_cure, Provenance.USER_CONFIRMED
                                              if case.inside_cure is not None
                                              else Provenance.UNVERIFIED)})


def _prototype(b: CaseBuilding, prototype_id: str) -> tuple[TowerPrototype, Polygon]:
    outline = Polygon(b.outline)
    centre = outline.centroid
    local = affinity.translate(outline, -centre.x, -centre.y)
    stilt = b.stilt_height_m if b.stilt_height_m is not None else 3.0
    per_floor = (b.height_m - stilt) / b.floors if b.height_m is not None else b.floor_height_m
    shape = Shape.from_shapely(local)
    long_side = max(local.bounds[2] - local.bounds[0], local.bounds[3] - local.bounds[1])
    return TowerPrototype(
        id=prototype_id, family="LEGACY_RECTANGLE", source_kind=CASE_KIND,
        source="a case traced from the firm's drawing", footprint=shape, length_m=long_side,
        depth_m=local.area / long_side, cores=0,
        modules=[{"id": f"{prototype_id}-1", "type_id": "case", "category": "2BHK",
                  "shape": shape, "saleable_sqft": 1.0}],
        per_floor={"flats": 1, "flats_by_type": {"2BHK": 1}, "gross_floor_sqm": local.area,
                   "flats_own_sqm": local.area, "common_core_sqm": 0.0, "saleable_sqft": 1.0},
        heights={"stilt_height_m": stilt, "floor_to_floor_m": per_floor}), outline


def inputs_of(case: Case, stilt_reading: str | None = "counted") -> Inputs:
    """The validator's inputs for a case; `stilt_reading` None leaves the stilt open (ALL)."""
    site = site_of(case)
    rules = resolved_rules(site)
    if stilt_reading is not None:
        select(rules, STILT_IN_RULE_HEIGHT, stilt_reading)
    brief = fixture("rectangle").brief.model_copy(update={"project_name": case.name})
    prototypes, towers = [], []
    for i, b in enumerate(case.buildings, 1):
        prototype, outline = _prototype(b, f"case-{i}")
        centre = outline.centroid
        prototypes.append(prototype)
        towers.append({"name": b.name, "prototype_id": prototype.id, "x": centre.x,
                       "y": centre.y, "floors_above_stilt": b.floors,
                       "footprint": Shape.from_shapely(outline)})
    candidate = CandidateLayout(
        candidate_id=f"{site.site_id}-case", site_ref=digest(site), rules_ref=digest(rules),
        brief_ref=digest(brief), strategy="case: buildings only", prototypes_used=prototypes,
        towers=towers, caveats=["Only the buildings are drawn: nothing else is known."])
    return Inputs(site, rules, brief, candidate, None)


def made_up_case(setback_of_stilt_6_block: float = 7.0) -> Case:
    """A plot 200 x 60 m with four stilt + 8 blocks (27 m) and one stilt + 6 (21 m), drawn like
    a firm that keeps 8 m round and between its tall blocks and 7 m round its low one."""
    def block(name, floors, x0, y0, x1, y1):
        return {"name": name, "floors": floors, "stilt_height_m": 3, "floor_height_m": 3,
                "outline": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]}

    low = setback_of_stilt_6_block
    return Case(
        name="Made up", evidence="firm_drawing", sources=["made up for the test"], authority="CMC",
        inside_cure=True, abutting_road_m=18.288, net_plot=[(0, 0), (200, 0), (200, 60), (0, 60)],
        buildings=[block("Tower 1", 8, 8, 8, 48, 26), block("Tower 2", 8, 56, 8, 96, 26),
                   block("Tower 3", 8, 104, 8, 144, 26), block("Tower 4", 8, 152, 8, 192, 26),
                   block("Tower 5", 6, low, 60 - low - 19, low + 40, 60 - low)])
