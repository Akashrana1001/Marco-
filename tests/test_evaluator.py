"""Task 5: pure evaluator decisions."""

from agent_breaker.evaluator import Action, evaluate


def test_below_all_thresholds_allows():
    d = evaluate(1.0, 10.0)
    assert d.action is Action.ALLOW
    assert d.pct == 0.1


def test_crossing_50_percent_warns():
    d = evaluate(5.0, 10.0)
    assert d.action is Action.WARN
    assert d.threshold_crossed == 0.5


def test_crossing_80_percent_warns_at_highest_threshold():
    d = evaluate(8.5, 10.0)
    assert d.action is Action.WARN
    assert d.threshold_crossed == 0.8


def test_at_budget_dry_run_warns_not_blocks():
    d = evaluate(10.0, 10.0, hard_kill=False)
    assert d.action is Action.WARN
    assert d.threshold_crossed == 1.0


def test_over_budget_dry_run_warns():
    d = evaluate(25.0, 10.0, hard_kill=False)
    assert d.action is Action.WARN


def test_at_budget_hard_kill_blocks():
    d = evaluate(10.0, 10.0, hard_kill=True)
    assert d.action is Action.BLOCK
    assert d.pct == 1.0


def test_over_budget_hard_kill_blocks():
    d = evaluate(12.0, 10.0, hard_kill=True)
    assert d.action is Action.BLOCK


def test_under_budget_hard_kill_still_allows():
    d = evaluate(1.0, 10.0, hard_kill=True)
    assert d.action is Action.ALLOW


def test_no_budget_always_allows():
    assert evaluate(100.0, None).action is Action.ALLOW
    assert evaluate(100.0, 0).action is Action.ALLOW
    assert evaluate(100.0, -5).action is Action.ALLOW


def test_custom_thresholds():
    d = evaluate(3.0, 10.0, warn_thresholds=(0.3, 0.6))
    assert d.action is Action.WARN
    assert d.threshold_crossed == 0.3
