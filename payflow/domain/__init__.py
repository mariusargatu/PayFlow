"""Domain layer: state machine, preconditions, fee logic, idempotency orchestration.

Owns the determinism seams (clock, id generator) and is the only path through
which the API reaches persistence.
"""
