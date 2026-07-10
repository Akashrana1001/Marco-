"""The public ``@crew_circuit_breaker`` decorator — orchestration.

On each decorated call it:

1. generates a ``crew_run_id`` and builds a configured :class:`~agent_breaker.state.RunState`;
2. registers the CrewAI ``before_llm_call``/``after_llm_call`` hooks (ref-counted, fail open);
3. binds the run to the contextvar so the hooks resolve it;
4. runs the wrapped ``kickoff()`` function; and
5. **always** unbinds the run and releases the hooks in ``finally``.

In hard-kill mode, the ``before_llm_call`` hook raises :class:`CircuitBreakerException`, which
propagates out of ``kickoff()`` and through this wrapper to the host. All other internal
failures fail open.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from agent_breaker import crew_adapter
from agent_breaker.state import bind_run, unbind_run

F = TypeVar("F", bound=Callable[..., Any])


def crew_circuit_breaker(
    max_budget_dollars: float | None = None,
    *,
    hard_kill: bool = False,
    warn_thresholds: tuple[float, ...] = (0.5, 0.8, 1.0),
) -> Callable[[F], F]:
    """Wrap a function that calls ``crew.kickoff()`` with an economic circuit-breaker.

    Args:
        max_budget_dollars: Dollar ceiling for the decorated crew run. ``None`` disables
            enforcement (pure passive tracking).
        hard_kill: If ``True``, block the next LLM call and raise ``CircuitBreakerException``
            once the budget is breached. Defaults to ``False`` (passive dry-run / audit mode).
        warn_thresholds: Fractions of the budget at which to emit escalating warnings.

    Returns:
        A decorator that returns a wrapper preserving the original function's metadata.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            crew_run_id = uuid.uuid4().hex
            state = crew_adapter.make_run_state(
                crew_run_id,
                budget_dollars=max_budget_dollars,
                hard_kill=hard_kill,
                warn_thresholds=warn_thresholds,
            )
            registered = crew_adapter.register()
            token = bind_run(state)
            try:
                return func(*args, **kwargs)
            finally:
                unbind_run(token)
                if registered:
                    crew_adapter.unregister()

        return wrapper  # type: ignore[return-value]

    return decorator
