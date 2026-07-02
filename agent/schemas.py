"""Structured schemas for the property generation agent.

Two families live here. The pydantic ``BaseModel`` classes are the structured
outputs every LLM node must return: the agent proposes in these shapes and
nothing else, which keeps the deterministic compiler (``agent.codegen``) a
template fill rather than an interpreter of free text. The dataclasses are
internal records the deterministic nodes pass around (failures, run results).

The design principle (design doc section 7.1): the LLM only ever proposes one of
these constrained shapes; Hypothesis and the triage checks dispose.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Codegen (agent.codegen) renders these fields directly into executable Python:
# names become `def {name}(self):`, ids and operation_ids go into tags and
# comments. Validating them here, at the one boundary where the LLM's free text
# enters the system, is what makes the compiler a template fill and not an
# interpreter of arbitrary text. A proposal that fails validation is rejected and
# the structured output call retries, exactly as intended.
_SHORT_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_OPERATION_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
STATE_VOCAB = frozenset(
    {
        "CREATED",
        "AUTHORIZED",
        "PARTIALLY_CAPTURED",
        "CAPTURED",
        "PARTIALLY_REFUNDED",
        "REFUNDED",
        "VOIDED",
    }
)


def _check_identifier(value: str) -> str:
    if not value.isidentifier() or keyword.iskeyword(value):
        raise ValueError(f"must be a valid non keyword python identifier, got {value!r}")
    return value


def _check_short_id(value: str) -> str:
    if not _SHORT_ID.match(value):
        raise ValueError(f"must match [A-Za-z0-9_-]+, got {value!r}")
    return value

# Closed vocabularies. The agent binds each discovered operation to one payment
# effect and each discovered property to one invariant kind; the compiler owns
# the concrete enactment of every member. A wrong binding is a wrong proposal
# that Hypothesis then falsifies.
Effect = Literal["none", "authorize", "capture", "refund", "void"]
RuleKind = Literal["create_account", "create_intent", "intent_transition", "query"]
InvariantKind = Literal[
    "captured_le_authorized",
    "refunded_le_captured",
    "conservation_zero",
    "nonneg_balance",
]
# ``needs_human`` is not a judgment the LLM ever returns; it is the deterministic
# outcome of a split triage vote (agent.nodes.triage majority voting). Refine skips
# it and the report flags it prominently, so a failure the judge cannot decide
# stably escalates instead of being acted on wrongly.
Classification = Literal[
    "real_bug", "bad_rule", "bad_invariant", "bad_relation", "needs_human"
]

# The transform vocabulary the MR compiler can enact (design section 8). The agent
# binds each proposed relation to one of these; the compiler owns the concrete
# baseline/variant scenario for each. A transform the compiler does not support is
# not proposable, which keeps codegen a template fill rather than an interpreter.
TransformKind = Literal[
    "split_capture",
    "reorder_independent",
    "scale_amounts",
    "replay_request",
    "void_recreate",
    "split_refund",
]
# The fee reasoning knob (spec section 3: a flat fee on every capture). For the
# two transforms that change the capture count (split, scale) the naive
# exact_equivalence relation is FALSE and fee_adjusted is correct; for the three
# count preserving transforms both collapse to plain equivalence. The agent
# chooses; Hypothesis falsifies a wrong choice and refine flips it.
FeeHandling = Literal["exact_equivalence", "fee_adjusted"]


class EndpointSpec(BaseModel):
    """One operation parsed out of the OpenAPI document (no LLM)."""

    operation_id: str
    http_method: str
    path: str
    summary: str = ""
    description: str = ""
    body_fields: list[str] = Field(default_factory=list)

    @field_validator("operation_id")
    @classmethod
    def _valid_operation_id(cls, v: str) -> str:
        if not _OPERATION_ID.match(v):
            raise ValueError(f"operation_id must be an identifier, got {v!r}")
        return v


class Rule(BaseModel):
    """An agent proposed ``@rule()`` candidate for one endpoint."""

    operation_id: str
    name: str = Field(description="python identifier for the generated rule method")
    kind: RuleKind
    effect: Effect = Field(
        description="which payment effect this operation has on an intent"
    )
    legal_states: list[str] = Field(
        default_factory=list,
        description="intent states in which this operation succeeds; empty for "
        "operations that do not act on an existing intent",
    )
    amount_field: str | None = Field(
        default=None, description="body field carrying an integer amount, or null"
    )
    success_status: int = Field(description="HTTP status of a successful call")
    rationale: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_identifier(v)

    @field_validator("legal_states")
    @classmethod
    def _valid_states(cls, v: list[str]) -> list[str]:
        unknown = [s for s in v if s not in STATE_VOCAB]
        if unknown:
            raise ValueError(f"unknown states {unknown}; must be in {sorted(STATE_VOCAB)}")
        return v


class Invariant(BaseModel):
    """An agent proposed system wide ``@invariant()`` candidate."""

    id: str = Field(description="short id, e.g. INV-1")
    name: str = Field(description="python identifier for the generated check")
    kind: InvariantKind
    description: str = ""
    rationale: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_identifier(v)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        return _check_short_id(v)


class MetamorphicRelation(BaseModel):
    """An agent proposed cross run relation: a transform plus its expected relation.

    The compiler renders one Hypothesis ``@given`` test per relation (design
    section 8.4): generate a scenario, run a baseline, apply the transform, run a
    variant against a fresh account, assert the expected relation over final
    balances and intent states.
    """

    id: str = Field(description="short id, e.g. MR-1")
    name: str = Field(description="python identifier for the generated test")
    transform: TransformKind
    fee_handling: FeeHandling = Field(
        default="exact_equivalence",
        description="whether the two runs' balances are exactly equivalent, or "
        "differ by the transform's exact flat fee deviation term",
    )
    description: str = ""
    rationale: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_identifier(v)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        return _check_short_id(v)


class TriageVerdict(BaseModel):
    """The triage node's classification of one observed failure."""

    failure_ref: str = Field(description="the failure tag being classified")
    classification: Classification
    target: str = Field(
        default="",
        description="name/id of the rule or invariant to fix when the verdict is "
        "bad_rule or bad_invariant; empty for real_bug",
    )
    reasoning: str = ""


# -- deterministic records (not LLM outputs) --------------------------------


@dataclass(frozen=True)
class Failure:
    """One falsification captured from the compiled spec's pytest run."""

    kind: Literal["invariant", "rule", "relation"]
    proposal_id: str
    message: str
    counterexample: str = ""

    def tag(self) -> str:
        return f"{self.kind}:{self.proposal_id}"


@dataclass
class TestRunResult:
    passed: bool
    failures: list[Failure] = field(default_factory=list)
    output_tail: str = ""
    error: str = ""
