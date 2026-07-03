"""execute node: run the compiled spec via pytest and capture falsifications.

Deterministic (no LLM). Runs the generated module in a pytest subprocess against
the live SUT, then parses the output into structured ``Failure`` records. Each
generated assertion carries a ``[RULE name]`` or ``[INV-x]`` tag, so a failure
maps back to the exact proposal for triage. The shrunk counterexample is the
Hypothesis reproduction block.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from ..schemas import Failure, TestRunResult
from ..state import AgentState

_ASSERTION = re.compile(r"AssertionError:\s*(\[(?:RULE|INV|MR)[^\n]*)")
_TAG = re.compile(r"\[(RULE|INV|MR)([^\]]*)\]")
_COUNTEREXAMPLE = re.compile(
    r"((?:Falsifying example|Steps leading up to this error):.*?)(?:\n\n|\n====|\Z)",
    re.DOTALL,
)


def _classify_tag(message: str) -> tuple[str, str]:
    match = _TAG.search(message)
    if not match:
        return "rule", "<unparsed>"
    family, rest = match.group(1), match.group(2).strip()
    if family == "INV":
        return "invariant", f"INV{rest}"
    if family == "MR":
        return "relation", f"MR{rest}"
    return "rule", rest


def parse_pytest_output(output: str, returncode: int) -> TestRunResult:
    if returncode == 0:
        return TestRunResult(passed=True, output_tail=_tail(output))

    # Each failing property prints its own counterexample block (Hypothesis
    # "Falsifying example" or the state machine "Steps leading up to this error")
    # just before its tagged AssertionError. Associate each assertion with the
    # nearest preceding block, so a multi failure run does not hand every failure
    # the first failure's reproduction (which would misdirect triage and refine).
    ce_blocks = [(m.start(), m.group(1).strip()) for m in _COUNTEREXAMPLE.finditer(output)]

    def _counterexample_before(pos: int) -> str:
        block = ""
        for start, text in ce_blocks:
            if start < pos:
                block = text
            else:
                break
        return block

    failures: list[Failure] = []
    seen: set[str] = set()
    for match in _ASSERTION.finditer(output):
        message = match.group(1).strip()
        kind, proposal_id = _classify_tag(message)
        dedupe = f"{kind}:{proposal_id}"
        if dedupe in seen:
            continue
        seen.add(dedupe)
        failures.append(
            Failure(
                kind=kind,
                proposal_id=proposal_id,
                message=message,
                counterexample=_counterexample_before(match.start()),
            )
        )

    if not failures:
        # A non zero exit with no tagged assertion means the module could not run
        # (import error, no server, collection error) rather than a SUT bug.
        return TestRunResult(
            passed=False,
            failures=[
                Failure(
                    kind="rule",
                    proposal_id="<execution_error>",
                    message="compiled spec failed to run (see output_tail)",
                    counterexample=ce_blocks[0][1] if ce_blocks else "",
                )
            ],
            output_tail=_tail(output),
            error="execution_error",
        )
    return TestRunResult(passed=False, failures=failures, output_tail=_tail(output))


def _tail(output: str, lines: int = 40) -> str:
    return "\n".join(output.strip().splitlines()[-lines:])


_RESULT_LINE = re.compile(r"::([\w\[\]-]+)\s+(PASSED|FAILED|ERROR)")


def _run_pytest(paths, env, on_progress) -> tuple[str, int]:
    """Run pytest, streaming per test outcomes to on_progress if present.

    Uses -v and reads stdout line by line so a live view can report each property
    as it resolves. Behaviour is identical to a blocking run when on_progress is
    None: the same combined output and return code feed parse_pytest_output.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", *paths, "-v", "-p", "no:cacheprovider"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        if on_progress is not None:
            m = _RESULT_LINE.search(line)
            if m:
                on_progress("execute_test", {"name": m.group(1), "outcome": m.group(2)})
    proc.wait()
    return "".join(lines), proc.returncode


def execute(state: AgentState, deps) -> dict:
    # Run the rule/invariant spec and, when present, the metamorphic relation
    # module in one pytest invocation against the same live server (they scope to
    # entities they each create, so sharing the server is safe). MR tags are
    # parsed alongside RULE/INV tags, so a relation failure routes through the same
    # triage -> refine loop.
    paths = [state["generated_spec_path"]]
    mr_path = state.get("generated_mr_path")
    if mr_path:
        paths.append(mr_path)
    env = dict(os.environ)
    env["PAYFLOW_SUT_BASE_URL"] = state["sut_base_url"]
    env["PAYFLOW_CAPTURE_FEE"] = str(deps.config.capture_fee)
    output, returncode = _run_pytest(paths, env, getattr(deps, "on_progress", None))
    result = parse_pytest_output(output, returncode)
    note = (
        "execute: all properties held"
        if result.passed
        else f"execute: {len(result.failures)} failing proposal(s): "
        + ", ".join(f.tag() for f in result.failures)
    )
    return {"hypothesis_results": result, "history": [note]}
