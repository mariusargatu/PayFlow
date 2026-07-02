"""Startup configuration.

The only configuration surface (specs/constraints.md): the capture fee, the
deliberate bug toggle, and the database path. Read once, at process start.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_CAPTURE_FEE = 30
DEFAULT_DB_PATH = "payflow.db"

VALID_BUGS = frozenset({"fm_a", "fm_b", "fm_c"})


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
    if bug is not None and bug not in VALID_BUGS:
        raise ValueError(f"PAYFLOW_BUG must be one of {sorted(VALID_BUGS)} or unset")

    return Config(
        db_path=os.environ.get("PAYFLOW_DB_PATH", DEFAULT_DB_PATH),
        capture_fee=capture_fee,
        bug=bug,
    )
