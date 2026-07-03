"""`uv run semantic-mutation`: the Layer 3 semantic explorer (ADR-0007, revised).

Generates realistic SEMANTIC bugs with a cross family Anthropic adversary, applies each
to one payment core file, runs the committed in process replay (mutation/replay/), records
killed / survived / timeout, always restores the file, and pre triages each survivor with
an equivalent mutant judge. Writes mutation/semantic_report.json.

INFORMATIONAL ONLY: it never gates, never touches mutation/baseline.json, never feeds
discovery, and always exits 0. A survivor is a candidate gap to confirm against the frozen
spec, not a proven bug (it may be an equivalent mutant under the suite's input
distribution) -- the judge only pre screens it, a human still confirms.

    uv run semantic-mutation             # LLM generation + survivor screening
    uv run semantic-mutation --no-screen  # generation only, skip the equivalent judge

The adversary is deliberately a different model family than the OpenAI proposer
(agent/config.py), so it does not share the proposer's blind spots (ADR-0007 decision 4).
It needs ANTHROPIC_API_KEY and the adversary extra: uv sync --extra adversary. Without
either it skips honestly (writes a "skipped" report, exits 0), so the keyless CI lane and
build-report keep working. Generation is nondeterministic; the reported number is
adversary dependent and timestamped, never mistaken for the gated mutmut kill rate.
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.budget import BudgetExceeded, CostGuard
from mutation.semantic import equivalence as eq
from mutation.semantic.equivalence import Mutant

_ROOT = Path(__file__).resolve().parents[2]
_REPORT = _ROOT / "mutation" / "semantic_report.json"
_REPLAY = "mutation/replay/test_agent_replay.py"

# The payment core the adversary mutates and the judge reasons about.
_TARGETS = [
    "payflow/domain/service.py",
    "payflow/domain/state_machine.py",
    "payflow/domain/fees.py",
    "payflow/domain/idempotency.py",
]

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ModuleNotFoundError:
    pass


@dataclass
class Generation:
    """Result of the generation phase, plus the live client for reuse in screening."""

    mutants: list[Mutant]
    preprocessing: dict
    source: str
    client: object | None  # an anthropic.Anthropic, or None when skipped


def _budget() -> CostGuard:
    """A cost guard with explorer specific caps, independent of the agent's budget."""
    return CostGuard(
        max_calls=int(os.environ.get("PAYFLOW_SEMANTIC_MAX_CALLS", 30)),
        max_tokens=int(os.environ.get("PAYFLOW_SEMANTIC_MAX_TOKENS", 300_000)),
    )


def _usage(msg: object) -> dict:
    """Pull token counts off an Anthropic message for the budget guard."""
    u = getattr(msg, "usage", None)
    inp = int(getattr(u, "input_tokens", 0) or 0)
    out = int(getattr(u, "output_tokens", 0) or 0)
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}


def _message_text(msg: object) -> str:
    return "".join(
        b.text for b in getattr(msg, "content", []) if getattr(b, "type", None) == "text"
    )


def _baseline_timeout() -> int:
    """Per mutant subprocess timeout, so a looping mutant cannot hang the run forever.

    Honors PAYFLOW_SEMANTIC_TIMEOUT if set; otherwise times one clean replay and scales
    off it (x4, floor 30s). A timed out mutant is reported as its own bucket, never folded
    into "killed" (see _run_replay), per the module's "don't flatter the number" rule and
    mutation/run_baseline.py's precedent.
    """
    override = os.environ.get("PAYFLOW_SEMANTIC_TIMEOUT")
    if override:
        return max(1, int(override))
    start = time.monotonic()
    subprocess.run(
        [sys.executable, "-m", "pytest", _REPLAY, "-q", "-p", "no:cacheprovider"],
        cwd=str(_ROOT), env={**os.environ}, capture_output=True, text=True,
    )
    elapsed = time.monotonic() - start
    return max(30, int(elapsed * 4))


def _failing_nodes(stdout: str) -> list[str]:
    """The pytest node ids that FAILED, from a `-rA` short summary. Lets a maintainer
    check the mutant's `expect` hypothesis against the test that actually fired."""
    nodes = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("FAILED "):
            nodes.append(line[len("FAILED "):].split(" ")[0])
    return nodes


