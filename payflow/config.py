"""Startup configuration.

The only configuration surface (specs/constraints.md): the capture fee, the
deliberate bug toggle, and the database path. Read once, at process start.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_CAPTURE_FEE = 30
DEFAULT_DB_PATH = "payflow.db"

# Runtime bug toggles, read once at startup: fm_a (idempotency check then act) and
# fm_c (non atomic ledger writes) each swap a correct implementation for a broken one
# in the running service. fm_b is deliberately absent: it is a build time toggle (an
# extra admin route module) caught structurally by Layer 0, so it has no runtime
# effect. load_config gives it an explicit signal; tools/seeded_bugs/ activates it.
VALID_BUGS = frozenset({"fm_a", "fm_c"})


@dataclass(frozen=True)
class Config:
    db_path: str
    capture_fee: int
    bug: str | None


def load_config() -> Config:
    fee_raw = os.environ.get("PAYFLOW_CAPTURE_FEE")
    capture_fee = int(fee_raw) if fee_raw is not None else DEFAULT_CAPTURE_FEE
    if capture_fee < 0:
        raise ValueError("PAYFLOW_CAPTURE_FEE must be a non-negative integer")

    bug = os.environ.get("PAYFLOW_BUG") or None
    if bug == "fm_b":
        raise ValueError(
            "fm_b is a build time toggle, not a runtime PAYFLOW_BUG: it is an admin "
            "route module caught structurally by Layer 0. Activate it with "
            "tools/seeded_bugs/activate_fm_b.sh and catch it with uv run lint-imports "
            "(or uv run catch)."
        )
    if bug is not None and bug not in VALID_BUGS:
        raise ValueError(f"PAYFLOW_BUG must be one of {sorted(VALID_BUGS)} or unset")

    return Config(
        db_path=os.environ.get("PAYFLOW_DB_PATH", DEFAULT_DB_PATH),
        capture_fee=capture_fee,
        bug=bug,
    )
