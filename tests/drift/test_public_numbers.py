"""Public-numbers drift gate: the advertised metrics cannot lie either.

The site is branded "nothing here is hand typed; every number comes from a real
artifact." The README repeats the headline mutation figures in prose. This gate
applies the project's own drift-gate discipline to those advertised numbers: the
committed kill rates in README.md and site/index.html must match
mutation/baseline.json. If the baseline moves and someone forgets to update the
prose (or regenerate the report), the build goes red -- exactly analogous to
tests/drift/test_importlinter_contracts.

Scope note: only the *current* baseline figures are enforced (headline and full
kill rates, and the headline killed/survived/covered counts the report renders).
The narrative "floor" figures the README cites for the before/after story are a
historical datapoint, not the current baseline, and are intentionally not gated
here.
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASELINE = _REPO_ROOT / "mutation" / "baseline.json"
_README = _REPO_ROOT / "README.md"
_SITE = _REPO_ROOT / "site" / "index.html"


def _baseline() -> dict:
    return json.loads(_BASELINE.read_text(encoding="utf-8"))


def _runs() -> dict:
    return _baseline()["runs"]


def test_readme_kill_rates_match_baseline():
    runs = _runs()
    readme = _README.read_text(encoding="utf-8")
    expected = {
        f'{runs["headline"]["kill_rate_pct"]}%': "headline (agent suites only)",
        f'{runs["full"]["kill_rate_pct"]}%': "full (agent + sanity machine)",
    }
    missing = {pct: what for pct, what in expected.items() if pct not in readme}
    assert not missing, (
        f"README.md is missing baseline kill rate(s) {missing}. The committed "
        "baseline moved; update the README prose to match mutation/baseline.json "
        "(headline and full kill rates)."
    )


def test_site_headline_numbers_match_baseline():
    h = _runs()["headline"]
    site = _SITE.read_text(encoding="utf-8")
    expected = {
        f'{h["kill_rate_pct"]}%': "headline kill rate",
        f'{h["killed"]} killed': "killed count",
        f'{h["survived"]} survived': "survived count",
    }
    missing = {frag: what for frag, what in expected.items() if frag not in site}
    assert not missing, (
        f"site/index.html is missing baseline figure(s) {missing}. Regenerate the "
        "folded trust report with `uv run build-report` after any baseline change."
    )


def test_site_full_kill_rate_matches_baseline():
    full = _runs()["full"]
    site = _SITE.read_text(encoding="utf-8")
    frag = f'{full["kill_rate_pct"]}%'
    assert frag in site, (
        f"site/index.html is missing the full-suite kill rate {frag}; regenerate "
        "the trust report with `uv run build-report`."
    )
