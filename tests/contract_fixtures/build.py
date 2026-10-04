"""Build the contract fixtures: an instance of every contract for each of four made-up plots.

    uv run python tests/contract_fixtures/build.py

The candidates come from the prototype generator through the adapters; the small plot's is made
by hand, because the generator does not lay out a site under 4,000 m². The validation reports
restate the generator's own findings and say so in validator_version: they show the contract's
shape, not an independent verdict (that is the validator's work, stream D).
"""

from __future__ import annotations

import sys
from pathlib import Path

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from siteplan import rules
from siteplan.adapters import Readings, brief, candidate_from_option, request, site_model
from siteplan.contracts import CandidateLayout, TowerPrototype, ValidationReport
from siteplan.contracts.common import Finding, Line, Shape, Status, digest, shapes_from
from siteplan.contracts.validation import (
    Check,
    Family,
    legal_verdict,
    program_verdict,
)
from siteplan.layout import mix_error, solve
from siteplan.library import FlatLibrary
from siteplan.project import Project
from siteplan.units import M_PER_FT, sqm_to_sqft

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from contract_fixtures.rules_and_envelope import envelope, resolved_rules  # noqa: E402

LIBRARY = FlatLibrary(
    flats=[{"name": "2A", "bhk": "2BHK", "width_m": 10.0, "depth_m": 11.0, "saleable_sqft": 1190},
           {"name": "3A", "bhk": "3BHK", "width_m": 13.5, "depth_m": 11.0,
            "saleable_sqft": 1690}],
    core_width_m=7.5)
NALA = LineString([(75, -5), (75, 125)])
L_PLOT = Polygon([(0, 0), (150, 0), (150, 100), (24, 100), (24, 160), (0, 160)])
SITES = {
    # A surrendered strip along the south road: gross 15,450 m², net 15,000 m².
    "rectangle": {"boundary": box(0, -3, 150, 100), "net": box(0, 0, 150, 100),
                  "strip": box(0, -3, 150, 0), "side": "S", "road_ft": 60, "dead_end": False,
                  "join": True, "floors": 8},
    "l_plot_with_arm": {"boundary": L_PLOT, "net": L_PLOT, "side": "S", "road_ft": 60,
                        "dead_end": None, "join": None, "floors": 8},
    "nala_plot": {"boundary": box(0, 0, 150, 120), "net": box(0, 0, 150, 120), "side": "W",
                  "road_ft": 60, "dead_end": False, "join": None, "floors": 8, "water": NALA},
    "small_plot": {"boundary": box(0, 0, 60, 50), "net": box(0, 0, 60, 50), "side": "S",
                   "road_ft": 40, "dead_end": None, "join": None, "floors": 5},
}
FIXTURE_VALIDATOR = ("fixture: the generator's own findings restated, not an independent "
                     "validation")


def _ring(polygon: Polygon) -> list[tuple[float, float]]:
    return [(x, y) for x, y in list(polygon.exterior.coords)[:-1]]


def project(name: str, spec: dict) -> Project:
    site = {"gross_area_sqm": spec["boundary"].area, "net_area_sqm": spec["net"].area,
            "net_plot_m": _ring(spec["net"]), "abutting_road_ft": spec["road_ft"],
            "abutting_road_status": "DECLARED_ON_SITE_PLAN", "access_side": spec["side"],
            "road_dead_end": spec["dead_end"], "street_joins_12m": spec["join"],
            "authority": "HMDA", "inside_cure": False}
    if "strip" in spec:
        site["road_strip_m"] = _ring(spec["strip"])
    if "water" in spec:
        site["water"] = [{"kind": "nala_over_10m", "survey_colour": "#00FFFF"}]
    answer, unknown = "architect: made-up fixture", "architect: unknown"
    sources = {"gross_area_sqm": "survey: made-up fixture", "net_area_sqm": answer,
               "net_plot_m": answer, "abutting_road": answer, "access_side": "survey: road 1",
               "authority": answer, "inside_cure": answer, "water": answer,
               "road_dead_end": unknown if spec["dead_end"] is None else answer,
               "street_joins_12m": unknown if spec["join"] is None else answer}
    status = {key: "USER_CONFIRMED" for key in sources} | {
        "gross_area_sqm": "EXTRACTED", "access_side": "EXTRACTED"} | {
        key: "UNVERIFIED" for key, text in sources.items() if text == unknown}
    return Project.model_validate({
        "name": f"Made-up {name.replace('_', ' ')}", "site": site, "sources": sources,
        "status": status,
        "layout": {"floors": spec["floors"], "unit_mix": {"2BHK": 0.7, "3BHK": 0.3}}})


