"""Pure planner unit tests for feature 0030 (slices 1–3). No database."""
import datetime

import pytest
from ai.mutation_planner import (
    BlockSnapshot,
    MutationPlan,
    PlanError,
    RuleSnapshot,
    ScheduleSnapshot,
    compute_apply_context_fingerprint,
    plan_mutations,
    snapshot_apply_context,
)
from ai.prompts import DAY_END, DAY_START
from schedules.http import parse_time


def _t(hhmm: str) -> datetime.time:
    return parse_time(hhmm)


def _block(
    id: int,
    start: str,
    end: str,
    title: str = "Block",
    category: str = "work",
    is_completed: bool = False,
) -> BlockSnapshot:
    return BlockSnapshot(
        id=id,
        start_time=_t(start),
        end_time=_t(end),
        title=title,
        category=category,
        is_completed=is_completed,
    )


def _schedule(blocks, schedule_id: int = 1, date: str = "2026-04-18") -> ScheduleSnapshot:
    return ScheduleSnapshot(
        id=schedule_id,
        date=datetime.date.fromisoformat(date),
        blocks=tuple(sorted(blocks, key=lambda b: b.id)),
    )


def _rule(id: int, text: str, priority: int = 0) -> RuleSnapshot:
    return RuleSnapshot(id=id, text=text, priority=priority)


def _move(task_id: int, start: str, end: str | None = None) -> dict:
    action = {"type": "move", "task_id": task_id, "start_time": start}
    if end is not None:
        action["end_time"] = end
    return action


def _resize(task_id: int, start: str | None = None, end: str | None = None) -> dict:
    action: dict = {"type": "resize", "task_id": task_id}
    if start is not None:
        action["start_time"] = start
    if end is not None:
        action["end_time"] = end
    return action


def _remove(task_id: int) -> dict:
    return {"type": "remove", "task_id": task_id}


def _add(title: str, start: str, end: str, category: str = "work") -> dict:
    return {
        "type": "add",
        "title": title,
        "start_time": start,
        "end_time": end,
        "category": category,
    }


def _canonical_intervals(plan: MutationPlan) -> dict[int, tuple[str, str]]:
    """Map real block id → (start, end) HH:MM for permutation comparisons."""
    snap = plan.diff  # type: ignore[attr-defined]
    result: dict[int, tuple[str, str]] = {}
    for entry in snap.updates:
        result[entry.block_id] = (
            entry.start_time.strftime("%H:%M"),
            entry.end_time.strftime("%H:%M"),
        )
    return result


def _final_intervals(snapshot: ScheduleSnapshot, plan: MutationPlan) -> dict[int, tuple[str, str]]:
    """Full final schedule intervals for blocks that survive or are created."""
    base = {
        b.id: (b.start_time.strftime("%H:%M"), b.end_time.strftime("%H:%M"))
        for b in snapshot.blocks
    }
    for entry in plan.diff.deletes:
        base.pop(entry.block_id, None)
    for entry in plan.diff.updates:
        base[entry.block_id] = (
            entry.start_time.strftime("%H:%M"),
            entry.end_time.strftime("%H:%M"),
        )
    return base


# --- Slice 1: fingerprint + snapshots ---


