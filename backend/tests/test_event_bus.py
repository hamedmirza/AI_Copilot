from app.services.run_engine.event_bus import EventBus


def test_unsubscribe_run_prunes_empty_run_id() -> None:
    bus = EventBus()
    queue = bus.subscribe_run("run-a")
    assert "run-a" in bus._run_queues
    bus.unsubscribe_run("run-a", queue)
    assert "run-a" not in bus._run_queues


def test_unsubscribe_chat_prunes_empty_session_id() -> None:
    bus = EventBus()
    queue = bus.subscribe_chat("session-a")
    assert "session-a" in bus._chat_queues
    bus.unsubscribe_chat("session-a", queue)
    assert "session-a" not in bus._chat_queues


def test_unsubscribe_run_keeps_other_subscribers() -> None:
    bus = EventBus()
    q1 = bus.subscribe_run("run-a")
    q2 = bus.subscribe_run("run-a")
    bus.unsubscribe_run("run-a", q1)
    assert bus._run_queues.get("run-a") == [q2]
    bus.unsubscribe_run("run-a", q2)
    assert "run-a" not in bus._run_queues
