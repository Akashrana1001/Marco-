"""Task 2: CircuitBreakerException fields + pass-through decorator."""

import crew_fusebox
from crew_fusebox import CircuitBreakerException, crew_circuit_breaker


def test_public_api_exports():
    assert hasattr(crew_fusebox, "crew_circuit_breaker")
    assert hasattr(crew_fusebox, "CircuitBreakerException")


def test_exception_stores_fields():
    exc = CircuitBreakerException(
        crew_run_id="run-123",
        spent_dollars=5.25,
        budget_dollars=5.0,
        call_count=7,
        recent_traces=["a", "b"],
    )
    assert exc.crew_run_id == "run-123"
    assert exc.spent_dollars == 5.25
    assert exc.budget_dollars == 5.0
    assert exc.call_count == 7
    assert exc.recent_traces == ["a", "b"]


def test_exception_str_is_informative():
    exc = CircuitBreakerException(
        crew_run_id="run-123", spent_dollars=5.25, budget_dollars=5.0, call_count=7
    )
    text = str(exc)
    assert "run-123" in text
    assert "5.25" in text or "5.2500" in text
    assert "7" in text


def test_exception_custom_message_overrides():
    exc = CircuitBreakerException("boom", crew_run_id="r")
    assert str(exc) == "boom"


def test_exception_is_an_exception():
    assert issubclass(CircuitBreakerException, Exception)


def test_decorator_passes_through_and_returns_value():
    @crew_circuit_breaker(max_budget_dollars=1.0)
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


def test_decorator_preserves_metadata():
    @crew_circuit_breaker(max_budget_dollars=1.0, hard_kill=True)
    def documented():
        """my docstring"""
        return 1

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "my docstring"


def test_decorator_forwards_args_and_kwargs():
    @crew_circuit_breaker()
    def echo(*args, **kwargs):
        return args, kwargs

    assert echo(1, 2, x=3) == ((1, 2), {"x": 3})