class TestFingerprint:
    def test_fingerprint_stable_for_block_order(self):
        blocks_a = [_block(1, "09:00", "10:00"), _block(2, "11:00", "12:00")]
        blocks_b = list(reversed(blocks_a))
        rules = [_rule(1, "rule one", 1)]
        fp_a = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks_a,
            rules=rules,
        )
        fp_b = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks_b,
            rules=rules,
        )
        assert fp_a == fp_b

    def test_fingerprint_changes_when_block_times_change(self):
        blocks = [_block(1, "09:00", "10:00")]
        fp_before = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=[],
        )
        blocks_changed = [_block(1, "09:30", "10:30")]
        fp_after = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks_changed,
            rules=[],
        )
        assert fp_before != fp_after

    @pytest.mark.parametrize(
        "field,value",
        [
            ("title", "Renamed"),
            ("category", "health"),
            ("is_completed", True),
        ],
    )
    def test_fingerprint_changes_for_prompt_visible_semantic_fields(self, field, value):
        base = _block(1, "09:00", "10:00")
        fp_base = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=[base],
            rules=[],
        )
        changed_kwargs = {
            "id": 1,
            "start_time": base.start_time,
            "end_time": base.end_time,
            "title": base.title,
            "category": base.category,
            "is_completed": base.is_completed,
        }
        changed_kwargs[field] = value
        changed = BlockSnapshot(**changed_kwargs)
        fp_changed = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=[changed],
            rules=[],
        )
        assert fp_base != fp_changed

    def test_fingerprint_ignores_sort_order_and_schedule_status(self):
        """sort_order and schedule.status are omitted from the canonical payload."""
        block = _block(1, "09:00", "10:00")
        fp = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=[block],
            rules=[],
        )
        # Recompute via snapshot helpers — status is not a ScheduleSnapshot field.
        snap = _schedule([block])
        ctx = snapshot_apply_context(snap, [])
        assert ctx.fingerprint == fp

    def test_fingerprint_rule_text_change(self):
        blocks = [_block(1, "09:00", "10:00")]
        fp_a = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=[_rule(1, "first", 0)],
        )
        fp_b = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=[_rule(1, "second", 0)],
        )
        assert fp_a != fp_b

    def test_fingerprint_rule_priority_change(self):
        blocks = [_block(1, "09:00", "10:00")]
        fp_a = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=[_rule(1, "same", 0)],
        )
        fp_b = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=[_rule(1, "same", 5)],
        )
        assert fp_a != fp_b

    def test_fingerprint_rule_add_remove(self):
        blocks = [_block(1, "09:00", "10:00")]
        fp_none = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=[],
        )
        fp_with = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=[_rule(2, "new rule", 1)],
        )
        assert fp_none != fp_with

    def test_fingerprint_equal_priority_rule_order_stable(self):
        blocks = [_block(1, "09:00", "10:00")]
        rules_a = [_rule(2, "b", 1), _rule(1, "a", 1)]
        rules_b = [_rule(1, "a", 1), _rule(2, "b", 1)]
        fp_a = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=rules_a,
        )
        fp_b = compute_apply_context_fingerprint(
            schedule_id=1,
            schedule_date="2026-04-18",
            blocks=blocks,
            rules=rules_b,
        )
        assert fp_a == fp_b


# --- Slice 2: mass forward shift ---


MASS_SHIFT_BLOCKS = [
    _block(1, "13:15", "14:00"),
    _block(2, "14:15", "15:00"),
    _block(3, "15:30", "16:30"),
]

MASS_SHIFT_EXPECTED = {
    1: ("14:15", "15:00"),
    2: ("15:15", "16:00"),
    3: ("16:30", "17:30"),
}


