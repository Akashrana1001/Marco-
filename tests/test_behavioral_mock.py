"""Behavioral proof of the ROADMAP hook spike — FREE, no key, no network, no spend.

The compatibility smoke test proves CrewAI *exposes* the hook symbols. This test proves the
breaker actually **halts a real crew**: it runs genuine CrewAI orchestration (so the real
``before_llm_call`` / ``after_llm_call`` dispatch executes and our block must survive CrewAI's own
hook machinery), while stubbing the OpenAI SDK's ``Completions.create`` — the actual network seam
CrewAI uses for this model — so there is no network call and no cost. It runs in the normal CI
matrix (CI installs CrewAI + the OpenAI SDK), unlike the live test which needs a paid API key.

How the trip is guaranteed (see src/agent_breaker/crew_adapter.py + breaker.py):
- ``after_llm_call`` books cost from message/response *content* via LiteLLM pricing using the real
  model name ("gpt-4o-mini" has non-zero pricing), so a stubbed response still books real dollars.
- ``before_llm_call`` gates on *cumulative* spend, 0 on the first call, so the first call is
  always allowed; the breaker blocks from the second gate onward. Two sequential tasks guarantee a
  second gate.
- On breach, ``before_llm_call`` *returns False* (CrewAI's documented block; a raising hook would
  be swallowed) and marks the run tripped; the decorator then raises ``CircuitBreakerException``.

Assertions: (a) the run raises ``CircuitBreakerException``, and (b) the LLM was invoked exactly
ONCE — proving the second call was blocked before it reached the provider.
"""

import importlib.util

import pytest

from agent_breaker import CircuitBreakerException, crew_circuit_breaker

_CREWAI_AVAILABLE = importlib.util.find_spec("crewai") is not None
_OPENAI_AVAILABLE = importlib.util.find_spec("openai") is not None


@pytest.mark.skipif(
    not (_CREWAI_AVAILABLE and _OPENAI_AVAILABLE),
    reason="requires crewai + openai installed (CI does; offline suite skips)",
)
def test_breaker_halts_real_crew_with_mocked_llm(monkeypatch):
    from crewai import Agent, Crew, Task
    from openai.resources.chat.completions import Completions
    from openai.types.chat import ChatCompletion
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message import ChatCompletionMessage
    from openai.types.completion_usage import CompletionUsage

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")

    # Stub the OpenAI SDK network call: keeps ALL of CrewAI's orchestration and hook dispatch
    # intact (before/after_llm_call still fire) while guaranteeing no network/spend, and counts
    # real provider calls directly.
    calls = {"n": 0}

    def _fake_create(self, *args, **kwargs):
        calls["n"] += 1
        return ChatCompletion(
            id="mock-cmpl",
            created=0,
            model="gpt-4o-mini",
            object="chat.completion",
            choices=[
                Choice(
                    index=0,
                    finish_reason="stop",
                    message=ChatCompletionMessage(role="assistant", content="A robot."),
                )
            ],
            usage=CompletionUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
        )

    monkeypatch.setattr(Completions, "create", _fake_create)

    agent = Agent(
        role="Writer",
        goal="Answer in one short sentence.",
        backstory="You reply in one brief sentence and stop.",
        llm="gpt-4o-mini",  # real model name -> non-zero LiteLLM pricing
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

    # The breach is booked after call #1; call #2 must be blocked before it reaches the provider.
    assert calls["n"] == 1, (
        f"expected exactly one real provider call before the block, got {calls['n']}"
    )
