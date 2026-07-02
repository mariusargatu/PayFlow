"""Shared Rich renderer for a property generation agent run, as a live DAG.

One renderer, two entry points: ``explain-run`` replays a finished run's
``report.json`` (deterministic, no LLM), and ``agent-run --view`` drives the same
graph live as the LangGraph pipeline streams node updates.

Liveness detail: LangGraph's update stream emits one chunk per node AFTER it
finishes, so the slow ``execute`` node (a Hypothesis pytest subprocess) would sit
with no feedback. The live view therefore drives a self refreshing renderable: a
spinner and an elapsed clock on the active node animate from Rich's refresh
thread while the main thread is blocked in the subprocess, and a "now" line names
what that node is doing. As each inference node completes, the proposals it
produced (rule / invariant / relation names) are listed, so you can read what was
proposed and what happens next.

No production code imports this; it is a presentation tool over run artifacts.
"""

from __future__ import annotations

import time

from rich.console import Console, Group
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

PIPELINE = [
    "ingest_spec",
    "infer_endpoint_rules",
    "infer_invariants",
    "infer_relations",
    "compile_spec",
    "execute",
    "triage",
    "refine",
    "report",
]

# What each node is doing, shown on the "now" line so the active step reads as
# working rather than stuck (execute is the slow one and says so).
NODE_JOB = {
    "ingest_spec": "parsing the OpenAPI document",
    "infer_endpoint_rules": "proposing a rule per endpoint (fan-out)",
    "infer_invariants": "proposing system wide invariants",
    "infer_relations": "proposing metamorphic relations",
    "compile_spec": "rendering proposals into a Hypothesis module",
    "execute": "running the properties through Hypothesis against the live SUT (slow step)",
    "triage": "classifying each falsification (real bug vs bad proposal)",
    "refine": "rewriting the offending proposal, then recompiling",
    "report": "writing the run report",
}

_ACCENT = "#a371f7"
_OK = "#3fb950"
_WARN = "#d29922"
_BAD = "#f85149"
_DIM = "grey58"

_GLYPH = {"done": ("✓", _OK), "active": ("◉", f"bold {_ACCENT}"), "pending": ("○", _DIM)}

_LAYOUT: list[list[tuple]] = [
    [("node", "ingest_spec", "ingest")],
    [("raw", "   │")],
    [("raw", "   ├─▶ "), ("node", "infer_endpoint_rules", "rules"), ("raw", "   (fan-out over endpoints)")],
    [("raw", "   │       "), ("endpoints", "", "")],
    [("raw", "   ▼")],
    [
        ("node", "infer_invariants", "invariants"), ("raw", " ─▶ "),
        ("node", "infer_relations", "relations"), ("raw", " ─▶ "),
        ("node", "compile_spec", "compile"),
    ],
    [("raw", "                                          │")],
    [("raw", "                                          ▼")],
    [
        ("raw", "   "), ("node", "report", "report"), ("raw", " ◀── "),
        ("node", "triage", "triage"), ("raw", " ◀────────  "),
        ("node", "execute", "execute"),
    ],
    [("raw", "                     │                      ▲")],
    [("raw", "                     └─▶ "), ("node", "refine", "refine"), ("raw", " ───────────┘")],
    [("raw", "                         "), ("loop", "", "")],
]


def _states_from(done: set[str], active: str | None) -> dict[str, str]:
    return {n: ("active" if n == active else ("done" if n in done else "pending")) for n in PIPELINE}


def _active_node(done: set[str]) -> str | None:
    for n in PIPELINE:
        if n not in done:
            return n
    return None


def _graph_text(states: dict[str, str], endpoints: list[str], iterations: int) -> Text:
    t = Text()
    for row in _LAYOUT:
        for seg in row:
            if seg[0] == "raw":
                t.append(seg[1], style=_DIM)
            elif seg[0] == "node":
                _, key, display = seg
                glyph, style = _GLYPH[states.get(key, "pending")]
                t.append(f"{glyph} {display}", style=style)
            elif seg[0] == "endpoints":
                if endpoints:
                    short = [e.replace("PaymentIntent", "").replace("Payment", "") for e in endpoints]
                    shown = " ".join(short[:5])
                    if len(endpoints) > 5:
                        shown += f" +{len(endpoints) - 5}"
                    t.append(shown[:58], style=_DIM)
            elif seg[0] == "loop":
                st = states.get("refine", "pending")
                mark = "↺" if st != "pending" else " "
                t.append(f"loop {mark} ×{iterations}", style=_ACCENT if iterations else _DIM)
        t.append("\n")
    return t


