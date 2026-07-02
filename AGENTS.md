# AGENTS.md

You are working on **PayFlow**, a project that demonstrates a trustworthy agentic SDLC: a coding agent implements a payment intent processor from a frozen specification, and a four layer verification pyramid is what makes that safe. Two documents rule everything:

- [`specs/`](specs/README.md) : the system specification. What PayFlow must do, as frozen contracts (domain, api, state machine, invariants, constraints). **Frozen** (see below).
- [`docs/design.md`](docs/design.md) : the pipeline design, covering the four layers, the property generation agent, the CI contract, and the roadmap.

Task tracking is maintained locally by the maintainer. Decisions of record live in [`docs/adr/`](docs/adr/); ADR-0001 is immutable.

## The one rule that matters

**Never weaken a gate or the specs to make a red check green.** `specs/**`, the Layer 0 contracts, and `docs/adr/0001-foundational-decisions.md` are invariant sources: the implementation conforms to them, never the reverse. If a task seems to require editing one, STOP: that is a human decision needing a superseding ADR. This repo's entire thesis is that this failure mode is the one to prevent.

Note on the contracts' location: they live in `pyproject.toml` under `[tool.importlinter]` (the deny rule on the root `.importlinter` path blocked its own creation; recorded in the build log). You may edit `pyproject.toml` for dependencies, but the `[tool.importlinter]` block only ever gets stronger; a drift check for it (`tests/drift/test_importlinter_contracts.py`) guards against silent edits.

## Commands

All phases are built; every command below runs today. Commands are listed here only **when they exist**. Never list a command you cannot run. Current state:

```bash
# Phase 0 (works now):
uv sync                              # install deps (Python >=3.12)
uv run lint-imports                  # Layer 0 architectural gate
uv run uvicorn payflow.api.app:app   # serve the API (/openapi.json)

# Phase 1 (works now):
uv run pytest tests/                 # Layer 1 sanity + concurrency + drift gates
uv run demo                          # run the fast gates, one screen colored summary

# Phase 2 + 3 (works now):
uv run agent-run                     # discovery agent vs correct PayFlow, now discovers rules, invariants AND metamorphic relations (renders generated_specs/payflow_spec.py + payflow_mr.py). COSTS OPENAI TOKENS (~$0.01/run); needs OPENAI_API_KEY in .env. Add --offline for a free deterministic pipeline pass. Add --view for a live Rich TUI of the pipeline.
uv run explain-run [latest|<ts>]     # replay a finished run visually (pipeline path, funnel, triage, cost) from agent_runs/<ts>/report.json; deterministic, no tokens
uv run python tools/triage_validation.py  # Run B: triage vs an in process broken PayFlow (dropped INV-1 precondition); costs a few tokens
uv run python tools/mr_validation.py      # flagship: a fee misroute only MR-1 catches (invariant suite green, MR red, triage real_bug); costs a few tokens

# Phase 4 (works now):
uv run trust-report                        # render site/trust-report.html from real artifacts (gates, funnel, mutation, agent graph)
uv run python -m mutmut run                # Layer 3 mutation run over the payment core (in process replay of the agent specs); minutes, no tokens
uv run python mutation/run_baseline.py     # recompute mutation/baseline.json (headline + full suite kill rates); nightly recomputes
actionlint .github/workflows/*.yml         # validate CI config (if actionlint installed)
# LangWatch tracing is guarded/optional: uv sync --extra observability, then set LANGWATCH_ENDPOINT (local docker compose deferred)

# Phase 5 (works now):
uv run pytest -m layer2                     # Layer 2 agent judgment suite (AGENT-MR verdict stability + rigged world scenarios). COSTS OPENAI TOKENS (~$0.02/run, `gpt-5.4-nano`, the default judge per ADR-0004 / `agent/config.py`); skips honestly without OPENAI_API_KEY. The default `uv run pytest` EXCLUDES layer2 via addopts `-m 'not layer2'`, so the keyless PR lane stays green.
uv run python tools/layer2_validation.py   # exit criterion demo: induce a triage regression (PAYFLOW_TRIAGE_REGRESSION=1) and show Layer 2 goes red while demo's Layers 0/1 stay green; artifacts to agent_runs/<ts>-layer2-validation/. Costs a few tokens.

# Triage hardening (works now):
uv run python tools/judge_comparison.py    # empirically rank triage judge models on the Layer 2 fixture bank (accuracy + stability + cost per verdict + the void regression case), voting on and off; writes agent_runs/<ts>-judge-comparison/. COSTS OPENAI TOKENS (budget guarded, default cap $3). This is how the default judge in agent/config.py is chosen (ADR-0004); rerun it to reselect. Add --dump-accepted <report.json> to regenerate generated_specs/accepted_proposals.json (offline).
```

