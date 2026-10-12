"""Contract tests for the shared pure schedule planner."""

import datetime as dt

import pytest
from schedules.commands import (
    BlockCandidate,
    BlockSnapshot,
    CreateCommand,
    DeleteCommand,
    ReorderCommand,
    RestoreCommand,
    ScheduleSnapshot,
    UpdateCommand,
)
from schedules.planning import (
    AI,
    DRAFT,
    IMPORT,
    MANUAL,
    UNDO,
    CommandError,
    diff_candidates,
    plan_commands,
    validate_block_interval,
    validate_final_state,
)
from schedules.window import ScheduleWindow


def clock(value: str) -> dt.time:
    return dt.time.fromisoformat(value)


WINDOW = ScheduleWindow(clock("06:00"), clock("21:00"))


def block(block_id: int, start: str, end: str, *, order: int = 0) -> BlockSnapshot:
    return BlockSnapshot(
        block_id, clock(start), clock(end), f"Task {block_id}", "work", False, order
    )


def schedule(*blocks: BlockSnapshot) -> ScheduleSnapshot:
    return ScheduleSnapshot(7, dt.date(2026, 10, 10), blocks)


def create(start: str, end: str, *, action_index: int | None = None) -> CreateCommand:
    return CreateCommand("New", clock(start), clock(end), "work", action_index=action_index)


def test_final_state_allows_swap_and_batch_shift() -> None:
    original = schedule(block(1, "08:00", "09:00"), block(2, "09:00", "10:00", order=1))
    swap = ReorderCommand(
        (
            UpdateCommand(1, start_time=clock("09:00"), end_time=clock("10:00")),
            UpdateCommand(2, start_time=clock("08:00"), end_time=clock("09:00")),
        )
    )
    plan = plan_commands(original, [swap], window=WINDOW)
    assert {entry.block_id for entry in plan.diff.updates} == {1, 2}
    assert validate_final_state(plan.candidates) == ()

    shifted = plan_commands(
        original,
        [
            UpdateCommand(1, start_time=clock("10:00"), end_time=clock("11:00")),
            UpdateCommand(2, start_time=clock("11:00"), end_time=clock("12:00")),
        ],
        window=WINDOW,
    )
    assert len(shifted.diff.updates) == 2


def test_half_open_adjacency_and_overlap_provenance() -> None:
    original = schedule(block(1, "08:00", "09:00"))
    assert len(plan_commands(original, [create("09:00", "10:00")], window=WINDOW).diff.creates) == 1
    with pytest.raises(CommandError) as caught:
        plan_commands(original, [create("08:55", "09:30", action_index=4)], window=WINDOW)
    assert caught.value.code == "overlap"
    assert caught.value.action_index == 4
    assert 1 in (caught.value.block_id, *caught.value.conflicting_block_ids)


def test_source_policies_grid_window_and_unchanged_imported_edge() -> None:
    original = schedule(block(1, "05:07", "08:07"))
    renamed = plan_commands(original, [UpdateCommand(1, title="Renamed")], window=WINDOW)
    assert renamed.candidates[0].start_time == clock("05:07")
    assert renamed.candidates[0].end_time == clock("08:07")
    changed_end = plan_commands(
        original, [UpdateCommand(1, end_time=clock("09:00"))], window=WINDOW
    )
    assert changed_end.candidates[0].start_time == clock("05:07")
    with pytest.raises(CommandError, match="5-minute") as caught:
        plan_commands(original, [UpdateCommand(1, end_time=clock("09:07"))], window=WINDOW)
    assert caught.value.code == "granularity"

    imported = plan_commands(schedule(), [create("05:07", "06:37")], policy=IMPORT, window=WINDOW)
    assert imported.candidates[0].start_time == clock("06:00")
    assert imported.candidates[0].end_time == clock("06:37")
    with pytest.raises(CommandError) as caught:
        plan_commands(schedule(), [create("06:07", "06:37")], policy=MANUAL, window=WINDOW)
    assert caught.value.code == "granularity"


