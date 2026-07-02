"""`uv run build-report`: render the self contained trust report (design §17.3).

One HTML file, no external assets, no server, dark friendly, viewable from a
file:// URL. Everything on it comes from real artifacts:

  - per gate status, by running demo's own fast gate set
  - the invariant/relation discovery funnel, per agent_runs/*/report.json over time
  - the Layer 3 mutation kill rates (headline + full) from mutation/baseline.json
  - the agent graph, from the committed agent/graph.mmd

The report is folded into site/index.html between its markers, so the project is
one page. Regenerate with `uv run build-report`.

The visual system matches site/index.html: mono terminal aesthetic, amber on a
dark tinted background, system fonts only (no webfont dependency).
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from tools.demo import GATES, _run

_ROOT = Path(__file__).resolve().parents[1]
_BASELINE = _ROOT / "mutation" / "baseline.json"
_GRAPH_MMD = _ROOT / "agent" / "graph.mmd"
_AGENT_RUNS = _ROOT / "agent_runs"

# palette shared with site/index.html
_BG = "#0A0E14"
_SURFACE = "#10151D"
_SURFACE2 = "#141A24"
_LINE = "rgba(255,255,255,.09)"
_LINE2 = "rgba(255,255,255,.17)"
_INK = "#E8EBF0"
_INK2 = "#9AA3B2"
_INK3 = "#7C8698"
_AMBER = "#D9A441"
_GREEN = "#4FAE7C"
_RED = "#E0645A"


# -- data (unchanged) -------------------------------------------------------


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


def _decompose(items: list | None, category: str) -> list[tuple[str, str]]:
    """(name, plain English sentence) for each proposed check, skipping any the
    glossary cannot map. Used to open the r/i/m counts into readable checks."""
    from tools.labels import describe

    out = []
    for it in items or []:
        name = (it.get("name") or it.get("id") or "") if isinstance(it, dict) else ""
        plain = describe(category, it)
        if plain:
            out.append((name, plain))
    return out


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
                # The triage reasoning per flagged bug: the plain English of why it
                # is a real bug, so the report explains the finding, not just its id.
                "flagged_why": {
                    t.get("failure_ref"): t.get("reasoning", "")
                    for t in data.get("triaged_failures", [])
                    if t.get("classification") == "real_bug"
                },
                # Plain English decomposition: each proposed check -> (name, layperson
                # sentence), so the r/i/m counts open up into what they actually verify.
                "decomp": {
                    "rules": _decompose(data.get("proposed_rules"), "rules"),
                    "invariants": _decompose(data.get("proposed_invariants"), "invariants"),
                    "relations": _decompose(data.get("proposed_relations"), "relations"),
                },
                "iterations": funnel.get("iterations_used", 0),
            }
        )
    return runs


# -- presentation (matches site/index.html) ---------------------------------


def _kill_color(pct: float) -> str:
    return _GREEN if pct >= 80 else (_AMBER if pct >= 60 else _RED)


def _badge(ok: bool) -> str:
    kind = "block" if ok else "fail"
    return f'<span class="badge {kind}">{"PASS" if ok else "FAIL"}</span>'


def _bar(value: float, total: float, color: str) -> str:
    frac = 0.0 if total <= 0 else max(0.0, min(1.0, value / total))
    return (
        f'<span class="bar"><span class="bar-fill" '
        f'style="width:{frac * 100:.1f}%;background:{color}"></span></span>'
    )


def _stacked_bar(killed: int, survived: int, no_tests: int) -> str:
    """Killed vs survived vs never covered, as one honest proportion bar."""
    total = max(1, killed + survived + no_tests)
    seg = lambda n, c: (
        f'<span style="width:{n / total * 100:.2f}%;background:{c}"></span>' if n else ""
    )
    return (
        '<span class="stack" role="img" aria-label="'
        f'{killed} killed, {survived} survived, {no_tests} never covered">'
        f"{seg(killed, _GREEN)}{seg(survived, _RED)}{seg(no_tests, _INK3)}</span>"
    )


def _metrics(baseline: dict | None, all_ok: bool, funnel: list[dict]) -> str:
    headline = (baseline or {}).get("runs", {}).get("headline")
    # Distinct headline metrics only: the kill rate lives here once (its full
    # breakdown is the mutation section, not repeated here), plus three numbers
    # that appear nowhere else in the header.
    bugs_caught = len({ref for r in funnel for ref in r.get("flagged", [])})
    cells = []
    if headline:
        cells.append(
            f'<div class="metric"><div class="n"><span class="amber">'
            f'{headline["kill_rate_pct"]}%</span></div>'
            '<div class="l">mutation kill rate, zero hand written tests</div></div>'
        )
    cells.append(
        f'<div class="metric"><div class="n" style="color:{_GREEN if all_ok else _RED}">'
        f'{"PASS" if all_ok else "FAIL"}</div>'
        '<div class="l">fast gates, run live just now</div></div>'
    )
    cells.append(
        f'<div class="metric"><div class="n">{bugs_caught}</div>'
        '<div class="l">real bugs the properties caught</div></div>'
    )
    cells.append(
        f'<div class="metric"><div class="n">{len(funnel)}</div>'
        '<div class="l">recorded agent discovery runs</div></div>'
    )
    return f'<div class="metrics">{"".join(cells)}</div>'


def _mutation_section(baseline: dict | None) -> str:
    if baseline is None:
        return (
            '<section id="mutation" class="rule"><p class="kicker">Layer 3 mutation</p>'
            "<h2>No baseline yet.</h2>"
            '<p class="lead">Run <code>uv run python mutation/run_baseline.py</code> '
            "to generate one.</p></section>"
        )
    runs = baseline.get("runs", {})
    labels = {
        "headline": "Agent discovered suites only, zero hand written tests",
        "full": "Full local suite, agent suites plus the Phase 1 sanity machine",
    }
    cards = []
    for key in ("headline", "full"):
        r = runs.get(key)
        if not r:
            continue
        pct = r["kill_rate_pct"]
        color = _kill_color(pct)
        cards.append(
            '<div class="fig" style="padding:20px 22px">'
            f'<div class="mut-label">{html.escape(labels[key])}</div>'
            f'<div class="mut-pct" style="color:{color}">{pct}%</div>'
            f'{_stacked_bar(r["killed"], r["survived"], r["no_tests"])}'
            '<div class="mut-legend">'
            f'<span><i style="background:{_GREEN}"></i>{r["killed"]} killed</span>'
            f'<span><i style="background:{_RED}"></i>{r["survived"]} survived</span>'
            f'<span><i style="background:{_INK3}"></i>{r["no_tests"]} never covered</span>'
            "</div>"
            f'<div class="mut-foot">{r["detected"]} detected / {r["covered"]} covered '
            f'&middot; {r["total"]} generated &middot; {r["runtime_seconds"]}s</div></div>'
        )
    scope = ", ".join(html.escape(s) for s in baseline.get("scope", []))
    return (
        '<section id="mutation" class="rule"><p class="kicker">Layer 3 mutation ground truth</p>'
        "<h2>How many injected bugs the suite actually kills.</h2>"
        f'<p class="lead">Kill rate is killed over covered. Mutants on paths a suite never '
        f"exercises are shown, not folded in to flatter the number. Scope: "
        f'<span class="mono">{scope}</span>. Baseline generated '
        f'{html.escape(baseline.get("generated_at", ""))}, nightly recomputes.</p>'
        f'<div class="two-up">{"".join(cards)}</div></section>'
    )


def _funnel_section(runs: list[dict]) -> str:
    if not runs:
        return (
            '<section id="funnel" class="rule"><p class="kicker">Discovery funnel</p>'
            "<h2>No agent runs recorded yet.</h2></section>"
        )
    from tools.labels import PROPERTY_LABELS

    def _tip(r: dict) -> str:
        return html.escape(
            f'{r["rules"]} {PROPERTY_LABELS["rules"][0]}, '
            f'{r["invariants"]} {PROPERTY_LABELS["invariants"][0]}, '
            f'{r["relations"]} {PROPERTY_LABELS["relations"][0]}'
        )

    def _flagged_cell(r: dict) -> str:
        if not r["flagged"]:
            return "&mdash;"
        why = r.get("flagged_why", {})
        items = []
        for ref in r["flagged"]:
            # humanise the id: "rule:capture_over_limit" -> "capture over limit"
            label = ref.split(":", 1)[-1].replace("_", " ")
            reason = html.escape(why.get(ref, ""))
            items.append(
                f'<div title="{reason}"><span style="color:{_AMBER}">{html.escape(label)}</span>'
                + (f'<div style="color:{_INK3};font-size:12px;line-height:1.4">{reason}</div>' if reason else "")
                + "</div>"
            )
        return "".join(items)

    from tools.labels import counts_phrase

    # Category legend (what the three kinds of check mean, in plain terms).
    chips = "".join(
        '<div style="background:var(--surface);border:1px solid var(--line);'
        'border-radius:8px;padding:10px 12px">'
        f'<div class="mono" style="font-size:12px;color:var(--ink);font-weight:700">{html.escape(name)}</div>'
        f'<div style="font-size:12.5px;color:var(--ink-2);margin-top:3px">{html.escape(gloss)}</div>'
        f'<div class="mono" style="font-size:11.5px;color:var(--ink-3);margin-top:3px">{html.escape(ex)}</div></div>'
        for _k, (name, gloss, ex) in PROPERTY_LABELS.items()
    )
    legend = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));'
        f'gap:10px;margin:14px 0 24px">{chips}</div>'
    )

    # -- the funnel flow for the latest run: proposed -> survived --------------
    f = runs[-1]
    proposed, survived = f["proposed"], f["survived"]
    surv_pct = 0 if proposed <= 0 else survived / proposed * 100

    def _stage(label: str, count: int, width: float, color: str, sub: str) -> str:
        return (
            '<div style="display:flex;align-items:center;gap:14px;margin:6px 0">'
            f'<span class="mono" style="color:var(--ink-3);width:96px;flex:none">{label}</span>'
            '<span style="flex:1;background:var(--surface-2);border-radius:6px;overflow:hidden">'
            f'<span style="display:block;height:26px;width:{width:.1f}%;background:{color}"></span></span>'
            f'<span class="mono" style="width:34px;text-align:right;flex:none">{count}</span></div>'
            f'<div style="margin:2px 0 0 110px;color:var(--ink-2);font-size:13px">{sub}</div>'
        )

    funnel = (
        f'<div style="border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin:4px 0 20px">'
        f'<div class="mono" style="font-size:12px;color:var(--ink-3);margin-bottom:10px">latest run &middot; {html.escape(f["run"])} &middot; {html.escape(f["model"])}</div>'
        + _stage("PROPOSED", proposed, 100.0, _AMBER, counts_phrase(f["rules"], f["invariants"], f["relations"]))
        + f'<div style="margin:8px 0 8px 110px;color:var(--ink-3);font-size:12.5px">&darr; Hypothesis falsifies, refine rewrites ({f["iterations"]} pass{"es" if f["iterations"] != 1 else ""})</div>'
        + _stage("SURVIVED", survived, surv_pct, _GREEN, "accepted into the spec")
        + "</div>"
    )

    # -- decompose the counts into plain English, one line per distinct check ---
    def _decomp_block(run: dict) -> str:
        cats = run.get("decomp", {})
        out = ""
        for cat_key in ("rules", "invariants", "relations"):
            items = cats.get(cat_key, [])
            if not items:
                continue
            groups: dict[str, list[str]] = {}
            for nm, plain in items:
                groups.setdefault(plain, []).append(nm)
            lines = "".join(
                f'<li style="margin:5px 0">{html.escape(plain)}'
                + (
                    f' <span class="mono" style="color:var(--ink-3);font-size:11.5px">'
                    f'({", ".join(html.escape(n) for n in names if n)})</span>'
                    if any(names)
                    else ""
                )
                + "</li>"
                for plain, names in groups.items()
            )
            out += (
                f'<div style="margin:12px 0"><div class="mono" style="color:var(--ink-2);'
                f'font-size:12.5px;font-weight:600">{html.escape(PROPERTY_LABELS[cat_key][0])}</div>'
                f'<ul style="margin:4px 0 0;padding-left:18px;color:var(--ink)">{lines}</ul></div>'
            )
        return out

    decomp = _decomp_block(f)
    decomp_html = (
        '<details open style="margin:8px 0 16px;background:var(--surface);border:1px solid var(--line);'
        'border-radius:12px;padding:6px 20px 16px">'
        f'<summary style="cursor:pointer;color:{_AMBER};font-size:16px;font-weight:600;padding:12px 0">'
        "What these checks actually verify, in plain English</summary>"
        f'<div style="font-size:14.5px;line-height:1.6;border-left:2px solid var(--line);padding-left:18px">{decomp}</div>'
        "</details>"
        if decomp
        else ""
    )

    # -- real bugs the properties caught, aggregated across all runs -----------
    bugs: dict[str, str] = {}
    for r in runs:
        for ref in r["flagged"]:
            bugs.setdefault(ref, r.get("flagged_why", {}).get(ref, ""))
    bugs_html = ""
    if bugs:
        cards = "".join(
            '<div style="border-left:3px solid var(--amber);padding:4px 0 4px 14px;margin:10px 0">'
            f'<div class="mono" style="color:var(--amber);font-weight:600">{html.escape(ref.split(":", 1)[-1].replace("_", " "))}</div>'
            f'<div style="color:var(--ink-2);font-size:13px;margin-top:2px">{html.escape(reason)}</div></div>'
            for ref, reason in bugs.items()
        )
        bugs_html = (
            '<h3 style="font-size:15px;margin:26px 0 4px">&#9889; Real bugs the properties caught</h3>'
            '<p class="lead" style="margin-top:4px">A proposal that fails against a correct system is a bad '
            "proposal; a proposal that fails against a broken one has caught a real bug. These are the latter.</p>"
            f"{cards}"
        )

    # -- compact history of every run, newest first ---------------------------
    rows = ""
    for r in reversed(runs):
        flag = ""
        if r["flagged"]:
            tip = html.escape("; ".join(r.get("flagged_why", {}).get(x, x) for x in r["flagged"]))
            flag = f'<span title="{tip}" style="color:{_AMBER};margin-left:8px">&#9889;</span>'
        rows += (
            f'<tr><td class="mono" style="color:{_INK3};font-size:12px">{html.escape(r["run"])}</td>'
            f'<td style="width:55%">{_bar(r["survived"], r["proposed"], _GREEN)}'
            f'<span class="mono" style="color:{_INK3};margin-left:8px">{r["survived"]}/{r["proposed"]}</span>{flag}</td>'
            f'<td class="mono num" title="{_tip(r)}">{r["rules"]}r/{r["invariants"]}i/{r["relations"]}m</td>'
            f'<td class="mono num">{r["iterations"]}</td></tr>'
        )
    history = (
        '<h3 style="font-size:15px;margin:26px 0 4px">Every run</h3>'
        '<p class="lead" style="margin-top:4px">Discovery is nondeterministic; each run proposes afresh. '
        "Hover a flag for the caught bug, hover the counts for the plain labels.</p>"
        '<div class="tbl"><table><thead><tr><th>run</th><th>survived falsification</th>'
        '<th class="num">proposed</th><th class="num">refine</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )

    return (
        '<section id="funnel" class="rule"><p class="kicker">Discovery funnel</p>'
        "<h2>What the agent proposed, and what survived.</h2>"
        '<p class="lead">The agent proposes falsifiable checks; Hypothesis tries to break them; '
        "refine rewrites the ones it breaks. What is left is the accepted spec. The three kinds "
        "of check, in plain terms:</p>"
        f"{legend}{funnel}{decomp_html}{bugs_html}{history}</section>"
    )


def _parse_graph(text: str) -> tuple[list[str], list[tuple[str, str, bool]]]:
    """Node ids (declaration order) and edges (src, dst, dashed) from a Mermaid graph."""
    nodes: list[str] = []
    seen: set[str] = set()
    edges: list[tuple[str, str, bool]] = []
    for raw in text.splitlines():
        s = raw.strip().rstrip(";").strip()
        if not s or s.startswith(("---", "config:", "flowchart:", "curve:", "graph", "classDef")):
            continue
        if "-.->" in s or "-->" in s:
            dashed = "-.->" in s
            a, b = re.split(r"-\.->|-->", s, maxsplit=1)
            edges.append((a.strip().split()[0], b.strip().split()[0], dashed))
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", s)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            nodes.append(m.group(1))
    return nodes, edges


def _node_roles() -> dict[str, str]:
    """Map each node to 'propose' (fallible LLM) or 'dispose' (deterministic engine),
    from agent/roles.py. Empty if roles are unavailable."""
    try:
        from agent.roles import DISPOSE, PROPOSE, nodes_with_role
    except Exception:
        return {}
    roles = {n: "propose" for n in nodes_with_role(PROPOSE)}
    roles.update({n: "dispose" for n in nodes_with_role(DISPOSE)})
    return roles


def _graph_svg(nodes: list[str], edges: list[tuple[str, str, bool]], roles: dict[str, str]) -> str:
    idx = {n: i for i, n in enumerate(nodes)}
    top0, step, nw, nh, cx = 16, 42, 178, 26, 235
    nx, height = cx - nw // 2, top0 + len(nodes) * step + 8
    ytop = lambda i: top0 + i * step
    ymid = lambda i: ytop(i) + nh // 2

    parts: list[str] = []
    fwd = back = 0
    for a, b, dashed in edges:
        if a not in idx or b not in idx:
            continue
        i, j = idx[a], idx[b]
        if j == i + 1:  # straight, adjacent
            cls = "g-edge-d" if dashed else "g-edge"
            parts.append(f'<path class="{cls}" marker-end="url(#garw)" d="M{cx},{ytop(i)+nh} V{ytop(j)}"/>')
        elif j > i:  # forward skip, curve out right
            fwd += 1
            lx = cx + nw // 2 + 14 + fwd * 16
            parts.append(
                f'<path class="g-edge-d" marker-end="url(#garw)" '
                f'd="M{cx+nw//2},{ymid(i)} C{lx},{ymid(i)} {lx},{ymid(j)} {cx+nw//2},{ymid(j)}"/>'
            )
        else:  # back edge (the refine loop), curve out left, amber
            back += 1
            lx = cx - nw // 2 - 14 - back * 16
            parts.append(
                f'<path class="g-loop" marker-end="url(#garwl)" '
                f'd="M{nx},{ymid(i)} C{lx},{ymid(i)} {lx},{ymid(j)} {nx},{ymid(j)}"/>'
            )

    for i, nid in enumerate(nodes):
        if nid in ("__start__", "__end__"):
            cls, label, rx = "g-term", ("start" if nid == "__start__" else "end"), nh // 2
        else:
            role = roles.get(nid)
            cls = "g-llm" if role == "propose" else "g-node"
            label, rx = nid, 5
        parts.append(
            f'<g><rect class="{cls}" x="{nx}" y="{ytop(i)}" width="{nw}" height="{nh}" rx="{rx}"/>'
            f'<text class="g-lab" x="{cx}" y="{ytop(i)+17}" text-anchor="middle">{label}</text></g>'
        )

    alt = (
        "Property generation agent graph, top to bottom: "
        + ", ".join("start" if n == "__start__" else "end" if n == "__end__" else n for n in nodes)
        + ". Dashed arrows are conditional branches; the amber arrow is the refine loop back to compile_spec."
    )
    defs = (
        '<defs>'
        '<marker id="garw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#7C8698"/></marker>'
        '<marker id="garwl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#D9A441"/></marker></defs>'
    )
    return (
        f'<svg viewBox="0 0 480 {height}" role="img" aria-label="{html.escape(alt)}">'
        f"{defs}{''.join(parts)}</svg>"
    )


def _pipeline_section(rows: list[dict], all_ok: bool) -> str:
    """One section for the whole pipeline: its structure (the role coloured graph),
    who proposes vs disposes, and the live gate status. Merges what used to be three
    overlapping sections (graph, propose/dispose, and the fast lane gates)."""
    graph_html = ""
    if _GRAPH_MMD.exists():
        nodes, edges = _parse_graph(_GRAPH_MMD.read_text())
        if nodes:
            graph_html = (
                f'<div class="fig" style="max-width:420px;margin-top:8px">'
                f'{_graph_svg(nodes, edges, _node_roles())}'
                '<div class="mut-legend" style="margin-top:16px">'
                f'<span><i style="background:rgba(217,164,65,.5);border:1px solid {_AMBER}"></i>the LLM proposes (fallible)</span>'
                f'<span><i style="background:{_SURFACE2};border:1px solid {_LINE2}"></i>the engine disposes (trustworthy)</span>'
                "</div></div>"
            )

    # the live gate status, as a compact strip (was the standalone fast lane)
    verdict = (
        f'<span class="badge {"block" if all_ok else "fail"}">'
        f'{"all fast gates green" if all_ok else "a gate is red"}</span>'
    )
    gate_rows = "".join(
        "<tr>"
        f'<td class="mono" style="color:{_AMBER}">{html.escape(r["layer"])}</td>'
        f"<td>{html.escape(r['name'])}</td><td>{_badge(r['ok'])}</td>"
        f'<td class="mono" style="color:{_INK3}">{html.escape(r["detail"])}</td>'
        f'<td class="mono num">{r["elapsed"]:.2f}s</td></tr>'
        for r in rows
    )
    gates_html = (
        f'<h3 style="font-size:15px;margin:28px 0 4px">Live gate status &middot; {verdict}</h3>'
        '<p class="lead" style="margin-top:4px">Layer 0 structural and drift plus the Layer 1 '
        "replay slice, run live when this page was generated. These are what block a merge.</p>"
        '<div class="tbl"><table><thead><tr><th>layer</th><th>gate</th><th>result</th>'
        '<th>detail</th><th class="num">elapsed</th></tr></thead>'
        f"<tbody>{gate_rows}</tbody></table></div>"
    )

    return (
        '<section id="pipeline" class="rule"><p class="kicker">The pipeline</p>'
        "<h2>Who proposes, what checks it, and whether it is green now.</h2>"
        '<p class="lead">The whole trust argument is one boundary: the LLM proposes (fallible), '
        "a deterministic engine disposes by compiling, executing, and scoring. The graph is "
        'coloured by that split (from <span class="mono">agent/roles.py</span>, drift gated); '
        "the gates below are the deterministic side, run live.</p>"
        f"{graph_html}{gates_html}</section>"
    )


def _report_extra_css() -> str:
    """The report specific CSS classes index.html does not already define, scoped
    under #trust so they can never affect the hand authored walkthrough. index.html
    already owns the base classes (.metric, .fig, .kicker, .lead, .rule, .badge,
    .amber, .mono, .wrap) and every CSS variable these rules use."""
    return """
  #trust .two-up{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:26px;}
  @media (max-width:720px){#trust .two-up{grid-template-columns:1fr;}}
  #trust .mut-label{font-family:var(--mono);font-size:12px;color:var(--ink-3);letter-spacing:.02em;}
  #trust .mut-pct{font-family:var(--mono);font-size:clamp(2.4rem,5vw,3.2rem);font-weight:600;letter-spacing:-.02em;line-height:1.1;margin:2px 0 12px;}
  #trust .stack{display:flex;width:100%;height:12px;border-radius:6px;overflow:hidden;background:var(--surface-2);}
  #trust .stack>span{display:block;height:100%;}
  #trust .mut-legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:12px;font-family:var(--mono);font-size:11.5px;color:var(--ink-2);}
  #trust .mut-legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;vertical-align:middle;}
  #trust .mut-foot{font-family:var(--mono);font-size:11.5px;color:var(--ink-3);margin-top:14px;border-top:1px solid var(--line);padding-top:12px;}
  #trust .bar{display:inline-block;width:130px;height:8px;background:var(--surface-2);border-radius:4px;overflow:hidden;vertical-align:middle;}
  #trust .bar-fill{display:block;height:8px;border-radius:4px;}
  #trust .tbl{margin-top:22px;border:1px solid var(--line);border-radius:10px;overflow:auto;}
  #trust .tbl table{border-collapse:collapse;width:100%;min-width:560px;}
  #trust .tbl th{text-align:left;font-family:var(--mono);color:var(--ink-3);font-size:11px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;padding:12px 16px;background:var(--surface);border-bottom:1px solid var(--line);}
  #trust .tbl td{padding:12px 16px;border-top:1px solid var(--line);font-size:13.5px;color:var(--ink-2);vertical-align:middle;}
  #trust .num{text-align:right;}
  #trust .badge.block{color:var(--green);background:rgba(79,174,124,.13);border:1px solid color-mix(in srgb,var(--green) 30%,transparent);}
  #trust .badge.fail{color:var(--red);background:rgba(224,100,90,.13);border:1px solid color-mix(in srgb,var(--red) 30%,transparent);}
  #trust .code{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;overflow:auto;color:var(--ink-2);font-family:var(--mono);font-size:12px;line-height:1.6;margin-top:22px;}
  #trust .fig svg{width:100%;height:auto;display:block;}
  #trust .g-node{fill:var(--surface-2);stroke:var(--line-2);}
  #trust .g-llm{fill:rgba(217,164,65,.10);stroke:var(--amber);}
  #trust .g-term{fill:rgba(217,164,65,.16);stroke:var(--amber);}
  #trust .g-lab{font-family:var(--mono);font-size:8.5px;fill:var(--ink);letter-spacing:.02em;}
  #trust .g-edge{stroke:var(--line-2);stroke-width:1.4;fill:none;}
  #trust .g-edge-d{stroke:var(--ink-3);stroke-width:1.2;fill:none;stroke-dasharray:3 3;}
  #trust .g-loop{stroke:var(--amber);stroke-width:1.4;fill:none;}
"""


def _inner_sections() -> str:
    """The report body (no page chrome), for injection into index.html."""
    rows, all_ok = _gate_rows()
    baseline = _load_baseline()
    funnel = _funnel_runs()
    return (
        '<section class="rule"><p class="kicker">Trust report, measured</p>'
        "<h2>Every number below comes from a real artifact.</h2>"
        '<p class="lead">Nothing here is hand typed: gate status is run live, kill rates come '
        "from the committed mutation baseline, and the discovery funnel is read from each agent "
        "run.</p>"
        + _metrics(baseline, all_ok, funnel)
        + "</section>"
        + _funnel_section(funnel)
        + _mutation_section(baseline)
        + _pipeline_section(rows, all_ok)
    )


_CSS_START, _CSS_END = "/* trust-report:css:start */", "/* trust-report:css:end */"
_BODY_START, _BODY_END = "<!-- trust-report:start -->", "<!-- trust-report:end -->"


def _splice(text: str, start: str, end: str, payload: str) -> str:
    i, j = text.find(start), text.find(end)
    if i == -1 or j == -1 or j < i:
        raise SystemExit(f"marker pair not found in index.html: {start} .. {end}")
    return text[: i + len(start)] + "\n" + payload + "\n" + text[j:]


def inject_index(index_path: Path) -> None:
    """Fold the report into index.html between its markers (CSS + body)."""
    text = index_path.read_text(encoding="utf-8")
    text = _splice(text, _CSS_START, _CSS_END, _report_extra_css())
    text = _splice(text, _BODY_START, _BODY_END, _inner_sections())
    index_path.write_text(text, encoding="utf-8")


_INDEX = _ROOT / "site" / "index.html"


def main() -> int:
    inject_index(_INDEX)
    print(f"build-report: folded into {_INDEX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
