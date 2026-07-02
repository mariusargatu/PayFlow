"""Full local suite add on for the secondary mutation kill rate.

Active only when ``PAYFLOW_MUT_FULL=1`` (the "full" run in mutation/run_baseline.py).
It folds the real Phase 1 hand written sanity machine into the mutation selection,
so the secondary number is honestly "agent discovered suites PLUS the hand written
sanity suite" using the actual committed machine, not a copy. When the env flag is
absent (the default, headline run) this module skips entirely and contributes
nothing, so the committed config's directory selection still measures the agent
suites alone.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

if os.environ.get("PAYFLOW_MUT_FULL") != "1":
    pytest.skip(
        "full-suite mutation run only (set PAYFLOW_MUT_FULL=1)",
        allow_module_level=True,
    )

_SANITY = Path(__file__).resolve().parents[2] / "tests" / "property" / "test_sanity_machine.py"
_spec = importlib.util.spec_from_file_location("payflow_sanity_machine", _SANITY)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re export so pytest collects the hand written machine's TestCase in this run.
TestSanityMachine = _mod.TestSanityMachine  # noqa: F401
