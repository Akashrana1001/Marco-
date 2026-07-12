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

import contextvars
import sys
import threading
from typing import Any

from crew_fusebox import pricing, reporting, webhooks
from crew_fusebox.evaluator import Action, evaluate
from crew_fusebox.state import RunState, get_active_run

_pre_call_metrics: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "crew_fusebox_pre_call_metrics", default=None
)


def _warn(msg: str) -> None:
    print(f"[crew-fusebox] adapter: {msg} (failing open)", file=sys.stderr)


def _resolve_model(ctx: Any) -> str:
    """Best-effort extraction of the model name from a hook context."""
    llm = getattr(ctx, "llm", None)
    for attr in ("model", "model_name"):
        val = getattr(llm, attr, None)
        if isinstance(val, str) and val:
            return val
    val = getattr(ctx, "model", None)
    return val if isinstance(val, str) and val else "unknown"


def _resolve_agent_name(ctx: Any) -> str | None:
    """Best-effort extraction of the agent name from a hook context."""
    agent = getattr(ctx, "agent", None)
    for attr in ("role", "name"):
        val = getattr(agent, attr, None)
        if isinstance(val, str) and val:
            return val
    return None


def _dispatch_webhook(
    state: RunState,
    *,
    event: str,
    pct: float,
    loop_info: str | None = None,
) -> None:
    """Fire a webhook alarm if ``state.webhook_url`` is set. Fail open."""
    if not state.webhook_url:
        return
    try:
        webhooks.dispatch_alarm(
            state.webhook_url,
            crew_run_id=state.crew_run_id,
            spent=state.dollars,
            budget=float(state.budget_dollars or 0.0),
            pct=pct,
            call_count=state.call_count,
            hard_kill=state.hard_kill,
            event=event,
            traces=list(state.traces),
            loop_info=loop_info,
        )
    except Exception as exc:
        _warn(f"webhook dispatch error: {exc!r}")


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

        # Try to capture pre-call token usage metrics
        llm = getattr(ctx, "llm", None)
        if llm and hasattr(llm, "get_token_usage_summary"):
            try:
                summary = llm.get_token_usage_summary()
                if summary is not None:
                    _pre_call_metrics.set(
                        {
                            "prompt_tokens": getattr(summary, "prompt_tokens", 0) or 0,
                            "completion_tokens": getattr(summary, "completion_tokens", 0) or 0,
                            "cached_prompt_tokens": getattr(summary, "cached_prompt_tokens", 0)
                            or 0,
                            "cache_creation_tokens": getattr(summary, "cache_creation_tokens", 0)
                            or 0,
                        }
                    )
            except Exception as exc:
                _warn(f"failed to read pre-call token usage: {exc!r}")

        decision = evaluate(
            state.dollars,
            state.budget_dollars,
            hard_kill=state.hard_kill,
            warn_thresholds=state.warn_thresholds,
        )

        if decision.action is Action.BLOCK:
            state.mark_tripped()
            _dispatch_webhook(state, event="BUDGET_BREACHED", pct=decision.pct)
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
                _dispatch_webhook(
                    state,
                    event="BUDGET_WARNING",
                    pct=decision.pct,
                )

        # Phase 2: trajectory loop detection (runs after budget check).
        if state.trajectory is not None:
            try:
                messages = getattr(ctx, "messages", None)
                agent_name = _resolve_agent_name(ctx)
                state.trajectory.record(messages, agent_name)
                alert = state.trajectory.detected
                if alert is not None:
                    loop_info = f"{alert.kind}: {alert.count}x by {alert.agent_name or 'unknown'}"
                    if state.hard_kill:
                        state.mark_tripped()
                        _dispatch_webhook(
                            state,
                            event="LOOP_DETECTED",
                            pct=decision.pct,
                            loop_info=loop_info,
                        )
                        return False
                    reporting.emit_loop_warning(
                        crew_run_id=state.crew_run_id,
                        loop_kind=alert.kind,
                        loop_count=alert.count,
                        agent_name=alert.agent_name,
                        call_count=state.call_count,
                        hard_kill=state.hard_kill,
                    )
                    _dispatch_webhook(
                        state,
                        event="LOOP_DETECTED",
                        pct=decision.pct,
                        loop_info=loop_info,
                    )
            except Exception as exc:
                _warn(f"trajectory detection error: {exc!r}")

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

        llm = getattr(ctx, "llm", None)
        old_metrics = _pre_call_metrics.get()
        _pre_call_metrics.set(None)  # reset

        prompt_tokens = 0
        completion_tokens = 0
        cached_prompt_tokens = 0
        cache_creation_tokens = 0
        used_summary = False

        if llm and hasattr(llm, "get_token_usage_summary") and old_metrics is not None:
            try:
                new_summary = llm.get_token_usage_summary()
                if new_summary is not None:
                    new_pt = getattr(new_summary, "prompt_tokens", 0) or 0
                    new_ct = getattr(new_summary, "completion_tokens", 0) or 0
                    new_cpt = getattr(new_summary, "cached_prompt_tokens", 0) or 0
                    new_cct = getattr(new_summary, "cache_creation_tokens", 0) or 0
                    prompt_tokens = new_pt - old_metrics["prompt_tokens"]
                    completion_tokens = new_ct - old_metrics["completion_tokens"]
                    cached_prompt_tokens = new_cpt - old_metrics["cached_prompt_tokens"]
                    cache_creation_tokens = new_cct - old_metrics["cache_creation_tokens"]
                    if prompt_tokens >= 0 and completion_tokens >= 0:
                        used_summary = True
            except Exception as exc:
                _warn(f"failed to read post-call token usage: {exc!r}")

        if not used_summary:
            prompt_tokens = pricing.count_input_tokens(model, messages)
            completion_tokens = pricing.count_output_tokens(model, response)
            cached_prompt_tokens = 0
            cache_creation_tokens = 0

        dollars = pricing.price(
            model,
            prompt_tokens,
            completion_tokens,
            cache_read_input_tokens=cached_prompt_tokens,
            cache_creation_input_tokens=cache_creation_tokens,
        )

        state.record_call(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            dollars=dollars,
            depth=int(iterations) if isinstance(iterations, int) else 0,
        )

        # Phase 2: record a human-readable trace for webhook payloads.
        agent_name = _resolve_agent_name(ctx) or "unknown"
        trace = f"{agent_name} → {model}: {prompt_tokens}pt+{completion_tokens}ct ${dollars:.4f}"
        state.add_trace(trace)

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
    detect_loops: bool = False,
    loop_threshold: int = 3,
    webhook_url: str | None = None,
) -> RunState:
    """Construct a configured :class:`RunState` for a decorated run."""
    from crew_fusebox.trajectory import TrajectoryTracker

    trajectory = TrajectoryTracker(threshold=loop_threshold) if detect_loops else None
    return RunState(
        crew_run_id=crew_run_id,
        budget_dollars=budget_dollars,
        hard_kill=hard_kill,
        warn_thresholds=warn_thresholds,
        trajectory=trajectory,
        webhook_url=webhook_url,
    )
