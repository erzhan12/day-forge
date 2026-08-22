"""Pure final-state mutation planner for AI chat apply (feature 0030).

Snapshot in, ``MutationPlan`` or ``PlanError`` out — no ORM writes.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from schedules.http import parse_time, times_overlap
from schedules.validators import validate_five_minute_granularity
from schedules.window import DEFAULT_WINDOW, ScheduleWindow, clamp_boundary

logger = logging.getLogger(__name__)

_UNKNOWN_TASK_DETAIL = "Referenced block no longer exists; it may have been deleted. Please retry."


@dataclass(frozen=True)
class BlockSnapshot:
    id: int
    start_time: datetime.time
    end_time: datetime.time
    title: str
    category: str
    is_completed: bool


@dataclass(frozen=True)
class ScheduleSnapshot:
    id: int
    date: datetime.date
    blocks: tuple[BlockSnapshot, ...]


@dataclass(frozen=True)
class RuleSnapshot:
    id: int
    text: str
    priority: int


@dataclass(frozen=True)
class ApplyContextSnapshot:
    schedule: ScheduleSnapshot
    rules: tuple[RuleSnapshot, ...]
    fingerprint: str


@dataclass
class BlockCandidate:
    id: int
    start_time: datetime.time
    end_time: datetime.time
    title: str
    category: str
    is_completed: bool
    source_action_index: int | None = None

    @classmethod
    def from_snapshot(cls, snap: BlockSnapshot) -> BlockCandidate:
        return cls(
            id=snap.id,
            start_time=snap.start_time,
            end_time=snap.end_time,
            title=snap.title,
            category=snap.category,
            is_completed=snap.is_completed,
            source_action_index=None,
        )


@dataclass(frozen=True)
class CreateMutation:
    action_index: int
    title: str
    category: str
    start_time: datetime.time
    end_time: datetime.time


@dataclass(frozen=True)
class UpdateMutation:
    action_index: int
    task_id: int
    new_start: datetime.time
    new_end: datetime.time
    start_supplied: bool
    end_supplied: bool
    bare_move_derived_end: bool
    wrapped: bool
    new_title: str | None = None
    new_category: str | None = None
    direction: str = "exact"


@dataclass(frozen=True)
class DeleteMutation:
    action_index: int
    task_id: int


@dataclass(frozen=True)
class DeleteDiffEntry:
    block_id: int
    action_index: int


@dataclass(frozen=True)
class UpdateDiffEntry:
    block_id: int
    start_time: datetime.time
    end_time: datetime.time
    action_index: int
    title: str | None = None
    category: str | None = None
    start_changed: bool = True
    end_changed: bool = True


@dataclass(frozen=True)
class CreateDiffEntry:
    temp_id: int
    title: str
    category: str
    start_time: datetime.time
    end_time: datetime.time
    action_index: int


@dataclass(frozen=True)
class MutationDiff:
    deletes: tuple[DeleteDiffEntry, ...]
    updates: tuple[UpdateDiffEntry, ...]
    creates: tuple[CreateDiffEntry, ...]


@dataclass(frozen=True)
class MutationPlan:
    diff: MutationDiff


@dataclass(frozen=True)
class SlotSuggestion:
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None
    direction: str | None = None
    direction_required: bool = False


@dataclass(frozen=True)
class ActionOutcome:
    action_index: int
    task_id: int | None
    status: str
    applied_fields: tuple[str, ...] = ()
    skipped_fields: tuple[str, ...] = ()
    reason_code: str | None = None
    conflicting_task_ids: tuple[int, ...] = ()
    suggestion: SlotSuggestion | None = None
    attempted_direction: str | None = None


@dataclass(frozen=True)
class PartialPlan(MutationPlan):
    outcomes: tuple[ActionOutcome, ...] = ()
    overall_status: str = "applied"


def _slot_suggestion_to_dict(suggestion: SlotSuggestion | None) -> dict | None:
    if suggestion is None:
        return None
    if suggestion.direction_required:
        return {"direction_required": True}
    if suggestion.start_time is None or suggestion.end_time is None:
        return None
    return {
        "start_time": suggestion.start_time.strftime("%H:%M"),
        "end_time": suggestion.end_time.strftime("%H:%M"),
        "direction": suggestion.direction,
    }


def action_outcome_to_dict(outcome: ActionOutcome) -> dict:
    return {
        "action_index": outcome.action_index,
        "task_id": outcome.task_id,
        "status": outcome.status,
        "applied_fields": list(outcome.applied_fields),
        "skipped_fields": list(outcome.skipped_fields),
        "reason_code": outcome.reason_code,
        "conflicting_task_ids": list(outcome.conflicting_task_ids),
        "attempted_direction": outcome.attempted_direction,
        "suggestion": _slot_suggestion_to_dict(outcome.suggestion),
    }


@dataclass(frozen=True)
class PlanError:
    action_index: int
    detail: str


@dataclass
class _EffectiveTimes:
    start_time: datetime.time
    end_time: datetime.time


def compute_move_resize_times(
    action: dict,
    block: _EffectiveTimes | BlockSnapshot | BlockCandidate,
):
    """Resolve effective ``(new_start, new_end)`` for a move/resize action.

    ``block`` must expose ``start_time`` and ``end_time``. Returns
    ``(new_start, new_end, wrapped_past_midnight)``.
    """
    kind = action["type"]
    new_start = parse_time(action["start_time"]) if "start_time" in action else block.start_time
    new_end = parse_time(action["end_time"]) if "end_time" in action else block.end_time

    if kind == "move" and "end_time" not in action:
        original = datetime.datetime.combine(
            datetime.date.min, block.end_time
        ) - datetime.datetime.combine(datetime.date.min, block.start_time)
        minutes = int(original.total_seconds()) // 60
        rounded = max(5, -(-minutes // 5) * 5)
        new_end = (
            datetime.datetime.combine(datetime.date.min, new_start)
            + datetime.timedelta(minutes=rounded)
        ).time()
        if new_end <= new_start:
            return new_start, new_end, True

    return new_start, new_end, False


def _time_iso(t: datetime.time) -> str:
    return t.isoformat()


def _block_payload(block: BlockSnapshot) -> dict[str, Any]:
    return {
        "id": block.id,
        "start_time": _time_iso(block.start_time),
        "end_time": _time_iso(block.end_time),
        "title": block.title,
        "category": block.category,
        "is_completed": block.is_completed,
    }


def _rule_payload(rule: RuleSnapshot) -> dict[str, Any]:
    return {
        "id": rule.id,
        "text": rule.text,
        "priority": rule.priority,
    }


def _fingerprint_payload(
    schedule: ScheduleSnapshot,
    rules: Sequence[RuleSnapshot],
) -> dict[str, Any]:
    blocks = sorted(schedule.blocks, key=lambda b: b.id)
    rule_rows = sorted(rules, key=lambda r: (-r.priority, r.id))
    return {
        "schedule": {
            "id": schedule.id,
            "date": schedule.date.isoformat(),
            "blocks": [_block_payload(b) for b in blocks],
        },
        "rules": [_rule_payload(r) for r in rule_rows],
    }


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def snapshot_from_blocks(schedule, blocks: Iterable) -> ScheduleSnapshot:
    """Build a locked schedule snapshot from ORM ``Schedule`` + block rows."""
    block_snaps = tuple(
        BlockSnapshot(
            id=b.id,
            start_time=b.start_time,
            end_time=b.end_time,
            title=b.title,
            category=b.category,
            is_completed=b.is_completed,
        )
        for b in blocks
    )
    return ScheduleSnapshot(
        id=schedule.id,
        date=schedule.date,
        blocks=tuple(sorted(block_snaps, key=lambda b: b.id)),
    )


def _rules_from_iterable(rules: Iterable) -> tuple[RuleSnapshot, ...]:
    snaps = tuple(RuleSnapshot(id=r.id, text=r.text, priority=r.priority) for r in rules)
    return tuple(sorted(snaps, key=lambda r: (-r.priority, r.id)))


def snapshot_apply_context(
    schedule_snapshot: ScheduleSnapshot,
    rules: Sequence[RuleSnapshot] | Iterable,
) -> ApplyContextSnapshot:
    """Canonical apply-context snapshot + fingerprint for stale-intent guard."""
    # Materialise first so a one-shot iterator is not partially consumed by the
    # RuleSnapshot type check (would silently drop the first rule).
    rules_list = list(rules)
    if not rules_list:
        rule_snaps = ()
    elif isinstance(rules_list[0], RuleSnapshot):
        rule_snaps = tuple(sorted(rules_list, key=lambda r: (-r.priority, r.id)))
    else:
        rule_snaps = _rules_from_iterable(rules_list)
    fingerprint = _hash_payload(_fingerprint_payload(schedule_snapshot, rule_snaps))
    return ApplyContextSnapshot(
        schedule=schedule_snapshot,
        rules=rule_snaps,
        fingerprint=fingerprint,
    )


def compute_apply_context_fingerprint(
    schedule: Any | None = None,
    blocks: Iterable | None = None,
    rules: Iterable | None = None,
    *,
    schedule_id: int | None = None,
    schedule_date: str | datetime.date | None = None,
) -> str:
    """Thin fingerprint helper for views and unit tests.

    Delegates to ``snapshot_from_blocks`` / ``snapshot_apply_context`` so the
    hash payload stays single-sourced with the apply-path snapshot helpers.

    Call-site modes:
    - View (``ai_chat``): ORM ``schedule`` + ORM ``blocks`` +
      Rule rows → ``snapshot_from_blocks`` then ``snapshot_apply_context``.
    - Unit tests: ``BlockSnapshot`` list with ``schedule_id`` /
      ``schedule_date`` kwargs (no ORM schedule).
    - Empty schedule / no blocks: build an empty ``ScheduleSnapshot`` from ids.
    """
    blocks_list = list(blocks) if blocks is not None else []
    rules_arg: Iterable = () if rules is None else rules

    # Mode 1 — production apply path: ORM schedule + ORM TimeBlock rows.
    if schedule is not None and (blocks_list and not isinstance(blocks_list[0], BlockSnapshot)):
        schedule_snap = snapshot_from_blocks(schedule, blocks_list)
    else:
        # Mode 2/3 — tests (BlockSnapshot list) or empty-block schedule.
        if schedule is not None and schedule_id is None:
            schedule_id = schedule.id
            schedule_date = schedule.date
        if schedule_date is None:
            raise ValueError("schedule_date is required")
        if isinstance(schedule_date, str):
            schedule_date = datetime.date.fromisoformat(schedule_date)
        if blocks_list and isinstance(blocks_list[0], BlockSnapshot):
            block_snaps = tuple(sorted(blocks_list, key=lambda b: b.id))
        elif blocks_list:
            # ORM rows without a schedule object (unusual); mirror snapshot_from_blocks.
            block_snaps = tuple(
                sorted(
                    (
                        BlockSnapshot(
                            id=b.id,
                            start_time=b.start_time,
                            end_time=b.end_time,
                            title=b.title,
                            category=b.category,
                            is_completed=b.is_completed,
                        )
                        for b in blocks_list
                    ),
                    key=lambda b: b.id,
                )
            )
        else:
            block_snaps = ()
        schedule_snap = ScheduleSnapshot(
            id=schedule_id,
            date=schedule_date,
            blocks=block_snaps,
        )

    return snapshot_apply_context(schedule_snap, rules_arg).fingerprint


def _day_bounds(day_start: str, day_end: str) -> tuple[datetime.time, datetime.time]:
    return parse_time(day_start), parse_time(day_end)


def _normalize_actions(
    snapshot: ScheduleSnapshot,
    parsed_actions: Sequence[dict],
) -> (
    PlanError
    | tuple[
        list[DeleteMutation],
        dict[int, UpdateMutation],
        list[CreateMutation],
    ]
):
    snapshot_by_id = {b.id: b for b in snapshot.blocks}
    removed: set[int] = set()
    deletes: list[DeleteMutation] = []
    creates: list[CreateMutation] = []
    merged_updates: dict[int, UpdateMutation] = {}
    chain_effective: dict[int, _EffectiveTimes] = {}

    for action_index, action in enumerate(parsed_actions):
        kind = action["type"]
        if kind == "add":
            title = action["title"].strip()
            category = action.get("category", "other")
            creates.append(
                CreateMutation(
                    action_index=action_index,
                    title=title,
                    category=category,
                    start_time=parse_time(action["start_time"]),
                    end_time=parse_time(action["end_time"]),
                )
            )
            continue

        task_id = action["task_id"]
        if kind == "remove":
            if task_id in removed:
                return PlanError(action_index=action_index, detail=_UNKNOWN_TASK_DETAIL)
            if task_id not in snapshot_by_id:
                return PlanError(action_index=action_index, detail=_UNKNOWN_TASK_DETAIL)
            removed.add(task_id)
            merged_updates.pop(task_id, None)
            chain_effective.pop(task_id, None)
            deletes.append(DeleteMutation(action_index=action_index, task_id=task_id))
            continue

        if kind not in ("move", "resize", "update"):
            continue

        if task_id in removed:
            return PlanError(action_index=action_index, detail=_UNKNOWN_TASK_DETAIL)
        if task_id not in snapshot_by_id:
            return PlanError(action_index=action_index, detail=_UNKNOWN_TASK_DETAIL)

        if task_id in chain_effective:
            effective = chain_effective[task_id]
        else:
            block = snapshot_by_id[task_id]
            effective = _EffectiveTimes(
                start_time=block.start_time,
                end_time=block.end_time,
            )

        new_start, new_end, wrapped = compute_move_resize_times(action, effective)
        start_supplied = "start_time" in action
        end_supplied = "end_time" in action
        bare_move = kind == "move" and not end_supplied
        if bare_move:
            bare_move_derived_end = True
            wrapped_flag = wrapped
        else:
            wrapped_flag = False
            bare_move_derived_end = False

        prev = merged_updates.get(task_id)
        if prev is not None and not start_supplied:
            start_supplied = prev.start_supplied
        if prev is not None and not end_supplied and not bare_move:
            end_supplied = prev.end_supplied
            bare_move_derived_end = prev.bare_move_derived_end
            wrapped_flag = prev.wrapped

        new_title = (
            action["title"].strip()
            if kind == "update" and isinstance(action.get("title"), str)
            else None
        )
        new_category = action.get("category") if kind == "update" else None
        # Direction is placement intent tied to THIS action's explicit
        # ``direction`` key. A later same-task action that supplies a time
        # but no ``direction`` must NOT clobber a prior action's later/earlier
        # with "exact" (regression: FIX-C). Only default to "exact" when
        # neither this action nor any prior action carried a direction.
        this_direction = action.get("direction")
        if this_direction is not None:
            direction = this_direction
        elif prev is not None:
            direction = prev.direction
        else:
            direction = "exact"
        if prev is not None:
            if new_title is None:
                new_title = prev.new_title
            if new_category is None:
                new_category = prev.new_category

        merged_updates[task_id] = UpdateMutation(
            action_index=action_index,
            task_id=task_id,
            new_start=new_start,
            new_end=new_end,
            start_supplied=start_supplied,
            end_supplied=end_supplied,
            bare_move_derived_end=bare_move_derived_end,
            wrapped=wrapped_flag,
            new_title=new_title,
            new_category=new_category,
            direction=direction,
        )
        chain_effective[task_id] = _EffectiveTimes(
            start_time=new_start,
            end_time=new_end,
        )

    return deletes, merged_updates, creates


def _build_candidate(
    snapshot: ScheduleSnapshot,
    deletes: list[DeleteMutation],
    merged_updates: dict[int, UpdateMutation],
    creates: list[CreateMutation],
) -> dict[int, BlockCandidate]:
    removed_ids = {d.task_id for d in deletes}
    candidate: dict[int, BlockCandidate] = {}
    for block in snapshot.blocks:
        if block.id not in removed_ids:
            candidate[block.id] = BlockCandidate.from_snapshot(block)

    for task_id, upd in merged_updates.items():
        base = candidate[task_id]
        candidate[task_id] = BlockCandidate(
            id=task_id,
            start_time=upd.new_start,
            end_time=upd.new_end,
            title=upd.new_title if upd.new_title is not None else base.title,
            category=upd.new_category if upd.new_category is not None else base.category,
            is_completed=base.is_completed,
            source_action_index=upd.action_index,
        )

    for create in creates:
        temp_id = -(create.action_index + 1)
        candidate[temp_id] = BlockCandidate(
            id=temp_id,
            start_time=create.start_time,
            end_time=create.end_time,
            title=create.title,
            category=create.category,
            is_completed=False,
            source_action_index=create.action_index,
        )

    return candidate


def plan_mutations(
    snapshot: ScheduleSnapshot,
    parsed_actions: Sequence[dict],
    *,
    day_start: str = DEFAULT_WINDOW.start_str,
    day_end: str = DEFAULT_WINDOW.end_str,
) -> PartialPlan | PlanError:
    """Plan the accepted subset of a chat turn.

    Structural misses still abort.  Policy failures (window, grid, interval,
    and overlap) reject only the affected time intent so independent metadata
    can safely persist in the same atomic turn.
    """
    normalized = _normalize_actions(snapshot, parsed_actions)
    if isinstance(normalized, PlanError):
        return normalized

    deletes, merged_updates, creates = normalized
    candidate = _build_candidate(snapshot, deletes, merged_updates, creates)
    snapshot_by_id = {block.id: block for block in snapshot.blocks}
    window_start, window_end = _day_bounds(day_start, day_end)
    window = ScheduleWindow(window_start, window_end)
    accepted_changed: set[int] = set()
    rejected: dict[int, tuple[str, tuple[int, ...]]] = {}

    def reject(block_id: int, reason: str, conflicts: tuple[int, ...] = ()) -> None:
        if block_id in rejected:
            return
        rejected[block_id] = (reason, conflicts)
        accepted_changed.discard(block_id)
        if block_id < 0:
            candidate.pop(block_id, None)
            return
        original = snapshot_by_id[block_id]
        current = candidate[block_id]
        candidate[block_id] = BlockCandidate(
            id=current.id,
            start_time=original.start_time,
            end_time=original.end_time,
            title=current.title,
            category=current.category,
            is_completed=current.is_completed,
            source_action_index=current.source_action_index,
        )

    def invalid_grid(value: datetime.time) -> bool:
        try:
            validate_five_minute_granularity(value)
        except ValidationError:
            return True
        return False

    # Intrinsic validation and the narrowly-scoped near-edge clamping pass.
    for task_id, upd in merged_updates.items():
        time_requested = upd.start_supplied or upd.end_supplied or upd.bare_move_derived_end
        if not time_requested:
            continue
        accepted_changed.add(task_id)
        start, end = upd.new_start, upd.new_end
        if upd.wrapped and upd.bare_move_derived_end:
            reject(task_id, "out_of_window")
            continue
        if (
            upd.start_supplied
            and start > window.day_end
            or upd.end_supplied
            and end < window.day_start
        ):
            reject(task_id, "out_of_window")
            continue
        if (upd.start_supplied and invalid_grid(start)) or (upd.end_supplied and invalid_grid(end)):
            reject(task_id, "granularity")
            continue
        if start >= end:
            reject(task_id, "interval")
            continue
        # A derived bare-move end is checked but never silently clamped.
        if upd.bare_move_derived_end and end > window.day_end:
            reject(task_id, "out_of_window")
            continue
        clamped = clamp_boundary(
            start,
            end,
            window,
            clamp_start=upd.start_supplied and start < window.day_start,
            clamp_end=upd.end_supplied and end > window.day_end,
        )
        if clamped is None:
            reject(task_id, "out_of_window")
            continue
        start, end = clamped
        if (upd.start_supplied and start != upd.new_start) or (
            upd.end_supplied and end != upd.new_end
        ):
            current = candidate[task_id]
            candidate[task_id] = BlockCandidate(
                current.id,
                start,
                end,
                current.title,
                current.category,
                current.is_completed,
                current.source_action_index,
            )

    for create in creates:
        temp_id = -(create.action_index + 1)
        accepted_changed.add(temp_id)
        start, end = create.start_time, create.end_time
        if invalid_grid(start) or invalid_grid(end):
            reject(temp_id, "granularity")
            continue
        if start >= end:
            reject(temp_id, "interval")
            continue
        if start > window.day_end or end < window.day_start:
            reject(temp_id, "out_of_window")
            continue
        clamped = clamp_boundary(
            start,
            end,
            window,
            clamp_start=start < window.day_start,
            clamp_end=end > window.day_end,
        )
        if clamped is None:
            reject(temp_id, "out_of_window")
            continue
        if clamped != (start, end):
            current = candidate[temp_id]
            candidate[temp_id] = BlockCandidate(
                current.id,
                clamped[0],
                clamped[1],
                current.title,
                current.category,
                current.is_completed,
                current.source_action_index,
            )

    # Rebuild after every rejection round.  This avoids action-order wins.
    for _round in range(len(accepted_changed) + 1):
        changed_vs_unchanged: dict[int, set[int]] = {}
        changed_vs_changed: dict[int, set[int]] = {}
        ids = sorted(candidate)
        for position, left_id in enumerate(ids):
            left = candidate[left_id]
            for right_id in ids[position + 1 :]:
                right = candidate[right_id]
                if not times_overlap(
                    left.start_time, left.end_time, right.start_time, right.end_time
                ):
                    continue
                left_changed, right_changed = (
                    left_id in accepted_changed,
                    right_id in accepted_changed,
                )
                if left_changed ^ right_changed:
                    changed_id, unchanged_id = (
                        (left_id, right_id) if left_changed else (right_id, left_id)
                    )
                    if unchanged_id > 0:
                        changed_vs_unchanged.setdefault(changed_id, set()).add(unchanged_id)
                elif left_changed and right_changed:
                    changed_vs_changed.setdefault(left_id, set()).add(right_id)
                    changed_vs_changed.setdefault(right_id, set()).add(left_id)
        if changed_vs_unchanged:
            for block_id, conflicts in changed_vs_unchanged.items():
                reject(block_id, "overlap", tuple(sorted(conflicts)))
            continue
        if changed_vs_changed:
            for block_id, related_ids in changed_vs_changed.items():
                others = tuple(sorted(other for other in related_ids if other > 0))
                reject(block_id, "unresolved_conflict", others)
            continue
        break
    else:
        # Exhausting the range without a ``break`` means the overlap
        # fixpoint never converged — the returned plan may still contain a
        # conflicting pair. Surface it loudly (logged error, not an assert
        # so production doesn't 500 on an unforeseen edge) rather than
        # silently returning a possibly-invalid plan.
        logger.error(
            "plan_mutations fixpoint did not converge; possible planner bug (schedule=%s)",
            snapshot.id,
        )

    update_entries: list[UpdateDiffEntry] = []
    outcomes: list[ActionOutcome] = []
    for task_id in sorted(merged_updates):
        upd = merged_updates[task_id]
        current = candidate[task_id]
        time_requested = upd.start_supplied or upd.end_supplied or upd.bare_move_derived_end
        time_accepted = task_id not in rejected and time_requested
        start_changed = time_accepted and upd.start_supplied
        end_changed = time_accepted and (upd.end_supplied or upd.bare_move_derived_end)
        title = upd.new_title
        category = upd.new_category
        if title is not None or category is not None or start_changed or end_changed:
            update_entries.append(
                UpdateDiffEntry(
                    task_id,
                    current.start_time,
                    current.end_time,
                    upd.action_index,
                    title,
                    category,
                    start_changed,
                    end_changed,
                )
            )
        applied = []
        skipped = []
        if title is not None:
            applied.append("title")
        if category is not None:
            applied.append("category")
        if time_requested:
            target = applied if time_accepted else skipped
            if upd.start_supplied:
                target.append("start_time")
            if upd.end_supplied or upd.bare_move_derived_end:
                target.append("end_time")
        reason, conflicts = rejected.get(task_id, (None, ()))
        suggestion = None
        attempted_direction = None
        # Allowlist: a directional free-slot search is meaningful ONLY for an
        # ``overlap`` skip. Any other reason code (window, grid, interval, or a
        # future one) must NOT reach ``find_slot`` — it would yield a
        # misleading direction question.
        if skipped and time_requested and reason == "overlap":
            from ai.free_slot import find_slot

            occupied = [
                (block.start_time, block.end_time)
                for block_id, block in candidate.items()
                if block_id != task_id
            ]
            suggestion = find_slot(upd.new_start, upd.new_end, upd.direction, window, occupied)
            attempted_direction = upd.direction
        status = "applied" if not skipped else "partial" if applied else "skipped"
        outcomes.append(
            ActionOutcome(
                upd.action_index,
                task_id,
                status,
                tuple(applied),
                tuple(skipped),
                reason,
                conflicts,
                suggestion,
                attempted_direction,
            )
        )

    create_entries: list[CreateDiffEntry] = []
    for create in creates:
        temp_id = -(create.action_index + 1)
        if temp_id not in rejected:
            current = candidate[temp_id]
            create_entries.append(
                CreateDiffEntry(
                    temp_id,
                    create.title,
                    create.category,
                    current.start_time,
                    current.end_time,
                    create.action_index,
                )
            )
            outcomes.append(
                ActionOutcome(
                    create.action_index,
                    None,
                    "applied",
                    ("title", "category", "start_time", "end_time"),
                )
            )
        else:
            reason, conflicts = rejected[temp_id]
            outcomes.append(
                ActionOutcome(
                    create.action_index,
                    None,
                    "skipped",
                    (),
                    ("title", "category", "start_time", "end_time"),
                    reason,
                    conflicts,
                )
            )

    delete_entries = tuple(
        DeleteDiffEntry(d.task_id, d.action_index) for d in sorted(deletes, key=lambda d: d.task_id)
    )
    outcomes.extend(ActionOutcome(d.action_index, d.task_id, "applied") for d in deletes)
    outcomes.sort(key=lambda outcome: outcome.action_index)
    statuses = [outcome.status for outcome in outcomes]
    overall = (
        "applied"
        if all(status == "applied" for status in statuses)
        else "skipped"
        if not any(status in {"applied", "partial"} for status in statuses)
        else "partial"
    )
    return PartialPlan(
        MutationDiff(delete_entries, tuple(update_entries), tuple(create_entries)),
        tuple(outcomes),
        overall,
    )
