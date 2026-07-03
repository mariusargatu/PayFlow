# ADR-0007: Semantic mutation as an informational Layer 3 companion

**Date:** 2026-07-03
**Status:** Accepted. Extends the Layer 3 design (design §11) without changing the gate.
**Revised:** 2026-07-03 — pivoted from a two source design (committed corpus + optional
`--llm`) to a single LLM adversary run by default. The corpus and its drift test are removed,
nondeterminism of the reported number is accepted, and the equivalent mutant screen below is
added. Decisions 2 (zero authority) and 4 (cross family) are unchanged; decisions 3 and 5 are
rewritten. Recorded here in place rather than as a superseding ADR because it is the same effort
and ADR-0007 is not in the immutable set (only ADR-0001 is).

## Context

Layer 3 is mutmut: mechanical, syntactic operators (flip `<`/`<=`, delete a
statement, tweak a constant) that ground truth whether the agent discovered suite
catches anything. Its dumbness is a feature: the operators are fixed, deterministic,
and independent of any LLM's worldview, which is exactly what lets the kill rate
gate and be compared over time.

Mechanical operators cannot express a *semantic* bug: "charge the fee on authorize
instead of capture", "cap the refund at captured rather than captured minus already
refunded", "swap the refund ledger direction". Those are the bugs a developer or a
coding agent actually ships. A spike (Anthropic generated and hand authored) confirmed
they find real gaps the committed suite misses (over refund via partials, zero amount
accepted everywhere, a swapped refund direction), and also produced at least one
likely equivalent mutant (a fingerprint ordering change the suite never exercises),
which is the central hazard: a survivor is not automatically a bug.

The original design shipped these as a committed, drift guarded corpus plus an optional
`--llm` exploration. In practice the corpus was maintenance heavy (a drift test guarding
exact snippets against every refactor) and its determinism bought little for an
explicitly informational tool. We studied Mutahunter and Meta ACH (*Mutation-Guided
LLM-based Test Generation at Meta*, FSE 2025) and concluded the LLM path, hardened with
ACH's own techniques, is enough on its own. The corpus is therefore removed.

## Decision

Add a semantic mutation explorer as an **informational companion** to Layer 3, not a
replacement and not a gate.

1. **mutmut stays the gate.** `mutation/baseline.json` remains the authoritative,
   reproducible kill rate. The explorer never touches it.
2. **Zero authority.** The explorer does not block a merge, does not move any gated
   number, does not feed discovery automatically, and always exits 0. It writes only
   `mutation/semantic_report.json`. A survivor is a *candidate gap for a human to
   confirm against the frozen spec*, never an auto adopted bug or auto generated
   property. This keeps the propose/dispose boundary intact: nothing here marks its
   own homework, and nothing redefines "correct" away from the frozen spec.
3. **One mutant source: the LLM adversary, by default.** Every run generates mutants
   with Anthropic (`uv sync --extra adversary`, `ANTHROPIC_API_KEY`); there is no flag
   and no committed corpus. Generation is nondeterministic, so the reported survivor
   count is adversary dependent and varies run to run; it is labelled and timestamped as
   such, never mistaken for the gated mutmut number. Without the key or extra the explorer
   skips honestly (writes a `skipped` report, exits 0), so the keyless CI lane and the
   trust report keep working. Raw model output is not trusted directly: it is first run
   through deterministic preprocessing (drop no op / comment only mutants and exact
   duplicates — ACH reports these are ~25% and 61% of the trivial cases respectively), and
   a per run cost guard caps generation and screening.
4. **Cross family adversary.** The adversary is Anthropic, deliberately a different model
   family than the OpenAI proposer (ADR-0002, `agent/config.py`), so it does not share the
   proposer's blind spots. Full de correlation is impossible between two LLMs; a different
   family is the cheap, honest reduction.
5. **The spec is the referee, and an equivalent mutant judge pre screens.** Survivors are
   reported as candidate gaps with the invariant or rule that *should* have caught them.
   Because the central hazard is the equivalent mutant, each survivor is additionally
   screened by a cross family LLM judge that labels it `equivalent`, `real`, or `unsure`
   with a one line reason (ACH reaches 0.95/0.96 precision/recall with the preprocessing in
   decision 3). This screen is **informational only**: it annotates the survivor, it never
   changes its status, never drops it, and never feeds discovery. Confirmation is still a
   human step; any real gap becomes a discovery target through the normal loop, and any
   conflict with the spec is an ADR, never a silent property that over constrains.

## Consequences

- The trust report shows two clearly separated numbers: the gated, adversary
  independent mutmut kill rate, and the informational, adversary dependent semantic
  survivor count. The second is labelled as exploration, so a strong number is never
  mistaken for a gate.
- Realistic bugs surface earlier, directed at the payment core, complementing mutmut's
  exhaustive but shallow operators.
- Cost accepted: every real run spends Anthropic tokens (bounded by the cost guard), and
  the reported number is no longer reproducible. Both are the price of dropping the corpus
  and are disclosed on the report.
- Self check lost with the corpus: there are no committed positive controls proving the
  harness catches a bug it should. The mutmut baseline remains the real ground truth of
  suite strength; the semantic explorer is exploration on top, not a second gate.
- New risk accepted knowingly and contained by decision 2: an unattended survivor to
  property loop would find the path of least resistance and could drift the definition
  of correct. It is therefore left informational; the equivalent mutant judge only pre
  triages. Promotion to a co evolution engine (survivors auto driving discovery) would
  need its own ADR, a held out mutant split, and a human owning every promotion.
