"""What kind of fact a number is: law, the firm's choice, the engine's choice, an open reading of
the law, or a fact about the site (constraints.py classifies every number generation uses).

It lives on its own so the contracts can carry it without importing the generation modules
that constraints.py reads its values from.
"""

from __future__ import annotations

from enum import StrEnum


class Basis(StrEnum):
    LEGAL_RULE = "LEGAL_RULE"
    FIRM_STANDARD = "FIRM_STANDARD"
    ENGINE_DESIGN_ASSUMPTION = "ENGINE_DESIGN_ASSUMPTION"
    UNRESOLVED_INTERPRETATION = "UNRESOLVED_INTERPRETATION"
    SITE_INPUT = "SITE_INPUT"
