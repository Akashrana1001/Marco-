"""CrewAI adapter — the *only* module that touches ``crewai.hooks``.

Isolating CrewAI here means a breaking change to CrewAI's hook signature or import path is
absorbed in one file, not scattered across the codebase (see ``ARCHITECTURE.md`` §8).

Enforcement binds to ``before_llm_call`` (runs before each LLM call; returning ``False`` blocks
it, and we raise ``CircuitBreakerException`` in hard-kill mode). Cost is reconciled in
``after_llm_call`` from the actual response. Both hooks resolve the active run from contextvars
(``state.get_active_run``), so a single globally-registered pair of hooks correctly serves any
number of concurrent runs.

Every hook body is wrapped so that an internal error fails open (warn on stderr, allow the
call). The only exception intentionally propagated is ``CircuitBreakerException``.
"""

from __future__ import annotations

import sys
import threading
from typing import Any

from agent_breaker import pricing, reporting
from agent_breaker.evaluator import Action, evaluate
from agent_breaker.state import RunState, get_active_run


def _warn(msg: str) -> None:
    print(f"[agent-breaker] adapter: {msg} (failing open)", file=sys.stderr)


def _resolve_model(ctx: Any) -> str:
    """Best-effort extraction of the model name from a hook context."""
    llm = getattr(ctx, "llm", None)
    for attr in ("model", "model_name"):
        val = getattr(llm, attr, None)
        if isinstance(val, str) and val:
            return val
    val = getattr(ctx, "model", None)
    return val if isinstance(val, str) and val else "unknown"


def before_llm_call(ctx: Any) -> bool | None:
    """Pre-call gate. Return ``False`` to block the call; ``None`` to allow.

    CrewAI's hook runner blocks a call only when a before-hook *returns* ``False`` — it catches
    and ignores exceptions raised by hooks. So on a hard-kill breach we mark the run ``tripped``
    and return ``False`` (never raise); the decorator surfaces ``CircuitBreakerException`` to the
    host after the run. In dry-run we warn and allow.
    """
    try:
        state = get_active_run()
        if state is None:
            return None  # no active breaker in this context; fail open

        # Once tripped, block every subsequent (retried) call cheaply — no re-evaluation.
        if state.tripped:
            return False

        decision = evaluate(
            state.dollars,
            state.budget_dollars,
            hard_kill=state.hard_kill,
            warn_thresholds=state.warn_thresholds,
        )

        if decision.action is Action.BLOCK:
            state.mark_tripped()
            return False

        if decision.action is Action.WARN and decision.threshold_crossed is not None:
            if state.mark_warned(decision.threshold_crossed):
                reporting.emit_warning(
                    crew_run_id=state.crew_run_id,
                    spent=state.dollars,
                    budget=float(state.budget_dollars or 0.0),
                    pct=decision.pct,
                    call_count=state.call_count,
                    hard_kill=state.hard_kill,
                )
        return None
    except Exception as exc:  # fail open on any internal error
        _warn(f"before_llm_call error: {exc!r}")
        return None


def after_llm_call(ctx: Any) -> str | None:
    """Post-call reconciliation. Counts tokens from the real call and books the cost.

    Returns ``None`` (never modifies the response). Fails open on any error.
    """
    try:
        state = get_active_run()
        if state is None:
            return None

        model = _resolve_model(ctx)
        messages = getattr(ctx, "messages", None)
        response = getattr(ctx, "response", None)
        iterations = getattr(ctx, "iterations", 0) or 0

        prompt_tokens = pricing.count_input_tokens(model, messages)
        completion_tokens = pricing.count_output_tokens(model, response)
        dollars = pricing.price(model, prompt_tokens, completion_tokens)

        state.record_call(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            dollars=dollars,
            depth=int(iterations) if isinstance(iterations, int) else 0,
        )
        return None
    except Exception as exc:  # fail open
        _warn(f"after_llm_call error: {exc!r}")
        return None


# --- Registration (ref-counted, isolates the crewai.hooks import surface) -----------------

_reg_lock = threading.Lock()
_ref_count = 0


def _crewai_hooks() -> Any | None:
    """Import ``crewai.hooks`` lazily; return the module or ``None`` (fail open)."""
    try:
        from crewai import hooks  # type: ignore

        return hooks
    except Exception as exc:  # pragma: no cover - exercised via monkeypatched import
        _warn(f"crewai.hooks unavailable: {exc!r}")
        return None


def register() -> bool:
    """Register the before/after hooks with CrewAI (idempotent, ref-counted).

    Returns ``True`` if the hooks are active after this call, ``False`` if CrewAI's hook API
    was unavailable (fail open — the breaker then simply does nothing).
    """
    global _ref_count
    with _reg_lock:
        hooks = _crewai_hooks()
        if hooks is None:
            return False
        if _ref_count == 0:
            try:
                hooks.register_before_llm_call_hook(before_llm_call)
                hooks.register_after_llm_call_hook(after_llm_call)
            except Exception as exc:
                _warn(f"hook registration failed: {exc!r}")
                return False
        _ref_count += 1
        return True


def unregister() -> None:
    """Unregister the hooks once the last active run releases them (ref-counted). Fail open."""
    global _ref_count
    with _reg_lock:
        if _ref_count == 0:
            return
        _ref_count -= 1
        if _ref_count > 0:
            return
        hooks = _crewai_hooks()
        if hooks is None:
            return
        for name, fn in (
            ("unregister_before_llm_call_hook", before_llm_call),
            ("unregister_after_llm_call_hook", after_llm_call),
        ):
            try:
                getattr(hooks, name)(fn)
            except Exception as exc:
                _warn(f"{name} failed: {exc!r}")


def _reset_for_tests() -> None:
    """Reset the ref-count (test helper only)."""
    global _ref_count
    with _reg_lock:
        _ref_count = 0


def make_run_state(
    crew_run_id: str,
    *,
    budget_dollars: float | None,
    hard_kill: bool,
    warn_thresholds: tuple[float, ...],
) -> RunState:
    """Construct a configured :class:`RunState` for a decorated run (used by the decorator)."""
    return RunState(
        crew_run_id=crew_run_id,
        budget_dollars=budget_dollars,
        hard_kill=hard_kill,
        warn_thresholds=warn_thresholds,
    )
