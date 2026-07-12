"""Structured webhook alarm dispatches — Slack / Discord compatible.

Sends a JSON POST to a user-configured webhook URL when the breaker emits a
warning or blocks a call. The payload contains structured context (run ID,
spend, budget, mode) plus the **last 3 execution traces** so the alert is
actionable without opening a terminal.

Payload format is compatible with both Slack (``text`` key) and Discord
(``content`` key) incoming-webhook contracts.

**Stdlib only** — uses ``urllib.request`` (no ``requests`` dependency). The
dispatch fires in a **daemon thread** so it never blocks the LLM call path.
Fails open on any error (logged to stderr, never raised).
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from typing import Any

_TIMEOUT_SECONDS = 5


def _warn(msg: str) -> None:
    print(
        f"[crew-fusebox] webhook: {msg} (failing open)",
        file=sys.stderr,
    )


def format_payload(
    *,
    crew_run_id: str,
    spent: float,
    budget: float,
    pct: float,
    call_count: int,
    hard_kill: bool,
    event: str = "BUDGET_WARNING",
    traces: list[str] | None = None,
    loop_info: str | None = None,
) -> dict[str, Any]:
    """Build the JSON payload dict.

    The ``text`` key is for Slack; ``content`` is for Discord. Both
    are set to the same human-readable summary so one URL works for
    either platform.
    """
    mode = "hard-kill" if hard_kill else "dry-run"
    pct_str = f"{pct * 100:.0f}%"

    lines = [
        f"🚨 **[crew-fusebox] {event}**",
        f"Run: `{crew_run_id}`",
        f"Spent: ${spent:.4f} / ${budget:.4f} ({pct_str})",
        f"Calls: {call_count} | Mode: {mode}",
    ]
    if loop_info:
        lines.append(f"Loop: {loop_info}")
    if traces:
        lines.append("")
        lines.append("**Last traces:**")
        for i, trace in enumerate(traces[-3:], 1):
            lines.append(f"  {i}. {trace}")

    body = "\n".join(lines)
    return {
        "text": body,  # Slack
        "content": body,  # Discord
    }


def dispatch_alarm(
    url: str,
    *,
    crew_run_id: str,
    spent: float,
    budget: float,
    pct: float,
    call_count: int,
    hard_kill: bool,
    event: str = "BUDGET_WARNING",
    traces: list[str] | None = None,
    loop_info: str | None = None,
) -> None:
    """Fire-and-forget a webhook POST in a daemon thread.

    Never blocks the caller. Never raises. Logs to stderr on error.
    """
    payload = format_payload(
        crew_run_id=crew_run_id,
        spent=spent,
        budget=budget,
        pct=pct,
        call_count=call_count,
        hard_kill=hard_kill,
        event=event,
        traces=traces,
        loop_info=loop_info,
    )

    def _send() -> None:
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS):
                pass
        except Exception as exc:
            _warn(f"dispatch failed to {url!r}: {exc!r}")

    t = threading.Thread(target=_send, daemon=True)
    t.start()
