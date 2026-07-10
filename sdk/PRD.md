# PRD — agent-breaker

> Index: [`CONTEXT.md`](./CONTEXT.md) · Source of truth: [`claude.md`](./claude.md)
> Related: [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`ROADMAP.md`](./ROADMAP.md) · [`GLOSSARY.md`](./GLOSSARY.md)

## 1. Executive summary

**agent-breaker** is an ultra-lightweight, open-source Python SDK that serves as an **economic
circuit-breaker** for multi-agent systems. Its job is to stop autonomous AI agents from bankrupting
developers via uncontrolled execution loops.

- **Core objective:** Prevent runaway agent loops from producing unexpected, large LLM bills.
- **Core hook:** *"Stop your AI agents from bankrupting you."*
- **Positioning:** An ultra-lightweight, zero-latency **financial utility** (an economic fuse box) —
  **not** a heavy enterprise security firewall.
- **Differentiator (vs. CrewAI native limits):** CrewAI already has per-agent `max_iter` and
  `max_rpm`, which cap *iteration count* and *request rate*. agent-breaker does **not** duplicate
  those. It stops loops **by real-time dollar cost, aggregated across all agents in a crew, and
  blocks the next LLM call when a budget ceiling is breached** — the economic dimension CrewAI's
  per-agent, count/rate-based knobs do not cover.
- **v1 focus:** **CrewAI only.**

## 2. Target audience

- Indie SaaS builders.
- Agile development teams.
- AI client agencies running agents against **production budgets**.

These users share a common trait: they run agents with real money on the line and need a
low-friction guardrail, not an enterprise security platform.

## 3. Problem space

When multi-agent systems are deployed, they are susceptible to two devastating **economic** failure
modes:

1. **The Tool Retry Loop** — An agent encounters a minor exception or unexpected output from a
   third-party tool and continuously fires retries against the LLM provider, burning tokens with no
   backoff.
2. **The Delegation Ping-Pong** — Agent A delegates a task to Agent B, which rephrases it slightly
   and delegates it back to Agent A. This circular handoff loops indefinitely.

### Impact

Because these loops **do not crash the runtime**, they run unattended. Developers have zero
real-time visibility and typically discover the failure only when an unexpected
**`$100`–`$2,400+` invoice shock** arrives from OpenAI or Anthropic.

## 4. Goals

- Give developers **real-time visibility** into token velocity and dollar spend during a crew run.
- Enforce a **hard dollar budget** that can forcefully terminate a runaway workflow.
- Integrate with **near-zero friction** (a single decorator around the existing `kickoff()` call).
- Be **safe by default** — never risk production uptime unless the developer opts in.
- Impose **negligible latency** and **minimal dependencies**.

## 5. Success criteria

- A developer can add the guard to an existing CrewAI pipeline by wrapping one function with a
  decorator, with no other code changes.
- In default mode, the SDK surfaces color-coded cost/velocity warnings to the terminal **without
  ever interrupting** a healthy run.
- In hard-kill mode, the SDK **deterministically blocks** the next outbound LLM request once the
  dollar ceiling is breached and raises a structured `CircuitBreakerException`. Enforcement binds to
  CrewAI's **`before_llm_call`** hook (which can block a call *before* it is dispatched), **not** to
  `step_callback`/`task_callback` (which only report after a step and cannot prevent the next call).
- The pre-call evaluation adds **sub-millisecond** overhead.
- An internal failure inside the breaker **never** crashes the host application.
- False positives are minimized so that developers trust the tool and do not uninstall it (the
  "Trust Gap"; see [`GLOSSARY.md`](./GLOSSARY.md)).

## 6. Scope

### In scope (v1)

- **CrewAI** execution-loop protection.
- Thread-safe, in-memory cost/token/depth tracking bound to a crew run.
- Dynamic dollar-cost calculation from provider token outputs, priced against **LiteLLM's
  maintained pricing data** (`model_prices_and_context_window.json` / `cost_per_token`) rather than
  a hand-maintained table that goes stale on every provider price change.
- Default passive **dry-run / audit mode** with terminal warnings.
- Opt-in deterministic **hard-kill** with a structured exception.

### Out of scope (v1)

- **Network proxy architecture** — rejected outright (adds latency, complicates SSL, breaks
  streaming, creates a single point of failure). The tool is a native SDK/wrapper only.
- **Microsoft Agent Framework (MAF) / legacy AutoGen** — explicitly de-prioritized. MAF maintainers
  declined native retry/circuit-breaking (they place resilience at the provider client layer) and
  token/latency telemetry is already handled via OpenTelemetry. There is no active community demand
  for Python-side cost gates there yet, so **100% of engineering focuses on CrewAI**.
- Enterprise security firewall features.
- Heavy analytics, dashboards, or persistent storage backends.

## 7. Key constraints

- **No network proxy** — native Python SDK only.
- **Intelligently scoped tracking** to avoid false-positive crashes (the Trust Gap).
- **Sub-millisecond** pre-call evaluation; minimal dependencies (stdlib-first).
- The breaker must **fail open** internally — on its own error, warn on stderr and let the agent
  proceed. See [`CONVENTIONS.md`](./CONVENTIONS.md).

## 8. Validation & go-to-market

Engineering-only docs risk producing a beautiful spec nobody uses. The build is pulled by real
usage, not shipped into a vacuum:

- **Validation gate:** dogfood the Phase 1 MVP against **3 real users' actual CrewAI pipelines
  before starting Phase 2** — real production loops, not synthetic demos.
- **Build-in-public cadence** runs alongside development, with direct outreach to interested CrewAI
  users (e.g. DMs to PsychologicalNeat105 / grahamdietz) to source those 3 validation pipelines.
- Success signal: at least one real user's pipeline where the breaker surfaces (dry-run) or prevents
  (hard-kill) spend the user did not anticipate.

## 9. Packaging & license

- Ship on **PyPI** as `agent-breaker`.
- **License: MIT**, chosen to fit the open-core monetization model (permissive core for adoption;
  paid/hosted layer on top). See [`CONVENTIONS.md`](./CONVENTIONS.md) §6 and
  [`ROADMAP.md`](./ROADMAP.md).
- Pin **`crewai>=1.14,<2`** (the range where the `before_llm_call` hook API exists); handle
  breaking hook-signature changes behind an internal adapter (see [`ARCHITECTURE.md`](./ARCHITECTURE.md) §8).