## Repository layout

Target layout is design.md §13, and it is all present today: `specs/`, `docs/` (design and adr), `.claude/`, this file, plus `payflow/` (`api/` → `domain/` → `infrastructure/`, agent implemented), `agent/` (the LangGraph property generation agent), `generated_specs/`, `tests/{property,concurrency,drift,agent_scenarios,agent_metamorphic}/`, `mutation/`, `site/` (the trust report), and `.github/workflows/`. A local build log and planning notes also exist for the maintainer but are not part of the published repo.

## The four layer gate

| Layer | Tool | Checks | Cadence / blocking |
|---|---|---|---|
| 0 | `import-linter` | Layering (`api → domain → infrastructure`) + single writer to ledger | Every commit, blocks |
| 1 | Hypothesis `RuleBasedStateMachine` + MR tests + the concurrency harness | PayFlow behavior vs the agent authored spec (invariants INV-1..7, relations MR-1..6) | PR = replay slice, blocks; discovery is the nightly agent run |
| 2 | `langwatch-scenario` + AGENT-MR tests | The verification agent's own judgment (triage verdicts stable under order/paraphrase/padding) | Nightly, warn only until baselined |
| 3 | `mutmut` | Whether Layer 1 actually catches anything (kill rate on `payflow/domain` + ledger core) | Nightly, warn only until baselined |

Failure messages are written for a coding agent to act on: the violated rule, the shrunk counterexample, or the exact offending import. A human is the escalation path, not the default reader.

## Conventions

- Money is **integer minor units**. No floats in any money path, ever.
- Time and IDs go through the injectable `clock` / `id_generator` seams (`specs/constraints.md`), never `datetime.now()` / `uuid4()` at call sites.
- Ledger entries are append only; corrections are new entries.
- `PAYFLOW_BUG` toggles (`specs/constraints.md`) are for the verification pipeline and demos only; never set in a merged configuration, and never "fixed" (they are specified broken behavior).
- Agent generated implementation commits are tagged as such in the commit body (`Provenance: agent-generated`), so provenance stays traceable (design §4).
- Triage judges each failure with two deterministic aids and a vote (ADR-0004): accepted slice annotations from `generated_specs/accepted_proposals.json` (regenerate whenever the committed slice changes) and majority voting over `PAYFLOW_TRIAGE_VOTES` calls (default 3; a tie or three way split escalates to `needs_human`). The judge model is chosen by `tools/judge_comparison.py`, never by size or recency.
- Do not implement anything in `specs/constraints.md` ("Do not invent"). Ambiguity in the specs is an escalation, not a creative opportunity.

## Do not touch

- `specs/**`, the `[tool.importlinter]` block in `pyproject.toml`, and `docs/adr/0001-foundational-decisions.md` are invariant sources (see the one rule above).
- Build log entries are append only: corrections are a new entry linking back, never an edit.

## Phase awareness

Built in phases 0–6 (design §14). **All phases complete (2026-07-02). Maintenance mode: nightly lanes manual until CI secrets exist.**

| Phase | Lands |
|---|---|
| 0 | Agent implemented PayFlow from `specs/` + Layer 0 contracts + `PAYFLOW_BUG` toggles |
| 1 | Hand written Hypothesis sanity harness, concurrency replay harness, state machine drift gate, `demo` skeleton |
| 2 | LangGraph property generation agent (rules → invariants → compile → execute → triage → refine), agent graph drift gate |
| 3 | Metamorphic relation inference + execution |
| 4 | LangWatch tracing/scoring, mutmut baseline, real CI config, trust report |
| 5 | Layer 2: scenario suite + AGENT-MR self referential tests |
| 6 | Polish: README metrics, recorded demo |

## Build log

A local, unpublished build log records every non trivial decision, demo, pivot, or surprise as it happens. It is maintainer only and feeds external writing; its tooling is not part of the published repo.

## Claude Code notes

- `CLAUDE.md` is a symlink to this file. Edit `AGENTS.md`, never `CLAUDE.md`.
- Maintainer local agent tooling lives under `.claude/` (unpublished).
- When authoring a skill: the frontmatter `description` drives activation: specific and signal dense; body under 500 lines.
