"""Persist a validated schedule diff inside the R04 mutation executor.

The caller holds the schedule write lock and has planned the complete final
candidate state.  This module performs database writes only; policy and
transport errors belong to the caller and planner.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError

from schedules.commands import MutationDiff
from schedules.models import TimeBlock


class PersistenceError(Exception):
    """A failed row write with the originating command's action index."""

    def __init__(self, action_index: int | None, cause: Exception):
        self.action_index = action_index
        self.cause = cause
        super().__init__(str(cause))


def persist_command_diff(
    schedule, locked_blocks: list[TimeBlock], diff: MutationDiff, *, restore: bool = False
) -> list[TimeBlock]:
    """Apply a planner diff and return created blocks in diff order.

    Restore intentionally replaces identities on a changed snapshot, matching
    the Undo endpoint's historical behavior. Empty diffs never write.
    """
    if not (diff.deletes or diff.updates or diff.creates):
        return []

    if restore:
        TimeBlock.objects.filter(schedule=schedule).delete()
        instances = [
            TimeBlock(
                schedule=schedule,
                title=entry.title,
                start_time=entry.start_time,
                end_time=entry.end_time,
                category=entry.category,
                is_completed=entry.is_completed,
                sort_order=entry.sort_order if entry.sort_order is not None else 0,
                origin=entry.origin,
            )
            for entry in diff.creates
        ]
        return TimeBlock.objects.bulk_create(instances)

    blocks_by_id = {block.pk: block for block in locked_blocks}
    for entry in sorted(diff.deletes, key=lambda item: item.block_id):
        block = blocks_by_id.pop(entry.block_id, None)
        if block is not None:
            try:
                block.delete()
            except (ValidationError, IntegrityError) as error:
                raise PersistenceError(entry.action_index, error) from error

    for entry in sorted(diff.updates, key=lambda item: item.block_id):
        block = blocks_by_id.get(entry.block_id)
        if block is None:
            continue
        update_fields = []
        for field in ("title", "category", "is_completed", "sort_order"):
            value = getattr(entry, field, None)
            if value is not None and getattr(block, field) != value:
                setattr(block, field, value)
                update_fields.append(field)
        for field, changed in (
            ("start_time", entry.start_changed),
            ("end_time", entry.end_changed),
        ):
            if changed:
                value = getattr(entry, field)
                if getattr(block, field) != value:
                    setattr(block, field, value)
                    update_fields.append(field)
        if update_fields:
            try:
                block.save(update_fields=update_fields)
            except (ValidationError, IntegrityError) as error:
                raise PersistenceError(entry.action_index, error) from error

    max_sort = max((block.sort_order for block in blocks_by_id.values()), default=-1)
    created = []
    for entry in sorted(
        diff.creates, key=lambda item: (item.action_index is None, item.action_index or 0)
    ):
        sort_order = getattr(entry, "sort_order", None)
        if sort_order is None:
            max_sort += 1
            sort_order = max_sort
        else:
            max_sort = max(max_sort, sort_order)
        block = TimeBlock(
            schedule=schedule,
            title=entry.title,
            start_time=entry.start_time,
            end_time=entry.end_time,
            category=entry.category,
            is_completed=getattr(entry, "is_completed", False),
            sort_order=sort_order,
            origin=entry.origin,
        )
        try:
            block.save()
        except (ValidationError, IntegrityError) as error:
            raise PersistenceError(entry.action_index, error) from error
        created.append(block)
    return created
