"""Task 3: thread-safe state matrix + contextvars registry."""

import threading

from crew_fusebox.state import (
    RunState,
    bind_run,
    get_active_run,
    unbind_run,
)


def test_record_call_accumulates():
    s = RunState(crew_run_id="r1")
    s.record_call(prompt_tokens=10, completion_tokens=5, dollars=0.01)
    s.record_call(prompt_tokens=20, completion_tokens=5, dollars=0.02)
    assert s.prompt_tokens == 30
    assert s.completion_tokens == 10
    assert s.total_tokens == 40
    assert s.call_count == 2
    assert round(s.dollars, 4) == 0.03


def test_depth_tracks_max():
    s = RunState(crew_run_id="r1")
    s.record_call(depth=3)
    s.record_call(depth=1)
    s.record_call(depth=5)
    assert s.depth == 5


def test_concurrent_updates_are_thread_safe():
    s = RunState(crew_run_id="r1")
    n_threads = 16
    per_thread = 500

    def worker():
        for _ in range(per_thread):
            s.record_call(prompt_tokens=1, completion_tokens=1, dollars=0.001)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = n_threads * per_thread
    assert s.call_count == expected
    assert s.prompt_tokens == expected
    assert s.completion_tokens == expected
    assert round(s.dollars, 3) == round(expected * 0.001, 3)


def test_snapshot_is_consistent():
    s = RunState(crew_run_id="r1")
    s.record_call(prompt_tokens=3, completion_tokens=4, dollars=0.05)
    snap = s.snapshot()
    assert snap["crew_run_id"] == "r1"
    assert snap["total_tokens"] == 7
    assert snap["call_count"] == 1
    assert snap["dollars"] == 0.05


def test_missing_context_fails_open():
    # No run bound in a fresh context -> None, never raises.
    assert get_active_run() is None


def test_bind_and_unbind_round_trip():
    s = RunState(crew_run_id="bound")
    token = bind_run(s)
    try:
        assert get_active_run() is s
    finally:
        unbind_run(token)
    assert get_active_run() is None


def test_runs_are_isolated_across_threads():
    results: dict[str, str | None] = {}
    barrier = threading.Barrier(2)

    def run_with(run_id: str):
        s = RunState(crew_run_id=run_id)
        token = bind_run(s)
        try:
            barrier.wait(timeout=5)  # ensure both threads are active simultaneously
            active = get_active_run()
            results[run_id] = active.crew_run_id if active else None
        finally:
            unbind_run(token)

    t1 = threading.Thread(target=run_with, args=("A",))
    t2 = threading.Thread(target=run_with, args=("B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Each thread sees only its own bound run (contextvars isolate per thread).
    assert results == {"A": "A", "B": "B"}