class TestMassForwardShift:
    def test_plan_mass_forward_shift_succeeds(self):
        snap = _schedule(MASS_SHIFT_BLOCKS)
        actions = [
            _move(1, "14:15"),
            _move(2, "15:15"),
            _move(3, "16:30"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert len(result.diff.updates) == 3
        assert len(result.diff.deletes) == 0
        assert len(result.diff.creates) == 0
        intervals = _canonical_intervals(result)
        assert intervals == MASS_SHIFT_EXPECTED

    def test_plan_mass_forward_shift_order_invariant(self):
        snap = _schedule(MASS_SHIFT_BLOCKS)
        forward = [_move(1, "14:15"), _move(2, "15:15"), _move(3, "16:30")]
        reverse = list(reversed(forward))
        middle_first = [_move(2, "15:15"), _move(1, "14:15"), _move(3, "16:30")]

        plan_fwd = plan_mutations(snap, forward, day_start=DAY_START, day_end=DAY_END)
        plan_rev = plan_mutations(snap, reverse, day_start=DAY_START, day_end=DAY_END)
        plan_mid = plan_mutations(snap, middle_first, day_start=DAY_START, day_end=DAY_END)

        assert isinstance(plan_fwd, MutationPlan)
        assert isinstance(plan_rev, MutationPlan)
        assert isinstance(plan_mid, MutationPlan)

        assert _final_intervals(snap, plan_fwd) == MASS_SHIFT_EXPECTED
        assert _final_intervals(snap, plan_rev) == MASS_SHIFT_EXPECTED
        assert _final_intervals(snap, plan_mid) == MASS_SHIFT_EXPECTED


# --- Slice 3: edge cases ---


class TestPlannerEdgeCases:
    def test_plan_uniform_backward_shift(self):
        snap = _schedule(MASS_SHIFT_BLOCKS)
        actions = [
            _move(1, "12:15"),
            _move(2, "13:15"),
            _move(3, "14:30"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        expected = {
            1: ("12:15", "13:00"),
            2: ("13:15", "14:00"),
            3: ("14:30", "15:30"),
        }
        assert _final_intervals(snap, result) == expected

    def test_plan_mixed_forward_backward(self):
        snap = _schedule(
            [
                _block(1, "09:00", "10:00"),
                _block(2, "13:00", "14:00"),
                _block(3, "14:00", "15:00"),
            ]
        )
        actions = [
            _move(1, "10:00"),  # +60m
            _move(2, "12:00"),  # -60m
            _move(3, "15:00"),  # +60m
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert _final_intervals(snap, result) == {
            1: ("10:00", "11:00"),
            2: ("12:00", "13:00"),
            3: ("15:00", "16:00"),
        }

    def test_plan_two_block_swap(self):
        snap = _schedule(
            [
                _block(1, "09:00", "10:00", title="A"),
                _block(2, "11:00", "12:00", title="B"),
            ]
        )
        actions = [
            _move(1, "11:00", "12:00"),
            _move(2, "09:00", "10:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert _final_intervals(snap, result) == {
            1: ("11:00", "12:00"),
            2: ("09:00", "10:00"),
        }

    def test_plan_three_block_cycle(self):
        snap = _schedule(
            [
                _block(1, "09:00", "10:00"),
                _block(2, "11:00", "12:00"),
                _block(3, "14:00", "15:00"),
            ]
        )
        actions = [
            _move(1, "11:00", "12:00"),
            _move(2, "14:00", "15:00"),
            _move(3, "09:00", "10:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert _final_intervals(snap, result) == {
            1: ("11:00", "12:00"),
            2: ("14:00", "15:00"),
            3: ("09:00", "10:00"),
        }

    def test_plan_move_and_resize_same_batch(self):
        snap = _schedule([_block(1, "09:00", "10:00")])
        actions = [
            _resize(1, end="11:00"),
            _move(1, "14:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert _final_intervals(snap, result) == {1: ("14:00", "16:00")}

    def test_plan_remove_then_add_same_slot(self):
        snap = _schedule([_block(1, "13:15", "14:00", title="Old")])
        actions = [
            _remove(1),
            _add("New", "13:15", "14:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert len(result.diff.deletes) == 1
        assert result.diff.deletes[0].block_id == 1
        assert len(result.diff.creates) == 1
        create = result.diff.creates[0]
        assert create.title == "New"
        assert create.start_time.strftime("%H:%M") == "13:15"
        assert create.end_time.strftime("%H:%M") == "14:00"

    def test_plan_rejects_genuine_final_overlap(self):
        snap = _schedule(
            [
                _block(1, "09:00", "10:00"),
                _block(2, "11:00", "12:00"),
            ]
        )
        actions = [
            _move(1, "10:30", "11:30"),
            _move(2, "10:00", "11:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, PlanError)
        assert result.detail == "block would overlap existing block"

    def test_plan_overlap_attribution_is_deterministic(self):
        snap = _schedule(
            [
                _block(1, "09:00", "10:00"),
                _block(2, "10:00", "11:00"),
            ]
        )
        # Both move into overlapping windows; action 0 should win attribution.
        actions = [
            _move(1, "09:30", "10:30"),
            _move(2, "09:45", "10:45"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, PlanError)
        assert result.action_index == 0
        assert result.detail == "block would overlap existing block"

    def test_plan_unknown_task_id(self):
        snap = _schedule([_block(1, "09:00", "10:00")])
        result = plan_mutations(
            snap,
            [_move(999, "10:00")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, PlanError)
        assert result.detail == (
            "Referenced block no longer exists; it may have been deleted. Please retry."
        )

    def test_plan_same_target_resize_then_bare_move(self):
        snap = _schedule([_block(1, "09:00", "10:00")])
        actions = [
            _resize(1, end="11:00"),
            _move(1, "14:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        # 2-hour effective duration after resize → 14:00–16:00
        assert _final_intervals(snap, result) == {1: ("14:00", "16:00")}

    def test_plan_post_remove_action_is_rejected(self):
        snap = _schedule([_block(1, "09:00", "10:00")])
        actions = [
            _remove(1),
            _move(1, "11:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, PlanError)
        assert result.action_index == 1

    def test_plan_duplicate_remove_is_rejected(self):
        snap = _schedule([_block(1, "09:00", "10:00")])
        actions = [_remove(1), _remove(1)]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, PlanError)
        assert result.action_index == 1

    def test_plan_temp_create_ids_are_strictly_negative(self):
        snap = _schedule([])
        actions = [_add("A", "09:00", "10:00")]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert len(result.diff.creates) == 1
        assert result.diff.creates[0].action_index == 0
        # Internal temp id is -(action_index + 1); action 0 → -1
        assert result.diff.creates[0].temp_id == -1

    def test_plan_inherited_off_grid_boundary_is_allowed(self):
        snap = _schedule([_block(1, "14:07", "14:33")])
        result = plan_mutations(
            snap,
            [_move(1, "16:00")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert _final_intervals(snap, result) == {1: ("16:00", "16:30")}

    def test_plan_effective_midnight_wrap_has_specific_detail(self):
        snap = _schedule([_block(1, "22:00", "23:30")])
        result = plan_mutations(
            snap,
            [_move(1, "23:00")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, PlanError)
        assert result.detail == "moved block would extend past midnight"

    def test_plan_overwritten_wrap_is_not_rejected(self):
        # Bare move would wrap past midnight; a later supplied end clears wrap provenance.
        snap = _schedule([_block(1, "21:00", "22:30")])
        actions = [
            _move(1, "22:30"),
            _resize(1, end="23:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert _final_intervals(snap, result) == {1: ("22:30", "23:00")}

    def test_plan_inherited_reversed_block_has_stable_fallback_index(self):
        bad = BlockSnapshot(
            id=1,
            start_time=_t("11:00"),
            end_time=_t("10:00"),
            title="Bad",
            category="work",
            is_completed=False,
        )
        snap = _schedule([bad])
        result = plan_mutations(snap, [], day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, PlanError)
        assert result.action_index == 0
        assert "start_time" in result.detail.lower()

    def test_plan_multiple_violations_choose_lowest_source_index(self):
        snap = _schedule(
            [
                _block(1, "09:00", "10:00"),
                _block(2, "11:00", "12:00"),
            ]
        )
        actions = [
            _move(1, "10:30", "11:30"),
            _move(2, "11:00", "11:00"),  # invalid interval on action 1
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, PlanError)
        assert result.action_index == 0
        assert result.detail == "block would overlap existing block"

    def test_plan_resize_day_window_precedes_interval(self):
        snap = _schedule([_block(1, "10:00", "11:00")])
        result = plan_mutations(
            snap,
            [_resize(1, start="23:00", end="23:30")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, PlanError)
        assert DAY_END in result.detail

    def test_plan_violation_ties_use_stable_candidate_key(self):
        snap = _schedule(
            [
                _block(1, "09:00", "10:00"),
                _block(2, "11:00", "12:00"),
            ]
        )
        # Two adds overlapping each other at action indices 0 and 1 — tie on rank;
        # lower temp id (action 0 → -1) should win over action 1 → -2.
        actions = [
            _add("A", "10:00", "11:30"),
            _add("B", "10:30", "11:00"),
        ]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, PlanError)
        assert result.action_index == 0
        assert result.detail == "block would overlap existing block"
