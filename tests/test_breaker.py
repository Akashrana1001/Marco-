"""Task 8: end-to-end decorator behavior with a simulated CrewAI kickoff.

A fake ``crewai.hooks`` module stores the registered hooks; a fake ``kickoff`` fires them
exactly like CrewAI would (before each LLM call, then after), so we exercise the full
orchestration without the real dependency.
"""

import sys
import types

import pytest

from agent_breaker import crew_adapter, crew_circuit_breaker
from agent_breaker.exceptions import CircuitBreakerException


class _FakeLLM:
    def __init__(self, model="gpt-4o-mini"):
        self.model = model


class _FakeCtx:
    def __init__(self, iterations=0):
        self.messages = [{"role": "user", "content": "hello world"}]
        self.response = "a b c d e"  # 5 words
        self.llm = _FakeLLM()
        self.iterations = iterations
        self.agent = self.task = self.crew = None


class _FakeLiteLLM(types.ModuleType):
    def __init__(self):
        super().__init__("litellm")

    def token_counter(self, model=None, messages=None, text=None):
        if messages is not None:
            return 100 * len(messages)  # 100 prompt tokens / call
        if text is not None:
            return len(text.split())  # 5 completion tokens / call
        return 0

    def cost_per_token(self, model=None, prompt_tokens=0, completion_tokens=0):
        # 100*0.001 + 5*0.002 = 0.11 dollars per call
        return (prompt_tokens * 0.001, completion_tokens * 0.002)


def _install_fakes(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", _FakeLiteLLM())

    crewai = types.ModuleType("crewai")
    hooks = types.ModuleType("crewai.hooks")
    store = {"before": [], "after": []}
    hooks.register_before_llm_call_hook = lambda fn: store["before"].append(fn)
    hooks.register_after_llm_call_hook = lambda fn: store["after"].append(fn)
    hooks.unregister_before_llm_call_hook = lambda fn: store["before"].remove(fn)
    hooks.unregister_after_llm_call_hook = lambda fn: store["after"].remove(fn)
    crewai.hooks = hooks
    monkeypatch.setitem(sys.modules, "crewai", crewai)
    monkeypatch.setitem(sys.modules, "crewai.hooks", hooks)
    return store


def _fake_kickoff(store, n_calls):
    """Simulate CrewAI firing before/after hooks around each LLM call."""
    for i in range(n_calls):
        ctx = _FakeCtx(iterations=i)
        for hb in list(store["before"]):
            if hb(ctx) is False:  # blocked (dry-run never returns False here)
                return "blocked"
        for ha in list(store["after"]):
            ha(ctx)
    return "done"


@pytest.fixture(autouse=True)
def _reset_refcount():
    crew_adapter._reset_for_tests()
    yield
    crew_adapter._reset_for_tests()


def test_dry_run_completes_and_warns(monkeypatch, capsys):
    store = _install_fakes(monkeypatch)

    @crew_circuit_breaker(max_budget_dollars=0.25, hard_kill=False)
    def pipeline():
        return _fake_kickoff(store, n_calls=5)

    assert pipeline() == "done"  # dry-run never interrupts
    err = capsys.readouterr().err
    assert "agent-breaker" in err  # warnings were emitted
    # hooks cleaned up
    assert store["before"] == []
    assert store["after"] == []


def test_hard_kill_trips_with_exception(monkeypatch):
    store = _install_fakes(monkeypatch)

    @crew_circuit_breaker(max_budget_dollars=0.25, hard_kill=True)
    def pipeline():
        return _fake_kickoff(store, n_calls=10)

    # 0.11/call: after 3 calls spent=0.33 >= 0.25 -> next before_llm_call blocks.
    with pytest.raises(CircuitBreakerException) as ei:
        pipeline()
    assert ei.value.spent_dollars == pytest.approx(0.33, abs=1e-6)
    assert ei.value.budget_dollars == 0.25
    assert ei.value.call_count == 3
    # hooks cleaned up even though an exception propagated
    assert store["before"] == []
    assert store["after"] == []


def test_hooks_unregistered_when_wrapped_fn_raises(monkeypatch):
    store = _install_fakes(monkeypatch)

    @crew_circuit_breaker(max_budget_dollars=5.0)
    def pipeline():
        raise ValueError("user code broke")

    with pytest.raises(ValueError):
        pipeline()
    assert store["before"] == []
    assert store["after"] == []


def test_no_budget_never_trips(monkeypatch):
    store = _install_fakes(monkeypatch)

    @crew_circuit_breaker(hard_kill=True)  # no budget -> enforcement disabled
    def pipeline():
        return _fake_kickoff(store, n_calls=20)

    assert pipeline() == "done"


def test_fails_open_when_crewai_missing(monkeypatch):
    # litellm present but crewai import fails -> breaker does nothing, fn still runs.
    monkeypatch.setitem(sys.modules, "litellm", _FakeLiteLLM())
    monkeypatch.setitem(sys.modules, "crewai", None)

    @crew_circuit_breaker(max_budget_dollars=0.01, hard_kill=True)
    def pipeline():
        return "ran anyway"

    assert pipeline() == "ran anyway"
