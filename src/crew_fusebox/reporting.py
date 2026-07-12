"""Reporting — color-coded, scannable spend warnings on stderr.

Stdlib-only ANSI coloring (no dependencies, per the ultra-lightweight positioning). Color is
suppressed when ``NO_COLOR`` is set, when ``FORCE_COLOR`` is unset and stderr is not a TTY, or
when explicitly disabled — so piped/CI logs stay clean plain text.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

_RESET = "\033[0m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BOLD = "\033[1m"


def _color_enabled(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _level_for(pct: float) -> tuple[str, str]:
    """Return (label, ansi_color) for a budget fraction."""
    if pct >= 1.0:
        return "BUDGET EXCEEDED", _RED
    if pct >= 0.8:
        return "BUDGET HIGH", _YELLOW
    return "BUDGET NOTICE", _GREEN


def format_warning(
    *,
    crew_run_id: str,
    spent: float,
    budget: float,
    pct: float,
    call_count: int,
    hard_kill: bool,
    color: bool,
) -> str:
    """Build the one-line warning string (color optional)."""
    label, ansi = _level_for(pct)
    mode = "hard-kill" if hard_kill else "dry-run"
    body = (
        f"[crew-fusebox] {label}: run {crew_run_id} spent "
        f"${spent:.4f} / ${budget:.4f} ({pct * 100:.0f}%) "
        f"over {call_count} call(s) [{mode}]"
    )
    if color:
        return f"{ansi}{_BOLD}{body}{_RESET}"
    return body


def emit_warning(
    *,
    crew_run_id: str,
    spent: float,
    budget: float,
    pct: float,
    call_count: int,
    hard_kill: bool,
    stream: TextIO | None = None,
) -> str:
    """Write a color-coded warning to ``stream`` (defaults to stderr) and return the raw line.

    Returns the (uncolored) message body for testability/logging. Never raises.
    """
    out = stream if stream is not None else sys.stderr
    try:
        line = format_warning(
            crew_run_id=crew_run_id,
            spent=spent,
            budget=budget,
            pct=pct,
            call_count=call_count,
            hard_kill=hard_kill,
            color=_color_enabled(out),
        )
        print(line, file=out)
    except Exception:
        # Reporting must never crash the host.
        pass
    return format_warning(
        crew_run_id=crew_run_id,
        spent=spent,
        budget=budget,
        pct=pct,
        call_count=call_count,
        hard_kill=hard_kill,
        color=False,
    )


def format_loop_warning(
    *,
    crew_run_id: str,
    loop_kind: str,
    loop_count: int,
    agent_name: str | None,
    call_count: int,
    hard_kill: bool,
    color: bool,
) -> str:
    """Build the loop-detection warning string (color optional)."""
    mode = "hard-kill" if hard_kill else "dry-run"
    agent = agent_name or "unknown"
    body = (
        f"[crew-fusebox] LOOP DETECTED ({loop_kind}): "
        f"run {crew_run_id} agent={agent} "
        f"{loop_count} consecutive repeats "
        f"over {call_count} call(s) [{mode}]"
    )
    if color:
        return f"{_RED}{_BOLD}{body}{_RESET}"
    return body


def emit_loop_warning(
    *,
    crew_run_id: str,
    loop_kind: str,
    loop_count: int,
    agent_name: str | None,
    call_count: int,
    hard_kill: bool,
    stream: TextIO | None = None,
) -> str:
    """Write a loop-detection warning to ``stream`` and return the raw line.

    Returns the (uncolored) message body. Never raises.
    """
    out = stream if stream is not None else sys.stderr
    try:
        line = format_loop_warning(
            crew_run_id=crew_run_id,
            loop_kind=loop_kind,
            loop_count=loop_count,
            agent_name=agent_name,
            call_count=call_count,
            hard_kill=hard_kill,
            color=_color_enabled(out),
        )
        print(line, file=out)
    except Exception:
        pass
    return format_loop_warning(
        crew_run_id=crew_run_id,
        loop_kind=loop_kind,
        loop_count=loop_count,
        agent_name=agent_name,
        call_count=call_count,
        hard_kill=hard_kill,
        color=False,
    )
