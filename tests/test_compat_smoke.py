"""Task 9: CrewAI compatibility smoke test.

Two layers:

1. **Offline symbol check** — if CrewAI is importable, assert its hook API exposes the exact
   symbols ``crew_adapter`` depends on. This catches a breaking change to CrewAI's hook surface
   in CI. It is *skipped* (not failed) when CrewAI is not installed, so the core suite stays
   dependency-free.

2. **Live test** — gated behind ``AGENT_BREAKER_LIVE=1`` plus a provider API key. Runs a tiny
   real crew with a near-zero budget and asserts the breaker trips with
   ``CircuitBreakerException``. Skipped by default so CI never makes paid API calls.
"""

import importlib.util
import os

import pytest

from agent_breaker import CircuitBreakerException, crew_circuit_breaker

REQUIRED_HOOK_SYMBOLS = (
    "register_before_llm_call_hook",
    "register_after_llm_call_hook",
    "unregister_before_llm_call_hook",
    "unregister_after_llm_call_hook",
)

_CREWAI_AVAILABLE = importlib.util.find_spec("crewai") is not None


@pytest.mark.skipif(not _CREWAI_AVAILABLE, reason="crewai not installed")
def test_crewai_hook_api_symbols_present():
    """The pinned CrewAI must expose the hook symbols the adapter relies on."""
    from crewai import hooks

    missing = [s for s in REQUIRED_HOOK_SYMBOLS if not hasattr(hooks, s)]
    assert not missing, (
        f"CrewAI hook API changed — missing symbols: {missing}. "
        "Update agent_breaker.crew_adapter to match."
    )


@pytest.mark.skipif(not _CREWAI_AVAILABLE, reason="crewai not installed")
def test_llm_call_hook_context_has_expected_fields():
    """LLMCallHookContext should expose the attributes the adapter reads."""
    try:
        from crewai.hooks import LLMCallHookContext  # type: ignore
    except Exception:
        pytest.skip("LLMCallHookContext not importable in this CrewAI version")
    annotations = getattr(LLMCallHookContext, "__annotations__", {})
    # Non-fatal informational assertion: at minimum these are documented fields.
    for field in ("messages", "response", "iterations"):
        assert field in annotations or hasattr(LLMCallHookContext, field), (
            f"LLMCallHookContext missing expected field {field!r}"
        )


_LIVE = os.environ.get("AGENT_BREAKER_LIVE") == "1"
_HAS_KEY = any(
    os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
)


@pytest.mark.skipif(
    not (_LIVE and _CREWAI_AVAILABLE and _HAS_KEY),
    reason="live test requires AGENT_BREAKER_LIVE=1, crewai installed, and a provider API key",
)
def test_live_hard_kill_trips_real_crew():  # pragma: no cover - only runs when explicitly gated
    """A real crew with a near-zero budget must trip the breaker deterministically."""
    from crewai import Agent, Crew, Task

    model = os.environ.get("AGENT_BREAKER_LIVE_MODEL", "gpt-4o-mini")

    agent = Agent(
        role="Writer",
        goal="Write a very long story",
        backstory="You write endlessly.",
        llm=model,
        max_iter=50,
    )
    task = Task(
        description="Write a 2000-word story about a robot. Keep expanding it.",
        expected_output="A long story.",
        agent=agent,
    )

    @crew_circuit_breaker(max_budget_dollars=0.0001, hard_kill=True)
    def run():
        return Crew(agents=[agent], tasks=[task]).kickoff()

    with pytest.raises(CircuitBreakerException):
        run()
