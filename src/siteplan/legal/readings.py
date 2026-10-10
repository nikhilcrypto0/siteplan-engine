"""The open readings of the law, as ResolvedRules carries them.

Where the orders leave a question open, the contract keeps every reading as an Interpretation.
Seven are carried as ALL, so every consumer evaluates every reading and a result that holds under
only some of them is UNVERIFIED: whether the stilt counts toward the Table IV height, of which
area the open space is measured, whether roads may run inside a setback, whether a tot-lot must
be soft to count as open space, what the rule's "etc." takes in, whether NBC's 15 m high-rise line
reaches a block the state calls non-high-rise, and whether a block that only touches a road opens
onto it. The others carry the
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
    COVERED_PARKING,
    FIRE_TURNING_RADIUS,
    MIXED_HEIGHT_SPACING,
    NBC_FIRE_HEIGHT,
    OPEN_SPACE_BASIS,
    OPEN_SPACE_OTHER_USES,
    OPENS_ONTO_ROAD,
    PLINTH,
    STILT_IN_RULE_HEIGHT,
    STILT_RAISE,
    TOT_LOT_SURFACE,
    VISITOR_PARKING,
)

# Readings beyond the ten every ResolvedRules must carry.
VISITOR_PARKING_IN_SETBACK = "visitor_parking_in_setback"
ROAD_IN_WATER_BUFFER = "road_in_water_buffer"
CELLAR_EXTRA_SETBACK = "cellar_extra_setback"
TABLE_IV_ROAD_WIDTH = "table_iv_road_width"  # carried only when a master-plan width is known
NAMED_USES = "'greenery, tot lot or soft landscaping, etc.'"

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
                     f"{rules.TABLE_III_STILT_CLAUSE}: Table III's height is read without the "
                     "stilt, which is the text and not this reading",
                     "rule 5's heading (p.9) calls the buildings below the class 'below 18m in "
                     "height inclusive of Stilt / Parking Floor': it leans to counting the stilt "
                     "for the class",
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
            STILT_RAISE,
            "How far above the ground a height is measured from does a parking stilt's floor "
            "stand?",
            {COVERED_PARKING: f"{rules.COVERED_PARKING_RAISE_M:g} m: a parking stilt is the "
                              "covered parking of NBC Part 3 12.1.2",
             PLINTH: f"{rules.PLINTH_MIN_M:g} m: it is part of the building, on 12.1.1's plinth"},
            COVERED_PARKING,
            sources=[rules.COVERED_PARKING_RAISE_CLAUSE + ": its heading names covered parking, "
                     "its sentence only interior courtyards", rules.PLINTH_CLAUSE],
            settles="a sanctioned stilt + N plan's section showing the stilt floor's level against "
                    "the ground the authority measured from"),
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
                     "without saying which block sets it",
                     f"{rules.GROUP_SCHEME_SPACING_CLAUSE}: for a block below 21 m beside a "
                     "high-rise, Column 10 of Table III or Column 4 of Table IV 'as the case may "
                     "be', and not which",
                     f"{rules.NON_HIGH_RISE_SPACING_CLAUSE}: two blocks below 21 m are not open "
                     "(the tallest block's side setback), so this reading is for a pair with a "
                     "high-rise in it"],
            settles="a sanctioned plan with two blocks of different heights, one a high-rise"),
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
            TOT_LOT_SURFACE,
            "Must a tot-lot stand on soft ground to count as organised open space?",
            {"any_surface": "a tot-lot counts whatever its surface: the rule names the tot-lot "
                            "and does not say what it is laid on",
             "soft_only": "a tot-lot counts only on soft ground"},
            ALL,
            sources=[f"{rules.OPEN_SPACE_CLAUSE}: {NAMED_USES}"],
            settles="a sanctioned plan whose counted tot-lot is paved, or the authority's "
                    "reading"),
        _reading(
            OPEN_SPACE_OTHER_USES,
            "Does the rule's 'etc.' take in open recreation other than the uses it names?",
            {"same_kind_only": "only greenery, a tot-lot and soft landscaping count",
             "any_open_recreation": "any recreation open to the sky counts too (a court, a "
                                    "pool, a paved deck)"},
            ALL,
            sources=[f"{rules.OPEN_SPACE_CLAUSE}: {NAMED_USES}"],
            settles="the organised open space a sanctioned plan's area statement counts"),
        _reading(
            NBC_FIRE_HEIGHT,
            "Is a block of 15 to 21 m that the state calls non-high-rise one of NBC 4.6's 'high "
            "rise buildings'?",
            {"state_line": "no: 4.6 reaches a block below the state's high-rise height only as a "
                           "special building (over a large or deep cellar)",
             "nbc_line": "yes: through rule 15(a)(i) 4.6 reaches every block of NBC's own 15 m "
                         "or more, measured as NBC measures it, the stilt included"},
            ALL,
            sources=[f"{rules.NBC_HIGH_RISE_CLAUSE}: 'A building 15 m or above in height "
                     "(irrespective of its occupancy)'",
                     f"{rules.HIGH_RISE_CLAUSE}: the state's own line",
                     f"{rules.NON_HIGH_RISE_NBC_CLAUSE}: the Code's requirements other than "
                     "heights and setbacks; whether NBC's definition of a high-rise is one of "
                     "its 'heights' is what is open"],
            settles="the fire NOC of a sanctioned 15 to 21 m block that is not over a large "
                    "cellar, or the fire department's written reading"),
        _reading(
            OPENS_ONTO_ROAD,
            "When does a block 'open onto' an internal road: when any part touches one, or only "
            "when a stretch of it as wide as a pathway faces one?",
            {"touch": "any part of the block within half a metre of the road",
             "frontage": "an unbroken stretch of the block's outline at least rule 8(l)'s "
                         "pathway width long faces the road; a corner that only touches it does "
                         "not open onto it"},
            ALL,
            sources=[f"{rules.PATHWAY_CLAUSE}: 'access through pathways of 6m width "
                     "branching out from the internal roads' for blocks up to 12 m, so a taller "
                     "block takes its access from a road, with no figure for how much of it "
                     "must face the road",
                     "the access a lower block may have is a 6 m pathway: the frontage reading "
                     "asks no less of a road"],
            settles="a sanctioned plan with a block that only touches a road at a corner, or "
                    "the authority's reading of rule 8(l) and (m)"),
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
