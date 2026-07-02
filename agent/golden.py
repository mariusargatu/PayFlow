"""A known correct proposal set, used only for the offline pipeline path.

``agent-run --offline`` swaps every LLM node for these fixed proposals. That
path exists so the deterministic half of the pipeline (codegen, execute, report)
and the graph drift gate can be exercised with zero token spend, for tests and
for local iteration. The real run discovers this same shape from
``/openapi.json`` with no hardcoded knowledge; this file is the compiler's
fixture, never a substitute for discovery in a scored run.
"""

from __future__ import annotations

from .schemas import Invariant, MetamorphicRelation, Rule

GOLDEN_RULES: list[Rule] = [
    Rule(
        operation_id="createAccount",
        name="create_account",
        kind="create_account",
        effect="none",
        legal_states=[],
        amount_field=None,
        success_status=201,
        rationale="creates a merchant account",
    ),
    Rule(
        operation_id="createPaymentIntent",
        name="create_intent",
        kind="create_intent",
        effect="none",
        legal_states=[],
        amount_field="amount",
        success_status=201,
        rationale="creates an intent in CREATED",
    ),
    Rule(
        operation_id="authorizePaymentIntent",
        name="authorize",
        kind="intent_transition",
        effect="authorize",
        legal_states=["CREATED"],
        amount_field=None,
        success_status=200,
        rationale="places the hold; CREATED -> AUTHORIZED",
    ),
    Rule(
        operation_id="capturePaymentIntent",
        name="capture",
        kind="intent_transition",
        effect="capture",
        legal_states=["AUTHORIZED", "PARTIALLY_CAPTURED"],
        amount_field="amount",
        success_status=200,
        rationale="captures all or part of the hold",
    ),
    Rule(
        operation_id="refundPaymentIntent",
        name="refund",
        kind="intent_transition",
        effect="refund",
        legal_states=["CAPTURED", "PARTIALLY_REFUNDED"],
        amount_field="amount",
        success_status=200,
        rationale="refunds all or part of captured funds",
    ),
    Rule(
        operation_id="voidPaymentIntent",
        name="void",
        kind="intent_transition",
        effect="void",
        legal_states=["CREATED", "AUTHORIZED", "PARTIALLY_CAPTURED"],
        amount_field=None,
        success_status=200,
        rationale="voids and releases any remaining hold",
    ),
]

GOLDEN_INVARIANTS: list[Invariant] = [
    Invariant(
        id="INV-1",
        name="inv1_captured_le_authorized",
        kind="captured_le_authorized",
        description="captured_amount <= authorized_amount at all times",
    ),
    Invariant(
        id="INV-2",
        name="inv2_refunded_le_captured",
        kind="refunded_le_captured",
        description="refunded_amount <= captured_amount at all times",
    ),
    Invariant(
        id="INV-4",
        name="inv4_conservation_zero",
        kind="conservation_zero",
        description="all account balances sum to zero (double entry conservation)",
    ),
    Invariant(
        id="INV-3",
        name="inv3_nonneg_balance",
        kind="nonneg_balance",
        description="merchant, holds and platform_fees balances never go negative",
    ),
]

# The correct relations, for the offline pipeline path only. split_capture is
# fee_adjusted: it adds a capture and so exactly one extra flat fee on platform_fees
# (the merchant keeps the full amount either way, ADR-0005). scale_amounts and the
# three count preserving transforms are exact_equivalence: scaling amounts does not
# change the capture count, so the flat fee is unchanged and the merchant scales
# cleanly. The real run discovers these; refine flips a wrong fee_handling guess.
GOLDEN_RELATIONS: list[MetamorphicRelation] = [
    MetamorphicRelation(
        id="MR-1",
        name="mr1_split_capture",
        transform="split_capture",
        fee_handling="fee_adjusted",
        description="one capture of N vs two captures N1+N2=N",
        rationale="splitting adds one capture, so exactly one extra flat fee",
    ),
    MetamorphicRelation(
        id="MR-2",
        name="mr2_reorder_independent",
        transform="reorder_independent",
        fee_handling="exact_equivalence",
        description="swap operation order across disjoint merchant accounts",
        rationale="independent operations commute; same captures, same fees",
    ),
    MetamorphicRelation(
        id="MR-3",
        name="mr3_scale_amounts",
        transform="scale_amounts",
        fee_handling="exact_equivalence",
        description="multiply every amount by k",
        rationale="scaling amounts keeps the capture count, so the merchant scales by k exactly and the flat fee is unchanged",
    ),
    MetamorphicRelation(
        id="MR-5",
        name="mr5_replay_request",
        transform="replay_request",
        fee_handling="exact_equivalence",
        description="resubmit an identical request; exactly one effect",
        rationale="idempotency identity relation; replay changes nothing",
    ),
    MetamorphicRelation(
        id="MR-6",
        name="mr6_void_recreate",
        transform="void_recreate",
        fee_handling="exact_equivalence",
        description="void then recreate an identical intent",
        rationale="equivalent to never having voided; same capture count",
    ),
    MetamorphicRelation(
        id="MR-7",
        name="mr7_split_refund",
        transform="split_refund",
        fee_handling="exact_equivalence",
        description="refund N in one call vs two refunds N1+N2=N",
        rationale="refunds carry no capture fee, so splitting a refund changes no balance",
    ),
]
