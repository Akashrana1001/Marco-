# CONVENTIONS — agent-breaker

> Index: [`CONTEXT.md`](./CONTEXT.md) · Source of truth: [`claude.md`](./claude.md)
> Related: [`ARCHITECTURE.md`](./ARCHITECTURE.md)

Code style and quality rules that all future code for this project **must** follow. These are hard
constraints derived from the blueprint, not suggestions.

## 1. Performance constraints

- The **pre-call evaluation layer must run in sub-millisecond execution time.**
- **Do not** use local embedding engines.
- **Do not** use heavy regex modules that introduce frame-processing latency.
- Prefer simple arithmetic and dictionary lookups over anything computationally expensive on the hot
  path.

## 2. Dependency management

- Keep external dependencies to an **absolute minimum**.
- Rely on the **Python Standard Library** wherever humanly possible.
- Every new third-party dependency must be justified against the "ultra-lightweight" positioning.
- **Pin CrewAI:** target **`crewai>=1.14,<2`** (the range where the `before_llm_call`/`after_llm_call`
  hook API exists). Record the exact tested version in the lockfile. CrewAI's API changes fast and
  hook/callback signatures have shifted across releases.
- **Handle breaking changes deliberately:** isolate all CrewAI hook registration and
  `LLMCallHookContext` access behind a **single thin adapter module**, and keep a CI
  **compatibility smoke test** that asserts `before_llm_call` can block a call against the pinned
  version. A CrewAI upgrade that breaks the signature must fail CI, never a user's production run.
- **Pricing data:** do **not** hand-maintain a provider price table (it goes stale on every
  OpenAI/Anthropic change). Reuse **LiteLLM's maintained pricing** —
  `model_prices_and_context_window.json` or `litellm.cost_per_token`/`completion_cost`. LiteLLM is
  already transitive via CrewAI, so this adds no meaningful weight.

## 3. Error handling (fail open)

- The circuit breaker must **never** throw an unhandled internal exception that crashes a healthy
  client application.
- If internal metric tracking fails, **log a warning to `stderr`** and **gracefully fall back** to
  letting the agent proceed.
- The only exception intentionally raised into the host app is `CircuitBreakerException`, and only
  in hard-kill mode when the budget is deliberately breached.

## 4. Interception rules

- Enforce at CrewAI's **`before_llm_call`** hook — it runs *before* each LLM call and can **block
  it** by returning `False`. Reconcile actual cost in the paired **`after_llm_call`** hook.
- **Do not** use `step_callback`/`task_callback` for enforcement. They fire *after* a step
  completes and only report the last action (`AgentAction`/`ToolResult`/`AgentFinish`); they cannot
  prevent the next call. (Verified — see [`ARCHITECTURE.md`](./ARCHITECTURE.md) §4.1.)
- **Never** monkey-patch raw socket connections.

## 5. Safety defaults

- The package **defaults to `hard_kill=False`** (dry-run / audit mode). Passive tracking must never
  risk production uptime.
- Tracking must be **intelligently scoped** to avoid false positives (the Trust Gap — see
  [`GLOSSARY.md`](./GLOSSARY.md)).

## 6. Packaging & license

- Distribute on **PyPI** as `agent-breaker`.
- **License: MIT.** Decided up front for the open-core model — a permissive core maximizes adoption
  and embedding, with paid/hosted features layered on top. Ship the MIT header from the first
  commit; do not leave the license undecided.