def _now_line(active: str | None, elapsed: float | None, exec_events: list[tuple]) -> Group | None:
    if active is None:
        return None
    g = Table.grid(padding=(0, 1))
    g.add_column(width=2)
    g.add_column()
    clock = f"  ({elapsed:.0f}s)" if elapsed is not None else ""
    msg = Text(f"{active}: {NODE_JOB.get(active, '')}{clock}", style=_ACCENT)
    g.add_row(Spinner("dots", style=_ACCENT), msg)
    # During execute, list each property as pytest resolves it (live).
    if active == "execute" and exec_events:
        checks = Text()
        for name, outcome in exec_events[-8:]:
            ok = outcome == "PASSED"
            label = "state machine (rules + invariants)" if name == "runTest" else name.replace("test_", "")
            checks.append("  ✓ " if ok else "  ✕ ", style=_OK if ok else _BAD)
            checks.append(f"{label}\n", style=_DIM)
        return Group(g, checks)
    return g


def _proposals_panel(rules: list, invariants: list, relations: list) -> Panel | None:
    if not (rules or invariants or relations):
        return None

    def name_of(p) -> str:
        return p.get("name", "") if isinstance(p, dict) else getattr(p, "name", str(p))

    def id_of(p) -> str:
        return p.get("id", "") if isinstance(p, dict) else getattr(p, "id", "")

    def fee_of(p) -> str:
        v = p.get("fee_handling", "") if isinstance(p, dict) else getattr(p, "fee_handling", "")
        return f" ({v})" if v else ""

    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold", justify="right")
    t.add_column(overflow="fold")
    if rules:
        t.add_row("rules", Text(", ".join(name_of(r) for r in rules), style=_DIM))
    if invariants:
        t.add_row("invariants", Text(", ".join(f"{id_of(i)} {name_of(i)}".strip() for i in invariants), style=_OK))
    if relations:
        t.add_row("relations", Text(", ".join(f"{id_of(r)} {name_of(r)}{fee_of(r)}".strip() for r in relations), style=_ACCENT))
    return Panel(t, title="proposed properties", border_style=_DIM, padding=(0, 1))


def _stats(funnel: dict, cost: dict) -> Table:
    rules = funnel.get("proposed_rules", 0)
    inv = funnel.get("proposed_invariants", 0)
    rel = funnel.get("proposed_relations", 0)
    total = funnel.get("proposed_total", rules + inv + rel)
    survived = funnel.get("survived_falsification", 0)
    real = funnel.get("flagged_real_bug", []) or []
    human = funnel.get("flagged_needs_human", []) or []

    width = 22
    filled = 0 if total <= 0 else round(width * survived / total)
    bar = Text()
    bar.append("█" * filled, style=_OK)
    bar.append("█" * (width - filled), style=_DIM)
    bar.append(f"  {survived}/{total} survived", style=_DIM)

    t = Table.grid(padding=(0, 3))
    t.add_column(style="bold", justify="right")
    t.add_column()
    t.add_row("proposed", Text(f"{total}  ({rules}r {inv}i {rel}m)", style=_ACCENT))
    t.add_row("survived", bar)
    if real:
        t.add_row("real bugs", Text(", ".join(real), style=_BAD))
    if human:
        t.add_row("needs human", Text(", ".join(human), style=_WARN))
    c = cost or {}
    t.add_row(
        "cost",
        Text(
            f"{c.get('model', '?')}   {c.get('calls', 0)}/{c.get('max_calls', 0)} calls   "
            f"{c.get('total_tokens', 0):,} tok   ${c.get('approx_cost_usd', 0.0):.4f}",
            style=_DIM,
        ),
    )
    return t


def _triage_panel(verdicts: list[dict]) -> Panel | None:
    if not verdicts:
        return None
    colors = {"real_bug": _BAD, "bad_rule": _WARN, "bad_invariant": _WARN, "bad_relation": _WARN, "needs_human": _ACCENT}
    t = Table(show_header=True, header_style=_DIM, box=None, padding=(0, 2))
    t.add_column("failure")
    t.add_column("verdict")
    t.add_column("reasoning", overflow="fold", max_width=56)
    for v in verdicts:
        cls = v.get("classification", "?")
        t.add_row(
            Text(v.get("failure_ref", "?")),
            Text(cls, style=colors.get(cls, _DIM)),
            Text((v.get("reasoning", "") or "").strip()[:150], style=_DIM),
        )
    return Panel(t, title="triage verdicts", border_style=_DIM, padding=(0, 1))


def _compose(states, endpoints, funnel, cost, verdicts, proposals, now, aborted) -> Group:
    title = Text("PayFlow agent run", style=f"bold {_ACCENT}")
    if aborted:
        title.append(f"   ABORTED: {aborted}", style=_BAD)
    parts = [title, Panel(_graph_text(states, endpoints, funnel.get("iterations_used", 0)),
                          title="pipeline", border_style=_DIM, padding=(1, 2))]
    if now is not None:
        parts.append(now)
    prop = _proposals_panel(*proposals)
    if prop:
        parts.append(prop)
    parts.append(Panel(_stats(funnel, cost), title="run", border_style=_DIM, padding=(0, 1)))
    tri = _triage_panel(verdicts)
    if tri:
        parts.append(tri)
    return Group(*parts)


