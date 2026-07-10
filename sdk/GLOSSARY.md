# GLOSSARY — agent-breaker

> Index: [`CONTEXT.md`](./CONTEXT.md) · Source of truth: [`claude.md`](./claude.md)

Definitions of the domain-specific terms used across the project docs.

- **Circuit breaker** — The core pattern of this SDK: a guard that monitors an agent workflow's cost
  and, once a threshold is breached, interrupts execution to prevent further spend.

- **Economic fuse box** — The product's positioning metaphor. Like an electrical fuse box trips to
  prevent damage, agent-breaker "trips" to prevent runaway spend. It is a financial utility, not a
  security firewall.

- **Dry-run / audit mode** — The **default** operating mode (`hard_kill=False`). The SDK passively
  tracks token velocity and cost, emitting color-coded terminal warnings without ever interrupting
  the run. Safe for production uptime.

- **Hard-kill** — The opt-in enforcement mode (`hard_kill=True`). When the running dollar balance
  breaches the ceiling, the breaker blocks the next outbound network request and raises a
  `CircuitBreakerException`.

- **Tool Retry Loop** — A failure mode in which an agent hits a minor tool exception or unexpected
  output and continuously retries the LLM with no backoff, burning tokens.

- **Delegation Ping-Pong** — A failure mode in which Agent A delegates to Agent B, which rephrases
  and delegates back to Agent A, creating an infinite circular handoff.

- **Invoice shock** — The `$100`–`$2,400+` unexpected bill a developer discovers after an
  unattended runaway loop; the primary harm this SDK exists to prevent.

- **`crew_run_id`** — The identifier for an active crew execution. Tracking state (depth, tokens,
  call counts) is bound to this ID (or the thread session).

- **Cost model / dynamic cost parsing** — The logic that computes true dollar spend on every
  iteration by mapping provider token outputs against **LiteLLM's maintained pricing data** (see
  *LiteLLM pricing data* below) rather than a hand-maintained table.

- **LiteLLM pricing data** — LiteLLM's community-maintained `model_prices_and_context_window.json`
  (and the `cost_per_token`/`completion_cost` helpers) that map model + token counts to dollar
  cost across thousands of models. agent-breaker sources pricing from here so the "prices go stale"
  maintenance burden stays upstream. LiteLLM is already transitive via CrewAI, so it adds no
  meaningful dependency weight.

- **Prompt caching** — Provider-side reuse of prompt tokens at reduced cost. The cost model accounts
  for these differentials where detectable (a Phase 2 refinement for full recognition).

- **Trajectory deduplication** — Detecting repeated execution paths to flag logical loops. Used to
  alert before hitting the budget ceiling (Phase 2), and must be intelligently scoped to avoid
  false positives.

- **Trust Gap / false positives** — Raw trajectory deduplication can trigger false positives when
  the same tool is legitimately called across different sub-tasks. False-positive crashes make
  developers uninstall the tool instantly, so tracking must be intelligently scoped.

- **Lifecycle hook** — A native CrewAI boundary where the SDK injects its logic instead of
  monkey-patching sockets. The **enforcement** hook is **`before_llm_call`** (see below);
  `step_callback`/`task_callback` are **not** usable for enforcement.

- **`before_llm_call` hook** — CrewAI's pre-call hook (CrewAI ≥ 1.14). Runs *before every LLM call*
  and **blocks that call when it returns `False`**. This is where agent-breaker's pre-call
  evaluation and deterministic hard-kill bind. Receives an `LLMCallHookContext`
  (`messages`, `agent`, `task`, `crew`, `llm`, `iterations`). Registered via
  `register_before_llm_call_hook`, `@before_llm_call`, or crew-scoped `@before_llm_call_crew`.

- **`after_llm_call` hook** — CrewAI's post-call hook. Runs after the call returns; agent-breaker
  uses it to reconcile true cost from the actual token usage on the response.

- **`step_callback` / `task_callback` (not for enforcement)** — CrewAI callbacks that fire *after* a
  step or task completes and only *report* the last action (`AgentAction`/`ToolResult`/
  `AgentFinish`). They cannot prevent the next LLM call, so they are unsuitable for the hard-kill;
  enforcement uses `before_llm_call` instead.

- **Native max_iter / max_rpm (CrewAI)** — CrewAI's built-in per-agent controls: `max_iter` caps an
  agent's iteration count (default ~20–25) and `max_rpm` caps its request rate. They are per-agent
  and count/rate-based. agent-breaker does **not** duplicate them.

- **Differentiator** — What agent-breaker adds beyond `max_iter`/`max_rpm`: stopping runaway loops
  **by real-time dollar cost, aggregated across all agents in a crew, with a hard budget ceiling**
  that blocks the next LLM call. The economic dimension CrewAI's native knobs do not model.

- **In-memory state matrix** — The lightweight, thread-safe, local structure tracking execution
  depth, token consumption, and call counts for an active run. No external storage.

- **`CircuitBreakerException`** — The custom, structured exception raised in hard-kill mode when the
  dollar ceiling is breached.

- **Fail open** — The breaker's resilience behavior: if its own internal tracking fails, it logs a
  stderr warning and lets the agent proceed rather than crashing the host application.

- **Network proxy (rejected)** — An external API proxy architecture, explicitly rejected because it
  adds latency, complicates SSL, breaks streaming, and creates a single point of failure.

- **MAF (Microsoft Agent Framework)** — Microsoft's newer agent ecosystem (successor to legacy
  AutoGen). De-prioritized for this project: its maintainers declined native circuit-breaking and
  telemetry is covered by OpenTelemetry, so v1 focuses 100% on CrewAI.
