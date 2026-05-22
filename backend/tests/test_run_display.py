from datetime import UTC, datetime

from app.services.run_display import derive_run_display_name, run_numbers_for_task


class _Run:
    def __init__(self, run_id: str, task_id: str, created_at: datetime) -> None:
        self.id = run_id
        self.task_id = task_id
        self.created_at = created_at


def test_derive_run_display_name_from_first_task_line():
    created = datetime(2026, 5, 22, 3, 0, tzinfo=UTC)
    name = derive_run_display_name(
        "0: Implement webhook for history sync.\n1: Add idempotency keys.",
        created,
    )
    assert name == "Implement webhook for history sync."


def test_derive_run_display_name_truncates_long_lines():
    created = datetime(2026, 5, 22, 3, 0, tzinfo=UTC)
    long_line = "A" * 120
    name = derive_run_display_name(long_line, created)
    assert name.endswith("…")
    assert len(name) == 80


def test_derive_run_display_name_adds_run_number():
    created = datetime(2026, 5, 22, 3, 0, tzinfo=UTC)
    name = derive_run_display_name("Fix sync bug", created, run_number=3)
    assert name == "Fix sync bug (3)"


def test_run_numbers_for_task():
    t0 = datetime(2026, 5, 22, 1, 0, tzinfo=UTC)
    t1 = datetime(2026, 5, 22, 2, 0, tzinfo=UTC)
    runs = [
        _Run("r1", "task-a", t0),
        _Run("r2", "task-a", t1),
        _Run("r3", "task-b", t0),
    ]
    numbers = run_numbers_for_task(runs)
    assert numbers == {"r1": 1, "r2": 2, "r3": 1}
