"""Semantic mutation explorer: Layer 3's informational companion (ADR-0007).

mutmut stays the mechanical, deterministic, gated kill rate. This module explores
*semantic* mutants (realistic domain bugs that a syntactic operator cannot express)
and reports which the agent discovered suite misses. It has ZERO authority: it does
not gate, does not touch mutation/baseline.json, does not feed discovery. A survivor
is a candidate gap for a human to confirm against the frozen spec, not a proven bug.
"""
