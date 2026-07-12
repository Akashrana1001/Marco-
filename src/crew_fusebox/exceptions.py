"""The one exception crew-fusebox intentionally raises into the host application.

Only raised in hard-kill mode when the dollar budget is deliberately breached. All other
internal failures fail open (see ``CONVENTIONS.md`` §3).
"""

from __future__ import annotations


class CircuitBreakerException(Exception):
    """Raised when a crew run breaches its dollar budget in hard-kill mode.

    Carries structured context so the host can log or report exactly why the breaker tripped.

    Attributes:
        crew_run_id: Identifier of the crew run that tripped the breaker.
        spent_dollars: Cumulative dollar spend recorded when the breaker tripped.
        budget_dollars: The configured dollar ceiling for the run.
        call_count: Number of LLM calls recorded for the run at trip time.
        recent_traces: Optional list of recent execution trace fragments (Phase 2 use).
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        crew_run_id: str | None = None,
        spent_dollars: float = 0.0,
        budget_dollars: float = 0.0,
        call_count: int = 0,
        recent_traces: list[str] | None = None,
    ) -> None:
        self.crew_run_id = crew_run_id
        self.spent_dollars = spent_dollars
        self.budget_dollars = budget_dollars
        self.call_count = call_count
        self.recent_traces = recent_traces or []
        if message is None:
            message = (
                f"crew-fusebox tripped: crew run {crew_run_id!r} spent "
                f"${spent_dollars:.4f} of ${budget_dollars:.4f} budget "
                f"after {call_count} LLM call(s)."
            )
        super().__init__(message)
