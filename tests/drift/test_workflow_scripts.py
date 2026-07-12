"""Drift gate: every ``uv run <x>`` in CI resolves to a real entrypoint.

A renamed console script silently breaks a whole CI lane. The nightly lane once
invoked ``uv run trust-report`` while the defined script was ``build-report``, so
the job failed before it produced anything and nobody noticed until it was
dispatched by hand. This gate turns that class of typo into a test failure: each
``uv run <name>`` in ``.github/workflows/`` must resolve to a ``[project.scripts]``
entry or a known dependency console script.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_PYPROJECT = _ROOT / "pyproject.toml"

# Console scripts provided by dependencies (not by [project.scripts]); uv run finds
# these on the venv PATH. Extend when CI starts invoking a new dev tool this way.
_DEP_ENTRYPOINTS = frozenset(
    {"python", "pytest", "lint-imports", "uvicorn", "mutmut"}
)


def _project_scripts() -> set[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return set(data.get("project", {}).get("scripts", {}))


def _uv_run_targets() -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        for match in re.finditer(r"\buv run\s+(\S+)", text):
            token = match.group(1)
            if token.startswith("-"):
                continue  # a uv flag, not the entrypoint
            targets.append((wf.name, token))
    return targets


def test_every_uv_run_in_ci_resolves_to_a_real_entrypoint():
    allowed = _project_scripts() | _DEP_ENTRYPOINTS
    unknown = sorted({t for t in _uv_run_targets() if t[1] not in allowed})
    assert not unknown, (
        "CI invokes `uv run <x>` for entrypoints that are neither a "
        f"[project.scripts] entry nor a known dependency console script: {unknown}. "
        "A renamed or mistyped script breaks the lane silently; fix the workflow, "
        "add the [project.scripts] entry, or extend _DEP_ENTRYPOINTS."
    )
