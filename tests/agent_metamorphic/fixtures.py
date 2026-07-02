"""Fixture bank for the AGENT-MR self referential suite (design section 8.6).

Each fixture is a triage input shaped exactly like real ``execute`` node output:
one or more tagged ``Failure`` records plus the proposed rules, invariants, and
relations that were in scope when the failure surfaced. Two fixtures are lifted
verbatim from real agent runs (``agent_runs/``): the dropped INV-1 precondition
over capture (a real_bug) and the MR-1 fee misroute (a real_bug). The other three
are synthetic but realistic bad_rule / bad_invariant / bad_relation cases, each
one an assumption a correct PayFlow build actually falsifies.

The two paraphrases per failure are precomputed and checked in here on purpose:
AGENT-MR-2 must not spend an extra LLM call rewording at test time. Ordering
(AGENT-MR-1) and padding (AGENT-MR-3) are mechanical and applied at test time by
``transforms.py``, no precomputation needed.

The ``expected`` label on each failure is the hand assigned ground truth used by
the verdict accuracy check; the AGENT-MR relations themselves assert only that the
verdict is *stable* under a no information transform.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.schemas import EndpointSpec, Invariant, MetamorphicRelation, Rule

# Shared proposal context (the accepted spec from agent_runs/20260701T221021Z),
# trimmed to what triage needs to reason about each failure. A real triage batch
# always sees the whole proposal set, so fixtures reference this shared context.
RULES = [
    Rule(
        operation_id="capturePaymentIntent",
        name="capture",
        kind="intent_transition",
        effect="capture",
        legal_states=["AUTHORIZED", "PARTIALLY_CAPTURED"],
        success_status=200,
        rationale="Capture is legal in AUTHORIZED and PARTIALLY_CAPTURED.",
    ),
    Rule(
        operation_id="authorizePaymentIntent",
        name="authorize",
        kind="intent_transition",
        effect="authorize",
        legal_states=["CREATED"],
        success_status=200,
        rationale="Authorize is legal only in CREATED.",
    ),
    Rule(
        operation_id="refundPaymentIntent",
        name="refund",
        kind="intent_transition",
        effect="refund",
        legal_states=["CAPTURED", "PARTIALLY_CAPTURED", "PARTIALLY_REFUNDED"],
        success_status=200,
        rationale="Refund is legal while captured funds remain.",
    ),
]

INVARIANTS = [
    Invariant(id="INV-1", name="captured_le_authorized", kind="captured_le_authorized",
              description="Captured never exceeds authorized."),
    Invariant(id="INV-2", name="refunded_le_captured", kind="refunded_le_captured",
              description="Refunded never exceeds captured."),
    Invariant(id="INV-3", name="conservation_zero", kind="conservation_zero",
              description="Per merchant, balance equals captures minus fees minus refunds."),
    Invariant(id="INV-4", name="nonneg_balance", kind="nonneg_balance",
              description="Merchant and platform-fee balances never go negative."),
]

RELATIONS = [
    MetamorphicRelation(id="MR-1", name="split_capture", transform="split_capture",
                        fee_handling="fee_adjusted",
                        description="Split one capture of N into two summing to N."),
    MetamorphicRelation(id="MR-2", name="reorder_independent", transform="reorder_independent",
                        fee_handling="exact_equivalence",
                        description="Swap the order of operations on disjoint merchants."),
    MetamorphicRelation(id="MR-3", name="scale_amounts", transform="scale_amounts",
                        fee_handling="exact_equivalence",
                        description="Scale every amount in the scenario by a constant k."),
]


@dataclass(frozen=True)
class FixtureFailure:
    """One tagged failure plus its ground truth and precomputed paraphrases."""

    kind: str  # "rule" | "invariant" | "relation"
    proposal_id: str
    message: str
    counterexample: str
    paraphrases: tuple[str, str]
    expected: str  # real_bug | bad_rule | bad_invariant | bad_relation
    sequence_shaped: bool  # True if the counterexample is a paddable step sequence

    @property
    def ref(self) -> str:
        return f"{self.kind}:{self.proposal_id}"


@dataclass(frozen=True)
class TriageFixture:
    name: str
    failures: tuple[FixtureFailure, ...]
    rules: list[Rule] = field(default_factory=lambda: list(RULES))
    invariants: list[Invariant] = field(default_factory=lambda: list(INVARIANTS))
    relations: list[MetamorphicRelation] = field(default_factory=lambda: list(RELATIONS))
    # Endpoints let triage enrichment pull an OpenAPI summary/description into the
    # advisory context. Empty for the historical fixtures (they predate enrichment);
    # the void fixture below carries the void endpoint so the whole enrichment path
    # is exercised end to end.
    endpoints: list[EndpointSpec] = field(default_factory=list)


# -- fixture 1: real over capture (real_bug), from the triage-validation run ----

_OVER_CAPTURE_CE = (
    "Falsifying example:\n"
    "E       state = PayFlowGeneratedMachine()\n"
    "E       accounts_0 = state.create_account()\n"
    "E       intents_0 = state.create_intent(account=accounts_0, amount=400)\n"
    "E       state.authorize(intent=intents_0)\n"
    "E       state.capture_over_limit_rejected(intent=intents_0)\n"
    "E       state.teardown()"
)
_OVER_CAPTURE_BODY = (
    '{"id":"pi_d502","state":"PARTIALLY_CAPTURED","authorized_amount":400,'
    '"captured_amount":401,"refunded_amount":0}'
)
CAPTURE_OVER_LIMIT = TriageFixture(
    name="capture_over_limit_real_bug",
    failures=(
        FixtureFailure(
            kind="rule",
            proposal_id="capture_over_limit",
            message=(
                f"[RULE capture_over_limit] expected 422 capturing 401 over "
                f"remaining 400, got 200: {_OVER_CAPTURE_BODY}"
            ),
            counterexample=_OVER_CAPTURE_CE,
            paraphrases=(
                f"[RULE capture_over_limit] a capture of 401 against a remaining "
                f"hold of only 400 was accepted with HTTP 200 where 422 was "
                f"expected; response body {_OVER_CAPTURE_BODY}",
                f"[RULE capture_over_limit] the API let an over-limit capture "
                f"through (401 requested, 400 remaining) returning status 200 "
                f"instead of rejecting it 422; body {_OVER_CAPTURE_BODY}",
            ),
            expected="real_bug",
            sequence_shaped=True,
        ),
    ),
)


# -- fixture 2: real MR-1 fee misroute (real_bug), from the mr-validation run ---

_MR1_CE = (
    "Falsifying example: test_split_capture(\n"
    "E           part1=31,\n"
    "E           part2=31,\n"
    "E       )"
)
MR1_FEE_MISROUTE = TriageFixture(
    name="mr1_fee_misroute_real_bug",
    failures=(
        FixtureFailure(
            kind="relation",
            proposal_id="MR-1",
            message=(
                "[MR-1] split capture: platform_fees gained 30 across two captures "
                "but expected 60 (one capture gained 30); every capture must "
                "contribute exactly one flat fee to platform_fees"
            ),
            counterexample=_MR1_CE,
            paraphrases=(
                "[MR-1] splitting a capture into two only credited platform_fees "
                "by 30, not the 60 expected (a single capture credits 30); each "
                "capture owes exactly one flat fee to platform_fees",
                "[MR-1] two captures added just 30 to platform_fees where 60 was "
                "due (30 per single capture); platform_fees is under-credited by "
                "one flat fee across the split",
            ),
            expected="real_bug",
            sequence_shaped=False,
        ),
    ),
)


# -- fixture 3: overly strict invariant a correct build falsifies (bad_invariant)

_PARTIAL_CAPTURE_CE = (
    "Falsifying example:\n"
    "E       state = PayFlowGeneratedMachine()\n"
    "E       accounts_0 = state.create_account()\n"
    "E       intents_0 = state.create_intent(account=accounts_0, amount=400)\n"
    "E       state.authorize(intent=intents_0)\n"
    "E       state.capture(intent=intents_0, amount=150)\n"
    "E       state.captured_equals_authorized()\n"
    "E       state.teardown()"
)
_PARTIAL_CAPTURE_BODY = (
    '{"id":"pi_a17c","state":"PARTIALLY_CAPTURED","authorized_amount":400,'
    '"captured_amount":150,"refunded_amount":0}'
)
PARTIAL_CAPTURE_INVARIANT = TriageFixture(
    name="partial_capture_invariant_bad_invariant",
    failures=(
        FixtureFailure(
            kind="invariant",
            proposal_id="INV-9",
            message=(
                f"[INV-9] captured_amount 150 must equal authorized_amount 400 "
                f"for a captured intent, but a partial capture left them unequal: "
                f"{_PARTIAL_CAPTURE_BODY}"
            ),
            counterexample=_PARTIAL_CAPTURE_CE,
            paraphrases=(
                f"[INV-9] a partially captured intent has captured_amount 150 "
                f"against authorized_amount 400, violating the assumption that "
                f"the two are always equal: {_PARTIAL_CAPTURE_BODY}",
                f"[INV-9] the check that captured always equals authorized failed "
                f"on a legal partial capture (150 of 400 captured): "
                f"{_PARTIAL_CAPTURE_BODY}",
            ),
            expected="bad_invariant",
            sequence_shaped=True,
        ),
    ),
    invariants=[
        *INVARIANTS,
        Invariant(
            id="INV-9",
            name="captured_equals_authorized",
            kind="captured_le_authorized",
            description="Every captured intent has captured_amount == authorized_amount "
            "(assumes captures are always for the full authorized amount).",
            rationale="Assumes no partial captures ever occur.",
        ),
    ],
)


# -- fixture 4: rule with a wrong precondition (bad_rule) ----------------------

_SECOND_CAPTURE_CE = (
    "Falsifying example:\n"
    "E       state = PayFlowGeneratedMachine()\n"
    "E       accounts_0 = state.create_account()\n"
    "E       intents_0 = state.create_intent(account=accounts_0, amount=400)\n"
    "E       state.authorize(intent=intents_0)\n"
    "E       state.capture(intent=intents_0, amount=150)\n"
    "E       state.capture_in_partially_captured_rejected(intent=intents_0)\n"
    "E       state.teardown()"
)
_SECOND_CAPTURE_BODY = (
    '{"id":"pi_bb90","state":"PARTIALLY_CAPTURED","authorized_amount":400,'
    '"captured_amount":250,"refunded_amount":0}'
)
CAPTURE_PRECONDITION_RULE = TriageFixture(
    name="capture_precondition_bad_rule",
    failures=(
        FixtureFailure(
            kind="rule",
            proposal_id="capture_in_partially_captured_rejected",
            message=(
                f"[RULE capture_in_partially_captured_rejected] expected the "
                f"capture to be rejected (409) in PARTIALLY_CAPTURED, got 200: "
                f"{_SECOND_CAPTURE_BODY}"
            ),
            counterexample=_SECOND_CAPTURE_CE,
            paraphrases=(
                f"[RULE capture_in_partially_captured_rejected] a second capture "
                f"on a PARTIALLY_CAPTURED intent was expected to fail 409 but the "
                f"API accepted it with 200: {_SECOND_CAPTURE_BODY}",
                f"[RULE capture_in_partially_captured_rejected] the rule assumed "
                f"capture is illegal once PARTIALLY_CAPTURED, yet the API allowed "
                f"the follow-on capture (status 200): {_SECOND_CAPTURE_BODY}",
            ),
            expected="bad_rule",
            sequence_shaped=True,
        ),
    ),
    rules=[
        *RULES,
        Rule(
            operation_id="capturePaymentIntent",
            name="capture_in_partially_captured_rejected",
            kind="intent_transition",
            effect="capture",
            legal_states=["AUTHORIZED"],
            success_status=200,
            rationale="Assumes capture is legal only in AUTHORIZED, so a capture "
            "in PARTIALLY_CAPTURED should be rejected.",
        ),
    ],
)


# -- fixture 5: relation with wrong fee handling (bad_relation) ----------------

_SCALE_CE = (
    "Falsifying example: test_scale_amounts(\n"
    "E           base_amount=40,\n"
    "E           k=3,\n"
    "E       )"
)
SCALE_FEE_RELATION = TriageFixture(
    name="scale_fee_relation_bad_relation",
    failures=(
        FixtureFailure(
            kind="relation",
            proposal_id="MR-3",
            message=(
                "[MR-3] scale by 3: variant merchant balance 90 != expected 30 "
                "(baseline 30, fee 30, fee_adjusted=False); scaling amounts by k "
                "was expected to scale balances by k exactly, but the flat fee is "
                "charged once per capture regardless of amount"
            ),
            counterexample=_SCALE_CE,
            paraphrases=(
                "[MR-3] with exact_equivalence, scaling every amount by 3 should "
                "have tripled the merchant balance to 30 but it landed at 90; the "
                "flat per-capture fee does not scale with the amount",
                "[MR-3] the relation assumed balances scale by k under exact "
                "equivalence (expected 30 at k=3), yet the observed 90 differs "
                "because one flat fee is charged per capture, not per unit amount",
            ),
            expected="bad_relation",
            sequence_shaped=False,
        ),
    ),
    relations=[
        MetamorphicRelation(id="MR-1", name="split_capture", transform="split_capture",
                            fee_handling="fee_adjusted",
                            description="Split one capture of N into two summing to N."),
        MetamorphicRelation(id="MR-2", name="reorder_independent",
                            transform="reorder_independent", fee_handling="exact_equivalence",
                            description="Swap the order of operations on disjoint merchants."),
        MetamorphicRelation(id="MR-3", name="scale_amounts", transform="scale_amounts",
                            fee_handling="exact_equivalence",
                            description="Scale every amount by a constant k; assumes balances "
                            "scale by k exactly (wrong: the flat fee does not scale)."),
    ],
)


ALL_FIXTURES: tuple[TriageFixture, ...] = (
    CAPTURE_OVER_LIMIT,
    MR1_FEE_MISROUTE,
    PARTIAL_CAPTURE_INVARIANT,
    CAPTURE_PRECONDITION_RULE,
    SCALE_FEE_RELATION,
)


# -- void regression fixture (bad_rule), from agent_runs/20260702T043505Z -------
#
# The 2026-07-02 bigger judge run proposed void legal only from AUTHORIZED and
# PARTIALLY_CAPTURED, dropping CREATED, which the accepted committed slice allows.
# Hypothesis falsified the derived void_illegal_state rule (void in CREATED returned
# 200, not 409) and triage then called it real_bug: a false positive against a
# correct system. The accepted slice annotation ("void is legal from CREATED per the
# accepted spec") is exactly the evidence that makes this a bad_rule. This fixture is
# deliberately NOT in ALL_FIXTURES: adding it to the parametrized pytest suite would
# change that suite's cost and findings. It is exported for tools/judge_comparison.py,
# which measures whether enrichment heals the misjudgment across candidate models.

_VOID_CREATED_CE = (
    "Falsifying example:\n"
    "E       state = PayFlowGeneratedMachine()\n"
    "E       accounts_0 = state.create_account()\n"
    "E       intents_0 = state.create_payment_intent(account=accounts_0, amount=400)\n"
    "E       state.void_illegal_state_rejected(intent=intents_0)\n"
    "E       state.teardown()"
)
_VOID_CREATED_BODY = (
    '{"id":"pi_c5e4","merchant_account_id":"acct_7528","amount":400,"state":"VOIDED",'
    '"authorized_amount":0,"captured_amount":0,"refunded_amount":0}'
)
VOID_ILLEGAL_STATE = TriageFixture(
    name="void_illegal_state_bad_rule",
    failures=(
        FixtureFailure(
            kind="rule",
            proposal_id="void_illegal_state",
            message=(
                f"[RULE void_illegal_state] expected 409 in state CREATED, got 200: "
                f"{_VOID_CREATED_BODY}"
            ),
            counterexample=_VOID_CREATED_CE,
            paraphrases=(
                f"[RULE void_illegal_state] voiding a CREATED intent was expected to "
                f"be rejected 409 but the API accepted it with 200: {_VOID_CREATED_BODY}",
                f"[RULE void_illegal_state] the rule assumed void is illegal in CREATED, "
                f"yet the API voided the CREATED intent (status 200): {_VOID_CREATED_BODY}",
            ),
            expected="bad_rule",
            sequence_shaped=True,
        ),
    ),
    rules=[
        *RULES,
        Rule(
            operation_id="voidPaymentIntent",
            name="void",
            kind="intent_transition",
            effect="void",
            legal_states=["AUTHORIZED", "PARTIALLY_CAPTURED"],
            success_status=200,
            rationale="Assumes voiding is only meaningful before full capture, so the "
            "success states are AUTHORIZED and PARTIALLY_CAPTURED (drops CREATED).",
        ),
    ],
    endpoints=[
        EndpointSpec(
            operation_id="voidPaymentIntent",
            http_method="POST",
            path="/payment_intents/{intent_id}/void",
            summary="Void a payment intent, releasing any remaining hold",
        ),
    ],
)
