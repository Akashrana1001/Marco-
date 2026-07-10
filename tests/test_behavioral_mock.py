"""Behavioral proof of the ROADMAP hook spike — FREE, no key, no network, no spend.

The compatibility smoke test proves CrewAI *exposes* the hook symbols. This test proves the
breaker actually **halts a real crew**: it runs genuine CrewAI orchestration (so the real
``before_llm_call`` / ``after_llm_call`` dispatch executes and our hard-kill raise must survive
CrewAI's own retry/error handling), but drives the LLM with CrewAI's native ``mock_response`` so
there is no network call and no cost. It runs in the normal CI matrix (CI installs CrewAI).

How the trip is guaranteed (see src/agent_breaker/crew_adapter.py):
- ``after_llm_call`` books cost from message/response *content* via LiteLLM pricing using the real
  model name ("gpt-4o-mini" has non-zero pricing), so a mocked response still books real dollars.
- ``before_llm_call`` evaluates *cumulative* spend, 0 on the first call, so the first call is
  always ALLOWED; the breaker can only BLOCK from the second gate onward. Two sequential tasks
  guarantee a second gate fires.
- In hard-kill mode the breaker *raises* ``CircuitBreakerException`` from ``before_llm_call``.

Assertions: (a) the run raises ``CircuitBreakerException``, and (b) exactly ONE real completion
happened (counted via CrewAI's own ``after_llm_call`` hook, which fires only after a call
returns) — proving the second call was blocked before dispatch.
"""

import importlib.util

import pytest

from agent_breaker import CircuitBreakerException, crew_circuit_breaker

_CREWAI_AVAILABLE = importlib.util.find_spec("crewai") is not None


@pytest.mark.skipif(not _CREWAI_AVAILABLE, reason="crewai not installed")
def test_breaker_halts_real_crew_with_mocked_llm(monkeypatch):
    from crewai import LLM, Agent, Crew, Task
    from crewai import hooks as crewai_hooks

    # No real key is ever used (mock_response short-circuits the provider call), but CrewAI may
    # validate one at construction time.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")

    # Count *completed* LLM calls via CrewAI's own after_llm_call hook: it fires only after a
    # call returns, so a call blocked in before_llm_call never increments it.
    completions = {"n": 0}

    def _count_after(ctx):
        completions["n"] += 1
        return None

    crewai_hooks.register_after_llm_call_hook(_count_after)

    try:
        # CrewAI-native mock: returns a canned string without any provider/network call, while
        # still going through CrewAI's LLM path so the before/after hooks fire for real.
        llm = LLM(model="gpt-4o-mini", mock_response="A robot.")

        agent = Agent(
            role="Writer",
            goal="Answer in one short sentence.",
            backstory="You reply in one brief sentence and stop.",
            llm=llm,
            max_iter=3,
            allow_delegation=False,
        )
        # Two sequential tasks guarantee at least two before_llm_call gates fire.
        tasks = [
            Task(
                description=f"Write one short sentence about a robot (variation {i}).",
                expected_output="One short sentence.",
                agent=agent,
            )
            for i in range(2)
        ]

        @crew_circuit_breaker(max_budget_dollars=1e-9, hard_kill=True)
        def run():
            return Crew(agents=[agent], tasks=tasks, memory=False).kickoff()

        with pytest.raises(CircuitBreakerException):
            run()

        # The breach is booked after call #1; call #2 must be blocked before it completes.
        assert completions["n"] == 1, (
            f"expected exactly one completed LLM call before the block, got {completions['n']}"
        )
    finally:
        crewai_hooks.unregister_after_llm_call_hook(_count_after)