def test_draft_rejects_window_and_undo_restores_off_grid_outside_window() -> None:
    with pytest.raises(CommandError) as caught:
        plan_commands(schedule(), [create("20:00", "22:00")], policy=DRAFT, window=WINDOW)
    assert caught.value.code == "out_of_window"
    assert "21:00" in caught.value.message

    restored = plan_commands(
        schedule(block(1, "08:00", "09:00")),
        [RestoreCommand((create("05:07", "05:37"),))],
        policy=MANUAL,
        window=WINDOW,
    )
    assert restored.restore
    assert restored.candidates[0].start_time == clock("05:07")
    assert len(restored.diff.deletes) == len(restored.diff.creates) == 1


def test_narrowed_window_and_changed_edge_clamp_precede_interval() -> None:
    original = schedule(block(1, "20:00", "22:00"))
    unchanged = plan_commands(original, [UpdateCommand(1, title="Later")], window=WINDOW)
    assert unchanged.candidates[0].end_time == clock("22:00")
    with pytest.raises(CommandError) as caught:
        plan_commands(original, [UpdateCommand(1, start_time=clock("23:35"))], window=WINDOW)
    assert caught.value.code == "out_of_window"
    adjusted = plan_commands(original, [UpdateCommand(1, end_time=clock("22:30"))], window=WINDOW)
    assert adjusted.candidates[0].end_time == clock("21:00")


def test_empty_diff_and_delete_action_index() -> None:
    original = schedule(block(1, "08:00", "09:00"))
    unchanged = plan_commands(original, [UpdateCommand(1, title="Task 1")], window=WINDOW)
    assert not unchanged.diff.deletes and not unchanged.diff.updates and not unchanged.diff.creates
    deleted = plan_commands(original, [DeleteCommand(1, action_index=6)], window=WINDOW)
    assert deleted.diff.deletes[0].action_index == 6

    restored = plan_commands(
        original,
        [RestoreCommand((CreateCommand("Task 1", clock("08:00"), clock("09:00"), "work"),))],
        policy=UNDO,
        window=WINDOW,
    )
    assert restored.restore and not restored.diff.deletes and not restored.diff.creates


def test_shared_ai_interval_and_diff_keep_action_index() -> None:
    original = block(1, "08:00", "09:00")
    candidate = BlockCandidate(1, clock("08:00"), clock("09:30"), "Task 1", "work", False, 7)
    validated = validate_block_interval(
        original, candidate, policy=AI, window=WINDOW,
        start_changed=False, end_changed=True,
    )
    diff = diff_candidates(schedule(original), [validated], delete_action_indices={})
    assert diff.updates[0].action_index == 7
    assert diff.updates[0].end_changed and not diff.updates[0].start_changed


def test_sort_order_limit_is_source_policy() -> None:
    command = CreateCommand("New", clock("08:00"), clock("09:00"), "work", sort_order=10_001)
    with pytest.raises(CommandError) as caught:
        plan_commands(schedule(), [command], policy=MANUAL, window=WINDOW)
    assert caught.value.code == "sort_order"
    ai_plan = plan_commands(schedule(), [command], policy=AI, window=WINDOW)
    assert ai_plan.diff.creates[0].sort_order == 10_001


def test_derived_ai_end_rejects_window_overflow_without_clamping() -> None:
    original = block(1, "20:00", "20:30")
    candidate = BlockCandidate(1, clock("20:00"), clock("22:00"), "Task 1", "work", False, 3)
    with pytest.raises(CommandError) as caught:
        validate_block_interval(
            original,
            candidate,
            policy=AI,
            window=WINDOW,
            start_changed=False,
            end_changed=True,
            clamp_end=False,
        )
    assert caught.value.code == "out_of_window"
    assert caught.value.action_index == 3


def test_final_overlap_reports_all_conflicting_pairs() -> None:
    candidates = (
        BlockCandidate(1, clock("08:00"), clock("10:00"), "A", "work", False),
        BlockCandidate(2, clock("08:30"), clock("09:30"), "B", "work", False),
        BlockCandidate(3, clock("09:00"), clock("11:00"), "C", "work", False),
    )
    pairs = {(item.left_id, item.right_id) for item in validate_final_state(candidates)}
    assert pairs == {(1, 2), (1, 3), (2, 3)}
