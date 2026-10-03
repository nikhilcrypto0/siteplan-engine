"""The open readings of the law, as ResolvedRules carries them.

Where the orders leave a question open, the contract keeps every reading as an Interpretation.
Three are carried as ALL, so every consumer evaluates every reading and a result that holds under
only some of them is UNVERIFIED: whether the stilt counts toward the Table IV height, of which
area the open space is measured, and whether roads may run inside a setback. The others carry the
reading the engine takes for the test (ASSUMED_FOR_TEST, never evidence). A test profile picks a
reading with `selections`; that choice is recorded ASSUMED_FOR_TEST and never stronger.

constraints.py and inventory.py hold the audit of each reading; tests/test_resolve.py fails when
a reading constraints.py calls UNRESOLVED_INTERPRETATION is not carried here.
"""

from __future__ import annotations

from siteplan import rules
from siteplan.contracts.common import Basis, Provenance
from siteplan.contracts.resolved_rules import (
    ALL,
    AMENITY_SHARE,
    APPROACH_WIDTH,
    CIRCULATION_IN_SETBACK,
    FIRE_TURNING_RADIUS,
    MIXED_HEIGHT_SPACING,
    OPEN_SPACE_BASIS,
    STILT_IN_RULE_HEIGHT,
    VISITOR_PARKING,
)

# Readings beyond the eight every ResolvedRules must carry.
VISITOR_PARKING_IN_SETBACK = "visitor_parking_in_setback"
ROAD_IN_WATER_BUFFER = "road_in_water_buffer"
CELLAR_EXTRA_SETBACK = "cellar_extra_setback"
LARGE_PROJECT_AMENITY_SHARE = "large_project_amenity_share"
TABLE_IV_ROAD_WIDTH = "table_iv_road_width"  # carried only when a master-plan width is known

# The three denominators of the organised open space: ResolvedRules gives the area under each.
OPEN_SPACE_READINGS = ("gross_before_surrender", "gross_after_surrender", "net_after_surrender")


def _reading(reading_id: str, question: str, alternatives: dict[str, str], selected: str, *,
             sources: list[str], settles: str,
             basis: Basis = Basis.UNRESOLVED_INTERPRETATION) -> dict:
    status = Provenance.UNVERIFIED if selected == ALL else Provenance.ASSUMED_FOR_TEST
    return {"id": reading_id, "question": question, "alternatives": alternatives,
            "selected": selected, "basis": basis, "status": status, "sources": sources,
            "settles": settles}


