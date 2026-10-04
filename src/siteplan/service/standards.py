"""The firm's standards a run is planned and judged with, and where each one comes from.

A standard is the firm's choice, never law (constraints.py classifies each one FIRM_STANDARD):
the stilt and floor heights, the common-area loading, the parking standards (a cellar storey's
height, the share of each cellar kept for utilities, the deepest the search digs), the longest
block, and the flat and amenity libraries. Each is taken

1. from the project file the architect approved (made through the intake flow, in the
   workspace), when the file states it, unless the file records it as the engine's default;
2. else from the workspace's siteplan.workspace.json, when the firm's file sets it;
3. else from the engine's default, labelled ASSUMED_FOR_TEST.

That is the legacy path's precedence: `siteplan layout` lays a project out from its own layout
section, which intake fills from the workspace, so for a project made through the intake flow both
pipelines plan with the same values. They part only once the firm sets in its workspace a
standard the project file leaves out or records as the engine's default: that value only stood
in until the firm set one, so the service takes the firm's, where `siteplan layout` keeps the
engine's. The libraries have no place in a project file: they are the workspace's, as the legacy
path finds them beside the project. The design margins are the workspace's too
(adapters.design_margins), as before.

Every standard reaches the DesignBrief with source kind FIRM_STANDARD (the engine's default
standing in for the firm's until the firm sets one, as constraints.py has it), its status, and a
source naming the project file, the workspace file or the engine's default. No request carries a
standard, so a caller never sets or overrides one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import ValidationError

from siteplan.adapters.legacy_site import kind_of
from siteplan.contracts import TowerPrototype
from siteplan.contracts.common import Provenance, SourceKind
from siteplan.intake import WORKSPACE_FILE, WorkspaceDefaults
from siteplan.project import Project
from siteplan.service.models import Fact, ServiceError

# As the project's layout section names them; intake writes each from the workspace.
LAYOUT = ("stilt_height_m", "floor_height_m", "common_area_pct", "cellar_floor_height_m",
          "cellar_utilities_pct", "max_cellars", "max_tower_length_m")
LIBRARIES = ("flat_library", "amenities")  # the workspace's only
KEYS = (*LAYOUT, *LIBRARIES)


class Origin(StrEnum):
    PROJECT = "the project file"
    WORKSPACE = "the workspace"
    ENGINE_DEFAULT = "the engine's default"


@dataclass(frozen=True)
class Standard:
    key: str
    value: float | int | str | None
    origin: Origin
    status: Provenance
    source: str

    def fact(self) -> Fact:
        return Fact(name=f"firm standard: {self.key}", value=self.value, status=self.status,
                    source_kind=SourceKind.FIRM_STANDARD, source=self.source)

    def line(self) -> str:
        """As the architect is shown it before a run."""
        value = "not set" if self.value is None else f"{self.value:g}" if isinstance(
            self.value, float) else str(self.value)
        return f"Firm standard {self.key}: {value} [{self.status}], from {self.source}"


def resolve(project: Project, defaults: WorkspaceDefaults, project_file: str
            ) -> tuple[Standard, ...]:
    """Every standard, from the project file, else the workspace, else the engine's default."""
    stated = project.layout.model_fields_set if project.layout is not None else set()
    found = []
    for key in KEYS:
        if key in stated and kind_of(project, key) is not SourceKind.ENGINE_DEFAULT:
            recorded = project.sources.get(key)
            found.append(Standard(
                key, getattr(project.layout, key), Origin.PROJECT,
                project.status.get(key, Provenance.USER_CONFIRMED),
                f"the project file {project_file}" + (f" ({recorded})" if recorded else "")))
        elif key in defaults.model_fields_set:
            found.append(Standard(key, getattr(defaults, key), Origin.WORKSPACE,
                                  defaults.standard_status(key),
                                  f"the workspace's {WORKSPACE_FILE}"))
        else:
            found.append(Standard(key, getattr(defaults, key), Origin.ENGINE_DEFAULT,
                                  Provenance.ASSUMED_FOR_TEST,
                                  f"the engine's default ({WORKSPACE_FILE} does not set it)"))
    return tuple(found)


def apply(project: Project, standards: Sequence[Standard]) -> Project:
    """The project with each standard in its layout section and its source, status and source
    kind beside it, where adapters.brief reads them into the DesignBrief."""
    if project.layout is None:
        return project
    values = {s.key: s.value for s in standards if s.key in LAYOUT}
    try:
        layout = type(project.layout).model_validate(
            {**project.layout.model_dump(exclude_unset=True), **values})
    except ValidationError as error:
        fields = sorted({str(e["loc"][0]) for e in error.errors() if e["loc"]})
        raise ServiceError(f"The firm's standards are not valid ({', '.join(fields)}).") \
            from None
    sources, status = dict(project.sources), dict(project.status)
    kinds = dict(project.source_kinds)
    for s in standards:
        sources[s.key], status[s.key], kinds[s.key] = s.source, s.status, SourceKind.FIRM_STANDARD
    return project.model_copy(update={"layout": layout, "sources": sources, "status": status,
                                      "source_kinds": kinds})


def within_longest_block(kit: Sequence[TowerPrototype], longest_m: float | None, source: str
                         ) -> tuple[list[TowerPrototype], list[str]]:
    """The prototypes no longer than the firm's longest block, and each one left out, with why.
    A block's length is the longer side of its footprint, as the validator measures it, so no
    tower the search places from what is kept can be longer than the firm's block."""
    if longest_m is None:
        return list(kit), []
    kept, left_out = [], []
    for prototype in kit:
        long_side = max(prototype.length_m, prototype.depth_m)
        if long_side <= longest_m:
            kept.append(prototype)
        else:
            left_out.append(f"Prototype {prototype.id} left out: {long_side:g} m long, over the "
                            f"firm's longest block of {longest_m:g} m, from {source}")
    return kept, left_out
