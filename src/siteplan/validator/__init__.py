"""The independent validator (docs/ARCHITECTURE.md, section 6, "D Validator").

    from siteplan.validator import validate
    report = validate(site, rules, brief, candidate, envelope=None)

It imports no generator module (tests/test_validator_independence.py enforces it): the geometry
it measures with is built here, so an error in the generator's geometry cannot pass silently.
"""

from siteplan.validator.report import VALIDATOR_VERSION
from siteplan.validator.validate import validate

__all__ = ["VALIDATOR_VERSION", "validate"]
