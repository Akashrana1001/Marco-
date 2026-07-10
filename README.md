# agent-breaker

[![CI](https://github.com/Akashrana1001/Marco-/actions/workflows/ci.yml/badge.svg)](https://github.com/Akashrana1001/Marco-/actions/workflows/ci.yml)

> Stop your AI agents from bankrupting you.

An ultra-lightweight, open-source **economic circuit-breaker** for
[CrewAI](https://crewai.com) multi-agent systems. Wrap your `kickoff()` with one decorator to
get real-time dollar-spend tracking across the whole crew and an opt-in hard budget ceiling that
deterministically stops a runaway loop before it produces an invoice-shock bill.

## Why not just `max_iter` / `max_rpm`?

CrewAI already caps an agent's *iteration count* (`max_iter`) and *request rate* (`max_rpm`).
agent-breaker does **not** duplicate those. It stops loops **by real-time dollar cost, aggregated
across every agent in a crew**, and blocks the next LLM call the moment a budget ceiling is
breached — the economic dimension CrewAI's per-agent, count/rate-based knobs don't model.

## Install

```bash
pip install agent-breaker
```

Requires Python 3.11–3.13 and `crewai>=1.14`.

## Quickstart

```python
from agent_breaker import crew_circuit_breaker, CircuitBreakerException
from crewai import Crew

# Dry-run / audit mode (default): passively tracks spend and prints color-coded warnings,
# never interrupts the run.
@crew_circuit_breaker(max_budget_dollars=5.00)
def run_pipeline():
    return Crew(agents=[...], tasks=[...]).kickoff()

# Hard-kill mode: blocks the next LLM call and raises CircuitBreakerException once the
# dollar ceiling is breached.
@crew_circuit_breaker(max_budget_dollars=5.00, hard_kill=True)
def run_guarded_pipeline():
    return Crew(agents=[...], tasks=[...]).kickoff()

try:
    run_guarded_pipeline()
except CircuitBreakerException as exc:
    print(f"Tripped after ${exc.spent_dollars:.4f} across {exc.call_count} calls")
```

## How it works

- **Enforcement** binds to CrewAI's `before_llm_call` hook, which runs *before* each LLM call and
  can block it — so a hard-kill stops spend *before* the next call is dispatched. (CrewAI's
  `step_callback`/`task_callback` fire *after* a step and only report; they can't prevent the next
  call.)
- **Cost** is computed from real token usage via LiteLLM's maintained pricing data
  (`token_counter` + `cost_per_token`), so there is no hand-maintained price table to go stale.
- **Safe by default:** ships in dry-run mode; only blocks when you opt in with `hard_kill=True`.
- **Fail-open:** any internal error in the breaker warns on stderr and lets your agent proceed —
  it never crashes a healthy host application.

## Enforcement semantics (read this)

Hard-kill blocks the **next** LLM call after the budget is breached — not the call that breaches
it. This is intentional:

- Cost is booked in `after_llm_call` from the *actual* response, so the breaker only knows a call
  put you over budget **after** that call returns. The following `before_llm_call` is then blocked
  and `CircuitBreakerException` is raised.
- The pre-call decision is deliberately a sub-millisecond compare (no tokenizing on the hot path),
  and true cost can't be known before a call anyway (output tokens don't exist yet).

Practical consequence: **you may overshoot the budget by roughly one call.** For the target use
case — a runaway loop against a budget many times a single call's cost (e.g. a `$5` ceiling with
`~$0.01` calls) — this is negligible. It only matters if one call is a large fraction of the whole
budget, so set the ceiling with a small buffer above a single expected call's cost.

## Configuration

| Argument | Default | Meaning |
| --- | --- | --- |
| `max_budget_dollars` | `None` | Dollar ceiling for the run. `None` = passive tracking only. |
| `hard_kill` | `False` | Block + raise on breach. `False` = warn only (dry-run). |
| `warn_thresholds` | `(0.5, 0.8, 1.0)` | Budget fractions at which to emit escalating warnings. |

## Status

Phase 1 MVP. License: **MIT**. See [`plan.md`](./plan.md) and the design docs in
[`sdk/`](./sdk).
