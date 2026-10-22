"""Pure final-state mutation planner for AI chat apply (feature 0030).

Snapshot in, ``MutationPlan`` or ``PlanError`` out — no ORM writes.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from schedules.commands import (
    BlockCandidate,
    BlockSnapshot,
    MutationDiff,
    ScheduleSnapshot,
)
from schedules.planning import (
    AI,
    CommandError,
    diff_candidates,
    snapshot_from_blocks,
    validate_block_interval,
    validate_final_state,
)
from schedules.time_validation import (
    parse_time,
    times_overlap,
)
from schedules.window import DEFAULT_WINDOW, ScheduleWindow

from ai.free_slot import GRID_MINUTES, find_slot

logger = logging.getLogger(__name__)

_UNKNOWN_TASK_DETAIL = "Referenced block no longer exists; it may have been deleted. Please retry."


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


# Feature 0067: deterministic auto-placement of untimed chat ``add`` actions.
# Defaults centralised here (the grid comes from ``free_slot.GRID_MINUTES``).
DEFAULT_AUTO_DURATION_MINUTES = 25
AUTO_PLACEMENT_GAP_MINUTES = 10


@dataclass(frozen=True)
class CreateMutation:
    action_index: int
    title: str
    category: str
    # ``start_time``/``end_time`` are ``None`` for an ``auto_place`` create
    # (feature 0067) — the placement pass fills them in. Explicit both-time
    # creates carry parsed times and ``auto_place=False``.
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None
    duration_minutes: int | None = None
    auto_place: bool = False


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
    # Feature 0068: duration resizing owns end arithmetic in integer-minute
    # space. ``new_end`` is only a representability-safe reconstruction.
    duration_derived_end: bool = False
    derived_end_minutes: int | None = None
    chain_poisoned: bool = False


@dataclass(frozen=True)
class DeleteMutation:
    action_index: int
    task_id: int


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

    if kind in {"move", "update"} and "start_time" in action and "end_time" not in action:
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
        "origin": block.origin,
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
            schedule_stub = ScheduleSnapshot(schedule_id, schedule_date, ())
            block_snaps = tuple(
                sorted(snapshot_from_blocks(schedule_stub, blocks_list).blocks, key=lambda b: b.id)
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


def _time_from_minutes(value: int) -> datetime.time:
    """Convert minutes-since-midnight to a ``datetime.time`` (feature 0067).

    Callers must clamp ``value`` into ``[0, 1439]`` in integer-minute space
    first; this never wraps past midnight.
    """
    hour, minute = divmod(value, 60)
    return datetime.time(hour, minute)


def _minutes_from_time(value: datetime.time) -> int:
    """Inverse of ``_time_from_minutes``: minutes since midnight (feature 0067)."""
    return value.hour * 60 + value.minute


def _padded_auto_intervals(
    blocks: Sequence[BlockCandidate], window: ScheduleWindow, gap: int,
) -> list[tuple[datetime.time, datetime.time]]:
    """Pad raw occupancy symmetrically, clamping in minutes before conversion."""
    padded = []
    for block in blocks:
        lo = max(_minutes_from_time(block.start_time) - gap, window.start_minutes)
        hi = min(_minutes_from_time(block.end_time) + gap, window.end_minutes)
        if hi > lo:
            padded.append((_time_from_minutes(lo), _time_from_minutes(hi)))
    return padded


def _find_auto_slot(
    blocks: Sequence[BlockCandidate], base_min: int, duration: int,
    window: ScheduleWindow, gap: int,
) -> SlotSuggestion | None:
    """Prefer smaller gaps only within the initial raw window (feature 0086)."""

    raw = sorted(blocks, key=lambda block: (block.start_time, block.end_time, block.id))
    next_start = next(
        (_minutes_from_time(block.start_time) for block in raw
         if _minutes_from_time(block.end_time) > base_min),
        None,
    )
    initial_end = window.end_minutes if next_start is None else min(next_start, window.end_minutes)
    fallback = find_slot(
        _time_from_minutes(base_min), _time_from_minutes(base_min + duration),
        "later", window, _padded_auto_intervals(raw, window, gap),
    )
    if initial_end <= base_min or (
        fallback is not None and fallback.end_time is not None
        and _minutes_from_time(fallback.end_time) <= initial_end
    ):
        return fallback

    # Derive smaller grid multiples per call, including zero. Day boundaries
    # need no gap; only an upcoming neighbour reduces the latest permitted end.
    for trial_gap in range(((gap - 1) // GRID_MINUTES) * GRID_MINUTES, -1, -GRID_MINUTES):
        end_min = window.end_minutes if next_start is None else min(
            window.end_minutes, next_start - trial_gap,
        )
        end_min = (end_min // GRID_MINUTES) * GRID_MINUTES
        start_min = end_min - duration
        if start_min < base_min:
            continue
        start, end = _time_from_minutes(start_min), _time_from_minutes(end_min)
        # Duration is schema-validated on the grid. Check exactly this right-aligned
        # candidate; a forward search could escape the initial window.
        if not any(
            times_overlap(start, end, lo, hi)
            for lo, hi in _padded_auto_intervals(raw, window, trial_gap)
        ):
            return SlotSuggestion(start, end, "later")
    return fallback


def _duration_fails_end_verdict(
    *,
    derived_end_minutes: int,
    start: datetime.time,
    start_supplied: bool,
    window: ScheduleWindow,
) -> bool:
    """Mirror the duration-end ladder in ``plan_mutations`` (integer space only)."""
    start_minutes = _minutes_from_time(start)
    if not 0 <= derived_end_minutes < 24 * 60:
        return True
    if start_supplied and start < window.day_start:
        return True
    if derived_end_minutes - start_minutes < GRID_MINUTES:
        return True
    if (
        derived_end_minutes > window.end_minutes
        or derived_end_minutes < window.start_minutes
        or derived_end_minutes >= 24 * 60
    ):
        return True
    return bool(derived_end_minutes % GRID_MINUTES)


def _duration_would_overlap(
    task_id: int,
    start: datetime.time,
    derived_end_minutes: int,
    snapshot_by_id: dict[int, BlockSnapshot],
    chain_effective: dict[int, _EffectiveTimes],
    removed: set[int],
) -> bool:
    """True when a duration-derived interval would overlap another live block."""
    if not 0 <= derived_end_minutes < 24 * 60:
        return False
    end = _time_from_minutes(derived_end_minutes)
    for other_id, block in snapshot_by_id.items():
        if other_id == task_id or other_id in removed:
            continue
        if other_id in chain_effective:
            eff = chain_effective[other_id]
            other_start, other_end = eff.start_time, eff.end_time
        else:
            other_start, other_end = block.start_time, block.end_time
        if times_overlap(start, end, other_start, other_end):
            return True
    return False


def _normalize_actions(
    snapshot: ScheduleSnapshot,
    parsed_actions: Sequence[dict],
    *,
    window: ScheduleWindow | None = None,
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
    chain_poisoned: set[int] = set()

    for action_index, action in enumerate(parsed_actions):
        kind = action["type"]
        if kind == "add":
            title = action["title"].strip()
            category = action["category"]
            # Feature 0067: an untimed chat add omits both time fields and is
            # placed deterministically by the placement pass. Explicit both-time
            # adds parse their times here as before.
            if "start_time" not in action and "end_time" not in action:
                creates.append(
                    CreateMutation(
                        action_index=action_index,
                        title=title,
                        category=category,
                        duration_minutes=action.get("duration_minutes"),
                        auto_place=True,
                    )
                )
            else:
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
            chain_poisoned.discard(task_id)
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

        changes = action["changes"] if kind == "update" else action
        # The public nested update contract is translated here, at the one
        # wire-to-canonical boundary.  Downstream time and placement logic only
        # sees the established flat operands.
        time_action = (
            {
                "type": "update",
                **{
                    field: changes[field]
                    for field in ("start_time", "end_time")
                    if field in changes
                },
            }
            if kind == "update"
            else action
        )
        duration_absolute = action.get("duration_minutes") if kind == "resize" else None
        duration_delta = action.get("duration_delta_minutes") if kind == "resize" else None
        duration_mode = duration_absolute is not None or duration_delta is not None

        # Keep boundary move/resize behaviour centralized in the established
        # helper. Duration actions intentionally bypass its time arithmetic:
        # their end is derived below in integer-minute space.
        new_start, new_end, wrapped = compute_move_resize_times(time_action, effective)
        start_supplied = "start_time" in changes
        end_supplied = "end_time" in changes
        bare_move = kind in {"move", "update"} and start_supplied and not end_supplied
        duration_derived_end = False
        derived_end_minutes: int | None = None
        if duration_mode:
            start_minutes = _minutes_from_time(effective.start_time)
            if duration_absolute is not None:
                derived_end_minutes = start_minutes + duration_absolute
            else:
                derived_end_minutes = _minutes_from_time(effective.end_time) + duration_delta
            # ``datetime.time`` cannot represent negative or >=24:00 values.
            # This clamped reconstruction is never used for duration verdicts.
            new_start = effective.start_time
            new_end = _time_from_minutes(min(max(derived_end_minutes, 0), 1439))
            duration_derived_end = True
            end_supplied = False
            bare_move = False
            wrapped = False
        if bare_move:
            bare_move_derived_end = True
            wrapped_flag = wrapped
        else:
            wrapped_flag = False
            bare_move_derived_end = False

        prev = merged_updates.get(task_id)
        if prev is not None and not start_supplied:
            start_supplied = prev.start_supplied
        if prev is not None and not end_supplied and not bare_move and not duration_mode:
            end_supplied = prev.end_supplied
            bare_move_derived_end = prev.bare_move_derived_end
            wrapped_flag = prev.wrapped
            # A metadata-only follow-up retains a prior duration end's
            # provenance so it cannot become a silent no-op.
            if prev.duration_derived_end:
                duration_derived_end = True
                derived_end_minutes = prev.derived_end_minutes
                # Invalid durations stay out of chain_effective for later moves,
                # but a metadata follow-up must retain the attempted boundary so
                # validation can still report its rejection instead of a no-op.
                new_end = prev.new_end

        new_title = (
            changes["title"].strip()
            if kind == "update" and isinstance(changes.get("title"), str)
            else None
        )
        new_category = changes.get("category") if kind == "update" else None
        # Direction is placement intent tied to THIS action's explicit
        # ``direction`` key. A later same-task action that supplies a time
        # but no ``direction`` must NOT clobber a prior action's later/earlier
        # with "exact" (regression: FIX-C). Only default to "exact" when
        # neither this action nor any prior action carried a direction.
        this_direction = action.get("placement_direction") if kind == "update" else None
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

        duration_out_of_range = (
            duration_derived_end
            and derived_end_minutes is not None
            and not 0 <= derived_end_minutes < 24 * 60
        )
        # This mutation remembers whether an *earlier* action poisoned the
        # chain. Its own invalid duration is handled by the dedicated ladder
        # below, preserving interval-vs-window precedence for that action.
        mutation_chain_poisoned = task_id in chain_poisoned
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
            duration_derived_end=duration_derived_end,
            derived_end_minutes=derived_end_minutes,
            chain_poisoned=mutation_chain_poisoned,
        )
        if duration_out_of_range:
            chain_poisoned.add(task_id)
        # A rejected duration must not feed same-turn chaining: ``chain_effective``
        # is updated in normalize (before the validation pass), so a window/interval/
        # granularity failure that only surfaces later would otherwise inflate a
        # subsequent bare move with the failed resize's clamped stand-in.
        skip_chain_update = False
        if duration_derived_end and derived_end_minutes is not None:
            if duration_out_of_range:
                skip_chain_update = True
            elif window is not None and _duration_fails_end_verdict(
                derived_end_minutes=derived_end_minutes,
                start=new_start,
                start_supplied=start_supplied,
                window=window,
            ):
                skip_chain_update = True
            elif _duration_would_overlap(
                task_id,
                new_start,
                derived_end_minutes,
                snapshot_by_id,
                chain_effective,
                removed,
            ):
                skip_chain_update = True
        if not skip_chain_update:
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
            sort_order=base.sort_order,
            origin=base.origin,
        )

    for create in creates:
        # Feature 0067: auto-placement creates carry no times yet — the
        # placement pass inserts them after the overlap fixpoint. Skip them
        # here so ``None`` boundaries never reach overlap/clamp logic.
        if create.auto_place:
            continue
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
    earliest_start: datetime.time | None = None,
) -> PartialPlan | PlanError:
    """Plan the accepted subset of a chat turn.

    Structural misses still abort.  Policy failures (window, grid, interval,
    and overlap) reject only the affected time intent so independent metadata
    can safely persist in the same atomic turn.

    ``earliest_start`` is the forward placement floor for untimed auto-place
    creates (feature 0067): ``None`` searches from the window start (used for
    non-today schedules), otherwise placement scans forward from this
    grid-aligned time. It never affects explicit-time adds.
    """

    window_start, window_end = _day_bounds(day_start, day_end)
    window = ScheduleWindow(window_start, window_end)
    normalized = _normalize_actions(snapshot, parsed_actions, window=window)
    if isinstance(normalized, PlanError):
        return normalized

    deletes, merged_updates, creates = normalized
    candidate = _build_candidate(snapshot, deletes, merged_updates, creates)
    snapshot_by_id = {block.id: block for block in snapshot.blocks}
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
            sort_order=current.sort_order,
            origin=current.origin,
        )

    # Intrinsic validation and the narrowly-scoped near-edge clamping pass.
    for task_id, upd in merged_updates.items():
        time_requested = (
            upd.start_supplied
            or upd.end_supplied
            or upd.bare_move_derived_end
            or upd.duration_derived_end
        )
        if not time_requested:
            continue
        accepted_changed.add(task_id)
        start, end = upd.new_start, upd.new_end
        # A follow-up after an unrepresentable duration must not run against
        # the clamped stand-in held in ``new_end``.
        if upd.chain_poisoned:
            reject(task_id, "out_of_window")
            continue
        if upd.wrapped and upd.bare_move_derived_end:
            reject(task_id, "out_of_window")
            continue
        if upd.duration_derived_end:
            if upd.derived_end_minutes is None:
                # Invariant: a duration-derived end always carries its integer
                # minutes. Reject defensively rather than assert (which a ``-O``
                # run strips, turning a slipped invariant into a wrong apply).
                reject(task_id, "out_of_window")
                continue
            derived_end = upd.derived_end_minutes
            start_minutes = _minutes_from_time(start)
            # An inherited supplied start would be clamped later; reject
            # instead of silently changing the requested duration.
            if upd.start_supplied and start < window.day_start:
                reject(task_id, "out_of_window")
                continue
            if derived_end - start_minutes < GRID_MINUTES:
                reject(task_id, "interval")
                continue
            if (
                derived_end > window.end_minutes
                or derived_end < window.start_minutes
                or derived_end >= 24 * 60
            ):
                reject(task_id, "out_of_window")
                continue
            if derived_end % GRID_MINUTES:
                reject(task_id, "granularity")
                continue
        if (upd.start_supplied and start > window.day_end) or (
            upd.end_supplied and end < window.day_start
        ):
            reject(task_id, "out_of_window")
            continue
        try:
            candidate[task_id] = validate_block_interval(
                snapshot_by_id[task_id], candidate[task_id],
                policy=AI, window=window,
                start_changed=upd.start_supplied,
                end_changed=(
                    upd.end_supplied or upd.bare_move_derived_end or upd.duration_derived_end
                ),
                clamp_start=upd.start_supplied,
                clamp_end=upd.end_supplied,
            )
        except CommandError as error:
            reject(task_id, error.code)

    for create in creates:
        # Feature 0067: auto-placement creates have no times to clamp/validate
        # here — the placement pass owns them (runs after the overlap fixpoint).
        if create.auto_place:
            continue
        temp_id = -(create.action_index + 1)
        accepted_changed.add(temp_id)
        try:
            candidate[temp_id] = validate_block_interval(
                None, candidate[temp_id], policy=AI, window=window,
            )
        except CommandError as error:
            reject(temp_id, error.code)

    # Rebuild after every rejection round.  This avoids action-order wins.
    for _round in range(len(accepted_changed) + 1):
        changed_vs_unchanged: dict[int, set[int]] = {}
        changed_vs_changed: dict[int, set[int]] = {}
        for overlap in validate_final_state(candidate.values()):
            left_id, right_id = overlap.left_id, overlap.right_id
            left_changed, right_changed = (
                left_id in accepted_changed, right_id in accepted_changed,
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

    # ------------------------------------------------------------------
    # Feature 0067: deterministic auto-placement of untimed chat adds.
    # Runs after the overlap fixpoint, with interval and final-state validation
    # retained below. Each auto searches from the common base, preferring full
    # gaps and reducing them only in the initial window (feature 0086). Its raw
    # placed interval feeds the next auto's padding.
    # ------------------------------------------------------------------
    auto_creates = [c for c in creates if c.auto_place]
    if auto_creates:
        base_min = window.start_minutes
        if earliest_start is not None:
            base_min = max(_minutes_from_time(earliest_start), window.start_minutes)

        for create in sorted(auto_creates, key=lambda c: c.action_index):
            temp_id = -(create.action_index + 1)
            dur = create.duration_minutes or DEFAULT_AUTO_DURATION_MINUTES

            # Reject via minute comparison BEFORE building any datetime.time so a
            # large duration never constructs a midnight-wrapped time. An exact
            # fit (base_min + dur == end_minutes) is allowed, matching find_slot.
            if base_min + dur > window.end_minutes:
                reject(temp_id, "no_slot")
                continue

            suggestion = _find_auto_slot(
                list(candidate.values()), base_min, dur, window, AUTO_PLACEMENT_GAP_MINUTES,
            )
            if suggestion is None or suggestion.start_time is None or suggestion.end_time is None:
                # Both producers — find_slot(direction="later") and
                # _find_auto_slot's own right-aligned candidate — populate both
                # bounds together; the end_time check documents that invariant
                # and guards against a broadened return contract.
                reject(temp_id, "no_slot")
                continue
            candidate[temp_id] = BlockCandidate(
                id=temp_id,
                start_time=suggestion.start_time,
                end_time=suggestion.end_time,
                title=create.title,
                category=create.category,
                is_completed=False,
                source_action_index=create.action_index,
            )
            try:
                candidate[temp_id] = validate_block_interval(
                    None, candidate[temp_id], policy=AI, window=window,
                )
            except CommandError as error:
                reject(temp_id, error.code)
                continue
            overlaps = validate_final_state(candidate.values())
            if any(temp_id in (pair.left_id, pair.right_id) for pair in overlaps):
                reject(temp_id, "overlap")
                continue
            # Marked accepted only after a slot is secured (mirrors the
            # explicit-create path); no_slot rejects never add it, so reject()
            # has nothing to discard for a skipped auto.
            accepted_changed.add(temp_id)

    outcomes: list[ActionOutcome] = []
    for task_id in sorted(merged_updates):
        upd = merged_updates[task_id]
        time_requested = (
            upd.start_supplied
            or upd.end_supplied
            or upd.bare_move_derived_end
            or upd.duration_derived_end
        )
        time_accepted = task_id not in rejected and time_requested
        title = upd.new_title
        category = upd.new_category
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
            if upd.end_supplied or upd.bare_move_derived_end or upd.duration_derived_end:
                target.append("end_time")
        reason, conflicts = rejected.get(task_id, (None, ()))
        suggestion = None
        attempted_direction = None
        # Allowlist: a directional free-slot search is meaningful ONLY for an
        # ``overlap`` skip. Any other reason code (window, grid, interval, or a
        # future one) must NOT reach ``find_slot`` — it would yield a
        # misleading direction question.
        if skipped and time_requested and reason == "overlap":
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

    for create in creates:
        temp_id = -(create.action_index + 1)
        if temp_id not in rejected:
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
    final_diff = diff_candidates(
        snapshot, candidate.values(),
        delete_action_indices={item.task_id: item.action_index for item in deletes},
    )
    # AI creates use the same order allocation as manual appends at persistence
    # time. Their temporary candidate order is only a planning placeholder.
    final_diff = replace(
        final_diff,
        creates=tuple(replace(entry, sort_order=None) for entry in final_diff.creates),
    )
    return PartialPlan(final_diff, tuple(outcomes), overall)
