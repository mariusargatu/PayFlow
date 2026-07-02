"""`uv run trust-report`: render the self contained trust report (design §17.3).

One HTML file, no external assets, no server, dark friendly, viewable from a
file:// URL. Everything on it comes from real artifacts:

  - per gate status, by running demo's own fast gate set
  - the invariant/relation discovery funnel, per agent_runs/*/report.json over time
  - the Layer 3 mutation kill rates (headline + full) from mutation/baseline.json
  - the agent graph, from the committed agent/graph.mmd

The committed output (site/trust-report.html) is checked in so the repo shows the
report without anyone running anything; regenerate it with `uv run trust-report`.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.demo import GATES, _run

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "site" / "trust-report.html"
_BASELINE = _ROOT / "mutation" / "baseline.json"
_GRAPH_MMD = _ROOT / "agent" / "graph.mmd"
_AGENT_RUNS = _ROOT / "agent_runs"

_BG = "#0d1117"
_PANEL = "#161b22"
_INK = "#e6edf3"
_MUTE = "#8b949e"
_GREEN = "#3fb950"
_RED = "#f85149"
_ACCENT = "#a371f7"
_BAR_BG = "#21262d"


def _gate_rows() -> tuple[list[dict], bool]:
    rows: list[dict] = []
    all_ok = True
    for layer, name, cmd, counter in GATES:
        ok, output, elapsed = _run(cmd)
        all_ok = all_ok and ok
        rows.append(
            {"layer": layer, "name": name, "ok": ok, "detail": counter(output), "elapsed": elapsed}
        )
    return rows, all_ok


def _load_baseline() -> dict | None:
    if not _BASELINE.exists():
        return None
    try:
        return json.loads(_BASELINE.read_text())
    except json.JSONDecodeError:
        return None


def _funnel_runs() -> list[dict]:
    runs = []
    for report in sorted(_AGENT_RUNS.glob("*/report.json")):
        try:
            data = json.loads(report.read_text())
        except json.JSONDecodeError:
            continue
        funnel = data.get("funnel")
        if not funnel or not funnel.get("proposed_total"):
            continue
        runs.append(
            {
                "run": report.parent.name,
                "model": data.get("model", "?"),
                "rules": funnel.get("proposed_rules", 0),
                "invariants": funnel.get("proposed_invariants", 0),
                "relations": funnel.get("proposed_relations", 0),
                "proposed": funnel.get("proposed_total", 0),
                "survived": funnel.get("survived_falsification", 0),
                "flagged": funnel.get("flagged_real_bug", []) or [],
                "iterations": funnel.get("iterations_used", 0),
            }
        )
    return runs


# -- HTML fragments ---------------------------------------------------------


def _badge(ok: bool) -> str:
    color = _GREEN if ok else _RED
    word = "PASS" if ok else "FAIL"
    return f'<span style="background:{color};color:{_BG};padding:2px 10px;border-radius:10px;font-weight:700;font-size:12px">{word}</span>'


def _bar(value: float, total: float, color: str, width: int = 260) -> str:
    frac = 0.0 if total <= 0 else max(0.0, min(1.0, value / total))
    filled = int(width * frac)
    return (
        f'<span style="display:inline-block;width:{width}px;height:12px;background:{_BAR_BG};'
        f'border-radius:6px;overflow:hidden;vertical-align:middle">'
        f'<span style="display:block;width:{filled}px;height:12px;background:{color}"></span></span>'
    )


def _gates_section(rows: list[dict], all_ok: bool) -> str:
    body = "".join(
        f'<tr><td style="color:{_MUTE}">{html.escape(r["layer"])}</td>'
        f"<td>{html.escape(r['name'])}</td>"
        f"<td>{_badge(r['ok'])}</td>"
        f'<td style="color:{_MUTE}">{html.escape(r["detail"])}</td>'
        f'<td style="color:{_MUTE};text-align:right">{r["elapsed"]:.2f}s</td></tr>'
        for r in rows
    )
    verdict = _badge(all_ok) + (
        " all fast gates green" if all_ok else " a gate is red"
    )
    return (
        f"<h2>Gate status</h2><p style='color:{_MUTE}'>Run live when this report was "
        f"generated. Layer 0 structural, drift, and Layer 1 replay slice.</p>"
        f"<p>{verdict}</p>"
        "<table><thead><tr><th>layer</th><th>gate</th><th>result</th><th>detail</th>"
        "<th style='text-align:right'>elapsed</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _mutation_section(baseline: dict | None) -> str:
    if baseline is None:
        return (
            "<h2>Layer 3 - mutation kill rate</h2>"
            f"<p style='color:{_MUTE}'>No baseline yet. Run "
            "<code>uv run python mutation/run_baseline.py</code>.</p>"
        )
    runs = baseline.get("runs", {})
    cards = []
    labels = {
        "headline": "Headline: agent discovered suites only (zero hand written tests)",
        "full": "Full local suite (agent suites + Phase 1 sanity machine)",
    }
    for key in ("headline", "full"):
        r = runs.get(key)
        if not r:
            continue
        pct = r["kill_rate_pct"]
        color = _GREEN if pct >= 80 else (_ACCENT if pct >= 60 else _RED)
        cards.append(
            f'<div style="background:{_PANEL};border:1px solid {_BAR_BG};border-radius:10px;'
            'padding:16px 18px;margin:8px 0">'
            f'<div style="color:{_MUTE};font-size:13px">{html.escape(labels[key])}</div>'
            f'<div style="font-size:40px;font-weight:800;color:{color};line-height:1.1">{pct}%</div>'
            f'<div style="margin:6px 0">{_bar(r["detected"], r["covered"], color)}</div>'
            f'<div style="color:{_MUTE};font-size:13px">'
            f'detected {r["detected"]} / {r["covered"]} covered '
            f'&middot; {r["survived"]} survived &middot; {r["no_tests"]} no-test '
            f'&middot; {r["total"]} generated &middot; {r["runtime_seconds"]}s</div></div>'
        )
    scope = ", ".join(html.escape(s) for s in baseline.get("scope", []))
    return (
        "<h2>Layer 3 - mutation kill rate</h2>"
        f"<p style='color:{_MUTE}'>Ground truth: how many injected bugs the suite "
        f"actually catches. Scope {scope}. Kill rate is killed / covered; no-test "
        f"mutants (paths a suite never exercises) are shown, not hidden. "
        f"Baseline (nightly recomputes) generated {html.escape(baseline.get('generated_at',''))}.</p>"
        + "".join(cards)
    )


def _funnel_section(runs: list[dict]) -> str:
    if not runs:
        return "<h2>Discovery funnel</h2><p>No agent runs found.</p>"
    rows = []
    for r in runs:
        flagged = ", ".join(html.escape(x) for x in r["flagged"]) or "-"
        rows.append(
            f'<tr><td style="color:{_MUTE};font-family:monospace;font-size:12px">{html.escape(r["run"])}</td>'
            f"<td>{r['rules']}r / {r['invariants']}i / {r['relations']}m</td>"
            f'<td>{r["proposed"]}</td>'
            f'<td>{_bar(r["survived"], r["proposed"], _GREEN, 160)} '
            f'<span style="color:{_MUTE}">{r["survived"]}/{r["proposed"]}</span></td>'
            f'<td style="color:{_ACCENT}">{flagged}</td>'
            f'<td style="color:{_MUTE};text-align:right">{r["iterations"]}</td></tr>'
        )
    return (
        "<h2>Discovery funnel</h2>"
        f"<p style='color:{_MUTE}'>Per agent run: what the agent proposed, how much "
        "survived Hypothesis falsification, and what it flagged as a real bug. "
        "r=rules, i=invariants, m=metamorphic relations.</p>"
        "<table><thead><tr><th>run</th><th>proposed (r/i/m)</th><th>total</th>"
        "<th>survived falsification</th><th>flagged real bug</th>"
        "<th style='text-align:right'>refine iters</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _graph_section() -> str:
    if not _GRAPH_MMD.exists():
        return ""
    mmd = html.escape(_GRAPH_MMD.read_text())
    return (
        "<h2>The property generation agent</h2>"
        f"<p style='color:{_MUTE}'>Rendered from the committed <code>agent/graph.mmd</code> "
        "(itself drift gated against LangGraph's own draw_mermaid output). Paste into "
        "any Mermaid viewer to see the graph.</p>"
        f'<pre style="background:{_PANEL};border:1px solid {_BAR_BG};border-radius:10px;'
        f'padding:14px;overflow:auto;color:{_INK};font-size:12px">{mmd}</pre>'
    )


def build_html() -> str:
    rows, all_ok = _gate_rows()
    baseline = _load_baseline()
    funnel = _funnel_runs()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    style = (
        f"body{{background:{_BG};color:{_INK};font-family:-apple-system,Segoe UI,Roboto,"
        "Helvetica,Arial,sans-serif;max-width:900px;margin:0 auto;padding:32px 20px;"
        "line-height:1.5}"
        f"h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:19px;margin:32px 0 8px;"
        f"border-bottom:1px solid {_BAR_BG};padding-bottom:6px}}"
        "table{border-collapse:collapse;width:100%;margin:8px 0}"
        f"th{{text-align:left;color:{_MUTE};font-size:12px;font-weight:600;"
        f"border-bottom:1px solid {_BAR_BG};padding:6px 10px}}"
        f"td{{padding:8px 10px;border-bottom:1px solid {_BAR_BG};font-size:14px}}"
        f"code{{background:{_PANEL};padding:1px 5px;border-radius:4px;font-size:13px}}"
        f"a{{color:{_ACCENT}}}"
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>PayFlow trust report</title><style>{style}</style></head><body>"
        "<h1>PayFlow trust report</h1>"
        f"<p style='color:{_MUTE}'>A trustworthy agentic SDLC, measured. Generated "
        f"{generated}. Self contained, no external assets.</p>"
        + _mutation_section(baseline)
        + _gates_section(rows, all_ok)
        + _funnel_section(funnel)
        + _graph_section()
        + "</body></html>"
    )


def main() -> int:
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(build_html(), encoding="utf-8")
    print(f"trust-report: wrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
