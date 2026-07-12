import json
import urllib.request
from unittest.mock import MagicMock, patch

from crew_fusebox import webhooks


def test_format_payload_basic():
    payload = webhooks.format_payload(
        crew_run_id="run-123",
        spent=1.5,
        budget=10.0,
        pct=0.15,
        call_count=5,
        hard_kill=True,
    )

    assert "text" in payload
    assert "content" in payload
    assert payload["text"] == payload["content"]

    text = payload["text"]
    assert "run-123" in text
    assert "$1.5000 / $10.0000" in text
    assert "(15%)" in text
    assert "hard-kill" in text


def test_format_payload_with_traces_and_loop():
    payload = webhooks.format_payload(
        crew_run_id="run-456",
        spent=5.0,
        budget=10.0,
        pct=0.5,
        call_count=10,
        hard_kill=False,
        traces=["trace1", "trace2", "trace3"],
        loop_info="REPEAT: 3x by AgentA",
    )

    text = payload["text"]
    assert "Loop: REPEAT: 3x by AgentA" in text
    assert "Last traces:" in text
    assert "1. trace1" in text
    assert "2. trace2" in text
    assert "3. trace3" in text


@patch("crew_fusebox.webhooks.threading.Thread")
def test_dispatch_alarm_spawns_thread(mock_thread):
    webhooks.dispatch_alarm(
        url="http://fake-webhook.com",
        crew_run_id="run-789",
        spent=1.0,
        budget=2.0,
        pct=0.5,
        call_count=1,
        hard_kill=True,
    )

    # Should spawn a daemon thread
    mock_thread.assert_called_once()
    assert mock_thread.call_args[1].get("daemon") is True

    # And start it
    mock_thread.return_value.start.assert_called_once()


@patch("crew_fusebox.webhooks.urllib.request.urlopen")
def test_dispatch_alarm_thread_behavior(mock_urlopen):
    # Call the inner function directly by extracting it or using a simple wait
    # We'll just patch Thread to run synchronously for this test

    def run_sync(target, daemon):
        target()
        return MagicMock()

    with patch("crew_fusebox.webhooks.threading.Thread", side_effect=run_sync):
        webhooks.dispatch_alarm(
            url="http://fake-webhook.com",
            crew_run_id="run-789",
            spent=1.0,
            budget=2.0,
            pct=0.5,
            call_count=1,
            hard_kill=True,
        )

    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert isinstance(req, urllib.request.Request)
    assert req.full_url == "http://fake-webhook.com"
    assert req.method == "POST"
    assert req.headers.get("Content-type") == "application/json"

    # Check payload is valid JSON
    data = json.loads(req.data.decode("utf-8"))
    assert "run-789" in data["text"]


@patch("crew_fusebox.webhooks._warn")
@patch("crew_fusebox.webhooks.urllib.request.urlopen")
def test_dispatch_alarm_fails_open(mock_urlopen, mock_warn):
    mock_urlopen.side_effect = Exception("Network error")

    def run_sync(target, daemon):
        target()
        return MagicMock()

    with patch("crew_fusebox.webhooks.threading.Thread", side_effect=run_sync):
        # Should not raise
        webhooks.dispatch_alarm(
            url="http://fake-webhook.com",
            crew_run_id="run-err",
            spent=0,
            budget=1,
            pct=0,
            call_count=1,
            hard_kill=False,
        )

    mock_warn.assert_called_once()
    assert "Network error" in mock_warn.call_args[0][0]
