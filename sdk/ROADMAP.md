# ROADMAP — crew-fusebox

> Index: [`CONTEXT.md`](./CONTEXT.md) · Source of truth: [`claude.md`](./claude.md)
> Related: [`PRD.md`](./PRD.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md)

This roadmap reflects the scope boundaries from the blueprint. Build **Phase 1 first**; everything
after the MVP boundary is post-MVP.

## Phase 1 — Core Engine (build this first)

- [ ] **Hook spike (do first):** confirm against the pinned CrewAI (`crewai>=1.14,<2`) that a
      `before_llm_call` hook returning `False` actually blocks the next LLM call. This de-risks the
      single most critical assumption before the state matrix is written.
- [ ] Thin CrewAI adapter isolating `before_llm_call`/`after_llm_call` registration + a CI
      compatibility smoke test (guards against breaking hook-signature changes).
- [ ] Thread-safe, in-memory cost tracking accumulator (priced via LiteLLM's pricing data, not a
      hand-rolled table).
- [ ] CrewAI `kickoff()` wrapping mechanism (the `@crew_circuit_breaker` decorator).
- [ ] Standard console log output warning system (color-coded, scannable).
- [ ] Basic hard-kill exception routing (`CircuitBreakerException`) via the `before_llm_call` gate.
- [ ] PyPI packaging skeleton with the **MIT** license header in place from the first commit.

### ▲ MVP boundary ▲

*Everything above delivers the minimum viable product: passive cost tracking + opt-in hard-kill for
CrewAI. Ship and validate before starting Phase 2.*

### ✅ Validation gate (must pass before Phase 2)

- [ ] **Validate against 3 real users' actual CrewAI pipelines before Phase 2** — real production
      loops, not synthetic demos. Run build-in-public cadence and direct outreach (e.g. DMs to
      PsychologicalNeat105 / grahamdietz) alongside the build to source these pipelines. See
      [`PRD.md`](./PRD.md) §8.

## Phase 2 — Refinement (post-MVP)

- [ ] Prompt caching recognition matrix (detect and account for cache differentials in cost).
- [ ] Basic trajectory duplication matching — alert on logical loops **before** spending the maximum
      limit (must stay intelligently scoped to avoid false positives / the Trust Gap).
- [ ] Structured Slack/Discord webhook alarm dispatches containing the **last 3 execution traces**.

## Explicitly out of scope

- Network proxy architecture (native SDK only).
- Microsoft Agent Framework (MAF) / legacy AutoGen support — de-prioritized; focus 100% on CrewAI.
- See [`PRD.md`](./PRD.md) §6 for the full scope rationale.
