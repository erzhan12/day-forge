"""Pure final-state mutation planner for AI chat apply (feature 0030).

Snapshot in, ``MutationPlan`` or ``PlanError`` out — no ORM writes.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from schedules.http import VALID_CATEGORIES, parse_time, times_overlap
from schedules.validators import validate_five_minute_granularity

from ai.prompts import DAY_END, DAY_START

_UNKNOWN_TASK_DETAIL = (
    "Referenced block no longer exists; it may have been deleted. Please retry."
)

# add: category/title → day window → granularity → interval → overlap → model
# move/resize: wrap → day window → granularity → interval → overlap → model
_RANK_CREATE_SCHEMA = 0
_RANK_WRAP = 1
_RANK_DAY_WINDOW = 2
_RANK_GRANULARITY = 3
_RANK_INTERVAL = 4
_RANK_OVERLAP = 5
_RANK_MODEL = 6
_RANK_INHERITED = 10


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
    new_start = (
        parse_time(action["start_time"])
        if "start_time" in action
        else block.start_time
    )
    new_end = (
        parse_time(action["end_time"])
        if "end_time" in action
        else block.end_time
    )

    if kind == "move" and "end_time" not in action:
        original = (
            datetime.datetime.combine(datetime.date.min, block.end_time)
            - datetime.datetime.combine(datetime.date.min, block.start_time)
        )
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
    snaps = tuple(
        RuleSnapshot(id=r.id, text=r.text, priority=r.priority) for r in rules
    )
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
    if schedule is not None and (
        blocks_list and not isinstance(blocks_list[0], BlockSnapshot)
    ):
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


def _violation(
    action_index: int,
    rank: int,
    candidate_key: int,
    detail: str,
) -> tuple[int, int, int, str]:
    return (action_index, rank, candidate_key, detail)


def _pick_violation(violations: list[tuple[int, int, int, str]]) -> PlanError | None:
    if not violations:
        return None
    action_index, _, _, detail = min(violations)
    return PlanError(action_index=action_index, detail=detail)


def _normalize_actions(
    snapshot: ScheduleSnapshot,
    parsed_actions: Sequence[dict],
) -> PlanError | tuple[
    list[DeleteMutation],
    dict[int, UpdateMutation],
    list[CreateMutation],
]:
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

        if kind not in ("move", "resize"):
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

        merged_updates[task_id] = UpdateMutation(
            action_index=action_index,
            task_id=task_id,
            new_start=new_start,
            new_end=new_end,
            start_supplied=start_supplied,
            end_supplied=end_supplied,
            bare_move_derived_end=bare_move_derived_end,
            wrapped=wrapped_flag,
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
            title=base.title,
            category=base.category,
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


def _validate_update(
    upd: UpdateMutation,
    day_start_t: datetime.time,
    day_end_t: datetime.time,
    candidate_key: int,
) -> list[tuple[int, int, int, str]]:
    violations: list[tuple[int, int, int, str]] = []
    idx = upd.action_index

    if upd.wrapped and upd.bare_move_derived_end:
        violations.append(
            _violation(idx, _RANK_WRAP, candidate_key, "moved block would extend past midnight")
        )

    if upd.start_supplied and upd.new_start < day_start_t:
        violations.append(
            _violation(
                idx,
                _RANK_DAY_WINDOW,
                candidate_key,
                f"start_time must be >= {DAY_START}",
            )
        )
    if (upd.end_supplied or upd.bare_move_derived_end) and upd.new_end > day_end_t:
        violations.append(
            _violation(
                idx,
                _RANK_DAY_WINDOW,
                candidate_key,
                f"end_time must be <= {DAY_END}",
            )
        )

    if upd.start_supplied:
        try:
            validate_five_minute_granularity(upd.new_start)
        except ValidationError as e:
            violations.append(_violation(idx, _RANK_GRANULARITY, candidate_key, str(e.message)))
    if upd.end_supplied:
        try:
            validate_five_minute_granularity(upd.new_end)
        except ValidationError as e:
            violations.append(_violation(idx, _RANK_GRANULARITY, candidate_key, str(e.message)))

    if upd.new_start >= upd.new_end:
        violations.append(
            _violation(idx, _RANK_INTERVAL, candidate_key, "start_time must be < end_time")
        )

    return violations


def _validate_create(
    create: CreateMutation,
    day_start_t: datetime.time,
    day_end_t: datetime.time,
    temp_id: int,
) -> list[tuple[int, int, int, str]]:
    violations: list[tuple[int, int, int, str]] = []
    idx = create.action_index

    if create.category not in VALID_CATEGORIES:
        violations.append(
            _violation(
                idx,
                _RANK_CREATE_SCHEMA,
                temp_id,
                f"invalid category {create.category!r}",
            )
        )
    if not create.title:
        violations.append(
            _violation(idx, _RANK_CREATE_SCHEMA, temp_id, "title must not be empty")
        )

    if create.start_time < day_start_t:
        violations.append(
            _violation(
                idx,
                _RANK_DAY_WINDOW,
                temp_id,
                f"start_time must be >= {DAY_START}",
            )
        )
    if create.end_time > day_end_t:
        violations.append(
            _violation(
                idx,
                _RANK_DAY_WINDOW,
                temp_id,
                f"end_time must be <= {DAY_END}",
            )
        )

    for t in (create.start_time, create.end_time):
        try:
            validate_five_minute_granularity(t)
        except ValidationError as e:
            violations.append(_violation(idx, _RANK_GRANULARITY, temp_id, str(e.message)))

    if create.start_time >= create.end_time:
        violations.append(
            _violation(idx, _RANK_INTERVAL, temp_id, "start_time must be < end_time")
        )

    return violations


def _validate_candidate(
    candidate: dict[int, BlockCandidate],
    merged_updates: dict[int, UpdateMutation],
    creates: list[CreateMutation],
    day_start: str,
    day_end: str,
) -> PlanError | None:
    day_start_t, day_end_t = _day_bounds(day_start, day_end)
    # Inherited-only integrity violations use min batch action_index; indices
    # are always 0..n-1 from enumerate, so the envelope fallback is 0.
    fallback_index = 0
    violations: list[tuple[int, int, int, str]] = []

    changed_ids = set(merged_updates.keys()) | {-(c.action_index + 1) for c in creates}

    for upd in merged_updates.values():
        violations.extend(
            _validate_update(upd, day_start_t, day_end_t, upd.task_id)
        )

    for create in creates:
        temp_id = -(create.action_index + 1)
        violations.extend(
            _validate_create(create, day_start_t, day_end_t, temp_id)
        )

    for block_id in sorted(candidate.keys()):
        block = candidate[block_id]
        if block_id in changed_ids:
            continue
        if block.start_time >= block.end_time:
            violations.append(
                _violation(
                    fallback_index,
                    _RANK_INHERITED,
                    block_id,
                    "start_time must be < end_time",
                )
            )

    candidate_ids = sorted(candidate.keys())
    for i, id1 in enumerate(candidate_ids):
        b1 = candidate[id1]
        for id2 in candidate_ids[i + 1:]:
            b2 = candidate[id2]
            if not times_overlap(
                b1.start_time, b1.end_time, b2.start_time, b2.end_time
            ):
                continue

            idx1 = b1.source_action_index
            idx2 = b2.source_action_index
            contributing = []
            if id1 in changed_ids and idx1 is not None:
                contributing.append(idx1)
            if id2 in changed_ids and idx2 is not None:
                contributing.append(idx2)

            if contributing:
                action_index = min(contributing)
                rank = _RANK_OVERLAP
            else:
                action_index = fallback_index
                rank = _RANK_INHERITED

            candidate_key = min(id1, id2)
            violations.append(
                _violation(
                    action_index,
                    rank,
                    candidate_key,
                    "block would overlap existing block",
                )
            )

    return _pick_violation(violations)


def _build_diff(
    snapshot: ScheduleSnapshot,
    candidate: dict[int, BlockCandidate],
    deletes: list[DeleteMutation],
    merged_updates: dict[int, UpdateMutation],
    creates: list[CreateMutation],
) -> MutationDiff:
    delete_entries = tuple(
        DeleteDiffEntry(block_id=d.task_id, action_index=d.action_index)
        for d in sorted(deletes, key=lambda d: d.task_id)
    )

    snapshot_by_id = {b.id: b for b in snapshot.blocks}
    update_entries = []
    for task_id in sorted(merged_updates.keys()):
        upd = merged_updates[task_id]
        orig = snapshot_by_id[task_id]
        if upd.new_start != orig.start_time or upd.new_end != orig.end_time:
            update_entries.append(
                UpdateDiffEntry(
                    block_id=task_id,
                    start_time=upd.new_start,
                    end_time=upd.new_end,
                    action_index=upd.action_index,
                )
            )

    create_entries = tuple(
        CreateDiffEntry(
            temp_id=-(c.action_index + 1),
            title=c.title,
            category=c.category,
            start_time=c.start_time,
            end_time=c.end_time,
            action_index=c.action_index,
        )
        for c in sorted(creates, key=lambda c: c.action_index)
    )

    return MutationDiff(
        deletes=delete_entries,
        updates=tuple(update_entries),
        creates=create_entries,
    )


def plan_mutations(
    snapshot: ScheduleSnapshot,
    parsed_actions: Sequence[dict],
    *,
    day_start: str = DAY_START,
    day_end: str = DAY_END,
) -> MutationPlan | PlanError:
    """Pure final-state planner: normalize, build candidate, validate, diff."""
    normalized = _normalize_actions(snapshot, parsed_actions)
    if isinstance(normalized, PlanError):
        return normalized

    deletes, merged_updates, creates = normalized
    candidate = _build_candidate(snapshot, deletes, merged_updates, creates)

    error = _validate_candidate(
        candidate,
        merged_updates,
        creates,
        day_start,
        day_end,
    )
    if error is not None:
        return error

    diff = _build_diff(snapshot, candidate, deletes, merged_updates, creates)
    return MutationPlan(diff=diff)