def _run_replay(timeout: int) -> tuple[str, list[str]]:
    """Run the committed in process replay. Returns (status, failing_node_ids).

    status is "killed" only when a test actually FAILED (pytest exit 1). "timeout" when
    the mutant made the suite hang past `timeout`. Any other non zero exit (2 interrupted,
    3 internal, 4 usage, 5 no tests collected) means the suite never really ran, e.g. the
    mutant broke an import; counting that as a kill would flatter the number and hide a
    gap, so it is reported as "error".
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", _REPLAY,
             "-q", "-x", "-rA", "--tb=no", "-p", "no:cacheprovider"],
            cwd=str(_ROOT), env={**os.environ},
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "timeout", []
    if proc.returncode == 0:
        return "survived", []
    if proc.returncode == 1:
        return "killed", _failing_nodes(proc.stdout)
    return "error", []


def _apply_and_test(m: Mutant, timeout: int) -> dict:
    """Apply one mutant, run the replay, always restore the file."""
    path = _ROOT / m.file
    original = path.read_text()
    occurrences = original.count(m.find)
    base = {"id": m.id, "file": m.file, "desc": m.desc}
    if occurrences == 0:
        return {**base, "status": "stale"}
    if occurrences > 1:
        return {**base, "status": "ambiguous"}

    try:
        path.write_text(original.replace(m.find, m.replace, 1))
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError:
            return {**base, "status": "invalid"}
        status, killed_by = _run_replay(timeout)
        result = {**base, "expect": m.expect, "status": status}
        if killed_by:
            result["killed_by"] = killed_by
        return result
    finally:
        path.write_text(original)  # always restore, even on crash


def _generate(model: str, budget: CostGuard) -> Generation:
    """Generate semantic mutants with Anthropic, then dedup + drop trivial ones."""
    try:
        import anthropic
    except ModuleNotFoundError:
        print("semantic-mutation: needs the adversary extra "
              "(uv sync --extra adversary); skipping.")
        return Generation([], {}, "skipped: no adversary extra", None)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("semantic-mutation: needs ANTHROPIC_API_KEY in .env; skipping.")
        return Generation([], {}, "skipped: no adversary key", None)

    sources = "\n\n".join(f"# FILE: {t}\n{(_ROOT / t).read_text()}" for t in _TARGETS)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    try:
        budget.before_call()
        msg = client.messages.create(
            model=model, max_tokens=16000,
            messages=[{"role": "user", "content": eq.build_generation_prompt(sources)}],
        )
        budget.record(_usage(msg))
    except BudgetExceeded as exc:
        print(f"semantic-mutation: {exc}")
        return Generation([], {}, "skipped: budget", client)

    text = _message_text(msg)
    if not text:
        print(f"semantic-mutation: no text from model "
              f"(stop_reason={getattr(msg, 'stop_reason', '?')}).")
        return Generation([], {"raw": 0}, f"anthropic:{model}", client)

    raw = eq.parse_generation(text)
    deduped, duplicates = eq.dedup(raw)
    kept = [m for m in deduped if not eq.is_trivial(m)]
    preprocessing = {
        "raw": len(raw),
        "duplicate": len(duplicates),
        "trivial": len(deduped) - len(kept),
        "kept": len(kept),
    }
    return Generation(kept, preprocessing, f"anthropic:{model}", client)


def _screen(pairs: list[tuple[Mutant, dict]], client: object, model: str,
            budget: CostGuard) -> None:
    """Pre triage every survivor with the equivalent mutant judge, in place.

    Informational only: writes each survivor's result["equivalent"] = {verdict, reason};
    it never changes result["status"]. A survivor screened "equivalent" is still a
    survivor, just flagged so a human does not chase it (ADR-0007 decisions 2 and 5).
    """
    for m, result in pairs:
        if result["status"] != "survived":
            continue
        try:
            budget.before_call()
            file_source = (_ROOT / m.file).read_text()
            msg = client.messages.create(  # type: ignore[attr-defined]
                model=model, max_tokens=500,
                messages=[{"role": "user",
                           "content": eq.build_screen_prompt(m, file_source)}],
            )
            budget.record(_usage(msg))
            result["equivalent"] = eq.parse_verdict(_message_text(msg))
        except BudgetExceeded:
            result["equivalent"] = {"verdict": "unsure",
                                    "reason": "budget cap reached before screening"}


def _budget_report(budget: CostGuard, model: str) -> dict:
    """Honest token/call accounting. No USD line: we have no committed Anthropic rate,
    and fabricating one would be dishonest for an informational tool."""
    return {
        "model": model,
        "calls": budget.calls,
        "max_calls": budget.max_calls,
        "input_tokens": budget.input_tokens,
        "output_tokens": budget.output_tokens,
        "total_tokens": budget.total_tokens,
    }


def _rel(path: Path) -> str:
    """Repo relative display of a path, falling back to the full path if it is not
    under the repo root (e.g. a redirected report path in a test)."""
    try:
        return str(path.relative_to(_ROOT))
    except ValueError:
        return str(path)


def _write_skipped(source: str) -> None:
    _REPORT.write_text(json.dumps({
        "source": source,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "note": "Semantic exploration did not run this cycle (adversary key/extra "
                "absent). Informational only; nothing gated.",
        "summary": {"total": 0, "killed": 0, "survived": 0, "timeout": 0, "other": 0},
        "mutants": [],
    }, indent=2) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Semantic mutation explorer (informational).")
    ap.add_argument("--model", default="claude-sonnet-5", help="Anthropic model")
    ap.add_argument("--no-screen", action="store_true",
                    help="skip the equivalent mutant judge on survivors")
    args = ap.parse_args()

    budget = _budget()
    gen = _generate(args.model, budget)

    if gen.source.startswith("skipped") or not gen.mutants:
        if not gen.mutants and not gen.source.startswith("skipped"):
            print("semantic-mutation: model returned no usable mutants.")
            _write_skipped(f"{gen.source} (no mutants)")
        else:
            _write_skipped(gen.source)
        print(f"wrote {_rel(_REPORT)}  (informational; nothing gated)")
        return 0

    print(f"\nsemantic-mutation ({gen.source}, informational only): "
          f"{len(gen.mutants)} mutants vs the committed agent replay "
          f"(raw {gen.preprocessing.get('raw', '?')}, "
          f"-{gen.preprocessing.get('duplicate', 0)} dup, "
          f"-{gen.preprocessing.get('trivial', 0)} trivial).\n")

    timeout = _baseline_timeout()
    pairs = [(m, _apply_and_test(m, timeout)) for m in gen.mutants]
    results = [r for _, r in pairs]

    if not args.no_screen and gen.client is not None:
        _screen(pairs, gen.client, args.model, budget)

    killed = [r for r in results if r["status"] == "killed"]
    survived = [r for r in results if r["status"] == "survived"]
    timed_out = [r for r in results if r["status"] == "timeout"]

    for r in results:
        mark = {"killed": "  killed  ", "survived": "> SURVIVED",
                "timeout": " timeout  "}.get(r["status"], f"  {r['status']}")
        print(f"[{mark}] {r['id']}  ({r['file']})")
        print(f"             {r['desc']}")
        if r["status"] == "survived":
            verdict = r.get("equivalent", {}).get("verdict")
            tag = f" [screened: {verdict}]" if verdict else ""
            print(f"             candidate gap{tag}; expected catcher: {r.get('expect')}")
        print()

    report = {
        "source": gen.source,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "note": "Informational only. Survivors are candidate gaps to confirm against "
                "the frozen spec; the equivalent mutant judge only pre screens them. "
                "Not a gate; the mutmut baseline (mutation/baseline.json) is the "
                "authoritative number.",
        "preprocessing": gen.preprocessing,
        "budget": _budget_report(budget, args.model),
        "summary": {
            "total": len(results),
            "killed": len(killed),
            "survived": len(survived),
            "timeout": len(timed_out),
            "other": len(results) - len(killed) - len(survived) - len(timed_out),
        },
        "mutants": results,
    }
    _REPORT.write_text(json.dumps(report, indent=2) + "\n")

    print("=" * 72)
    print(f"killed {len(killed)}  |  SURVIVED {len(survived)}  |  "
          f"timeout {len(timed_out)}  |  other {report['summary']['other']}  "
          f"(of {len(results)})")
    print(f"wrote {_rel(_REPORT)}  (informational; nothing gated)")
    return 0  # never fails: zero authority


if __name__ == "__main__":
    raise SystemExit(main())
