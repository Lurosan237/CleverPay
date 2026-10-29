"""A mobile money simulator with Cameroon-style usage and fraud scenarios.

PaySim cannot support behavioural fraud detection: 99.85% of its senders appear only
once, and its fraudsters always drain the whole balance. This simulator models a
population that transacts repeatedly over weeks, with documented local scams in a
naive and an adaptive version. See docs/simulator.md for the design and sources.
"""
