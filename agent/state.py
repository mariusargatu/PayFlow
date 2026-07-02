"""The ``AgentState`` graph channel schema (design doc section 7.2).

``proposed_rules`` carries an ``operator.add`` reducer so the ``Send`` fan out
over endpoints (design section 7.5) can append from parallel branches without
clobbering. Everything else is last write wins.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from .schemas import (
    EndpointSpec,
    Invariant,
    MetamorphicRelation,
    Rule,
    TestRunResult,
    TriageVerdict,
)


class AgentState(TypedDict, total=False):
    # Input
    openapi_spec: dict
    sut_base_url: str
    run_dir: str
    current_endpoint: EndpointSpec

    # Understanding phase
    endpoints: list[EndpointSpec]
    proposed_rules: Annotated[list[Rule], operator.add]
    proposed_invariants: list[Invariant]
    proposed_relations: list[MetamorphicRelation]

    # Generation phase
    generated_spec_code: str
    generated_spec_path: str
    generated_mr_code: str
    generated_mr_path: str

    # Execution phase
    hypothesis_results: TestRunResult
    mutation_score: float | None

    # Feedback phase
    triaged_failures: list[TriageVerdict]
    iteration: int
    max_iterations: int

    # Bookkeeping
    aborted: bool
    abort_reason: str
    history: Annotated[list[str], operator.add]
