# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

Phase 1 MVP — passive cost tracking + opt-in hard-kill for CrewAI.

### Added
- `@crew_circuit_breaker` decorator wrapping a CrewAI `kickoff()` with real-time, cross-agent
  dollar-spend tracking.
- Enforcement bound to CrewAI's `before_llm_call` hook (blocks the next call pre-dispatch);
  cost reconciled in `after_llm_call`.
- Passive **dry-run / audit mode** (default) with color-coded, `NO_COLOR`-aware stderr warnings
  at configurable budget thresholds.
- Opt-in **hard-kill** mode raising a structured `CircuitBreakerException` when the dollar
  ceiling is breached.
- Thread-safe, `contextvars`-bound in-memory state matrix (tokens, dollars, call counts).
- Pricing via LiteLLM's maintained data (`token_counter` + `cost_per_token`); no hand-rolled
  price table.
- Fail-open resilience: any internal breaker error warns on stderr and lets the agent proceed.
- Thin CrewAI adapter isolating the `crewai.hooks` surface, plus an offline compatibility smoke
  test and an env-gated (`AGENT_BREAKER_LIVE=1`) live test.

### Project
- uv + hatchling toolchain, `src/` layout, MIT license, typed (`py.typed`).
- GitHub Actions CI (`.github/workflows/ci.yml`): lint + full test suite across Python
  3.11–3.13 with CrewAI installed (so the compatibility smoke test runs for real), plus a
  build + `twine check` job.
- Runnable dogfood example (`examples/quickstart.py`) for the ROADMAP validation gate.
- Python floor set to **3.11** (CrewAI's transitive `onnxruntime` no longer ships cp310 wheels;
  confirmed via CI — 3.11/3.12/3.13 pass, 3.10 fails at install).
