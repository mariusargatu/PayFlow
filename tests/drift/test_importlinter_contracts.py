"""Layer 0 contract drift gate.

The architectural contracts live in ``[tool.importlinter]`` inside
pyproject.toml, a file every phase legitimately edits for dependencies. A path
level permission cannot express "these contracts only get stronger", so this
test snapshots the block and fails when the live block drifts from the committed
snapshot. The message is the discipline: contracts change only alongside an ADR
and a matching snapshot update in the same commit.

Background: docs/journey/2026-07-01-guardrail-blocked-its-own-installation.md.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_SNAPSHOT = Path(__file__).resolve().parent / "importlinter_contracts.snapshot"

_HEADER = "[tool.importlinter]"


def extract_importlinter_block(pyproject_text: str) -> str:
    """Return the raw text of the importlinter block, including its comments."""
    captured: list[str] = []
    capturing = False
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped == _HEADER:
            capturing = True
            captured.append(line)
            continue
        if capturing:
            is_foreign_table = (
                stripped.startswith("[")
                and not stripped.startswith("[tool.importlinter")
                and not stripped.startswith("[[tool.importlinter")
            )
            if is_foreign_table:
                break
            captured.append(line)
    assert captured, f"no {_HEADER} block found in pyproject.toml"
    return "\n".join(captured).rstrip() + "\n"


def _parse(block_text: str) -> dict:
    return tomllib.loads(block_text)["tool"]["importlinter"]


def test_importlinter_block_matches_snapshot():
    live_block = extract_importlinter_block(_PYPROJECT.read_text(encoding="utf-8"))
    assert _SNAPSHOT.exists(), (
        f"missing {_SNAPSHOT.name}; regenerate it from the current "
        "[tool.importlinter] block and commit it with the change"
    )
    snapshot_block = _SNAPSHOT.read_text(encoding="utf-8")

    if _parse(live_block) != _parse(snapshot_block):
        raise AssertionError(
            "Layer 0 contract drift: the [tool.importlinter] block in "
            "pyproject.toml differs from tests/drift/importlinter_contracts.snapshot.\n"
            "The Layer 0 contracts are an invariant source: they only ever get "
            "stronger, and any change must land in the same commit as a "
            "superseding ADR and an updated snapshot.\n"
            "--- live block ---\n"
            f"{live_block}"
            "--- snapshot ---\n"
            f"{snapshot_block}"
        )