def build(name: str, spec: dict) -> dict:
    p = project(name, spec)
    site = site_model(p, site_id=name, boundary=spec["boundary"])
    if "water" in spec:
        site.water[0].lines = [Line(points=list(spec["water"].coords))]
    design, readings = brief(p), Readings.of(p.layout)
    rules_ = resolved_rules(site)
    env = envelope(site, rules_)
    refs = {"site_ref": digest(site), "rules_ref": digest(rules_), "brief_ref": digest(design)}
    if name == "small_plot":
        candidate = _small_candidate(spec, refs, readings)
    else:
        zone = spec["water"].buffer(9.0) if "water" in spec else None
        option = solve(spec["net"], LIBRARY, request(design, readings),
                       abutting_road_m=spec["road_ft"] * M_PER_FT, keep_out=zone,
                       access_side=spec["side"], authority="HMDA", inside_cure=False,
                       gross_area_sqm=spec["boundary"].area)[0]
        candidate = candidate_from_option(option, spec["net"], candidate_id=f"{name}-1",
                                          readings=readings.selections,
                                          access_side=spec["side"], keep_out=zone, **refs)
    candidate.envelope_ref = digest(env)
    return {"CanonicalSiteModel": site, "DesignBrief": design, "ResolvedRules": rules_,
            "BuildableEnvelope": env, "TowerPrototype": candidate.prototypes_used[0],
            "CandidateLayout": candidate, "PartitionLedger": candidate.partition,
            "RuleLayers": env.rule_layers,
            "ValidationReport": report(candidate, spec["net"], design.program.unit_mix.value,
                                       digest(env))}


def single_core_prototype() -> TowerPrototype:
    """Four flats round one core: 2BHK and 3BHK either side of a corridor."""
    depth, corridor = 11.0, 2.13
    half = depth + corridor / 2
    x = [-15.5, -5.5, 2.0, 15.5]  # 2BHK, the 7.5 m core, 3BHK along the block
    flats = [(box(x[0], corridor / 2, x[1], half), "2A", "2BHK", 1190),
             (box(x[2], corridor / 2, x[3], half), "3A", "3BHK", 1690),
             (box(x[0], -half, x[1], -corridor / 2), "2A", "2BHK", 1190),
             (box(x[2], -half, x[3], -corridor / 2), "3A", "3BHK", 1690)]
    footprint, core_zone = box(x[0], -half, x[3], half), box(x[1], -half, x[2], half)
    own = sum(f.area for f, *_ in flats)
    corridor_shape = footprint.difference(core_zone).difference(
        unary_union([f for f, *_ in flats]))
    return TowerPrototype(
        id="single-core-small-4", family="SINGLE_CORE_SMALL", source_kind="ENGINE_DEFAULT",
        source="made-up contract fixture", footprint=Shape.from_shapely(footprint),
        length_m=x[3] - x[0], depth_m=2 * half, cores=1,
        modules=[{"id": f"m{i}", "type_id": t, "category": c, "shape": Shape.from_shapely(f),
                  "saleable_sqft": s} for i, (f, t, c, s) in enumerate(flats, 1)],
        core_zones=[{"shape": Shape.from_shapely(core_zone), "lifts": 2, "stairs": 1}],
        corridor=shapes_from(corridor_shape),
        per_floor={"flats": 4, "flats_by_type": {"2BHK": 2, "3BHK": 2},
                   "gross_floor_sqm": footprint.area, "flats_own_sqm": own,
                   "common_core_sqm": footprint.area - own, "saleable_sqft": 2 * (1190 + 1690)},
        heights={})