def render_report(report: dict, console: Console | None = None) -> None:
    """Static render of a finished run (explain-run): no spinner, no now line."""
    console = console or Console()
    aborted = report.get("abort_reason", "") if report.get("aborted") else None
    done = set() if report.get("aborted") else set(PIPELINE)
    console.print(_compose(
        _states_from(done, None),
        report.get("endpoints", []) or [],
        report.get("funnel", {}),
        report.get("cost", {}),
        report.get("triaged_failures", []) or [],
        (report.get("proposed_rules", []), report.get("proposed_invariants", []), report.get("proposed_relations", [])),
        None,
        aborted,
    ))


class _Refreshing:
    """A renderable Rich re renders every refresh tick, so the spinner and the
    elapsed clock advance while the main thread is blocked inside a node."""

    def __init__(self, view: "LiveRunView") -> None:
        self._view = view

    def __rich__(self):
        return self._view._compose_live()


class LiveRunView:
    """Drives the DAG live as agent-run streams node updates."""

    def __init__(self) -> None:
        from rich.live import Live

        self._console = Console()
        self._done: set[str] = set()
        self._endpoints: list[str] = []
        self._funnel: dict = {}
        self._cost: dict = {}
        self._triage: list[dict] = []
        self._rules: list = []
        self._invariants: list = []
        self._relations: list = []
        self._exec_events: list[tuple] = []
        self._active: str | None = "ingest_spec"
        self._active_since = time.monotonic()
        self._live = Live(_Refreshing(self), console=self._console, refresh_per_second=10)

    def __enter__(self) -> "LiveRunView":
        self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self._active = None
        self._live.__exit__(*exc)

    def _compose_live(self) -> Group:
        elapsed = time.monotonic() - self._active_since if self._active else None
        return _compose(
            _states_from(self._done, self._active),
            self._endpoints, self._funnel, self._cost, self._triage,
            (self._rules, self._invariants, self._relations),
            _now_line(self._active, elapsed, self._exec_events),
            None,
        )

    def _set_active(self, node: str | None) -> None:
        if node != self._active:
            self._active = node
            self._active_since = time.monotonic()
            if node == "execute":  # fresh list each execute (refine loops re run it)
                self._exec_events = []

    def on_progress(self, kind: str, payload: dict) -> None:
        """Progress sink passed to the execute node: one call per property outcome."""
        if kind == "execute_test":
            self._exec_events.append((payload.get("name", "?"), payload.get("outcome", "?")))

    def on_node(self, name: str, state: dict) -> None:
        self._done.add(name)
        self._set_active(_active_node(self._done))
        if state.get("endpoints"):
            self._endpoints = [
                e.get("operation_id", "") if isinstance(e, dict) else getattr(e, "operation_id", str(e))
                for e in state["endpoints"]
            ]
        if state.get("proposed_rules"):
            self._rules = list(state["proposed_rules"])
        if state.get("proposed_invariants"):
            self._invariants = list(state["proposed_invariants"])
        if state.get("proposed_relations"):
            self._relations = list(state["proposed_relations"])
        if state.get("cost"):
            self._cost = state["cost"]
        if state.get("triaged_failures"):
            self._triage = [v.model_dump() if hasattr(v, "model_dump") else v for v in state["triaged_failures"]]
        self._funnel = self._partial_funnel(state)

    def _partial_funnel(self, state: dict) -> dict:
        res = state.get("hypothesis_results")
        total = len(self._rules) + len(self._invariants) + len(self._relations)
        merged = dict(self._funnel)
        merged.update({
            "proposed_rules": len(self._rules),
            "proposed_invariants": len(self._invariants),
            "proposed_relations": len(self._relations),
            "proposed_total": total,
        })
        if res is not None:
            merged["survived_falsification"] = max(0, total - len(getattr(res, "failures", []) or []))
        if "iteration" in state:
            merged["iterations_used"] = state["iteration"]
        return merged

    def finish(self, report: dict) -> None:
        self._done = set(PIPELINE) if not report.get("aborted") else self._done
        self._active = None
        self._funnel = report.get("funnel", self._funnel)
        self._cost = report.get("cost", self._cost)
        self._triage = report.get("triaged_failures", self._triage) or self._triage
        self._rules = report.get("proposed_rules", self._rules) or self._rules
        self._invariants = report.get("proposed_invariants", self._invariants) or self._invariants
        self._relations = report.get("proposed_relations", self._relations) or self._relations
