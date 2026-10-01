"""Temporary, site-specific assumptions for a test run, kept apart from the rules.

While a site's facts wait on the architect, a profile sets chosen project values for that one
site so the work can go on: a road width measured off a drawing, a reading of the stilt, roads
allowed inside the setback. It changes nothing general. A value it sets lands in that run's
project with its source and its status (ASSUMED_FOR_TEST unless the profile says otherwise),
and the report lists every one; nothing in it reaches rules.py, constraints.py or a workspace
default. When the answers come, the profile is edited or dropped and the run repeated, with no
change to the code.

A profile names a real site, so it is client data: it lives in gitignored fixtures/.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from siteplan.layout import LayoutRequest
from siteplan.project import Project, SiteIn
from siteplan.provenance import Provenance

# The project keys a site value is tracked under in `sources` and `status`.
STATUS_KEY = {"abutting_road_m": "abutting_road", "abutting_road_ft": "abutting_road",
              "abutting_road_status": "abutting_road"}
# The same quantity in another unit: set one, and the other is dropped so they cannot disagree.
PAIRED = {"abutting_road_m": "abutting_road_ft", "abutting_road_ft": "abutting_road_m",
          "master_plan_road_m": "master_plan_road_ft",
          "master_plan_road_ft": "master_plan_road_m",
          "net_area_sqm": "net_area_sqyd", "net_area_sqyd": "net_area_sqm"}


class ProfileValue(BaseModel):
    value: Any
    source: str = Field(description="Where the value comes from, e.g. 'measured from the DXF'")
    status: Provenance = Provenance.ASSUMED_FOR_TEST
    note: str = ""


class AssumptionProfile(BaseModel):
    """One site's temporary assumptions. Keys are the project's own field names."""

    name: str
    purpose: str
    site: dict[str, ProfileValue] = {}
    layout: dict[str, ProfileValue] = {}
    open_facts: list[str] = Field(
        default_factory=list, description="Facts kept UNVERIFIED and reported, never set")
    debug_fixture: bool = Field(
        False, description="The survey given is a finished plan's outline, so the run is a "
        "debug or test-fixture run, not blind acceptance")

    @model_validator(mode="after")
    def _known_fields(self) -> AssumptionProfile:
        for section, values, model in (("site", self.site, SiteIn),
                                       ("layout", self.layout, LayoutRequest)):
            unknown = sorted(set(values) - set(model.model_fields))
            if unknown:
                raise ValueError(f"profile {section} has no field(s) {unknown}")
        return self


def load_profile(path: str | Path) -> AssumptionProfile:
    return AssumptionProfile.model_validate(json.loads(Path(path).read_text()))


def apply_profile(project: dict, profile: AssumptionProfile) -> dict:
    """The project with the profile's values set, each one's source and status recorded. It is
    validated whole, so a profile that makes the project inconsistent is refused."""
    out = copy.deepcopy(project)
    out.setdefault("layout", {})
    for section, values in (("site", profile.site), ("layout", profile.layout)):
        for key, item in values.items():
            out[section][key] = item.value
            out[section].pop(PAIRED.get(key, ""), None)
            tracked = STATUS_KEY.get(key, key)
            out["sources"][tracked] = f"test profile '{profile.name}': {item.source}"
            out["status"][tracked] = item.status
    Project.model_validate(out)
    return out


def describe(profile: AssumptionProfile) -> list[str]:
    """The profile as report lines: every value it set, and every fact it leaves open."""
    lines = [f"  Profile '{profile.name}': {profile.purpose}"]
    if profile.debug_fixture:
        lines.append("  DEBUG / TEST-FIXTURE RUN: the plot outline comes from a finished plan, "
                     "so this is not blind acceptance.")
    for section, values in (("site", profile.site), ("layout", profile.layout)):
        for key, item in values.items():
            note = f" {item.note}" if item.note else ""
            lines.append(f"  - {section}.{key} = {item.value!r} [{item.status}] "
                         f"{item.source}.{note}")
    lines += [f"  - kept UNVERIFIED: {fact}" for fact in profile.open_facts]
    return lines
