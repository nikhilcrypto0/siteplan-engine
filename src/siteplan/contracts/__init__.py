"""The permanent contracts between pipeline stages (docs/ARCHITECTURE.md).

raw survey -> CanonicalSiteModel -> ResolvedRules -> BuildableEnvelope -> TowerPrototype
-> CandidateLayout -> ValidationReport, with DesignBrief carrying the architect's program and
PartitionLedger / RuleLayers the two kinds of area accounting. The code here is authoritative;
docs/contracts/*.schema.json is generated from it (`siteplan schema`).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from siteplan.contracts.accounting import (
    OwnershipReconciliation,
    PartitionLedger,
    RuleLayers,
)
from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.common import CONTRACTS_VERSION, digest
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.envelope import BuildableEnvelope
from siteplan.contracts.prototype import TowerPrototype
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.contracts.validation import ValidationReport

ALL_CONTRACTS: dict[str, type[BaseModel]] = {
    "CanonicalSiteModel": CanonicalSiteModel,
    "DesignBrief": DesignBrief,
    "ResolvedRules": ResolvedRules,
    "BuildableEnvelope": BuildableEnvelope,
    "TowerPrototype": TowerPrototype,
    "CandidateLayout": CandidateLayout,
    "ValidationReport": ValidationReport,
    "PartitionLedger": PartitionLedger,
    "RuleLayers": RuleLayers,
}

__all__ = ["ALL_CONTRACTS", "CONTRACTS_VERSION", "BuildableEnvelope", "CandidateLayout",
           "CanonicalSiteModel", "DesignBrief", "OwnershipReconciliation", "PartitionLedger",
           "ResolvedRules", "RuleLayers", "TowerPrototype", "ValidationReport", "digest",
           "export_schemas", "schema_text"]


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def export_schemas(folder: str | Path) -> list[Path]:
    """Write every contract's JSON Schema into the folder; returns the files written."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in ALL_CONTRACTS.items():
        path = folder / f"{name}.schema.json"
        path.write_text(schema_text(model))
        written.append(path)
    return written
