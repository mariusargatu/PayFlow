"""Deterministic mutant preprocessing + the pieces of an LLM equivalent mutant judge.

Since the semantic explorer's only mutant source is the LLM adversary (ADR-0007,
revised 2026-07-03), raw generated mutants need two guards before their survivors are
worth a human's time:

  1. Deterministic, free preprocessing (the pure functions here): drop no op /
     comment only mutants and exact duplicates. Meta ACH (FSE 2025) reports syntactic
     dedup removes ~25% of LLM mutants and comment stripping recovers 61% of the
     "almost trivially equivalent" cases.
  2. An LLM equivalent mutant judge that pre triages each SURVIVOR as
     equivalent / real / unsure. This module owns only its *pure* halves (prompt
     construction + verdict parsing); the network call and its budget live in the
     explorer. The judge is INFORMATIONAL ONLY: it annotates, never changes a
     mutant's status, never drops a survivor, never feeds discovery. A human still
     confirms every survivor against the frozen spec (ADR-0007 decision 2).

Everything here is stdlib only, so importing it never weighs down the keyless lane.
"""

from __future__ import annotations

import io
import json
import textwrap
import tokenize
from dataclasses import dataclass

_SKIP_TOKENS = frozenset({
    tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
    tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER,
})

_VERDICTS = frozenset({"equivalent", "real", "unsure"})


@dataclass(frozen=True)
class Mutant:
    """One semantic mutant: an exact snippet replacement in one payment core file.

    Kept structurally identical to the field set the report and trust report expect
    (id, file, find, replace, desc, expect), so nothing downstream had to change when
    the source moved from a committed corpus to LLM generation.
    """

    id: str
    file: str  # repo relative
    find: str  # exact snippet
    replace: str  # the semantic bug
    desc: str  # plain English: the bug introduced
    expect: str  # the invariant/rule that SHOULD catch it (a hypothesis)


def normalize(src: str) -> str:
    """Strip comments and collapse whitespace so two snippets differing only in
    comments or formatting normalize equal.

    Best effort and deliberately conservative: LLM snippets are often partial lines
    that do not tokenize on their own, so on any tokenizer error we fall back to a
    plain whitespace collapse *without* comment removal. That can only make us miss a
    trivial mutant (harmless: it just gets tested), never wrongly drop a real one.
    """
    dedented = textwrap.dedent(src)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(dedented + "\n").readline)
        parts = [tok.string for tok in tokens if tok.type not in _SKIP_TOKENS]
        return " ".join("".join(parts).split())
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return " ".join(dedented.split())


def is_trivial(mutant: Mutant) -> bool:
    """True if the mutation is a no op / comment only change under `normalize`."""
    return normalize(mutant.find) == normalize(mutant.replace)


def dedup(mutants: list[Mutant]) -> tuple[list[Mutant], list[Mutant]]:
    """Split into (kept, dropped_duplicates). Two mutants are duplicates when they
    touch the same file with the same normalized find and replace."""
    seen: set[tuple[str, str, str]] = set()
    kept: list[Mutant] = []
    dropped: list[Mutant] = []
    for m in mutants:
        key = (m.file, normalize(m.find), normalize(m.replace))
        if key in seen:
            dropped.append(m)
        else:
            seen.add(key)
            kept.append(m)
    return kept, dropped


# -- generation prompt (pure) ------------------------------------------------

# Illustrative fault *styles* to steer the adversary toward realistic domain bugs.
# This is prompt text, not a reported or applied corpus (ADR-0007 revised): nothing
# here is scored or shown; it only shapes what the model proposes.
_FEW_SHOT = (
    "  - cap the refund at captured_amount instead of "
    "captured_amount - refunded_amount, so repeated partial refunds exceed the capture\n"
    "  - release the full authorized_amount on void instead of the still held remainder "
    "after a partial capture, over crediting external settlement\n"
    "  - swap the source and destination of the refund ledger pair, crediting the "
    "merchant on a refund instead of debiting them\n"
    "  - accept an amount of zero where the rule requires an integer >= 1\n"
)


def build_generation_prompt(sources: str) -> str:
    """The adversary prompt: propose realistic semantic bugs as exact snippet swaps."""
    return (
        "You are an adversarial reviewer of a payment system. Introduce realistic "
        "SEMANTIC bugs (the kind a developer actually ships), not syntactic noise. "
        "Each bug: a minimal, unique, exact snippet replacement in one file that "
        "compiles and changes observable behavior. Avoid equivalents and comment only "
        "changes. Examples of the STYLE of bug wanted (do not just copy these):\n"
        f"{_FEW_SHOT}"
        "Return ONLY a JSON array of objects "
        '{"id","file","find","replace","desc","expect"} where find is an exact '
        "substring of that file and expect names the invariant or rule that should "
        "catch the bug. 6 to 10 bugs.\n\n" + sources
    )


def parse_generation(text: str) -> list[Mutant]:
    """Defensively parse the model's JSON array into Mutants. A stray bracket in
    prose, malformed JSON, or a missing field must never crash the explorer (its
    contract is informational, always exits 0); on any failure return []."""
    start, end = text.find("["), text.rfind("]") + 1
    if not (0 <= start < end):
        return []
    try:
        raw = json.loads(text[start:end])
        return [
            Mutant(
                str(d.get("id", f"llm_{i}")),
                d["file"],
                d["find"],
                d["replace"],
                d.get("desc", ""),
                d.get("expect", "?"),
            )
            for i, d in enumerate(raw)
        ]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return []


# -- equivalent mutant judge (pure halves) -----------------------------------

def build_screen_prompt(mutant: Mutant, file_source: str) -> str:
    """Ask a cross family judge whether a survivor is an equivalent mutant."""
    return (
        "You judge whether a code mutation changes the OBSERVABLE behavior of a "
        "payment system under its frozen specification, or is an EQUIVALENT mutant "
        "(no input distinguishes the two versions).\n\n"
        f"FILE: {mutant.file}\n"
        f"INVARIANT THAT SHOULD CATCH A REAL BUG: {mutant.expect}\n\n"
        f"ORIGINAL SNIPPET:\n{mutant.find}\n\n"
        f"MUTATED SNIPPET:\n{mutant.replace}\n\n"
        f"FULL FILE FOR CONTEXT:\n{file_source}\n\n"
        'Answer with ONLY a JSON object {"verdict": "equivalent"|"real"|"unsure", '
        '"reason": "<one sentence>"}. "equivalent" = no valid input yields different '
        'observable behavior; "real" = some input does; "unsure" if you cannot tell.'
    )


def parse_verdict(text: str) -> dict:
    """Parse the judge's JSON object into {verdict, reason}. Defensive: unknown or
    unparseable output degrades to 'unsure' rather than raising."""
    start, end = text.find("{"), text.rfind("}") + 1
    if 0 <= start < end:
        try:
            obj = json.loads(text[start:end])
            verdict = str(obj.get("verdict", "")).strip().lower()
            reason = str(obj.get("reason", "")).strip()
            if verdict in _VERDICTS:
                return {"verdict": verdict, "reason": reason}
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    # last resort: sniff a bare keyword from prose
    low = text.lower()
    for v in ("equivalent", "real"):
        if v in low:
            return {"verdict": v, "reason": "parsed from unstructured judge output"}
    return {"verdict": "unsure", "reason": "could not parse judge output"}