def _small_candidate(spec: dict, refs: dict, readings: Readings) -> CandidateLayout:
    """A block of 5 floors on 3,000 m², laid to Table III (row 11 up to 15 m: 6 m on the sides,
    the 3 m Building Line of its 12 m road in front): the open space between the block and the
    north setback, and the 1 m strip round the plot broken only where the driveway comes in."""
    proto, strip_m, net = single_core_prototype(), rules.NON_HIGH_RISE_FRONTAGE_STRIP_M, spec["net"]
    floors, (cx, cy) = spec["floors"], (30.0, 25.0)
    footprint = box(cx - 15.5, cy - 12.065, cx + 15.5, cy + 12.065)
    driveway, gate = box(25, 0, 29.5, cy - 12.065), box(25, 0, 29.5, strip_m)
    pocket = box(6, 37.5, 54, 44)  # 312 m²: clear of the 6 m setback, the block and the road
    strip = net.difference(net.buffer(-strip_m)).difference(driveway)
    rest = net.difference(unary_union([footprint, driveway, pocket, strip]))
    by_type = {k: n * floors for k, n in proto.per_floor.flats_by_type.items()}
    gross = proto.per_floor.gross_floor_sqm * floors
    return CandidateLayout(
        candidate_id="small_plot-1", strategy="hand-made", **refs,
        interpretation_basis=readings.selections, prototypes_used=[proto],
        towers=[{"name": "T1", "prototype_id": proto.id, "x": cx, "y": cy,
                 "floors_above_stilt": floors, "footprint": Shape.from_shapely(footprint)}],
        circulation={"roads": [{"id": "road-1", "kind": "DRIVEWAY",
                                "shapes": [Shape.from_shapely(driveway)],
                                "declared_width_m": 4.5}],
                     "gates": [{"shape": Shape.from_shapely(gate), "side": "S", "width_m": 4.5}]},
        program={"open_space": [Shape.from_shapely(pocket)], "green_strip": shapes_from(strip)},
        partition={"net_area_sqm": spec["net"].area, "entries": [
            {"use": "TOWER", "shapes": [Shape.from_shapely(footprint)],
             "area_sqm": footprint.area, "ref": "T1"},
            {"use": "ROAD", "shapes": [Shape.from_shapely(driveway)], "area_sqm": driveway.area,
             "ref": "road-1"},
            {"use": "SOFT_OPEN_SPACE", "shapes": [Shape.from_shapely(pocket)],
             "area_sqm": pocket.area, "ref": "tot-lot 1"},
            {"use": "GREEN_STRIP", "shapes": shapes_from(strip), "area_sqm": strip.area,
             "ref": "green strip"},
            {"use": "UNALLOCATED", "shapes": shapes_from(rest), "area_sqm": rest.area,
             "reason": "made-up fixture: ground left without a use"}]},
        rule_layers={"layers": []},
        metrics={"total_flats": sum(by_type.values()), "flats_by_type": by_type,
                 "saleable_sqft": proto.per_floor.saleable_sqft * floors,
                 "tower_floor_sqft": round(sqm_to_sqft(gross)),
                 "flats_own_sqft": round(sqm_to_sqft(proto.per_floor.flats_own_sqm * floors)),
                 "common_core_sqft": round(sqm_to_sqft(proto.per_floor.common_core_sqm * floors)),
                 "built_up_sqft": round(sqm_to_sqft(gross)), "open_space_sqm": pocket.area,
                 "open_space_share_pct": round(pocket.area / spec["net"].area * 100, 2),
                 "mix_error": mix_error(proto.per_floor.flats_by_type, {"2BHK": 0.7,
                                                                        "3BHK": 0.3})},
        generator_claims=[Finding("Setbacks (Table III)", Status.PASS, "12.9 m least",
                                  ">= 6 m on the sides, >= 3 m in front", rules.TABLE_III_CLAUSE,
                                  "row 11 up to 15 m, read above the stilt")],
        caveats=["made-up fixture: a non-high-rise block on a site under 4,000 m²"])


FAMILY_WORDS = ((Family.SETBACK, ("setback",)), (Family.SPACING, ("gap between",)),
                (Family.FIRE, ("fire",)), (Family.ROADS, ("road", "driveway")),
                (Family.HEIGHT, ("height", "high-rise", "plot size")),
                (Family.OPEN_SPACE, ("open space", "open-space", "tot-lot")),
                (Family.PARKING, ("parking", "cellar", "ramp")),
                (Family.AMENITIES, ("amenit", "club")), (Family.WATER, ("water",)),
                (Family.GREEN_STRIP, ("green strip",)), (Family.EGRESS, ("egress",)))


def _family(rule: str) -> Family:
    text = rule.lower()
    return next((family for family, words in FAMILY_WORDS if any(w in text for w in words)),
                Family.OTHER)


def report(candidate: CandidateLayout, net: Polygon, mix: dict[str, float],
           envelope_ref: str) -> ValidationReport:
    legal = [Check(family=_family(f.rule), finding=f) for f in candidate.generator_claims]
    error = candidate.metrics.mix_error
    program = [Check(family=Family.PROGRAM, finding=Finding(
        "Unit mix", Status.PASS if error <= 0.05 else Status.FAIL, f"mix error {error:.3f}",
        f"within 0.05 of {mix}", "the brief"))]
    problems = candidate.partition.problems(Shape.from_shapely(net))
    return ValidationReport(
        candidate_ref=digest(candidate), site_ref=candidate.site_ref,
        rules_ref=candidate.rules_ref, brief_ref=candidate.brief_ref, envelope_ref=envelope_ref,
        validator_version=FIXTURE_VALIDATOR, legal=legal, program=program,
        accounting={"partition": candidate.partition, "partition_problems": problems,
                    "rule_layers": candidate.rule_layers},
        not_checked=[c.finding.rule for c in legal if c.finding.status is Status.NOT_CHECKED],
        verdict={"legal": legal_verdict(legal, []), "program": program_verdict(program),
                 "reasons": [f"{c.finding.rule}: {c.finding.status}" for c in legal
                             if c.finding.status in (Status.FAIL, Status.UNVERIFIED)]})


def main() -> None:
    for name, spec in SITES.items():
        folder = HERE / name
        folder.mkdir(exist_ok=True)
        for contract, instance in build(name, spec).items():
            (folder / f"{contract}.json").write_text(instance.model_dump_json(indent=1) + "\n")
        print(f"{name}: written to {folder}")


if __name__ == "__main__":
    main()
