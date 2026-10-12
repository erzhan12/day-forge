"""Schedule mutation values shared by HTTP adapters and the AI planner.

These types carry no request, response, or database objects.  A negative
candidate ID is temporary and is never persisted as a TimeBlock primary key.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class BlockSnapshot:
    id: int
    start_time: datetime.time
    end_time: datetime.time
    title: str
    category: str
    is_completed: bool
    sort_order: int = 0
    origin: str = "manual"


@dataclass(frozen=True)
class ScheduleSnapshot:
    id: int | None
    date: datetime.date
    blocks: tuple[BlockSnapshot, ...]


@dataclass
class BlockCandidate:
    id: int
    start_time: datetime.time
    end_time: datetime.time
    title: str
    category: str
    is_completed: bool
    source_action_index: int | None = None
    sort_order: int = 0
    origin: str = "manual"

    @classmethod
    def from_snapshot(cls, snap: BlockSnapshot) -> BlockCandidate:
        return cls(
            snap.id,
            snap.start_time,
            snap.end_time,
            snap.title,
            snap.category,
            snap.is_completed,
            None,
            snap.sort_order,
            snap.origin,
        )


@dataclass(frozen=True)
class CreateCommand:
    title: str
    start_time: datetime.time
    end_time: datetime.time
    category: str
    is_completed: bool = False
    sort_order: int | None = 0
    action_index: int | None = None
    origin: str = "manual"


@dataclass(frozen=True)
class UpdateCommand:
    block_id: int
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None
    title: str | None = None
    category: str | None = None
    is_completed: bool | None = None
    sort_order: int | None = None
    action_index: int | None = None


@dataclass(frozen=True)
class DeleteCommand:
    block_id: int
    action_index: int | None = None


@dataclass(frozen=True)
class ReorderCommand:
    updates: tuple[UpdateCommand, ...]


@dataclass(frozen=True)
class RestoreCommand:
    blocks: tuple[CreateCommand, ...]


@dataclass(frozen=True)
class DeleteDiffEntry:
    block_id: int
    action_index: int | None = None


@dataclass(frozen=True)
class UpdateDiffEntry:
    block_id: int
    start_time: datetime.time
    end_time: datetime.time
    action_index: int | None = None
    title: str | None = None
    category: str | None = None
    start_changed: bool = True
    end_changed: bool = True
    is_completed: bool | None = None
    sort_order: int | None = None


@dataclass(frozen=True)
class CreateDiffEntry:
    temp_id: int
    title: str
    category: str
    start_time: datetime.time
    end_time: datetime.time
    action_index: int | None = None
    is_completed: bool = False
    sort_order: int | None = None
    origin: str = "manual"


@dataclass(frozen=True)
class MutationDiff:
    deletes: tuple[DeleteDiffEntry, ...] = ()
    updates: tuple[UpdateDiffEntry, ...] = ()
    creates: tuple[CreateDiffEntry, ...] = ()


@dataclass(frozen=True)
class CommandPlan:
    diff: MutationDiff
    candidates: tuple[BlockCandidate, ...]
    restore: bool = False
