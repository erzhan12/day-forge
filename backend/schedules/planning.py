"""Pure schedule planning and final-state validation.

HTTP adapters own wire parsing and user category membership.  This module
owns the interval rules that must agree across manual, import, AI, and undo.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from schedules.commands import (
    BlockCandidate,
    BlockSnapshot,
    CommandPlan,
    CreateCommand,
    CreateDiffEntry,
    DeleteCommand,
    DeleteDiffEntry,
    MutationDiff,
    ReorderCommand,
    RestoreCommand,
    ScheduleSnapshot,
    UpdateCommand,
    UpdateDiffEntry,
)
from schedules.time_validation import (
    TimeValidationError,
    times_overlap,
    validate_five_minute_granularity,
    validate_time_range,
)
from schedules.window import DEFAULT_WINDOW, ScheduleWindow, clamp_boundary


@dataclass(frozen=True)
class SchedulePolicy:
    name: str
    require_grid: bool
    window_rule: str  # "clamp", "reject", or "ignore"


MANUAL = SchedulePolicy("manual", True, "clamp")
IMPORT = SchedulePolicy("import", False, "clamp")
AI = SchedulePolicy("ai", True, "clamp")
DRAFT = SchedulePolicy("draft", True, "reject")
UNDO = SchedulePolicy("undo", False, "ignore")

POLICIES = {policy.name: policy for policy in (MANUAL, IMPORT, AI, DRAFT, UNDO)}


class CommandError(ValueError):
    def __init__(
        self,
        code: str,
        field: str,
        message: str,
        *,
        block_id: int | None = None,
        action_index: int | None = None,
        conflicting_block_ids: tuple[int, ...] = (),
    ):
        self.code = code
        self.field = field
        self.message = message
        self.block_id = block_id
        self.action_index = action_index
        self.conflicting_block_ids = conflicting_block_ids
        super().__init__(message)


@dataclass(frozen=True)
class Overlap:
    left_id: int
    right_id: int


def snapshot_from_blocks(schedule, blocks: Iterable) -> ScheduleSnapshot:
    """Copy loaded model rows into values without issuing queries."""
    snapshots = tuple(
        BlockSnapshot(
            block.id,
            block.start_time,
            block.end_time,
            block.title,
            block.category,
            block.is_completed,
            block.sort_order,
            getattr(block, "origin", "manual"),
        )
        for block in blocks
    )
    return ScheduleSnapshot(schedule.id, schedule.date, snapshots)


def validate_candidate_fields(
    candidate: BlockCandidate,
    *,
    title_changed: bool = True,
    category_changed: bool = True,
    completed_changed: bool = True,
    order_changed: bool = True,
    max_sort_order: int | None = 10_000,
) -> None:
    """Check scalar fields being written; category ownership belongs to the adapter."""
    context = {"block_id": candidate.id, "action_index": candidate.source_action_index}
    if title_changed and (
        not isinstance(candidate.title, str)
        or not candidate.title.strip()
        or len(candidate.title) > 255
    ):
        raise CommandError("title", "title", "Title must be 1 to 255 characters.", **context)
    if category_changed and (
        not isinstance(candidate.category, str)
        or not candidate.category
        or len(candidate.category) > 32
    ):
        raise CommandError("category", "category", "Invalid category.", **context)
    if completed_changed and not isinstance(candidate.is_completed, bool):
        raise CommandError(
            "is_completed", "is_completed", "is_completed must be a boolean.", **context
        )
    if order_changed and (
        isinstance(candidate.sort_order, bool)
        or not isinstance(candidate.sort_order, int)
        or candidate.sort_order < 0
        or (max_sort_order is not None and candidate.sort_order > max_sort_order)
    ):
        raise CommandError(
            "sort_order",
            "sort_order",
            "sort_order must be between 0 and 10000."
            if max_sort_order is not None
            else "sort_order must be a non-negative integer.",
            **context,
        )


def validate_block_interval(
    original: BlockSnapshot | None,
    candidate: BlockCandidate,
    *,
    policy: SchedulePolicy = MANUAL,
    window: ScheduleWindow = DEFAULT_WINDOW,
    start_changed: bool | None = None,
    end_changed: bool | None = None,
    clamp_start: bool | None = None,
    clamp_end: bool | None = None,
) -> BlockCandidate:
    """Validate changed boundaries and return a possibly clamped candidate.

    Explicit ``start_changed``/``end_changed`` carry AI action provenance.
    ``clamp_* = False`` lets AI reject a derived boundary instead of moving it.
    Existing unchanged off-grid or out-of-window boundaries remain valid.
    """
    if start_changed is None:
        start_changed = original is None or candidate.start_time != original.start_time
    if end_changed is None:
        end_changed = original is None or candidate.end_time != original.end_time
    context = {"block_id": candidate.id, "action_index": candidate.source_action_index}
    if policy.require_grid:
        for changed, value in (
            (start_changed, candidate.start_time),
            (end_changed, candidate.end_time),
        ):
            if changed:
                try:
                    validate_five_minute_granularity(value)
                except TimeValidationError as error:
                    raise CommandError(
                        "granularity", error.field, error.message, **context
                    ) from error
    if policy.window_rule == "ignore":
        _validate_range(candidate, context)
        return candidate
    if policy.window_rule == "reject":
        if (start_changed and not window.day_start <= candidate.start_time <= window.day_end) or (
            end_changed and not window.day_start <= candidate.end_time <= window.day_end
        ):
            raise CommandError(
                "out_of_window",
                "time",
                f"Times must fall within {window.start_str}-{window.end_str}.",
                **context,
            )
        _validate_range(candidate, context)
        return candidate
    if policy.window_rule != "clamp":
        raise ValueError(f"Unknown window policy: {policy.window_rule}")

    use_start = start_changed if clamp_start is None else clamp_start
    use_end = end_changed if clamp_end is None else clamp_end
    # A changed derived AI edge can be marked non-clampable. It must still
    # satisfy the window, while an unchanged inherited edge need not.
    if (
        start_changed
        and not use_start
        and not window.day_start <= candidate.start_time <= window.day_end
    ) or (
        end_changed and not use_end and not window.day_start <= candidate.end_time <= window.day_end
    ):
        raise CommandError("out_of_window", "time", "Block is outside your day window.", **context)
    # An in-window reversed range is an interval error. A changed boundary
    # beyond the window can instead be clamped first; if it collapses the
    # interval, the established manual result is out_of_window.
    if candidate.start_time >= candidate.end_time and (
        not use_start or window.day_start <= candidate.start_time <= window.day_end
    ) and (not use_end or window.day_start <= candidate.end_time <= window.day_end):
        _validate_range(candidate, context)
    clamped = clamp_boundary(
        candidate.start_time,
        candidate.end_time,
        window,
        clamp_start=use_start,
        clamp_end=use_end,
    )
    if clamped is None:
        raise CommandError("out_of_window", "time", "Block is outside your day window.", **context)
    result = replace(candidate, start_time=clamped[0], end_time=clamped[1])
    _validate_range(result, context)
    return result


def _validate_range(candidate: BlockCandidate, context: dict) -> None:
    try:
        validate_time_range(candidate.start_time, candidate.end_time)
    except TimeValidationError as error:
        raise CommandError("interval", error.field, error.message, **context) from error


def validate_final_state(candidates: Iterable[BlockCandidate]) -> tuple[Overlap, ...]:
    """Return every overlapping pair in a complete half-open candidate set."""
    ordered = sorted(candidates, key=lambda block: (block.start_time, block.end_time, block.id))
    overlaps: list[Overlap] = []
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if right.start_time >= left.end_time:
                break
            if times_overlap(left.start_time, left.end_time, right.start_time, right.end_time):
                overlaps.append(Overlap(left.id, right.id))
    return tuple(overlaps)


def diff_candidates(
    before: ScheduleSnapshot,
    candidates: Iterable[BlockCandidate],
    *,
    delete_action_indices: Mapping[int, int | None] | None = None,
) -> MutationDiff:
    """Compute a persistence diff from final candidate values.

    The caller may supply delete provenance for AI outcomes.  Unchanged rows
    are omitted so an empty diff remains a true no-op.
    """
    originals = {block.id: block for block in before.blocks}
    after = {block.id: block for block in candidates}
    delete_action_indices = delete_action_indices or {}
    deletes = tuple(
        DeleteDiffEntry(block_id, delete_action_indices.get(block_id))
        for block_id in sorted(originals.keys() - after.keys())
    )
    updates = []
    for block_id in sorted(originals.keys() & after.keys()):
        old, new = originals[block_id], after[block_id]
        if (
            old.start_time,
            old.end_time,
            old.title,
            old.category,
            old.is_completed,
            old.sort_order,
        ) == (
            new.start_time,
            new.end_time,
            new.title,
            new.category,
            new.is_completed,
            new.sort_order,
        ):
            continue
        updates.append(
            UpdateDiffEntry(
                block_id,
                new.start_time,
                new.end_time,
                new.source_action_index,
                title=new.title if new.title != old.title else None,
                category=new.category if new.category != old.category else None,
                start_changed=new.start_time != old.start_time,
                end_changed=new.end_time != old.end_time,
                is_completed=new.is_completed if new.is_completed != old.is_completed else None,
                sort_order=new.sort_order if new.sort_order != old.sort_order else None,
            )
        )
    creates = tuple(
        CreateDiffEntry(
            block.id,
            block.title,
            block.category,
            block.start_time,
            block.end_time,
            block.source_action_index,
            block.is_completed,
            block.sort_order,
            block.origin,
        )
        for block in sorted(after.values(), key=lambda item: item.id, reverse=True)
        if block.id < 0
    )
    return MutationDiff(deletes, tuple(updates), creates)


def plan_commands(
    snapshot: ScheduleSnapshot,
    commands: Sequence[
        CreateCommand | UpdateCommand | DeleteCommand | ReorderCommand | RestoreCommand
    ],
    *,
    policy: SchedulePolicy = MANUAL,
    window: ScheduleWindow = DEFAULT_WINDOW,
) -> CommandPlan:
    """Apply commands to values, then validate and diff their final state."""
    before = {block.id: block for block in snapshot.blocks}
    after = {block.id: BlockCandidate.from_snapshot(block) for block in snapshot.blocks}
    restore = False
    delete_indices: dict[int, int | None] = {}
    next_temp_id = -1
    if any(isinstance(command, RestoreCommand) for command in commands):
        if len(commands) != 1 or not isinstance(commands[0], RestoreCommand):
            raise CommandError("command", "blocks", "Restore must be a single command.")
        restore = True
        policy = UNDO
        after.clear()
        commands = commands[0].blocks
    for command in commands:
        if isinstance(command, ReorderCommand):
            nested = command.updates
        else:
            nested = (command,)
        for item in nested:
            if isinstance(item, CreateCommand):
                order = item.sort_order
                if order is None:
                    order = max((block.sort_order for block in after.values()), default=-1) + 1
                after[next_temp_id] = BlockCandidate(
                    next_temp_id,
                    item.start_time,
                    item.end_time,
                    item.title,
                    item.category,
                    item.is_completed,
                    item.action_index,
                    order,
                    item.origin,
                )
                next_temp_id -= 1
            elif isinstance(item, UpdateCommand):
                current = after.get(item.block_id)
                if current is None or item.block_id < 0:
                    raise CommandError(
                        "unknown_block",
                        "id",
                        "Block not found.",
                        block_id=item.block_id,
                        action_index=item.action_index,
                    )
                changes = {
                    field: value
                    for field in (
                        "start_time",
                        "end_time",
                        "title",
                        "category",
                        "is_completed",
                        "sort_order",
                    )
                    if (value := getattr(item, field)) is not None
                }
                after[item.block_id] = replace(
                    current, **changes, source_action_index=item.action_index
                )
            elif isinstance(item, DeleteCommand):
                if item.block_id not in after:
                    raise CommandError(
                        "unknown_block",
                        "id",
                        "Block not found.",
                        block_id=item.block_id,
                        action_index=item.action_index,
                    )
                del after[item.block_id]
                delete_indices[item.block_id] = item.action_index
            else:
                raise CommandError("command", "command", "Unsupported schedule command.")

    for block_id, candidate in list(after.items()):
        original = before.get(block_id)
        if restore or original is None or candidate != BlockCandidate.from_snapshot(original):
            validate_candidate_fields(
                candidate,
                title_changed=original is None or candidate.title != original.title,
                category_changed=original is None or candidate.category != original.category,
                completed_changed=original is None
                or candidate.is_completed != original.is_completed,
                order_changed=original is None or candidate.sort_order != original.sort_order,
                max_sort_order=None if policy in (AI, DRAFT) else 10_000,
            )
        after[block_id] = validate_block_interval(
            original if not restore else None, candidate, policy=policy, window=window
        )
    overlaps = validate_final_state(after.values())
    if overlaps:
        overlap = overlaps[0]
        left, right = after[overlap.left_id], after[overlap.right_id]
        action = (
            left.source_action_index
            if left.source_action_index is not None
            else right.source_action_index
        )
        raise CommandError(
            "overlap",
            "time",
            "Blocks would overlap.",
            block_id=overlap.left_id,
            action_index=action,
            conflicting_block_ids=(overlap.right_id,),
        )

    candidates = tuple(sorted(after.values(), key=lambda b: (b.start_time, b.sort_order, b.id)))
    if restore:
        old_values = sorted(
            (
                (
                    b.title, b.start_time, b.end_time, b.category,
                    b.is_completed, b.sort_order, b.origin,
                )
                for b in before.values()
            ),
            key=lambda values: (values[1], values[5]),
        )
        new_values = [
            (b.title, b.start_time, b.end_time, b.category, b.is_completed, b.sort_order, b.origin)
            for b in candidates
        ]
        if old_values == new_values:
            return CommandPlan(MutationDiff(), candidates, restore=True)
        diff = MutationDiff(
            tuple(DeleteDiffEntry(block_id) for block_id in sorted(before)),
            (),
            tuple(
                CreateDiffEntry(
                    block.id,
                    block.title,
                    block.category,
                    block.start_time,
                    block.end_time,
                    block.source_action_index,
                    block.is_completed,
                    block.sort_order,
                    block.origin,
                )
                for block in candidates
            ),
        )
    else:
        diff = diff_candidates(snapshot, after.values(), delete_action_indices=delete_indices)
    return CommandPlan(diff, candidates, restore=restore)
