# Layer 3 - mutation ground truth

Coverage says a line ran; mutation testing says a bug in that line would be
caught. This directory holds the committed Layer 3 baseline ([design §11.1](../docs/design.md)): how
many deliberately injected bugs the agent discovered suites actually kill.

## The headline

`baseline.json` / `baseline.txt` carry two numbers:

- **headline** - kill rate of the agent discovered suites ALONE, replayed in
  process, with **zero hand written test cases**. This is the README claim.
- **full** - the same, plus the Phase 1 hand written sanity machine, for contrast.

Kill rate is reported as `killed / covered` where `covered = killed + survived`.
Mutants with no covering test (`no_tests`, e.g. the seeded bug variants that are
never active in a correct build) are reported separately, never folded into the
denominator to flatter the number. `survivors.txt` lists every non killed mutant
per run.

## Why in process

The committed specs in `generated_specs/` drive PayFlow over real HTTP against a
uvicorn subprocess, and mutmut only sees a mutated module inside the process that
imported it - a subprocess never sees the parent's mutations. So `mutation/replay/`
replays the exact committed specs, byte for byte, but swaps their `httpx.Client`
for a Starlette `TestClient` wired to an in process PayFlow (`conftest.py`). The
assertions, fee reasoning, and relations are the agent's; only the wire changes.

## Scope

`[tool.mutmut]` in `pyproject.toml` mutates the payment DECISION logic only:
`service.py`, `state_machine.py`, `fees.py`, `idempotency.py`, and the ledger
`core.py`. [ADR-0001](../docs/adr/0001-foundational-decisions.md) fixed the boundary at `payflow/domain` + ledger core; [ADR-0003](../docs/adr/0003-mutation-thresholds.md)
narrows it within that boundary and explains why the data holders, port
protocols, SQLite adapters (`repositories.py`), and composition root
(`factory.py`) are excluded, and records the runtime driven decision.

The mutation sweep runs the same properties at a reduced Hypothesis example budget
(env in `conftest.py`) for tractable runtime. Fewer examples can only miss kills,
never invent them, so the reported rate is a conservative floor.

## Reproduce

```bash
uv run python mutation/run_baseline.py            # both runs, rewrites the artifacts
uv run python mutation/run_baseline.py --headline # headline only
```

Expect minutes, not seconds: the committed baseline runtimes live in `baseline.json` (`runtime_seconds`). `baseline.txt` is the human readable form of the same run.

Thresholds (warn/block) are set from this baseline in
[`docs/adr/0003-mutation-thresholds.md`](../docs/adr/0003-mutation-thresholds.md).
The nightly workflow recomputes and uploads these artifacts; the PR lane never
runs mutmut (too slow to block on).
