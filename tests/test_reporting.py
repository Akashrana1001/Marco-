"""Task 6: color-coded, NO_COLOR-aware reporting."""

import io

from crew_fusebox import reporting


def _kwargs(**over):
    base = dict(
        crew_run_id="run-1",
        spent=5.0,
        budget=10.0,
        pct=0.5,
        call_count=3,
        hard_kill=False,
    )
    base.update(over)
    return base


def test_message_content_notice():
    msg = reporting.format_warning(color=False, **_kwargs(pct=0.5))
    assert "crew-fusebox" in msg
    assert "run-1" in msg
    assert "50%" in msg
    assert "dry-run" in msg
    assert "BUDGET NOTICE" in msg


def test_message_content_high():
    msg = reporting.format_warning(color=False, **_kwargs(spent=8.5, pct=0.85))
    assert "BUDGET HIGH" in msg
    assert "85%" in msg


def test_message_content_exceeded_hard_kill():
    msg = reporting.format_warning(color=False, **_kwargs(spent=10.0, pct=1.0, hard_kill=True))
    assert "BUDGET EXCEEDED" in msg
    assert "hard-kill" in msg
    assert "100%" in msg


def test_color_present_when_enabled():
    msg = reporting.format_warning(color=True, **_kwargs(pct=1.0))
    assert "\033[" in msg  # some ANSI escape present


def test_color_absent_when_disabled():
    msg = reporting.format_warning(color=False, **_kwargs(pct=1.0))
    assert "\033[" not in msg


def test_no_color_env_suppresses_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    stream = io.StringIO()
    reporting.emit_warning(stream=stream, **_kwargs(pct=1.0))
    written = stream.getvalue()
    assert "\033[" not in written
    assert "BUDGET EXCEEDED" in written


def test_force_color_env_enables_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    stream = io.StringIO()
    reporting.emit_warning(stream=stream, **_kwargs(pct=1.0))
    assert "\033[" in stream.getvalue()


def test_non_tty_stream_is_plain(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    stream = io.StringIO()  # StringIO.isatty() is False
    reporting.emit_warning(stream=stream, **_kwargs(pct=0.85))
    assert "\033[" not in stream.getvalue()


def test_emit_returns_uncolored_body():
    stream = io.StringIO()
    returned = reporting.emit_warning(stream=stream, **_kwargs(pct=0.5))
    assert "\033[" not in returned
    assert "BUDGET NOTICE" in returned
