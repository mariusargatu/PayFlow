"""In process execution mode for the committed agent discovered suites.

Mutation testing (mutmut) only sees a mutated module inside the process that
imported it. The agent discovered specs in ``generated_specs/`` drive PayFlow
over real HTTP against a uvicorn subprocess, and a subprocess never sees the
parent's mutated code. So for the mutation run we replay the exact same committed
specs, unedited, but swap their transport: every ``httpx.Client`` they build is
redirected to a Starlette ``TestClient`` wired to a fresh in process PayFlow app
with its own throwaway SQLite file. The generated assertions, the fee reasoning,
the metamorphic relations are byte for byte the ones the agent authored; only the
wire changes.

Loaded automatically by pytest for ``mutation/replay/``. Kept out of the normal
``tests/`` tree so ``uv run pytest tests/`` never picks it up.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, Phase, settings

# Keep the fee consistent with the committed specs (they default to 30 too).
os.environ.setdefault("PAYFLOW_CAPTURE_FEE", "30")

# Budgets small enough that a full mutant sweep finishes in minutes, large enough
# that a real behavioural mutant is reliably caught. Env overridable for a wider
# confirmation sweep. Set before the generated modules import (they read these).
os.environ.setdefault("PAYFLOW_SPEC_MAX_EXAMPLES", "25")
os.environ.setdefault("PAYFLOW_SPEC_STEP_COUNT", "14")
os.environ.setdefault("PAYFLOW_MR_MAX_EXAMPLES", "10")

# A deterministic Hypothesis profile: derandomize so the same mutant yields the
# same verdict every run, no example database so a kill from one mutant never
# leaks into the next. The generated machine builds its own settings() which
# inherit these from the loaded default.
#
# Crucially the shrink phase is dropped: mutation testing only needs kill vs
# survive, not a minimal counterexample. Shrinking a stateful failure is slow and
# can blow the per mutant CPU limit (misreported as a timeout), so skipping it
# speeds kills sharply WITHOUT weakening detection at all (generation is
# unchanged; a mutant that fails still fails, just without minimisation).
settings.register_profile(
    "payflow_mutation",
    derandomize=True,
    deadline=None,
    database=None,
    phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
    suppress_health_check=list(HealthCheck),
)
settings.load_profile("payflow_mutation")

# The committed specs are a flat module dir (no package); expose them for import.
_GENERATED = Path(__file__).resolve().parents[2] / "generated_specs"
if str(_GENERATED) not in sys.path:
    sys.path.insert(0, str(_GENERATED))

from payflow.api.app import create_app  # noqa: E402  (after path/env setup)
from payflow.config import Config  # noqa: E402

_CAPTURE_FEE = int(os.environ["PAYFLOW_CAPTURE_FEE"])


class _InProcessClient(TestClient):
    """Drop in for ``httpx.Client`` that talks to a fresh in process PayFlow.

    Each instance owns a private SQLite file so instances never see each other's
    rows, matching how the generated specs already scope every check to entities
    they created. Ignores the ``base_url``/``timeout`` kwargs the specs pass.
    """

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self._db_dir = tempfile.mkdtemp(prefix="payflow_mut_")
        config = Config(
            db_path=str(Path(self._db_dir) / "payflow.db"),
            capture_fee=_CAPTURE_FEE,
            bug=None,
        )
        super().__init__(create_app(config))

    def _cleanup(self) -> None:
        shutil.rmtree(self._db_dir, ignore_errors=True)

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._cleanup()

    def __exit__(self, *exc: object) -> None:
        try:
            super().__exit__(*exc)
        finally:
            self._cleanup()


# The swap the whole harness turns on: the generated specs' httpx.Client(...)
# calls now build in process clients against mutated code.
httpx.Client = _InProcessClient  # type: ignore[misc, assignment]
