"""Evaluator — the pure, sub-millisecond budget decision.

This is the hot path. It does only arithmetic and comparisons: no I/O, no tokenizing, no
locks. Given the cumulative spend and the budget, it returns whether the next call should be
allowed, warned about, or blocked. Enforcement/side-effects live elsewhere (adapter/reporter).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Action(StrEnum):
    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class Decision:
    """Outcome of a budget evaluation.

    Attributes:
        action: What the caller should do next.
        pct: Fraction of budget consumed (``spent / budget``); ``inf`` if budget <= 0.
        threshold_crossed: The highest warn threshold reached (for WARN), else ``None``.
    """

    action: Action
    pct: float
    threshold_crossed: float | None = None


def evaluate(
    spent: float,
    budget: float | None,
    *,
    hard_kill: bool = False,
    warn_thresholds: tuple[float, ...] = (0.5, 0.8, 1.0),
) -> Decision:
    """Decide whether the next LLM call should be allowed, warned, or blocked.

    Args:
        spent: Cumulative dollars spent so far in the run.
        budget: The dollar ceiling. ``None`` or ``<= 0`` disables enforcement (always ALLOW,
            since there is no meaningful budget to compare against).
        hard_kill: If ``True``, a breach (>= 100% of budget) yields ``BLOCK``. If ``False``
            (dry-run), a breach yields ``WARN`` and the run is never interrupted.
        warn_thresholds: Ascending fractions of the budget at which to warn.

    Returns:
        A :class:`Decision`. This function never raises for ordinary inputs.
    """
    if budget is None or budget <= 0:
        return Decision(Action.ALLOW, pct=float("inf") if spent > 0 else 0.0)

    pct = spent / budget

    if pct >= 1.0:
        if hard_kill:
            return Decision(Action.BLOCK, pct=pct, threshold_crossed=1.0)
        return Decision(Action.WARN, pct=pct, threshold_crossed=1.0)

    crossed: float | None = None
    for t in sorted(warn_thresholds):
        if t < 1.0 and pct >= t:
            crossed = t
    if crossed is not None:
        return Decision(Action.WARN, pct=pct, threshold_crossed=crossed)

    return Decision(Action.ALLOW, pct=pct)
