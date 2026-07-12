"""uv run showcase: run the whole verify pipeline locally, with SOFT assertions.

Three ways to run PayFlow's checks, three purposes:
  - `uv run demo`     : the fast gate subset, quick and green, for a sanity glance.
  - `uv run catch`    : seed each deliberate bug and watch its layer catch it, in red.
  - `uv run showcase` : run EVERY check in the verify pipeline as one matrix, soft.

The point here is soft assertions. CI runs under `bash -e`, so the first red step
halts the rest and you never see the others. This runs every check regardless of
failures and prints one matrix, so a demo shows the full picture. With a scenario
argument it seeds a fault first and shows exactly which check localizes it while
every other check stays green. The failure is the interesting part, so it is shown
in full, not hidden behind an early exit.

  uv run showcase                      # every check, clean, one green matrix
  uv run showcase spec-change          # add INV-8 to the frozen spec; the coverage gate localizes it
  uv run showcase fm_b                 # wire an admin route around the domain; Layer 0 localizes it
  uv run showcase all                  # clean, then every fault scenario in turn
  uv run showcase all --report out/    # also write out/showcase-report.{json,md}

Every scenario restores a pristine tree in a finally block. The Markdown report is
shaped for a GitHub Actions job summary, and both files upload cleanly as artifacts.
Exit code: 0 when the run behaves as intended (clean is all green; a scenario is
localized to exactly its expected check), nonzero otherwise, so this doubles as a
self check.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.demo import (
    BOLD,
    DIM,
    GREEN,
    RED,
    RESET,
    _PYTEST,
    _REPLAY_A,
    _contracts_count,
    _pytest_count,
    _run,
    _status,
)

_ROOT = Path(__file__).resolve().parents[1]

# The full verify pipeline (ci.yml), one row per check so the matrix localizes a
# fault to a single line. Layer 0, every drift gate broken out, and the Layer 1
# replay slice: exactly what blocks a merge.
_CHECKS = (
    ("Layer 0", "import contracts", ["lint-imports"], _contracts_count),
    ("Drift", "state machine diagram", _PYTEST + ["tests/drift/test_state_machine_diagram.py"], _pytest_count),
    ("Drift", "agent graph diagram", _PYTEST + ["tests/drift/test_agent_graph_diagram.py"], _pytest_count),
    ("Drift", "importlinter snapshot", _PYTEST + ["tests/drift/test_importlinter_contracts.py"], _pytest_count),
    ("Drift", "node roles (propose vs dispose)", _PYTEST + ["tests/drift/test_node_roles.py"], _pytest_count),
    ("Drift", "spec coverage (gate on the gate)", _PYTEST + ["tests/drift/test_spec_coverage.py"], _pytest_count),
    ("Drift", "public numbers", _PYTEST + ["tests/drift/test_public_numbers.py"], _pytest_count),
    ("Drift", "workflow scripts", _PYTEST + ["tests/drift/test_workflow_scripts.py"], _pytest_count),
    ("Drift", "vocabulary coupling", _PYTEST + ["tests/drift/test_vocabulary_coupling.py"], _pytest_count),
    ("Layer 1", "property sanity machine", _PYTEST + ["tests/property"], _pytest_count),
    ("Layer 1", "idempotent replay (concurrency A)", _PYTEST + [_REPLAY_A], _pytest_count),
    ("Layer 1", "agent discovered replay", _PYTEST + ["mutation/replay/test_agent_replay.py"], _pytest_count),
)


def _fail_reason(output: str) -> str:
    """One concise line explaining a red row, for the fault demos and the report."""
    for needle in ("AssertionError:", "BROKEN"):
        for line in output.splitlines():
            if needle in line:
                return line.strip()[:120]
    tail = [line for line in output.splitlines() if line.strip()]
    return tail[-1].strip()[:120] if tail else ""


def _run_matrix() -> list[dict]:
    """Run every check, soft: none halts the others. One row per check."""
    print(f"{DIM}{'layer':8} {'check':40} {'result':6} {'detail':20} elapsed{RESET}")
    rows = []
    for layer, name, cmd, counter in _CHECKS:
        ok, output, elapsed = _run(cmd)
        reason = "" if ok else _fail_reason(output)
        rows.append(
            {"layer": layer, "name": name, "ok": ok,
             "detail": counter(output), "elapsed": round(elapsed, 2), "reason": reason}
        )
        print(f"{layer:8} {name:40} {_status(ok)} {counter(output):20} {elapsed:6.2f}s")
        if not ok:
            print(f"         {RED}why: {reason}{RESET}")
    return rows


# -- fault scenarios: each seeds a problem and names the check meant to catch it ---


def _seed_spec_change():
    path = _ROOT / "specs" / "invariants.md"
    original = path.read_text(encoding="utf-8")
    anchor = "| INV-7 | Every intent in state `AUTHORIZED`"
    line = next(l for l in original.splitlines() if l.startswith(anchor))
    added = "| INV-8 | (demo) The sum of a merchant's captured amounts never exceeds its lifetime authorized total |"
    path.write_text(original.replace(line, line + "\n" + added), encoding="utf-8")
    return lambda: path.write_text(original, encoding="utf-8")


def _seed_fm_b():
    src = _ROOT / "tools" / "seeded_bugs" / "fm_b_admin.py"
    dst = _ROOT / "payflow" / "api" / "admin.py"
    shutil.copyfile(src, dst)
    return lambda: dst.unlink(missing_ok=True)


_SCENARIOS = {
    "spec-change": {
        "title": "A human adds a new invariant (INV-8) to the frozen spec",
        "seed": _seed_spec_change,
        "expect": "spec coverage (gate on the gate)",
    },
    "fm_b": {
        "title": "An admin route writes to the ledger around the domain layer",
        "seed": _seed_fm_b,
        "expect": "import contracts",
    },
}


def _section_clean() -> dict:
    print(f"\n{BOLD}Showcase: the whole verify pipeline, clean{RESET}")
    rows = _run_matrix()
    reds = [r["name"] for r in rows if not r["ok"]]
    ok = not reds
    print()
    if ok:
        print(f"{GREEN}{BOLD}VERDICT: all {len(rows)} checks green{RESET}")
    else:
        print(f"{RED}{BOLD}VERDICT: {len(reds)} check(s) red on a clean tree: {reds}{RESET}")
    return {"scenario": "clean", "title": "the whole verify pipeline, clean",
            "checks": rows, "ok": ok, "localized": None, "expected": None, "reds": reds}


def _section_scenario(key: str) -> dict:
    sc = _SCENARIOS[key]
    print(f"\n{BOLD}Showcase fault: {sc['title']}{RESET}")
    print(f"{DIM}seeded, then every check runs anyway; only the guilty check should go red.{RESET}\n")
    restore = sc["seed"]()
    try:
        rows = _run_matrix()
    finally:
        restore()
    reds = [r["name"] for r in rows if not r["ok"]]
    localized = reds == [sc["expect"]]
    print()
    if localized:
        print(f"{GREEN}{BOLD}VERDICT: fault localized.{RESET} Only {BOLD}{sc['expect']}{RESET} "
              f"went red; the other {len(rows) - 1} checks stayed green.")
        print(f"{DIM}Each check falsifies a different claim, so the red one names the fault. Tree restored.{RESET}")
    else:
        print(f"{RED}{BOLD}VERDICT: not localized as expected.{RESET} "
              f"expected only [{sc['expect']}] red, got {reds}. Tree restored.")
    return {"scenario": key, "title": sc["title"], "checks": rows,
            "ok": localized, "localized": localized, "expected": sc["expect"], "reds": reds}


# -- report artifacts -------------------------------------------------------------


def _render_markdown(sections: list[dict], stamp: str) -> str:
    icon = lambda ok: "✅ pass" if ok else "❌ **fail**"
    out = ["## PayFlow pipeline showcase", "",
           f"_Every check runs; nothing stops at the first failure. Generated {stamp}._", ""]
    for s in sections:
        out.append(f"### {s['title']}")
        out.append("")
        out.append("| layer | check | result | detail | elapsed |")
        out.append("| --- | --- | --- | --- | --- |")
        for r in s["checks"]:
            out.append(f"| {r['layer']} | {r['name']} | {icon(r['ok'])} | {r['detail']} | {r['elapsed']}s |")
        out.append("")
        if s["scenario"] == "clean":
            verdict = f"✅ all {len(s['checks'])} checks green" if s["ok"] \
                else f"❌ {len(s['reds'])} red on a clean tree: {s['reds']}"
        else:
            verdict = (f"✅ fault localized to `{s['expected']}`; the other {len(s['checks']) - 1} checks stayed green"
                       if s["localized"] else f"❌ expected only `{s['expected']}` red, got {s['reds']}")
        out.append(f"**Verdict:** {verdict}")
        reds = [r for r in s["checks"] if not r["ok"]]
        if reds:
            out.append("")
            out.append("Red checks and why:")
            for r in reds:
                out.append(f"- `{r['name']}`: {r['reason']}")
        out.append("")
    return "\n".join(out)


def _write_report(directory: str, sections: list[dict], stamp: str) -> None:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": stamp, "sections": sections}
    (d / "showcase-report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (d / "showcase-report.md").write_text(_render_markdown(sections, stamp), encoding="utf-8")
    print(f"\n{DIM}report written: {d / 'showcase-report.json'}, {d / 'showcase-report.md'}{RESET}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="showcase", description="run the whole verify pipeline, soft")
    parser.add_argument("scenario", nargs="?", default="clean",
                        choices=["clean", "all", *_SCENARIOS], help="clean (default), a fault name, or all")
    parser.add_argument("--report", metavar="DIR", default=None,
                        help="also write showcase-report.json and showcase-report.md to DIR")
    args = parser.parse_args()

    if args.scenario == "clean":
        sections = [_section_clean()]
    elif args.scenario == "all":
        sections = [_section_clean(), *(_section_scenario(k) for k in _SCENARIOS)]
    else:
        sections = [_section_scenario(args.scenario)]

    if args.report:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_report(args.report, sections, stamp)

    return 0 if all(s["ok"] for s in sections) else 1


if __name__ == "__main__":
    sys.exit(main())
