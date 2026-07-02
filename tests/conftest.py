"""Fixtures shared across the test layers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

import pytest

from _layer2 import CachingTriageRunner, load_env_key

# Load .env before the Layer 2 modules evaluate their key gated pytestmark. A
# single session scoped runner is shared across both Layer 2 suites so the whole
# lane reports one combined cost.
load_env_key()


@pytest.fixture(scope="session")
def triage_runner() -> CachingTriageRunner:
    runner = CachingTriageRunner()
    yield runner
    line = runner.cost_line()
    print("\n" + line)
    cost_file = os.environ.get("PAYFLOW_LAYER2_COST_FILE")
    if cost_file:
        with open(cost_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(runner.budget.summary(runner.config.model)) + "\n")


@pytest.fixture
def db_path_factory(tmp_path: Path) -> Callable[[], str]:
    """Hand out unique, empty SQLite paths inside the test's temp directory."""
    counter = {"n": 0}

    def make() -> str:
        counter["n"] += 1
        return str(tmp_path / f"payflow_{counter['n']}.db")

    return make


@pytest.fixture
def tmp_db_path(db_path_factory: Callable[[], str]) -> str:
    return db_path_factory()
