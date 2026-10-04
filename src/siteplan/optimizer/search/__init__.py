"""The full search over prototypes, heights and positions (docs/ARCHITECTURE.md, stream C2).

    from siteplan.optimizer.search import FullSearchStrategy
    optimize(site, rules, brief, [FullSearchStrategy()], envelope=envelope, prototypes=kit)

It plugs into the optimizer core through the Strategy interface, beside the legacy generator. See
strategy.py for how a run is staged; the modules beside it each hold one decision:

- readings.py: the profiles a layout is built for (every reading, or one) and the floor counts
  each leaves open;
- land.py: the setback zone, the planted strip, the roadable ground and the ground the blocks may
  stand on;
- columns.py: blocks in columns, solved exactly (prototype, floors and position of each);
- network.py: the streets, the ring road, the entrance and the fire lanes, drawn from the blocks;
- ground.py, fit.py, parking_plan.py: the club house, the ramp, the open space, the facilities and
  the cellars, on the ground the blocks and roads leave;
- build.py: a laid-out configuration as a CandidateLayout, with its ledger and rule layers;
- verdicts.py: what a validation report says a candidate rests on.
"""

from siteplan.optimizer.search.strategy import NAME, FullSearchStrategy, Limits

__all__ = ["NAME", "FullSearchStrategy", "Limits"]
