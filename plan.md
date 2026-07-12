# crew-fusebox — Build Plan (zero → PyPI-ready Phase 1 MVP)

> Execution plan for turning the docs in `sdk/` into a working, MIT-licensed, pip-installable
> Python SDK. Source-of-truth docs: `sdk/claude.md`, `sdk/ARCHITECTURE.md`, `sdk/PRD.md`,
> `sdk/CONVENTIONS.md`, `sdk/GLOSSARY.md`, `sdk/ROADMAP.md`.

## Goal

Build `crew-fusebox`: a single decorator (`@crew_circuit_breaker`) that wraps a CrewAI
`kickoff()`, tracks real-time dollar spend across the whole crew, warns in dry-run mode, and
deterministically blocks the next LLM call (raising `CircuitBreakerException`) in hard-kill mode —
without ever crashing a healthy host application.

## Execution protocol

1. Write this plan to `plan.md` (done).
2. Build task by task, in order.
3. After each task, run its tests and confirm green **before** proceeding. Do not proceed past a
   failing task.
4. Toolchain: `uv` + `hatchling`, `src/` layout, Python `>=3.10,<3.14`, `pytest` + `ruff`.

## Design decisions (locked)

- **Enforcement** binds to CrewAI's `before_llm_call` hook (blocks the call pre-dispatch); cost is
  reconciled in `after_llm_call`. Never use `step_callback`/`task_callback` for enforcement; never
  patch sockets.
- **Cost** is computed via LiteLLM: `litellm.token_counter` (input from `messages` in the
  before-hook, output from the `response` string in the after-hook) + `litellm.cost_per_token`
  against LiteLLM's maintained `model_prices_and_context_window.json`. No hand-rolled price table.
  (Rationale: CrewAI's `after_llm_call` context exposes `response` as a string, not a usage object.)
- **Sub-ms** guarantee applies to the block *decision* (dict lookup + float compare); token
  counting is amortized in the after-hook, off the blocking path.
- **Defaults** to `hard_kill=False` (dry-run). Fail open on any internal breaker error (stderr
  warning, let the agent proceed). Only `CircuitBreakerException` is intentionally raised into the
  host, and only in hard-kill when the budget is breached.
- **Binding**: active `RunState` bound per run via `contextvars` (async/thread-safe), keyed to a
  generated `crew_run_id`, since CrewAI hooks register globally.
- **Pins**: `crewai>=1.14,<2`; LiteLLM used transitively for pricing.
- **Assumptions**: budget is per decorated kickoff run; default warn thresholds ~50/80/100%; cost is
  a LiteLLM token estimate (not exact provider usage); no persistence/telemetry in Phase 1.

> Environment note: CrewAI and LiteLLM are heavy and the build network is slow/unreliable. The
> package uses **lazy imports** for both, and unit tests inject fakes via `sys.modules`, so the full
> suite (Tasks 1–9) runs without installing those deps. Real installs are only needed for the
> env-gated live smoke test (Task 9b) and packaging (Task 10).

## Package structure

```
src/crew_fusebox/
  __init__.py      # public API: crew_circuit_breaker, CircuitBreakerException
  exceptions.py    # CircuitBreakerException (crew_run_id, spent_dollars, budget_dollars, call_count, recent_traces)
  state.py         # RunState + thread-safe registry (contextvars-bound)
  pricing.py       # LiteLLM pricing adapter (token_counter + cost_per_token), fail-open
  evaluator.py     # pure sub-ms decision: ALLOW / WARN / BLOCK
  reporting.py     # color-coded stderr warnings (stdlib ANSI, NO_COLOR aware)
  crew_adapter.py  # thin isolation over crewai.hooks (register/unregister before/after)
  breaker.py       # @crew_circuit_breaker orchestration
  py.typed
tests/             # mirrored unit tests + env-gated live smoke test
LICENSE (MIT), README.md, CHANGELOG.md, pyproject.toml, plan.md
```

## Task breakdown (build in order; test after each)

- **Task 1 — Scaffold + toolchain.** uv/hatchling `src/` package, MIT LICENSE, `pyproject.toml`
  (dist `crew-fusebox`, pkg `crew_fusebox`, `requires-python>=3.10,<3.14`, dep `crewai>=1.14,<2`,
  dev extras pytest+ruff), ruff+pytest config, `py.typed`.
  Test: trivial import test passes; `import crew_fusebox` works.
- **Task 2 — `CircuitBreakerException` + public API skeleton.** Structured exception + exported
  pass-through `crew_circuit_breaker`.
  Test: exception fields + `__str__`; decorator calls through and returns value.
- **Task 3 — State matrix (`state.py`).** `RunState` (+Lock) and contextvars-bound registry.
  Test: concurrent updates correct; runs isolated; missing context fails open.
- **Task 4 — Pricing (`pricing.py`).** `count_input_tokens`, `count_output_tokens`, `price` over
  LiteLLM; fail open to 0.0 + stderr on error/unknown model.
  Test: mocked litellm known/unknown model behavior.
- **Task 5 — Evaluator (`evaluator.py`).** Pure `evaluate(...) -> Decision{ALLOW|WARN|BLOCK, pct}`.
  Test: threshold transitions for dry-run vs hard-kill.
- **Task 6 — Reporting (`reporting.py`).** Color-coded stderr warnings; NO_COLOR / non-TTY aware.
  Test: message content per level; color present/absent.
- **Task 7 — CrewAI adapter (`crew_adapter.py`).** before/after hook closures; register/unregister;
  fail-open. Isolates all `crewai.hooks` symbols.
  Test: fake `LLMCallHookContext`; allow/warn/block transitions; state updates; internal error fails open.
- **Task 8 — Decorator wiring (`breaker.py`).** Real `@crew_circuit_breaker`; contextvar RunState;
  register hooks; always unregister in `finally`; hard-kill raises `CircuitBreakerException`.
  Test: end-to-end mocked kickoff; dry-run warns/never raises; hard-kill trips; hooks always cleaned up; fail open.
- **Task 9 — Compat smoke test.** Offline symbol check against pinned CrewAI (CI) + env-gated live
  test (`AGENT_BREAKER_LIVE=1` + API key), skipped by default.
- **Task 10 — Packaging & release prep.** Finalize metadata/classifiers, README, CHANGELOG;
  `uv build` → wheel+sdist; `twine check`; clean-venv install + import.

## Verification rules

After each task: `python -m pytest tests/test_<name>.py` (and `ruff` where available), confirm green
before proceeding. Keep `sdk/` docs unchanged unless a discovered inconsistency requires it. Clean
up temp files.
