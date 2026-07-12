"""Task 7: CrewAI adapter hooks + registration, all with fakes (no real deps)."""

import sys
import types

import pytest

from crew_fusebox import crew_adapter
from crew_fusebox.state import bind_run, unbind_run

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

    def cost_per_token(
        self,
        model=None,
        prompt_tokens=0,
        completion_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    ):
        uncached_prompt = max(
            prompt_tokens - cache_creation_input_tokens - cache_read_input_tokens,
            0,
        )
        prompt_cost = (
            uncached_prompt * 0.001
            + cache_read_input_tokens * 0.0005
            + cache_creation_input_tokens * 0.00125
        )
        return (prompt_cost, completion_tokens * 0.002)


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
    assert "BUDGET NOTICE" in first or "crew-fusebox" in first
    # Second call at the same threshold should not re-emit.
    assert crew_adapter.before_llm_call(_FakeCtx()) is None
    second = capsys.readouterr().err
    assert second == ""


def test_before_over_budget_dry_run_does_not_raise(bound_run):
    bound_run(dollars=20.0, budget_dollars=10.0, hard_kill=False)
    assert crew_adapter.before_llm_call(_FakeCtx()) is None


def test_before_hard_kill_returns_false_and_marks_tripped(bound_run):
    state = bound_run(dollars=10.0, budget_dollars=10.0, hard_kill=True)
    # CrewAI blocks only on a False return; the hook must not raise.
    assert crew_adapter.before_llm_call(_FakeCtx()) is False
    assert state.tripped is True
    assert state.trip_info is not None
    assert state.trip_info["budget_dollars"] == 10.0
    assert state.trip_info["crew_run_id"] == "run-x"
    # Once tripped, every subsequent call is blocked cheaply.
    assert crew_adapter.before_llm_call(_FakeCtx()) is False


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


class _FakeUsageMetrics:
    def __init__(
        self,
        prompt_tokens=0,
        completion_tokens=0,
        cached_prompt_tokens=0,
        cache_creation_tokens=0,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.cached_prompt_tokens = cached_prompt_tokens
        self.cache_creation_tokens = cache_creation_tokens


def test_after_llm_call_with_summary_and_caching(bound_run, fake_litellm):
    state = bound_run(budget_dollars=100.0)

    # Setup the mock LLM with get_token_usage_summary
    metrics_before = _FakeUsageMetrics(
        prompt_tokens=100,
        completion_tokens=50,
        cached_prompt_tokens=10,
        cache_creation_tokens=0,
    )
    metrics_after = _FakeUsageMetrics(
        prompt_tokens=300,
        completion_tokens=100,
        cached_prompt_tokens=90,
        cache_creation_tokens=50,
    )

    summary_calls = []

    def get_summary():
        if not summary_calls:
            summary_calls.append(1)
            return metrics_before
        return metrics_after

    ctx = _FakeCtx(response="hello world")
    ctx.llm.get_token_usage_summary = get_summary

    # Run before_llm_call to store metrics_before
    assert crew_adapter.before_llm_call(ctx) is None

    # Run after_llm_call to compute diff and price with cache
    assert crew_adapter.after_llm_call(ctx) is None

    # prompt_tokens = 300 - 100 = 200
    # completion_tokens = 100 - 50 = 50
    # cached_prompt_tokens = 90 - 10 = 80
    # cache_creation_tokens = 50 - 0 = 50
    # uncached = max(200 - 50 - 80, 0) = 70.
    # Cost = 70 * 0.001 (0.07) + 80 * 0.0005 (0.04) + 50 * 0.00125 (0.0625) = 0.1725.
    # Completion cost = 50 * 0.002 = 0.10.
    # Total expected cost = 0.1725 + 0.10 = 0.2725.
    assert state.prompt_tokens == 200
    assert state.completion_tokens == 50
    assert state.call_count == 1
    assert state.dollars == pytest.approx(0.2725)
