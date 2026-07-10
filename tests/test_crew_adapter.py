"""Task 7: CrewAI adapter hooks + registration, all with fakes (no real deps)."""

import sys
import types

import pytest

from agent_breaker import crew_adapter
from agent_breaker.exceptions import CircuitBreakerException
from agent_breaker.state import bind_run, unbind_run


# --- Fakes ---------------------------------------------------------------------------------


class _FakeLLM:
    def __init__(self, model="gpt-4o-mini"):
        self.model = model


class _FakeCtx:
    """Mimics CrewAI's LLMCallHookContext surface."""

    def __init__(self, messages=None, response=None, model="gpt-4o-mini", iterations=0):
        self.messages = messages or []
        self.response = response
        self.llm = _FakeLLM(model)
        self.iterations = iterations
        self.agent = None
        self.task = None
        self.crew = None


class _FakeLiteLLM(types.ModuleType):
    def __init__(self):
        super().__init__("litellm")

    def token_counter(self, model=None, messages=None, text=None):
        if messages is not None:
            return 100 * len(messages)
        if text is not None:
            return len(text.split())
        return 0

    def cost_per_token(self, model=None, prompt_tokens=0, completion_tokens=0):
        return (prompt_tokens * 0.001, completion_tokens * 0.002)


@pytest.fixture
def fake_litellm(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", _FakeLiteLLM())


@pytest.fixture
def bound_run():
    """Bind a configured run and clean it up afterwards."""
    states = []

    def _bind(**cfg):
        state = crew_adapter.make_run_state(
            cfg.pop("crew_run_id", "run-x"),
            budget_dollars=cfg.pop("budget_dollars", 10.0),
            hard_kill=cfg.pop("hard_kill", False),
            warn_thresholds=cfg.pop("warn_thresholds", (0.5, 0.8, 1.0)),
        )
        # allow presetting accumulated spend
        state.dollars = cfg.pop("dollars", 0.0)
        token = bind_run(state)
        states.append((state, token))
        return state

    yield _bind

    for _, token in states:
        unbind_run(token)


# --- before_llm_call -----------------------------------------------------------------------


def test_before_no_active_run_allows():
    assert crew_adapter.before_llm_call(_FakeCtx()) is None


def test_before_under_budget_allows(bound_run):
    bound_run(dollars=1.0, budget_dollars=10.0)
    assert crew_adapter.before_llm_call(_FakeCtx()) is None


def test_before_warns_in_dry_run_and_dedups(bound_run, capsys):
    bound_run(dollars=5.0, budget_dollars=10.0, hard_kill=False)
    assert crew_adapter.before_llm_call(_FakeCtx()) is None
    first = capsys.readouterr().err
    assert "BUDGET NOTICE" in first or "agent-breaker" in first
    # Second call at the same threshold should not re-emit.
    assert crew_adapter.before_llm_call(_FakeCtx()) is None
    second = capsys.readouterr().err
    assert second == ""


def test_before_over_budget_dry_run_does_not_raise(bound_run):
    bound_run(dollars=20.0, budget_dollars=10.0, hard_kill=False)
    assert crew_adapter.before_llm_call(_FakeCtx()) is None


def test_before_hard_kill_blocks_with_exception(bound_run):
    bound_run(dollars=10.0, budget_dollars=10.0, hard_kill=True)
    with pytest.raises(CircuitBreakerException) as ei:
        crew_adapter.before_llm_call(_FakeCtx())
    assert ei.value.budget_dollars == 10.0
    assert ei.value.crew_run_id == "run-x"


def test_before_internal_error_fails_open(bound_run, monkeypatch, capsys):
    bound_run(dollars=5.0, budget_dollars=10.0)

    def boom(*a, **k):
        raise RuntimeError("evaluate exploded")

    monkeypatch.setattr(crew_adapter, "evaluate", boom)
    # Must not raise; fails open.
    assert crew_adapter.before_llm_call(_FakeCtx()) is None
    assert "failing open" in capsys.readouterr().err


# --- after_llm_call ------------------------------------------------------------------------


def test_after_no_active_run_returns_none():
    assert crew_adapter.after_llm_call(_FakeCtx()) is None


def test_after_records_cost(bound_run, fake_litellm):
    state = bound_run(budget_dollars=100.0)
    ctx = _FakeCtx(
        messages=[{"role": "user", "content": "hello world"}],
        response="one two three four five",
    )
    assert crew_adapter.after_llm_call(ctx) is None
    # 1 message -> 100 prompt tokens; response 5 words -> 5 completion tokens.
    assert state.prompt_tokens == 100
    assert state.completion_tokens == 5
    assert state.call_count == 1
    # cost = 100*0.001 + 5*0.002 = 0.1 + 0.01 = 0.11
    assert round(state.dollars, 4) == 0.11


def test_after_internal_error_fails_open(bound_run, monkeypatch, capsys):
    bound_run(budget_dollars=100.0)

    monkeypatch.setattr(
        crew_adapter.pricing,
        "count_input_tokens",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert crew_adapter.after_llm_call(_FakeCtx(messages=[{"content": "x"}])) is None
    assert "failing open" in capsys.readouterr().err


# --- registration --------------------------------------------------------------------------


def _make_fake_crewai(registered):
    crewai = types.ModuleType("crewai")
    hooks = types.ModuleType("crewai.hooks")

    def reg_before(fn):
        registered["before"].append(fn)

    def reg_after(fn):
        registered["after"].append(fn)

    def unreg_before(fn):
        registered["before"].remove(fn)

    def unreg_after(fn):
        registered["after"].remove(fn)

    hooks.register_before_llm_call_hook = reg_before
    hooks.register_after_llm_call_hook = reg_after
    hooks.unregister_before_llm_call_hook = unreg_before
    hooks.unregister_after_llm_call_hook = unreg_after
    crewai.hooks = hooks
    return crewai, hooks


@pytest.fixture(autouse=True)
def _reset_refcount():
    crew_adapter._reset_for_tests()
    yield
    crew_adapter._reset_for_tests()


def test_register_and_unregister_refcounted(monkeypatch):
    registered = {"before": [], "after": []}
    crewai, hooks = _make_fake_crewai(registered)
    monkeypatch.setitem(sys.modules, "crewai", crewai)
    monkeypatch.setitem(sys.modules, "crewai.hooks", hooks)

    assert crew_adapter.register() is True
    assert crew_adapter.register() is True  # second run, ref-count 2
    assert len(registered["before"]) == 1  # only registered once
    assert len(registered["after"]) == 1

    crew_adapter.unregister()  # ref-count -> 1, still active
    assert len(registered["before"]) == 1
    crew_adapter.unregister()  # ref-count -> 0, now removed
    assert registered["before"] == []
    assert registered["after"] == []


def test_register_fails_open_when_crewai_missing(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "crewai", None)
    assert crew_adapter.register() is False
    assert "failing open" in capsys.readouterr().err
