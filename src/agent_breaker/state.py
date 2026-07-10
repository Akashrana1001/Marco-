"""In-memory state matrix: per-run cost/token/depth tracking, thread-safe.

A ``RunState`` accumulates tokens, dollars, and call counts for a single crew run. The
active run is bound via a :class:`contextvars.ContextVar`, so the globally-registered CrewAI
hooks (see ``crew_adapter``) resolve the correct state even when multiple crew runs execute
concurrently in different threads or async tasks.
"""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field


@dataclass
class RunState:
    """Mutable, thread-safe accumulator for a single crew run.

    All mutation goes through :meth:`record_call` under a lock, so concurrent hook
    invocations for the same run cannot corrupt the totals.
    """

    crew_run_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    call_count: int = 0
    dollars: float = 0.0
    depth: int = 0
    # Per-run config. Lives on the state so the globally-registered hooks can resolve
    # everything they need from the single contextvar-bound active run.
    budget_dollars: float | None = None
    hard_kill: bool = False
    warn_thresholds: tuple[float, ...] = (0.5, 0.8, 1.0)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _warned: set[float] = field(default_factory=set, repr=False, compare=False)

    def mark_warned(self, threshold: float) -> bool:
        """Record that ``threshold`` was warned about; return ``True`` only the first time.

        Used to avoid re-emitting the same threshold warning on every subsequent call.
        """
        with self._lock:
            if threshold in self._warned:
                return False
            self._warned.add(threshold)
            return True

    def record_call(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        dollars: float = 0.0,
        depth: int = 0,
    ) -> None:
        """Atomically fold one LLM call's usage into the running totals."""
        with self._lock:
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.dollars += dollars
            self.call_count += 1
            if depth > self.depth:
                self.depth = depth

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def snapshot(self) -> dict[str, float | int | str]:
        """Return a consistent, lock-guarded copy of the current totals."""
        with self._lock:
            return {
                "crew_run_id": self.crew_run_id,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
                "call_count": self.call_count,
                "dollars": self.dollars,
                "depth": self.depth,
            }


# The active run for the current context (thread / async task). ``None`` when no breaker is
# active, in which case hooks must fail open rather than raise.
_active_run: contextvars.ContextVar[RunState | None] = contextvars.ContextVar(
    "agent_breaker_active_run", default=None
)


def bind_run(state: RunState) -> contextvars.Token:
    """Bind ``state`` as the active run for the current context.

    Returns a token that must be passed to :func:`unbind_run` to restore the previous run.
    """
    return _active_run.set(state)


def unbind_run(token: contextvars.Token) -> None:
    """Restore the active run to whatever it was before the matching :func:`bind_run`."""
    try:
        _active_run.reset(token)
    except (ValueError, LookupError):
        # Token from a different context; fail open rather than crash the host.
        _active_run.set(None)


def get_active_run() -> RunState | None:
    """Return the active :class:`RunState`, or ``None`` if none is bound (fail open)."""
    return _active_run.get()
