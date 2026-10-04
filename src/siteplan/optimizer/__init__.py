"""The optimizer core (docs/ARCHITECTURE.md, stream C1).

    strategies --propose--> candidates --guard (validator)--> scored --Pareto--> alternatives

- floors.py: which floor counts the law leaves open to a tower, from metres and the firm's floor
  heights, under every reading of the stilt; the whole set, never only the most.
- interfaces.py: the Strategy and Validator protocols, the search context (site, rules, brief,
  envelope, prototypes, seed, budget) and the time budget every strategy keeps to.
- objective.py and pareto.py: what a candidate is worth, the Pareto front, and the three
  alternatives (maximum yield, balanced, conventional with open space) that are different ideas.
- guard.py: a candidate whose legal verdict is FAIL is never returned, whatever its score. The
  verdict is stream D's independent validator's (`siteplan.validator`), the default in `optimize`.
- legacy.py: today's generator as one strategy. The full search over prototypes and positions
  (stream C2) is another, plugged in through the same interface.
- core.py: `optimize`, which runs them in that order.
"""

from siteplan.optimizer.core import Alternative, OptimizerResult, optimize
from siteplan.optimizer.floors import (
    FloorOption,
    LimitCheck,
    assess_floor_count,
    assess_floors,
    feasible_floors,
    floors_by_reading,
)
from siteplan.optimizer.guard import Rejection
from siteplan.optimizer.interfaces import (
    Budget,
    Proposal,
    SearchContext,
    Strategy,
    Validator,
)
from siteplan.optimizer.legacy import LegacyRun, LegacyStrategy

__all__ = ["Alternative", "Budget", "FloorOption", "LegacyRun",
           "LegacyStrategy", "LimitCheck", "OptimizerResult", "Proposal", "Rejection",
           "SearchContext", "Strategy", "Validator", "assess_floor_count", "assess_floors",
           "feasible_floors", "floors_by_reading", "optimize"]
