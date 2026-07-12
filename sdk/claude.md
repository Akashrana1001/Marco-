# Project Blueprint: crew-fusebox (Working Title)

You are an expert AI Engineer and Python Systems Architect. Your task is to build a lightweight, high-performance, open-source Python SDK that serves as an economic circuit-breaker for multi-agent systems, focusing strictly on **CrewAI** for the version 1 release.

---

## 1. Executive Summary

* **Core Objective:** Stop autonomous AI agents from bankrupting developers via uncontrolled execution loops.
* **Target Audience:** Indie SaaS builders, agile development teams, and AI client agencies running agents with production budgets.
* **Core Hook:** *"Stop your AI agents from bankrupting you."*
* **Positioning:** An ultra-lightweight, zero-latency financial utility (an economic fuse box), not a heavy enterprise security firewall.
* **Key Differentiator (vs. CrewAI's native limits):** CrewAI already ships per-agent `max_iter` (default ~20–25) and `max_rpm` controls that cap an agent's *iteration count* and *request rate*. **crew-fusebox does not re-implement those.** Our differentiator is stopping loops **by real-time dollar cost, aggregated across every agent in a crew run, and deterministically blocking the next LLM call the moment a budget ceiling is breached.** CrewAI's native guards are per-agent and count/rate-based — they do not model spend, do not aggregate cost across the crew, and cannot enforce a dollar ceiling. Most CrewAI cost guards hook into `step_callback`/`task_callback` — they can only react after a step finishes. `crew-fusebox` hooks into `before_llm_call` — it blocks the next request before it's sent, mid-step if needed. If a use case is fully covered by `max_iter`/`max_rpm`, crew-fusebox adds no value there; our scope is strictly the *economic* dimension those knobs ignore.

---

## 2. The Problem Space

When multi-agent systems are deployed, they are highly susceptible to two devastating economic failure modes:
1.  **The Tool Retry Loop:** An agent encounters a minor exception or unexpected output from a third-party tool and continuously fires retries against the LLM provider, burning tokens without backoff.
2.  **The Delegation Ping-Pong:** Agent A delegates a task to Agent B, which rephrases it slightly and delegates it back to Agent A. This circular handoff loops infinitely.

### The Impact
Because standard application loops do not crash the runtime, these behaviors continue unattended. Developers have zero real-time visibility and typically discover the failure only when they receive an unexpected **$100 to $2,400+ invoice shock** from OpenAI or Anthropic.

---

## 3. Ground-Truth Research Insights & Architectural Constraints

Our production landscape research has uncovered critical architecture constraints that you must respect:

* **No Network Proxy Architecture:** We reject external API network proxies. They introduce latency, complicate SSL handling, break streaming payloads, and create an unacceptable single point of failure. The tool must be a native Python SDK/Wrapper.
* [cite_start]**The Trust Gap (False Positives):** Real-world telemetry shows that raw trajectory deduplication triggers false positives when the same tool is legitimately called across different sub-tasks[cite: 84, 85]. [cite_start]If an crew-fusebox causes false-positive crashes, developers will uninstall it instantly[cite: 85]. The tracking must be intelligently scoped.
* **De-prioritize Microsoft Agent Framework (MAF):** Legacy AutoGen is entering maintenance mode. [cite_start]A deep dive into Microsoft's new Agent Framework (MAF) ecosystem reveals that the maintainers explicitly declined to build native framework-level retry/circuit-breaking controls, stating resilience belongs at the underlying provider client layer[cite: 549, 555, 562]. [cite_start]Furthermore, core token and latency telemetry are already handled out-of-the-box via OpenTelemetry[cite: 566, 568, 569]. Therefore, there is no active community out-cry for Python-side cost gates there yet. **Focus 100% of your engineering on CrewAI execution loops.**

* **Lifecycle-hook timing — VERIFIED (this is the single riskiest technical assumption; confirm again against the pinned CrewAI source before writing the state matrix):** `step_callback` and `task_callback` fire *after* a step or task has already completed and only *report* on the last action — they receive an `AgentAction`, `ToolResult`, or `AgentFinish` object. They **cannot** prevent the next outbound LLM call; by the time they run, the money is already spent. Therefore the deterministic hard-kill **must not** be built on these callbacks. Instead, inject at CrewAI's dedicated **`before_llm_call` hook** (`crewai.hooks.register_before_llm_call_hook`, the `@before_llm_call` decorator, or the crew-scoped `@before_llm_call_crew`), which runs *before every LLM call* and **blocks that call when the hook returns `False`**. The hook receives an `LLMCallHookContext` exposing `messages`, `agent`, `task`, `crew`, `llm`, and `iterations`. True cost is then reconciled from real token usage in the paired **`after_llm_call`** hook. This hook API is available in CrewAI **≥ 1.14** (see `ARCHITECTURE.md` §4.1).

---

## 4. The Solution Architecture

You will build a pip-installable Python package (`crew-fusebox`) that implements a local, in-memory execution guard. It sits directly inside the local application runtime to track, evaluate, and forcefully terminate runaway workflows.

### User DX Design
The integration must be effortless, wrapping the execution loop using a clean Python decorator pattern:

```python
from crew_breaker import crew_circuit_breaker

@crew_circuit_breaker(max_budget_dollars=5.00, hard_kill=True)
def initiate_research_pipeline():
    my_crew = Crew(agents=[...], tasks=[...])
    return my_crew.kickoff()Core Technical Specs
Native Lifecycle Hook Injection: Do not monkey-patch raw socket connections. Intercept execution at CrewAI's native **LLM call hooks**. The pre-call gate and hard-kill bind to `before_llm_call` (returns `False` to block the impending call); cost reconciliation from actual token usage binds to `after_llm_call`. Do **not** rely on `step_callback`/`task_callback` for enforcement — they only fire *after* a step completes and cannot block the next call (see §3, VERIFIED). Target CrewAI ≥ 1.14, where this hook API exists.

In-Memory State Matrix: Maintain a lightweight, thread-safe local directory tracking execution depth, token consumption metrics, and call counts bound to the active crew_run_id or thread session.

Dynamic Cost Model Parsing: Calculate true dynamic monetary spend on every iteration by mapping provider token outputs against up-to-date pricing schemas (accounting for prompt caching differentials where detectable). **Do not hand-maintain a pricing table** — provider prices go stale on every OpenAI/Anthropic change. Source pricing from **LiteLLM's maintained `model_prices_and_context_window.json`** (CrewAI already routes through LiteLLM), or call LiteLLM's `cost_per_token`/`completion_cost` helpers directly, so the table updates upstream.

Dry-Run / Audit Mode (Default): The package must default to hard_kill=False. In this mode, it tracks token velocity and costs passively, outputting color-coded, scannable warnings to the terminal without risking production uptime.

Deterministic Hard-Kill Switch: When hard_kill=True and the running dollar balance breaches the user's hard ceiling, the middleware must block the next outbound network request entirely and raise a custom, structured CircuitBreakerException.

5. Implementation Roadmap (Scope Boundaries)
Phase 1: Core Engine (Build This First)
Thread-safe, in-memory cost tracking accumulator.

CrewAI kickoff wrapping mechanism.

Standard console log output warning system.

Basic hard-kill exception routing.

Phase 2: Refinement (Post-MVP)
Prompt caching recognition matrix.

Basic trajectory duplication matching to alert on logical loops before spending maximum limits.

Structured Slack/Discord webhook alarm dispatches containing the last 3 execution traces.

**Validation gate (do this before starting Phase 2):** Dogfood the Phase 1 MVP against **3 real users' actual CrewAI pipelines** — not synthetic demos — and confirm it catches real spend before it happens. Build-in-public cadence and direct outreach (e.g. the DMs to PsychologicalNeat105 / grahamdietz) run alongside the build so the engineering is pulled by real usage, not shipped into a vacuum.

6. Code Style & Quality Rules
Performance Constraints: The pre-call evaluation layer must run in sub-millisecond execution speeds. Do not use local embedding engines or heavy regex modules that introduce frame processing latency.

Dependency Management: Keep external dependencies to an absolute minimum. Rely on the Python Standard Library wherever humanly possible. **Pin CrewAI to a tested version range (target CrewAI ≥ 1.14, `crewai>=1.14,<2`).** CrewAI's API moves fast and hook/callback signatures have changed across releases; wrap all CrewAI hook interactions behind a thin internal adapter and add a compatibility smoke test so a breaking change surfaces in CI, not in a user's production run.

Error Handling: Never allow the circuit breaker itself to throw an unhandled internal exception that crashes a healthy client application. If our metric tracking fails internally, log a stderr warning and gracefully fall back to letting the agent proceed.

Packaging & License: Ship on PyPI as `crew-fusebox`. **License: MIT** — chosen deliberately for the open-core monetization model (maximally permissive core drives adoption/embedding; paid/hosted features layer on top). Decide this now so the license header ships from the first commit.