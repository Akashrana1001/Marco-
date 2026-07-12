from crew_fusebox.trajectory import LoopKind, TrajectoryTracker


def test_trajectory_tracker_no_loop():
    tracker = TrajectoryTracker(threshold=3)

    # Send 5 completely different messages
    for i in range(5):
        tracker.record([{"content": f"msg_{i}"}], agent_name="AgentA")
        assert tracker.detected is None


def test_trajectory_tracker_repeat():
    tracker = TrajectoryTracker(threshold=3)

    # 1. First distinct call
    tracker.record([{"content": "A"}], agent_name="AgentA")
    assert tracker.detected is None

    # 2. Start of repeating calls
    msg = [{"content": "B"}]
    tracker.record(msg, agent_name="AgentA")
    assert tracker.detected is None

    tracker.record(msg, agent_name="AgentA")
    assert tracker.detected is None

    # 3. Third repeat hits threshold=3
    tracker.record(msg, agent_name="AgentA")
    alert = tracker.detected
    assert alert is not None
    assert alert.kind == LoopKind.REPEAT
    assert alert.count == 3
    assert alert.agent_name == "AgentA"


def test_trajectory_tracker_ping_pong():
    tracker = TrajectoryTracker(threshold=3)

    # Ping-Pong requires threshold*2 = 6 alternating agents
    # Let's send identical messages but alternate agents. Actually the ping-pong
    # check only looks at agents, so messages can be anything (or empty).
    agents = ["AgentA", "AgentB"] * 3

    for i, agent in enumerate(agents):
        tracker.record([{"content": str(i)}], agent_name=agent)

        # Should only alert on the 6th call
        if i < 5:
            assert tracker.detected is None
        else:
            alert = tracker.detected
            assert alert is not None
            assert alert.kind == LoopKind.PING_PONG
            assert alert.count == 6
            assert alert.agent_name == "AgentB"


def test_trajectory_tracker_window_size():
    tracker = TrajectoryTracker(threshold=3, window_size=5)

    for i in range(10):
        tracker.record([{"content": str(i)}], agent_name="AgentA")

    assert len(tracker._fingerprints) == 5
    assert len(tracker._agents) == 5


def test_fingerprint_handles_unserializable():
    # json.dumps default=str should handle random objects gracefully
    class Unserializable:
        pass

    tracker = TrajectoryTracker(threshold=2)
    tracker.record([{"obj": Unserializable()}], agent_name="A")
    tracker.record([{"obj": Unserializable()}], agent_name="A")

    # They will fingerprint to the same string representation because of default=str
    assert tracker.detected is not None
    assert tracker.detected.kind == LoopKind.REPEAT