def _defaults(master_plan_road: bool) -> list[dict]:
    readings = [
        _reading(
            STILT_IN_RULE_HEIGHT,
            "Does the stilt count toward the height that picks the Table IV row and the "
            "high-rise class?",
            {"counted": "the stilt counts toward the Table IV height (the stricter reading)",
             "not_counted": "the stilt does not count toward the Table IV height"},
            ALL,
            sources=["G.O.168 rule 2(e): leaves out only the parapet, staircase head room, lift "
                     "room and water tank",
                     "rule 5(c) excludes the stilt for Table III only",
                     rules.PARKING_FLOOR_HEIGHT_CLAUSE,
                     "the firm's own unsanctioned drawing keeps setbacks as if the stilt were "
                     "not counted (not evidence)"],
            settles="a sanctioned stilt + N high-rise whose approved setback or road width fits "
                    "one reading only"),
        _reading(
            OPEN_SPACE_BASIS,
            "Of which site area is the organised open space share taken?",
            {"gross_before_surrender": "the gross site area, before any land is surrendered",
             "gross_after_surrender": "the gross site area less the land surrendered",
             "net_after_surrender": "the net site area, after every ownership deduction"},
            ALL,
            sources=[f"{rules.OPEN_SPACE_CLAUSE}: 'at least 10% of total site area'",
                     "G.O.168 rule 8(g): 'Minimum of 10% of site area'",
                     "neither says whether the area is gross or net"],
            settles="a sanctioned plan's organised open space and the site area it was taken of"),
        _reading(
            CIRCULATION_IN_SETBACK,
            "May internal roads and fire lanes run inside the mandatory setback?",
            {"allowed": "roads and fire lanes may run inside the setback",
             "not_allowed": "roads and fire lanes run outside the setback"},
            ALL,
            sources=[f"{rules.RAMP_CLAUSE}: ramps 'shall not be allowed in mandatory setbacks "
                     "including building line, however they may be permitted in the side and "
                     "rear setbacks after leaving minimum 7m of setback for movement of "
                     "fire-fighting vehicles': an implication, not a permission",
                     "the firm's own unsanctioned drawing runs driveways inside its setbacks "
                     "(not evidence)"],
            settles="the architect, or a sanctioned plan whose roads run inside the setback"),
        _reading(
            FIRE_TURNING_RADIUS,
            "Where is the fire tender's turning radius measured?",
            {"outer_edge": "at the outer edge of the fire lane (the tender's turning circle)",
             "centreline": "at the lane's centreline"},
            "outer_edge",
            sources=[rules.FIRE_ACCESS_CLAUSE + ": the order gives the radius, not where it "
                     "is measured",
                     "the outer-edge reading is the one that fits the state's minimum high-rise "
                     "setback and the width rule 13(c)(vii) keeps for fire vehicles; a "
                     "centreline reading needs more"],
            settles="the fire NOC of a sanctioned high-rise, or the layout agreed with the "
                    "Chief Fire Officer"),
        _reading(
            APPROACH_WIDTH,
            "How wide is the main approach road within the range rule 8(m) gives?",
            {"minimum": "the least the rule allows (the engine draws it at this width)",
             "authority_choice": "whatever the authority asks within the range the rule gives"},
            "minimum",
            sources=[rules.INTERNAL_ROAD_CLAUSE],
            settles="the authority's practice",
            basis=Basis.ENGINE_DESIGN_ASSUMPTION),
        _reading(
            MIXED_HEIGHT_SPACING,
            "Which block's Table IV gap applies between blocks of different heights?",
            {"taller_governs": "the taller block's gap applies between the two",
             "each_own": "each block keeps its own gap"},
            "taller_governs",
            sources=[f"{rules.BLOCK_SPACING_CLAUSE}: 'the open space mentioned in Col. 4' "
                     "without saying which block sets it"],
            settles="a sanctioned plan with two blocks of different heights"),
        _reading(
            VISITOR_PARKING,
            "Where must visitors' parking be?",
            {"at_ground": "at ground level, in the stilt or on the surface",
             "anywhere": "anywhere parking is"},
            "at_ground",
            sources=[f"{rules.VISITOR_PARKING_CLAUSE}: 'properly demarcated on ground'"],
            settles="the visitors' parking on a sanctioned plan: marked in the stilt or only in "
                    "the open"),
        _reading(
            AMENITY_SHARE,
            "Is the amenities share of the built-up area a minimum, or an upper figure with a "
            "cap?",
            {"minimum_3_percent": "at least the share, the 2012 wording kept as the planning "
                                  "minimum",
             "up_to_3_percent_or_cap": "up to the share or the capped area, whichever is "
                                       "lower (the 2016 wording)"},
            "minimum_3_percent",
            sources=[rules.AMENITY_CLAUSE],
            settles="the amenities area on a sanctioned plan of 100 units or more, against its "
                    "built-up area, or the architect's reading of the 2016 wording"),
        _reading(
            VISITOR_PARKING_IN_SETBACK,
            "May visitors' parking use a side or rear setback?",
            {"not_used": "no bay stands in a setback (rule 13(b) puts Table V parking over and "
                         "above the setbacks, and NBC 4.6(c) keeps the compulsory open space "
                         "round a high-rise free of parking)",
             "side_and_rear": "visitors' parking may use a side or rear setback wider than the "
                              "rule names, the green strip left out, never the front setback "
                              "and never where setback was transferred"},
            "not_used",
            sources=[f"{rules.VISITOR_PARKING_CLAUSE}: visitors' parking 'may be accommodated "
                     "in the mandatory setbacks other than front setback where ever such "
                     "setbacks are more than 6m (excluding green strip)'",
                     f"{rules.FIRE_ACCESS_CLAUSE}: 'The compulsory open spaces around the "
                     "building shall not be used for parking'"],
            settles="a sanctioned high-rise plan with visitors' bays in a side or rear setback, "
                    "or the fire department's reading"),
        _reading(
            ROAD_IN_WATER_BUFFER,
            "May a road or fire lane run inside a water body's buffer?",
            {"allowed": "a road is not a building, and the text bars only building activity in "
                        "the buffer",
             "not_allowed": "the buffer is kept as a green zone: nothing motorable in it"},
            "not_allowed",
            sources=[f"{rules.WATER_BUFFER_CLAUSE}: 'no building activity shall be carried out "
                     "within' the buffer",
                     "as read in the 2012 text, rule 3(a)(iii)(1) lets the buffer of a river or "
                     "a lake of 10 ha or more carry a road of 12 m where feasible; it says "
                     "nothing of a nala"],
            settles="a sanctioned plan with a road or fire lane inside a water buffer, or the "
                    "word of HMDA or the irrigation department"),
        _reading(
            CELLAR_EXTRA_SETBACK,
            "Does the extra cellar setback for every cellar beyond the first apply to every "
            "cellar level, or only to the deeper ones?",
            {"all_levels": "every level keeps the deepest cellar's setback (the cellars are "
                           "one box: the stricter reading)",
             "deeper_levels_only": "each deeper level keeps its own larger setback and the "
                                   "first keeps the base figure"},
            "all_levels",
            sources=[f"{rules.CELLAR_SETBACK_CLAUSE}: 'additional setback for every additional "
                     "cellar floor' fixes the amounts, not which floors keep them"],
            settles="the cellar section on a sanctioned plan with two or more cellars"),
        _reading(
            LARGE_PROJECT_AMENITY_SHARE,
            "Does the share of the site area for common amenities in a project above a set "
            "size, written for row and cluster housing, also bind a group development scheme?",
            {"not_applied": "no: rule 8 has no such clause, and a group scheme's amenities are "
                            "rule 15(a)(x)'s share of the built-up area",
             "applied": "yes: the authority holds every very large project to it"},
            "not_applied",
            sources=[rules.LARGE_PROJECT_AMENITY_CLAUSE],
            settles="the authority's practice on a sanctioned group scheme above the size"),
    ]
    if master_plan_road:
        readings.append(_reading(
            TABLE_IV_ROAD_WIDTH,
            "Which width of the access road does Table IV read when the master plan widens it?",
            {"existing": "the road as it stands (Table II is headed 'minimum abutting existing "
                         "road width')",
             "master_plan": "the master-plan width, counted once its strip is surrendered"},
            ALL,
            sources=[rules.ROAD_WIDENING_CLAUSE],
            settles="an approval letter on a road due for widening: which width did it use?"))
    return readings


def interpretations(*, master_plan_road: bool = False,
                    selections: dict[str, str] | None = None) -> list[dict]:
    """Every open reading, as Interpretation fields. `selections` maps a reading's id to the
    reading a test profile takes (or ALL): recorded ASSUMED_FOR_TEST, and refused when the id or
    the reading is not one this site carries."""
    readings = _defaults(master_plan_road)
    known = {r["id"]: r for r in readings}
    for reading_id, chosen in (selections or {}).items():
        if reading_id not in known:
            raise ValueError(f"selections: no open reading '{reading_id}' "
                             f"(known: {', '.join(known)})")
        reading = known[reading_id]
        if chosen != ALL and chosen not in reading["alternatives"]:
            raise ValueError(f"selections: '{chosen}' is not a reading of {reading_id} "
                             f"(readings: {', '.join(reading['alternatives'])}, or {ALL})")
        reading["selected"] = chosen
        reading["status"] = Provenance.UNVERIFIED if chosen == ALL else (
            Provenance.ASSUMED_FOR_TEST)
        reading["sources"] = [*reading["sources"], "selected by a test profile"]
    return readings
