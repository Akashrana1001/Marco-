"""Behavioral proof of the ROADMAP hook spike — FREE, no key, no network, no spend.

Runs genuine CrewAI orchestration (so the real ``before_llm_call`` / ``after_llm_call`` dispatch
executes) with the OpenAI SDK's ``Completions.create`` stubbed — the actual network seam CrewAI
uses for this model — so there is no network call and no cost. Runs in the normal CI matrix.

Trip logic (see src/agent_breaker/crew_adapter.py): ``after_llm_call`` books cost from content via
LiteLLM pricing (real model name -> non-zero pricing); ``before_llm_call`` gates on *cumulative*
spend (0 on the first call, so the first call is always allowed and the breaker blocks from the
second gate). Two sequential tasks guarantee a second gate.

This module currently also captures diagnostics (hook firings, provider calls, surfaced exception)
so CI reveals the exact real-CrewAI behavior.
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
    from crewai import hooks as crewai_hooks
    from openai.resources.chat.completions import Completions
    from openai.types.chat import ChatCompletion
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message import ChatCompletionMessage
    from openai.types.completion_usage import CompletionUsage

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")

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

    # Independent diagnostic counters registered alongside the breaker's hooks.
    before = {"n": 0}
    after = {"n": 0}

    def _cb(ctx):
        before["n"] += 1
        return None

    def _ca(ctx):
        after["n"] += 1
        return None

    crewai_hooks.register_before_llm_call_hook(_cb)
    crewai_hooks.register_after_llm_call_hook(_ca)

    agent = Agent(
        role="Writer",
        goal="Answer in one short sentence.",
        backstory="You reply in one brief sentence and stop.",
        llm="gpt-4o-mini",
        max_iter=3,
        allow_delegation=False,
    )
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

    raised: BaseException | None = None
    try:
        run()
    except BaseException as exc:  # capture whatever surfaces, for diagnosis
        raised = exc
    finally:
        crewai_hooks.unregister_before_llm_call_hook(_cb)
        crewai_hooks.unregister_after_llm_call_hook(_ca)

    diag = (
        f"before_fired={before['n']} after_fired={after['n']} provider_calls={calls['n']} "
        f"raised={type(raised).__name__ if raised else None}: {raised!r}"
    )
    assert isinstance(raised, CircuitBreakerException), f"breaker did not halt crew -> {diag}"
    assert calls["n"] == 1, f"expected exactly one real provider call -> {diag}"
