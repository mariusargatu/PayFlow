"""Unit tests for the deterministic mutant preprocessing + judge parsing (ADR-0007).

All pure and free: no key, no tokens, no subprocess.
"""

from __future__ import annotations

from mutation.semantic.equivalence import (
    Mutant,
    build_generation_prompt,
    build_screen_prompt,
    dedup,
    is_trivial,
    normalize,
    parse_generation,
    parse_verdict,
)


def _m(find: str, replace: str, mid: str = "m", file: str = "payflow/domain/service.py") -> Mutant:
    return Mutant(mid, file, find, replace, "desc", "INV: something")


# -- normalize / is_trivial --------------------------------------------------

def test_normalize_strips_comments() -> None:
    assert normalize("x = 1  # a comment") == normalize("x = 1")


def test_normalize_collapses_whitespace() -> None:
    assert normalize("a   =    1") == normalize("a = 1")


def test_is_trivial_comment_only_change() -> None:
    assert is_trivial(_m("a = 1  # foo", "a = 1  # bar"))


def test_is_trivial_whitespace_only_change_partial_snippet() -> None:
    # partial snippet that does not tokenize alone; the conservative fallback still
    # collapses whitespace and catches the no op.
    assert is_trivial(_m("if  amount < 1:", "if amount < 1:"))


def test_real_semantic_change_is_not_trivial() -> None:
    assert not is_trivial(_m("amount < 1", "amount < 0"))


# -- dedup -------------------------------------------------------------------

def test_dedup_drops_exact_duplicate() -> None:
    a = _m("amount < 1", "amount < 0", mid="a")
    b = _m("amount  <  1", "amount  <  0", mid="b")  # same after normalize
    kept, dropped = dedup([a, b])
    assert [m.id for m in kept] == ["a"]
    assert [m.id for m in dropped] == ["b"]


def test_dedup_keeps_distinct() -> None:
    a = _m("amount < 1", "amount < 0", mid="a")
    b = _m("refundable = x", "refundable = y", mid="b")
    kept, dropped = dedup([a, b])
    assert len(kept) == 2 and dropped == []


# -- generation parsing ------------------------------------------------------

def test_parse_generation_valid_array() -> None:
    text = (
        'prose before ['
        '{"id":"x","file":"f.py","find":"a","replace":"b","desc":"d","expect":"e"}'
        '] prose after'
    )
    out = parse_generation(text)
    assert len(out) == 1 and out[0].file == "f.py" and out[0].replace == "b"


def test_parse_generation_missing_field_returns_empty() -> None:
    assert parse_generation('[{"id":"x","file":"f.py"}]') == []


def test_parse_generation_garbage_returns_empty() -> None:
    assert parse_generation("no json here") == []


def test_build_generation_prompt_embeds_sources() -> None:
    p = build_generation_prompt("# FILE: f.py\ncode")
    assert "SEMANTIC bugs" in p and "# FILE: f.py" in p


# -- verdict parsing ---------------------------------------------------------

def test_parse_verdict_structured() -> None:
    v = parse_verdict('{"verdict": "equivalent", "reason": "no input differs"}')
    assert v == {"verdict": "equivalent", "reason": "no input differs"}


def test_parse_verdict_real() -> None:
    assert parse_verdict('{"verdict":"real","reason":"r"}')["verdict"] == "real"


def test_parse_verdict_unknown_degrades_to_unsure() -> None:
    assert parse_verdict("total nonsense")["verdict"] == "unsure"


def test_parse_verdict_sniffs_prose_keyword() -> None:
    assert parse_verdict("I think this mutation is equivalent overall.")["verdict"] == "equivalent"


def test_build_screen_prompt_has_both_snippets() -> None:
    p = build_screen_prompt(_m("orig", "mutated"), "full file source")
    assert "orig" in p and "mutated" in p and "full file source" in p
