"""Task 4: pricing adapter over LiteLLM, with fail-open behavior.

A fake ``litellm`` module is injected into ``sys.modules`` so these tests run without the real
(heavy) dependency installed.
"""

import sys
import types

import pytest

from agent_breaker import pricing


class _FakeLiteLLM(types.ModuleType):
    """Minimal stand-in for the litellm module surface we use."""

    KNOWN = {"gpt-4o-mini"}

    def __init__(self):
        super().__init__("litellm")

    def token_counter(self, model=None, messages=None, text=None):
        if model not in self.KNOWN:
            raise ValueError(f"unknown model {model!r}")
        if messages is not None:
            # 10 tokens per message, deterministic.
            return 10 * len(messages)
        if text is not None:
            return len(text.split())
        return 0

    def cost_per_token(self, model=None, prompt_tokens=0, completion_tokens=0):
        if model not in self.KNOWN:
            raise ValueError(f"unknown model {model!r}")
        # $1 per 1000 prompt tokens, $2 per 1000 completion tokens.
        return (prompt_tokens * 0.001, completion_tokens * 0.002)


@pytest.fixture
def fake_litellm(monkeypatch):
    fake = _FakeLiteLLM()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


def test_count_input_tokens_known_model(fake_litellm):
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    assert pricing.count_input_tokens("gpt-4o-mini", msgs) == 20


def test_count_output_tokens_known_model(fake_litellm):
    assert pricing.count_output_tokens("gpt-4o-mini", "one two three") == 3


def test_price_known_model(fake_litellm):
    # 1000 prompt * 0.001 + 500 completion * 0.002 = 1.0 + 1.0 = 2.0
    assert pricing.price("gpt-4o-mini", 1000, 500) == pytest.approx(2.0)


def test_empty_inputs_short_circuit_to_zero(fake_litellm):
    assert pricing.count_input_tokens("gpt-4o-mini", []) == 0
    assert pricing.count_output_tokens("gpt-4o-mini", "") == 0
    assert pricing.price("gpt-4o-mini", 0, 0) == 0.0


def test_unknown_model_fails_open(fake_litellm, capsys):
    assert pricing.price("no-such-model", 1000, 1000) == 0.0
    assert pricing.count_input_tokens("no-such-model", [{"role": "user", "content": "x"}]) == 0
    err = capsys.readouterr().err
    assert "failing open" in err


def test_missing_litellm_fails_open(monkeypatch, capsys):
    # Simulate litellm not being importable.
    monkeypatch.setitem(sys.modules, "litellm", None)
    assert pricing.price("gpt-4o-mini", 100, 100) == 0.0
    assert pricing.count_input_tokens("gpt-4o-mini", [{"role": "user", "content": "x"}]) == 0
    err = capsys.readouterr().err
    assert "failing open" in err
