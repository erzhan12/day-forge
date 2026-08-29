"""Pure planner unit tests for feature 0030 (slices 1–3). No database."""

import datetime

import ai.mutation_planner as mutation_planner
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
from schedules.http import parse_time
from schedules.window import DEFAULT_WINDOW

# Feature 0053: the working-day window is now the canonical ``ScheduleWindow``
# (``schedules.window``), no longer the demoted ``ai.prompts.DAY_START/DAY_END``
# module constants. The existing hardcoded-06:00-23:00 planner tests are
# converted to pass the DEFAULT window explicitly so behaviour stays identical
# under the default while proving the window is a parameter, not a constant.
DAY_START = DEFAULT_WINDOW.start_str  # "06:00"
DAY_END = DEFAULT_WINDOW.end_str  # "23:00"


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


def _duration_resize(
    task_id: int, *, duration_minutes: int | None = None, duration_delta_minutes: int | None = None
) -> dict:
    action: dict = {"type": "resize", "task_id": task_id}
    if duration_minutes is not None:
        action["duration_minutes"] = duration_minutes
    if duration_delta_minutes is not None:
        action["duration_delta_minutes"] = duration_delta_minutes
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


def _auto_add(title: str, category: str = "work", duration_minutes: int | None = None) -> dict:
    """An untimed chat ``add`` (feature 0067): no start_time/end_time."""
    action: dict = {"type": "add", "title": title, "category": category}
    if duration_minutes is not None:
        action["duration_minutes"] = duration_minutes
    return action


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
        assert isinstance(result, MutationPlan)
        assert result.overall_status == "skipped"
        assert {o.reason_code for o in result.outcomes} == {"unresolved_conflict"}

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
        assert isinstance(result, MutationPlan)
        assert result.overall_status == "skipped"
        assert {o.reason_code for o in result.outcomes} == {"unresolved_conflict"}

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
        assert isinstance(result, MutationPlan)
        assert result.outcomes[0].reason_code == "out_of_window"
        # FIX-1: out_of_window rejections never call find_slot, so no suggestion.
        assert result.outcomes[0].suggestion is None

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
        assert isinstance(result, MutationPlan)
        assert result.diff == result.diff.__class__((), (), ())

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
        assert isinstance(result, MutationPlan)
        assert {o.reason_code for o in result.outcomes} == {"overlap", "interval"}

    def test_plan_resize_day_window_precedes_interval(self):
        snap = _schedule([_block(1, "10:00", "11:00")])
        result = plan_mutations(
            snap,
            [_resize(1, start="23:00", end="23:30")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert result.outcomes[0].reason_code == "out_of_window"

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
        assert isinstance(result, MutationPlan)
        assert result.overall_status == "partial"


# --- Feature 0053: per-user configurable day window ---


class TestNonDefaultDayWindow:
    """The planner rejects (never clamps) out-of-window actions, keyed off the
    per-user window strings threaded through ``plan_mutations`` — not the demoted
    ``ai.prompts`` constants. The rejection error text must name the *passed*
    bound so a narrowed window reports the correct edge, not a stale ``23:00``.
    """

    # A widened window whose upper bound is 5-minute-valid (never 23:59, which
    # ``validate_window`` rejects for off-grid).
    WIDE_START = "06:00"
    WIDE_END = "23:55"

    NARROW_START = "08:00"
    NARROW_END = "21:00"

    def test_create_rejected_under_narrowed_window_names_narrowed_bound(self):
        # 22:00–22:30 is inside the default 06:00–23:00 but outside a narrowed
        # 08:00–21:00; the planner must reject and the detail must name 21:00,
        # not the stale default 23:00.
        snap = _schedule([])
        actions = [_add("Late block", "22:00", "22:30")]
        result = plan_mutations(
            snap,
            actions,
            day_start=self.NARROW_START,
            day_end=self.NARROW_END,
        )
        assert isinstance(result, MutationPlan)
        assert result.outcomes[0].reason_code == "out_of_window"
        assert not result.diff.creates

    def test_update_rejected_under_narrowed_window_names_narrowed_bound(self):
        # An in-default-window block resized to 22:00–22:30: rejected under the
        # narrowed window with the narrowed upper bound in the message.
        snap = _schedule([_block(1, "10:00", "11:00")])
        result = plan_mutations(
            snap,
            [_resize(1, start="22:00", end="22:30")],
            day_start=self.NARROW_START,
            day_end=self.NARROW_END,
        )
        assert isinstance(result, MutationPlan)
        assert result.outcomes[0].reason_code == "out_of_window"

    def test_create_accepted_under_widened_window(self):
        # A block ending 23:30 is outside the default 23:00 upper bound but
        # inside a widened 06:00–23:55 window → accepted.
        snap = _schedule([])
        actions = [_add("Evening", "23:00", "23:30")]
        result = plan_mutations(
            snap,
            actions,
            day_start=self.WIDE_START,
            day_end=self.WIDE_END,
        )
        assert isinstance(result, MutationPlan)
        assert len(result.diff.creates) == 1
        create = result.diff.creates[0]
        assert create.start_time.strftime("%H:%M") == "23:00"
        assert create.end_time.strftime("%H:%M") == "23:30"

    def test_update_accepted_under_widened_window(self):
        # A block resized to end 23:30 is accepted under a widened window.
        snap = _schedule([_block(1, "22:00", "22:30")])
        result = plan_mutations(
            snap,
            [_resize(1, end="23:30")],
            day_start=self.WIDE_START,
            day_end=self.WIDE_END,
        )
        assert isinstance(result, MutationPlan)
        assert _final_intervals(snap, result) == {1: ("22:00", "23:30")}

    def test_default_window_still_rejects_ending_past_23_00(self):
        # Same 23:00–23:30 create is rejected under the DEFAULT window — proving
        # the widened-window acceptance above is genuinely window-driven, not a
        # loosening of the default.
        snap = _schedule([])
        actions = [_add("Evening", "23:00", "23:30")]
        result = plan_mutations(snap, actions, day_start=DAY_START, day_end=DAY_END)
        assert isinstance(result, MutationPlan)
        assert result.outcomes[0].reason_code == "out_of_window"

    def test_supplied_start_past_day_end_is_rejected_symmetric_bound(self):
        # SYMMETRIC-bound hole: a supplied start PAST day_end. The block's stored
        # (inherited) end 23:50 is itself legacy-outside the default window, so a
        # naive ``start < day_start`` / ``end > day_end`` check would never fire
        # on the supplied start. The 0053 ``start <= day_end`` half must reject a
        # start of 23:35 under the default 06:00–23:00 window — not silently
        # accept it.
        snap = _schedule([_block(1, "23:30", "23:50")])
        result = plan_mutations(
            snap,
            [_resize(1, start="23:35")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert result.outcomes[0].reason_code == "out_of_window"

    def test_supplied_end_before_day_start_is_rejected_symmetric_bound(self):
        # Mirror of the above: a supplied end BEFORE day_start (05:35 under the
        # default 06:00 start), opposite endpoint 05:10 inherited-outside. The
        # ``end >= day_start`` half must reject it.
        snap = _schedule([_block(1, "05:10", "05:30")])
        result = plan_mutations(
            snap,
            [_resize(1, end="05:35")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert result.outcomes[0].reason_code == "out_of_window"


def test_update_metadata_persists_when_requested_time_conflicts():
    snap = _schedule([_block(1, "09:00", "10:00", title="Old"), _block(2, "10:00", "11:00")])
    result = plan_mutations(
        snap,
        [
            {
                "type": "update",
                "task_id": 1,
                "title": "Renamed",
                "category": "health",
                "start_time": "10:00",
                "end_time": "11:00",
            }
        ],
        day_start=DAY_START,
        day_end=DAY_END,
    )
    assert isinstance(result, MutationPlan)
    assert result.overall_status == "partial"
    outcome = result.outcomes[0]
    assert outcome.status == "partial"
    assert outcome.applied_fields == ("title", "category")
    assert outcome.skipped_fields == ("start_time", "end_time")
    assert outcome.reason_code == "overlap"
    entry = result.diff.updates[0]
    assert entry.title == "Renamed" and not entry.start_changed and not entry.end_changed


def test_update_title_is_stripped():
    """FIX-5: an ``update`` title is whitespace-stripped (like ``add``), so a
    padded ``"  Work  "`` persists as ``"Work"`` in the diff entry."""
    snap = _schedule([_block(1, "09:00", "10:00", title="Old")])
    result = plan_mutations(
        snap,
        [{"type": "update", "task_id": 1, "title": "  Work  "}],
        day_start=DAY_START,
        day_end=DAY_END,
    )
    assert isinstance(result, MutationPlan)
    entry = result.diff.updates[0]
    assert entry.title == "Work"


def test_same_task_bare_move_preserves_prior_direction():
    """FIX-C: an ``update`` carrying a ``direction=later`` followed by a bare
    ``move`` (a time but no explicit ``direction``) on the SAME task_id must
    keep ``direction=later`` — the merge must not reset it to ``exact``. Proven
    via the resulting skip: a later slot is proposed, not a direction_required
    question."""
    snap = _schedule([_block(1, "09:00", "10:00", title="Gym"), _block(2, "11:00", "12:00")])
    result = plan_mutations(
        snap,
        [
            {
                "type": "update",
                "task_id": 1,
                "title": "Gym renamed",
                "start_time": "11:00",
                "end_time": "12:00",
                "direction": "later",
            },
            # Bare move (no explicit direction) onto the still-conflicting slot.
            {"type": "move", "task_id": 1, "start_time": "11:00"},
        ],
        day_start=DAY_START,
        day_end=DAY_END,
    )
    assert isinstance(result, MutationPlan)
    outcome = next(o for o in result.outcomes if o.task_id == 1)
    assert outcome.status == "partial"
    assert outcome.reason_code == "overlap"
    # Merged direction survived: the slot finder proposed a concrete LATER
    # slot rather than a direction_required prompt.
    assert outcome.attempted_direction == "later"
    assert outcome.suggestion is not None
    assert not outcome.suggestion.direction_required
    assert outcome.suggestion.direction == "later"
    assert outcome.suggestion.start_time >= _t("11:00")


def test_plan_update_unknown_task_id():
    """An ``update`` referencing a task_id absent from the snapshot is a
    structural miss — ``plan_mutations`` returns a ``PlanError`` (whole-turn
    abort), mirroring the move/resize unknown-id behavior."""
    snap = _schedule([_block(1, "09:00", "10:00")])
    result = plan_mutations(
        snap,
        [
            {
                "type": "update",
                "task_id": 999,
                "title": "Renamed",
            }
        ],
        day_start=DAY_START,
        day_end=DAY_END,
    )
    assert isinstance(result, PlanError)
    assert result.detail == (
        "Referenced block no longer exists; it may have been deleted. Please retry."
    )


# ---------------------------------------------------------------------------
# Feature 0067: deterministic auto-placement of untimed chat ``add`` actions.
# ``plan_mutations(..., earliest_start=...)`` places a titled/categorised add
# with no start/end at the nearest free 5-min-grid slot forward from
# ``earliest_start`` (today) or the window start (other dates), 25-min default
# duration, 10-min gaps around neighbours. Failure → ``no_slot`` skip.
# ---------------------------------------------------------------------------


def _create_intervals(plan: MutationPlan) -> list[tuple[str, str]]:
    return [
        (c.start_time.strftime("%H:%M"), c.end_time.strftime("%H:%M")) for c in plan.diff.creates
    ]


def _union_intervals(
    snapshot: ScheduleSnapshot, plan: MutationPlan
) -> list[tuple[datetime.time, datetime.time]]:
    """Final non-overlapping set: unchanged snapshot blocks + diff (feature 0067).

    ``MutationDiff`` carries deletes/updates/creates only, so the union with the
    surviving unchanged snapshot blocks is the real occupancy a placement or
    padding miss would collide with.
    """
    deleted = {e.block_id for e in plan.diff.deletes}
    updated = {e.block_id for e in plan.diff.updates}
    intervals: list[tuple[datetime.time, datetime.time]] = []
    for b in snapshot.blocks:
        if b.id in deleted or b.id in updated:
            continue
        intervals.append((b.start_time, b.end_time))
    for e in plan.diff.updates:
        intervals.append((e.start_time, e.end_time))
    for c in plan.diff.creates:
        intervals.append((c.start_time, c.end_time))
    return intervals


def _assert_non_overlapping(intervals):
    ordered = sorted(intervals, key=lambda iv: iv[0])
    for (a_start, a_end), (b_start, b_end) in zip(ordered, ordered[1:]):
        assert a_end <= b_start, f"overlap between {a_start}-{a_end} and {b_start}-{b_end}"


class TestAutoPlacement:
    def test_empty_today_places_at_earliest_start_default_25(self):
        snap = _schedule([])
        result = plan_mutations(
            snap,
            [_auto_add("LeverX")],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("10:05"),
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("10:05", "10:30")]

    def test_today_never_starts_before_earliest_start(self):
        # A block occupies 10:00-10:30; earliest_start 10:05 → first free grid
        # slot with 10-min padding is 10:40 (after 10:30 + 10 min).
        snap = _schedule([_block(1, "10:00", "10:30")])
        result = plan_mutations(
            snap,
            [_auto_add("Task")],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("10:05"),
        )
        assert isinstance(result, MutationPlan)
        start, _ = _create_intervals(result)[0]
        assert start >= "10:05"

    def test_custom_duration(self):
        snap = _schedule([])
        result = plan_mutations(
            snap,
            [_auto_add("Task", duration_minutes=30)],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("09:00", "09:30")]

    def test_exact_fit_at_window_end_allowed(self):
        # A default-duration auto whose end lands exactly on day_end must be
        # placed, not rejected: the no_slot guard is strict `>` (base_min + dur
        # > end_minutes), mirroring find_slot's `candidate + duration <=
        # end_minutes`. A regression to `>=` would spuriously return no_slot.
        snap = _schedule([])
        result = plan_mutations(
            snap,
            [_auto_add("Edge")],
            day_start="08:00",
            day_end="08:25",
            earliest_start=None,
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("08:00", "08:25")]

    def test_gap_before_a_neighbour(self):
        # Neighbour at 09:40-10:00; a 25-min auto from base 09:00 may end
        # exactly 10 min before it (09:00-09:25 ends before 09:30 padded edge).
        snap = _schedule([_block(1, "09:40", "10:00")])
        result = plan_mutations(
            snap,
            [_auto_add("Task")],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("09:00", "09:25")]

    def test_gap_after_a_neighbour(self):
        # Neighbour 09:00-09:30; earliest_start 09:00. The placed block may
        # start exactly 10 min after it: 09:40-10:05.
        snap = _schedule([_block(1, "09:00", "09:30")])
        result = plan_mutations(
            snap,
            [_auto_add("Task")],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("09:40", "10:05")]

    def test_rejected_update_original_interval_still_blocks_placement(self):
        # Two blocks: id1 09:00-09:30, id2 09:40-10:10. An update tries to move
        # id2 onto id1 (overlap → rejected, reverts to 09:40-10:10). An auto add
        # must still avoid the reverted original 09:40-10:10.
        snap = _schedule([_block(1, "09:00", "09:30"), _block(2, "09:40", "10:10")])
        actions = [
            {"type": "update", "task_id": 2, "start_time": "09:10", "end_time": "09:40"},
            _auto_add("Auto"),
        ]
        result = plan_mutations(
            snap,
            actions,
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        # id2 update rejected (overlap) so it reverts to 09:40-10:10.
        assert 2 not in {e.block_id for e in result.diff.updates}
        _assert_non_overlapping(_union_intervals(snap, result))

    def test_deleted_block_frees_its_space(self):
        # id1 occupies 09:00-09:30; removing it frees the slot so an auto with
        # earliest_start 09:00 lands at 09:00-09:25.
        snap = _schedule([_block(1, "09:00", "09:30")])
        actions = [_remove(1), _auto_add("Auto")]
        result = plan_mutations(
            snap,
            actions,
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("09:00", "09:25")]

    def test_sequential_two_default_adds_preserve_order_and_gap(self):
        snap = _schedule([])
        actions = [_auto_add("First"), _auto_add("Second")]
        result = plan_mutations(
            snap,
            actions,
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("09:00", "09:25"), ("09:35", "10:00")]

    def test_unequal_durations_later_add_may_take_earlier_gap(self):
        # An early hole 09:00-09:25 sits before a padded block (block 09:35-11:00
        # pads to 09:25-11:10). The long 60-min add does NOT fit the 25-min hole,
        # so from base 09:00 it lands after the block at 11:10-12:10. The short
        # 25-min add searches from the SAME common base 09:00 and DOES fit the
        # early hole (09:00-09:25 touches the padded block half-open) — so the
        # later action occupies a strictly EARLIER slot than the first, which is
        # the plan's common-base decision (not sequential-append).
        snap = _schedule([_block(1, "09:35", "11:00")])
        actions = [
            _auto_add("Long", duration_minutes=60),
            _auto_add("Short"),
        ]
        result = plan_mutations(
            snap,
            actions,
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        intervals = _create_intervals(result)
        assert set(intervals) == {("11:10", "12:10"), ("09:00", "09:25")}
        # The later (short) add starts strictly earlier than the first (long) add.
        long_iv = next(iv for iv in intervals if iv == ("11:10", "12:10"))
        short_iv = next(iv for iv in intervals if iv == ("09:00", "09:25"))
        assert short_iv[0] < long_iv[0]

    def test_no_slot_when_window_fully_padded(self):
        # A single block spans the entire window: no forward slot fits.
        snap = _schedule([_block(1, "06:00", "23:00")])
        result = plan_mutations(
            snap,
            [_auto_add("Auto")],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("06:00"),
        )
        assert isinstance(result, MutationPlan)
        assert result.diff.creates == ()
        outcome = result.outcomes[0]
        assert outcome.status == "skipped"
        assert outcome.reason_code == "no_slot"
        assert outcome.conflicting_task_ids == ()
        assert outcome.suggestion is None
        assert outcome.attempted_direction is None

    @pytest.mark.parametrize("date", ["2026-04-10", "2026-04-25"])
    def test_non_today_searches_from_window_start(self, date):
        # earliest_start=None (past or future date) → search begins at day_start.
        snap = _schedule([], date=date)
        result = plan_mutations(
            snap,
            [_auto_add("Auto")],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=None,
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("06:00", "06:25")]

    def test_grid_alignment_of_returned_boundaries(self):
        snap = _schedule([_block(1, "09:00", "09:30")])
        result = plan_mutations(
            snap,
            [_auto_add("Auto")],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:07"),
        )
        assert isinstance(result, MutationPlan)
        for c in result.diff.creates:
            assert c.start_time.minute % 5 == 0
            assert c.end_time.minute % 5 == 0

    def test_custom_window_honored_at_both_edges(self):
        # Window 08:00-10:00; a 25-min auto from a past-date search starts at
        # 08:00-08:25; and an add that cannot fit near the end → no_slot.
        snap = _schedule([_block(1, "08:00", "09:40")])
        result = plan_mutations(
            snap,
            [_auto_add("Auto")],
            day_start="08:00",
            day_end="10:00",
            earliest_start=None,
        )
        assert isinstance(result, MutationPlan)
        # Only free padded slot: after 09:40 + 10 min = 09:50, but 09:50+25 > 10:00 → no_slot.
        assert result.diff.creates == ()
        assert result.outcomes[0].reason_code == "no_slot"

    def test_very_large_duration_returns_no_slot_without_wrapping(self):
        # duration exceeding the window span must be rejected via minute
        # comparison (no wrapped datetime.time constructed).
        snap = _schedule([])
        result = plan_mutations(
            snap,
            [_auto_add("Huge", duration_minutes=20 * 60)],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("06:00"),
        )
        assert isinstance(result, MutationPlan)
        assert result.diff.creates == ()
        assert result.outcomes[0].reason_code == "no_slot"

    def test_near_midnight_window_padding_stays_in_minute_space(self):
        # Custom near-midnight window 00:00-23:55; a block adjacent to the
        # 00:00 edge is padded/clamped in integer minutes before any
        # datetime.time is built — no hour∉0..23 error, no inverted pair.
        snap = _schedule([_block(1, "00:00", "00:30")])
        result = plan_mutations(
            snap,
            [_auto_add("Auto")],
            day_start="00:00",
            day_end="23:55",
            earliest_start=None,
        )
        assert isinstance(result, MutationPlan)
        # First free padded slot after 00:30 + 10 = 00:40.
        assert _create_intervals(result) == [("00:40", "01:05")]
        _assert_non_overlapping(_union_intervals(snap, result))

    def test_explicit_create_regression_not_auto_moved(self):
        # An explicit both-time add keeps its clamp/validation/overlap/outcome
        # behaviour and is not auto-moved to satisfy the 10-min policy.
        snap = _schedule([_block(1, "09:00", "09:30")])
        result = plan_mutations(
            snap,
            [_add("Explicit", "09:35", "10:00")],
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        # Placed exactly where requested — no 10-min inflation applied.
        assert _create_intervals(result) == [("09:35", "10:00")]

    def test_auto_inserted_after_overlap_fixpoint_union_is_non_overlapping(self):
        # Defensive: find_slot is the sole overlap guard for autos. Assert
        # non-overlap over the union of unchanged snapshot blocks and the diff.
        snap = _schedule([_block(1, "09:00", "09:30"), _block(2, "11:00", "11:30")])
        actions = [_auto_add("A"), _auto_add("B")]
        result = plan_mutations(
            snap,
            actions,
            day_start=DAY_START,
            day_end=DAY_END,
            earliest_start=_t("09:00"),
        )
        assert isinstance(result, MutationPlan)
        assert len(result.diff.creates) == 2
        _assert_non_overlapping(_union_intervals(snap, result))

    def test_earliest_start_defaults_none_keeps_existing_callers(self):
        # An untimed add with no earliest_start kwarg starts at window start.
        snap = _schedule([])
        result = plan_mutations(
            snap,
            [_auto_add("Auto")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert _create_intervals(result) == [("06:00", "06:25")]


class TestDurationResize:
    def test_normalize_absolute_duration_sets_derived_end_minutes(self):
        snap = _schedule([_block(1, "12:00", "13:00")])
        normalized = mutation_planner._normalize_actions(
            snap, [_duration_resize(1, duration_minutes=20)]
        )
        assert not isinstance(normalized, PlanError)
        _deletes, updates, _creates = normalized
        update = updates[1]
        assert update.new_end == _t("12:20")
        assert update.duration_derived_end is True
        assert update.derived_end_minutes == 740
        assert update.end_supplied is False

    @pytest.mark.parametrize(("delta", "expected"), [(30, 810), (-15, 765)])
    def test_normalize_relative_duration_delta_sets_derived_end_minutes(self, delta, expected):
        snap = _schedule([_block(1, "12:00", "13:00")])
        normalized = mutation_planner._normalize_actions(
            snap, [_duration_resize(1, duration_delta_minutes=delta)]
        )
        assert not isinstance(normalized, PlanError)
        assert normalized[1][1].derived_end_minutes == expected

    def test_plan_resize_absolute_duration_emits_end_only_update(self):
        snap = _schedule([_block(1, "12:00", "13:00")])
        result = plan_mutations(
            snap, [_duration_resize(1, duration_minutes=20)], day_start=DAY_START, day_end=DAY_END
        )
        assert isinstance(result, MutationPlan)
        assert len(result.diff.updates) == 1
        update = result.diff.updates[0]
        assert update.start_changed is False
        assert update.end_changed is True
        assert update.end_time == _t("12:20")
        assert result.outcomes[0].applied_fields == ("end_time",)

    def test_plan_resize_delta_uses_effective_chained_duration(self):
        snap = _schedule([_block(1, "12:00", "13:00")])
        result = plan_mutations(
            snap,
            [
                _duration_resize(1, duration_minutes=20),
                _duration_resize(1, duration_delta_minutes=30),
            ],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert result.diff.updates[0].end_time == _t("12:50")

    def test_plan_bare_move_after_duration_resize_preserves_resized_duration(self):
        snap = _schedule([_block(1, "12:00", "13:00")])
        result = plan_mutations(
            snap,
            [_duration_resize(1, duration_minutes=20), _move(1, "14:00")],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        update = result.diff.updates[0]
        assert (update.start_time, update.end_time) == (_t("14:00"), _t("14:20"))

    @pytest.mark.parametrize("delta", (-60, -65))
    def test_plan_relative_resize_below_floor_is_skipped(self, delta):
        snap = _schedule([_block(1, "12:00", "13:00")])
        result = plan_mutations(
            snap,
            [_duration_resize(1, duration_delta_minutes=delta)],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert result.diff.updates == ()
        outcome = result.outcomes[0]
        assert outcome.skipped_fields == ("end_time",)
        assert outcome.reason_code == "interval"

    def test_plan_duration_past_window_is_rejected_not_clamped(self):
        snap = _schedule([_block(1, "22:00", "22:30")])
        result = plan_mutations(
            snap, [_duration_resize(1, duration_minutes=120)], day_start=DAY_START, day_end=DAY_END
        )
        assert isinstance(result, MutationPlan)
        assert result.diff.updates == ()
        assert result.outcomes[0].reason_code == "out_of_window"

    def test_failed_oow_duration_does_not_inflate_later_bare_move(self):
        # A rejected window-OOW duration must not poison same-turn bare-move
        # duration arithmetic via chain_effective (0068 regression).
        snap = _schedule([_block(1, "20:00", "21:00")])
        result = plan_mutations(
            snap,
            [
                _duration_resize(1, duration_minutes=200),  # 23:20, past default 23:00 end
                _move(1, "14:00"),
            ],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert len(result.diff.updates) == 1
        update = result.diff.updates[0]
        assert (update.start_time, update.end_time) == (_t("14:00"), _t("15:00"))
        outcome = result.outcomes[0]
        assert outcome.status == "applied"
        assert outcome.applied_fields == ("start_time", "end_time")

    def test_unrepresentable_duration_poison_blocks_later_bare_move(self):
        snap = _schedule([_block(1, "12:00", "13:00")])
        result = plan_mutations(
            snap,
            [
                _duration_resize(1, duration_minutes=1500),
                _move(1, "14:00"),
            ],
            day_start=DAY_START,
            day_end=DAY_END,
        )
        assert isinstance(result, MutationPlan)
        assert result.diff.updates == ()
        # Same-task actions merge to one outcome keyed by the last action index.
        outcome = result.outcomes[0]
        assert outcome.action_index == 1
        assert outcome.reason_code == "out_of_window"
        assert outcome.status == "skipped"
