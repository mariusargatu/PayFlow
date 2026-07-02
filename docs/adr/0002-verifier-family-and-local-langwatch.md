# ADR-0002: Verifier model family and local LangWatch

**Date:** 2026-07-02 (decisions taken 2026-07-01, at the Phase 1/2 boundary)
**Status:** Accepted. Supersedes ADR-0001 decisions 8 and 9 in part.

## Context

ADR-0001 decision 9 chose the same LLM family for implementer and verifier in v1, deferring adversarial model diversity to a later experiment. ADR-0001 decision 8 chose the LangWatch cloud free tier. Both met reality: the only API credential available to the project is an OpenAI key, while the implementer (Claude Code) is an Anthropic model; and the user chose to run LangWatch locally rather than open a cloud account.

## Decisions

1. **The verification agent runs on OpenAI models.** The implementer stays Claude Code. Adversarial model diversity therefore arrives in v1 rather than as a later experiment: the model judging the code does not share the model that wrote it, so correlated blind spots between implementer and verifier are reduced by construction rather than by intent. The concrete model is configurable (`PAYFLOW_AGENT_MODEL` env var) with a cheap default; per phase costs get recorded before any upgrade.
2. **LangWatch runs locally via docker compose** (`LANGWATCH_ENDPOINT` env var), no cloud account. Docker 29.x is available on the build machine. OTel native wiring keeps a later move to cloud cheap.

## Consequences

- Phases 2, 3, and 5 consume OpenAI tokens; the agent code carries a per run call and token budget guard so a runaway refine loop cannot spend unbounded money.
- Any future claim about "the verifier caught what the implementer missed" now has a model diversity confound worth naming honestly: catches may come from the technique or from the different model family, and the write up must not attribute them to diversity without evidence.
- Phase 4 gains a docker compose step and loses a SaaS dependency.
