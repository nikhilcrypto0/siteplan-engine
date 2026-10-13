"""What the engine does not check, each with its clause and the reason (2026-10-13).

The engine generates and checks site layouts. Some requirements in force are outside that scope,
and a report must say so rather than let a layout read as fully compliant. Three kinds:

- OUT_OF_SCOPE: building services the architectural firm designs and places by hand (the
  architect, 2026-10-13). The engine places nothing for them and reserves no land.
- CONDITION: an obligation attached to a permission (a fee in TDR, an authority, a certificate):
  not a layout question, but reported where it applies, never dropped.
- SITE_FACT: checkable only once a fact about the site is given (a road's surface, the site's
  location); reported as such until then.

Each entry is listed in the rule inventory (`siteplan inventory`) as not modelled, with its kind
and the reason. A figure in a clause is part of the clause's words: no number here is used by any
check.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    OUT_OF_SCOPE = "outside automated scope"
    CONDITION = "condition of the permission"
    SITE_FACT = "needs a site fact"


@dataclass(frozen=True)
class Requirement:
    id: str
    name: str
    clause: str
    kind: Kind
    why: str


FIRM = ("designed and placed by the architectural firm (the architect, 2026-10-13); no land "
        "reserved")

NOT_CHECKED: tuple[Requirement, ...] = (
    Requirement(
        "stp_solid_waste", "Sewage treatment plant and solid-waste collection and disposal",
        "G.O.Ms.No.135 of 2017, rule 15(c) (commercial, industrial and residential building "
        "constructions over 10,000 Sq. Mts area and above: an STP and a complete system for "
        "municipal solid waste; applicable to pending applications)",
        Kind.OUT_OF_SCOPE, FIRM),
    Requirement(
        "services_plan", "Services and utilities plan and landscaping plan of a group scheme",
        "G.O.168 rule 8(e) (water supply, drainage and storm water, sewerage, rainwater "
        "harvesting and other utilities; landscaping with rainwater harvesting and recycling)",
        Kind.OUT_OF_SCOPE, FIRM),
    Requirement(
        "ev_charging", "Electric vehicle charging in parking places",
        "G.O.Ms.No.49 of 2023, rule 15(f) (parking places provided with EV charging "
        "infrastructure as per the CEA and Ministry of Power standards)",
        Kind.OUT_OF_SCOPE, FIRM),
    Requirement(
        "dual_piping", "Dual piping",
        "G.O.Ms.No.49 of 2023, rule 15(g) (constructions over 10,000 Sq.mt and group housing of "
        "100 units and above: potable water for drinking, cooking and bathing only)",
        Kind.OUT_OF_SCOPE, FIRM),
    Requirement(
        "digital_infrastructure", "Space for broadband and telecom infrastructure",
        "G.O.Ms.No.49 of 2023, rule 15(h) (sections within buildings and on rooftops for digital "
        "connectivity, with power)",
        Kind.OUT_OF_SCOPE, FIRM),
    Requirement(
        "tdr_loading", "TDR loaded on the built-up area above the 10th floor",
        "G.O.Ms.No.16 of 2026, rule 17(f)(xii), as substituted by G.O.Ms.No.95 of 2026 "
        "(high-rise buildings above 10 floors: 3% of the built-up area above 10 floors loaded "
        "with TDR, above 20 floors 5%; half at permission, half before occupancy; Core Urban "
        "Region, applications received on or after publication)",
        Kind.CONDITION, "a TDR the owner submits with the permission, not a layout question; "
        "whether it applies depends on the floors counted, the site being in CURE and the date "
        "of the application"),
    Requirement(
        "sanctioning_authority", "Which authority grants the permission",
        "G.O.Ms.No.45 of 2026 (in the Core Urban Region, GHMC permits buildings up to 10 floors, "
        "HMDA those above; applications in process stay with the authority they went to)",
        Kind.CONDITION, "a procedure, not a layout question"),
    Requirement(
        "fire_noc", "Prior No Objection Certificate from the Fire Services Department",
        "G.O.168 rule 7(a)(vi) (every high-rise)",
        Kind.CONDITION, "a certificate, not a drawing; the fire access the layout must give is "
                        "checked (NBC 2016 Part 3 4.6)"),
    Requirement(
        "approach_road_surface", "The approach road black-topped or cement concrete",
        "G.O.168 rule 4(g), added by G.O.Ms.No.50 of 2019 (other than individual residential "
        "buildings: the approach road BT/CC, formed by the applicant before the occupancy "
        "certificate if it is not); rule 8(b) (a group scheme's abutting road existing and "
        "black-topped)",
        Kind.SITE_FACT, "a survey does not show a road's surface; its width is checked"),
    Requirement(
        "no_high_rise_areas", "Areas where no high-rise is permitted",
        "G.O.168 rule 7(a)(i), Annexures I and II (village settlement areas; within 1 km of "
        "defence airports and establishments)",
        Kind.SITE_FACT, "needs the site's location, which the project does not hold"),
    Requirement(
        "defence_clearance", "Defence establishments near the site",
        "G.O.168 rule 3(f) as substituted by G.O.Ms.No.7 of 2016 (no NOC insisted; the applicant "
        "follows the defence authorities' rules)",
        Kind.SITE_FACT, "needs the site's location, which the project does not hold"),
)


def scope_statement() -> str:
    """What a PASS covers: the layout checks the validator runs, never the requirements above."""
    return ("Within the declared scope only: the site layout (heights, setbacks, spacing, roads, "
            "fire access, open space, club house, parking, land). Not checked: "
            + "; ".join(r.name for r in NOT_CHECKED) + ".")


__all__ = ["Kind", "NOT_CHECKED", "Requirement", "scope_statement"]
