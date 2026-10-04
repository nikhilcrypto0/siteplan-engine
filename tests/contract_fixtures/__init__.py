"""Contract fixtures on made-up land (see build.py): one JSON instance of every contract for each
of four plots, so every stream can start against the contracts with the same data."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from siteplan.contracts import ALL_CONTRACTS

HERE = Path(__file__).parent
SITES = ("rectangle", "l_plot_with_arm", "nala_plot", "small_plot")


def load(site: str, contract: str) -> BaseModel:
    """One fixture, validated against its contract."""
    return ALL_CONTRACTS[contract].model_validate_json((HERE / site / f"{contract}.json")
                                                        .read_text())
