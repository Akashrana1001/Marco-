"""Trajectory duplication detector — catch loops *before* the budget is exhausted.

Detects the two catastrophic failure modes from the PRD:

1. **Tool Retry Loop:** The same messages repeat on consecutive LLM calls (agent
   retries a failed tool with no variation).
2. **Delegation Ping-Pong:** Alternating agent names produce an A→B→A→B pattern
   (circular delegation).

The detector operates on a rolling window of message fingerprints (SHA-256) and
agent names. Only *consecutive* duplicates count, so the same tool legitimately
called at different points in the run does **not** trigger a false positive (the
Trust Gap — see ``GLOSSARY.md``).

Pure logic, no I/O, sub-ms. Stdlib only (``hashlib`` + ``collections.deque``).
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum


class LoopKind(StrEnum):
    """Classification of a detected loop pattern."""

    REPEAT = "REPEAT"
    PING_PONG = "PING_PONG"


@dataclass(frozen=True)
class TrajectoryAlert:
    """Information about a detected loop, for reporting/webhook payloads."""

    kind: LoopKind
    count: int  # consecutive occurrences
    agent_name: str | None = None


@dataclass
class TrajectoryTracker:
    """Rolling window of message fingerprints for loop detection.

    Args:
        threshold: Number of consecutive identical fingerprints that
            triggers a REPEAT alert. Defaults to 3.
        window_size: Maximum number of entries retained. Defaults to 20.
    """

    threshold: int = 3
    window_size: int = 20
    _fingerprints: deque[str] = field(
        default_factory=deque,
        repr=False,
    )
    _agents: deque[str] = field(
        default_factory=deque,
        repr=False,
    )
    _alert: TrajectoryAlert | None = field(
        default=None,
        repr=False,
    )

    def record(
        self,
        messages: list[dict[str, object]] | None,
        agent_name: str | None = None,
    ) -> None:
        """Record a call's message fingerprint and check for loops.

        Args:
            messages: The ``ctx.messages`` list from the hook context.
            agent_name: The agent's name/role (from ``ctx.agent``).
        """
        fp = _fingerprint(messages)
        name = agent_name or ""

        self._fingerprints.append(fp)
        self._agents.append(name)

        # Trim to window size
        while len(self._fingerprints) > self.window_size:
            self._fingerprints.popleft()
            self._agents.popleft()

        self._alert = None
        self._check_repeat()
        if self._alert is None:
            self._check_ping_pong()

    @property
    def detected(self) -> TrajectoryAlert | None:
        """Return the most recent alert, or ``None``."""
        return self._alert

    def _check_repeat(self) -> None:
        """Check for N consecutive identical fingerprints."""
        if len(self._fingerprints) < self.threshold:
            return
        tail = list(self._fingerprints)[-self.threshold :]
        if len(set(tail)) == 1:
            agent = list(self._agents)[-1] if self._agents else None
            self._alert = TrajectoryAlert(
                kind=LoopKind.REPEAT,
                count=self.threshold,
                agent_name=agent or None,
            )

    def _check_ping_pong(self) -> None:
        """Check for alternating A-B-A-B agent pattern.

        Requires ``threshold`` pairs (i.e. ``threshold * 2`` entries)
        to trigger, so a threshold of 3 requires 6 alternating entries.
        """
        required = self.threshold * 2
        if len(self._agents) < required:
            return
        tail = list(self._agents)[-required:]
        # Must have exactly 2 distinct agents
        unique = set(tail)
        if len(unique) != 2:
            return
        # Check strict alternation
        for i in range(1, len(tail)):
            if tail[i] == tail[i - 1]:
                return
        self._alert = TrajectoryAlert(
            kind=LoopKind.PING_PONG,
            count=required,
            agent_name=tail[-1] or None,
        )


def _fingerprint(
    messages: list[dict[str, object]] | None,
) -> str:
    """SHA-256 hex digest of a deterministic JSON serialization of messages."""
    if not messages:
        return "empty"
    try:
        raw = json.dumps(messages, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
    except Exception:
        return "error"


"""Module for trajectory-based loop detection in CrewAI runs."""
