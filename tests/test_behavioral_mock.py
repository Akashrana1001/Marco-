"""Behavioral proof of the ROADMAP hook spike — FREE, no key, no network, no spend.

The compatibility smoke test proves CrewAI *exposes* the hook symbols. This test proves the
breaker actually **halts a real crew**: it runs genuine CrewAI orchestration (so the real
``before_llm_call`` / ``after_llm_call`` dispatch executes and our hard-kill raise must survive
CrewAI's hook machinery), but replaces ``litellm.completion`` with a canned mock so there is no
network call and no cost. It therefore runs in the normal CI matrix on every push (CI installs
CrewAI), unlike the live test which needs a paid API key.

How the trip is guaranteed (see src/agent_breaker/crew_adapter.py):
- ``after_llm_call`` books cost from message/response *content* via LiteLLM pricing using the real
  model name ("gpt-4o-mini" has non-zero pricing), so a mocked response still books real dollars.
- ``before_llm_call`` evaluates *cumulative* spend, which is 0 on the first call, so the first
  call is always ALLOWED; the breaker can only BLOCK from the second gate onward. Two sequential
  tasks guarantee a second gate fires.
- In hard-kill mode the breaker *raises* ``CircuitBreakerException`` from ``before_llm_call``.

Assertions: (a) the run raises ``CircuitBreakerException``, and (b) exactly ONE real completion
happened — proving the second call was genuinely blocked before dispatch, not merely that some
exception occurred.
"""

import importlib.util

import pytest

from agent_breaker import CircuitBreakerException, crew_circuit_breaker

_CREWAI_AVAILABLE = importlib.util.find_spec("crewai") is not None


@pytest.mark.skipif(not _CREWAI_AVAILABLE, reason="crewai not installed")
def test_breaker_halts_real_crew_with_mocked_llm(monkeypatch):
    import litellm
    from crewai import Agent, Crew, Task

    # No real key is ever used (the completion is mocked), but CrewAI/LiteLLM may check for one
    # at construction/validation time.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")

    # Wrap litellm.completion: count real invocations and short-circuit to LiteLLM's own mock
    # handling (returns a valid ModelResponse, no network) by injecting mock_response.
    calls = {"n": 0}
    real_completion = litellm.completion

    def fake_completion(*args, **kwargs):
        calls["n"] += 1
        kwargs["mock_response"] = "A robot."
        return real_completion(*args, **kwargs)

    monkeypatch.setattr(litellm, "completion", fake_completion)

    model = "gpt-4o-mini"  # real model name -> non-zero LiteLLM pricing
    agent = Agent(
        role="Writer",
        goal="Answer in one short sentence.",
        backstory="You reply in one brief sentence and stop.",
        llm=model,
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

    # The breach is booked after call #1; call #2's before_llm_call must block before any
    # further completion -> exactly one real LLM call.
    assert calls["n"] == 1, f"expected exactly one real LLM call before the block, got {calls['n']}"
