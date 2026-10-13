"""Serialize day writes and capture their response before releasing the lock.

Every supported writer locks User, Schedule, then TimeBlock. On SQLite the
first statement is a write, so concurrent transactions never upgrade a stale
read snapshot to a write lock. Callbacks perform database work only: a busy
transaction can be rolled back and retried in full.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.db import OperationalError, connection, transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone

from schedules.models import Schedule
from schedules.serialization import serialize_schedule_snapshot

MAX_REVISION = 2**63 - 1


def _valid_revision(value):
    return type(value) is int and 0 <= value <= MAX_REVISION


class ScheduleChanged(Exception):
    code = "schedule_changed"

    def __init__(self, message="Schedule changed. Refresh the page and try again.", snapshot=None):
        super().__init__(message)
        self.snapshot = snapshot


class MutationRejected(Exception):
    """Abort all writes made before a callback returned an error response."""

    def __init__(self, response):
        self.response = response
        super().__init__("Schedule mutation rejected.")


def schedule_changed_response(exc=None):
    error = exc or ScheduleChanged()
    return JsonResponse(
        {"errors": {"detail": str(error)}, "code": ScheduleChanged.code}, status=409
    )


def parse_expected_revision(data):
    revision = data.get("expected_revision") if isinstance(data, dict) else None
    if not _valid_revision(revision):
        raise ScheduleChanged("Schedule version is missing or invalid. Refresh the page.")
    return revision


@dataclass
class MutationContext:
    schedule: Schedule
    blocks: list


@dataclass
class MutationResult:
    schedule: Schedule
    blocks: list
    changed: bool
    value: Any
    snapshot: dict


@contextmanager
def user_write_lock(user_id):
    """Acquire the shared policy/write lock before any transactional reads."""
    user_model = get_user_model()
    with transaction.atomic():
        # UPDATE takes the SQLite writer reservation and a PostgreSQL row lock.
        if not user_model.objects.filter(pk=user_id).update(
            **{user_model._meta.pk.name: F("pk")}
        ):
            raise user_model.DoesNotExist
        yield user_model.objects.select_for_update().get(pk=user_id)


def _retry_write(operation):
    # Retrying a savepoint inside someone else's transaction cannot refresh its
    # SQLite snapshot. Only this executor's own whole transactions are retried.
    attempts = 1 if connection.in_atomic_block else 3
    for attempt in range(attempts):
        try:
            return operation()
        except OperationalError as exc:
            busy = connection.vendor == "sqlite" and any(
                marker in str(exc).lower() for marker in ("locked", "busy")
            )
            if not busy:
                raise
            if attempt == attempts - 1:
                raise ScheduleChanged() from exc
            time.sleep(0.02 * (attempt + 1))


def run_user_maintenance(user_id, mutate):
    """Explicit maintenance/policy entry point; callback receives locked User."""
    def operation():
        with user_write_lock(user_id) as user:
            return mutate(user)

    return _retry_write(operation)


def _block_state(blocks):
    # Include identities and exact times rather than the display payload, which
    # intentionally truncates seconds. Ordering is canonical for comparisons.
    return sorted(
        (
            b.pk, b.title, b.start_time, b.end_time, b.category,
            b.is_completed, b.sort_order, b.origin,
        )
        for b in blocks
    )


def _execute(
    user_id, schedule_id, expected_revision, mutate, *, maintenance, precondition, date=None
):
    def operation():
        with user_write_lock(user_id):
            query = Schedule.objects.select_for_update().filter(user_id=user_id)
            if schedule_id is None:
                if date is None:
                    raise ValueError("A date is required when creating a schedule.")
                query = query.filter(date=date)
            else:
                query = query.filter(pk=schedule_id)
            deferred_revision = callable(expected_revision)
            valid_revision = _valid_revision(expected_revision)
            cas = query
            if not maintenance and not deferred_revision:
                cas = cas.filter(revision=expected_revision) if valid_revision else cas.none()
            # CAS precedes reads. A no-op write reserves the version without
            # advancing it; the accepted state comparison decides the one bump.
            matched = cas.update(revision=F("revision"))
            try:
                schedule = query.get()
            except Schedule.DoesNotExist:
                if schedule_id is not None:
                    raise
                if expected_revision != 0 or not valid_revision:
                    raise ScheduleChanged()
                # The shared User lock makes first-day creation serial. Any
                # rejected callback rolls this row back along with its blocks.
                schedule = Schedule.objects.create(user_id=user_id, date=date)
                matched = 1
                query = Schedule.objects.select_for_update().filter(pk=schedule.pk)
            blocks = list(
                schedule.time_blocks.select_for_update().order_by("start_time", "sort_order", "id")
            )
            context = MutationContext(schedule, blocks)
            if precondition is not None:
                early_value = precondition(context)
                if early_value is not None:
                    if getattr(early_value, "status_code", 200) >= 400:
                        raise MutationRejected(early_value)
                    return MutationResult(
                        schedule, blocks, False, early_value,
                        serialize_schedule_snapshot(schedule, blocks),
                    )
            if deferred_revision:
                resolved_revision = expected_revision(context)
                valid_revision = _valid_revision(resolved_revision)
                matched = (
                    query.filter(revision=resolved_revision).update(revision=F("revision"))
                    if valid_revision else 0
                )
            if not maintenance and not matched:
                if not valid_revision:
                    raise ScheduleChanged(
                        "Schedule version is missing or invalid. Refresh the page."
                    )
                raise ScheduleChanged(snapshot=serialize_schedule_snapshot(schedule, blocks))
            before = (schedule.status, _block_state(blocks))
            value = mutate(context)
            if getattr(value, "status_code", 200) >= 400:
                raise MutationRejected(value)
            # Re-read inside the transaction to include bulk/conditional writes.
            schedule.refresh_from_db()
            blocks = list(schedule.time_blocks.order_by("start_time", "sort_order", "id"))
            changed = before != (schedule.status, _block_state(blocks))
            if changed:
                schedule.revision += 1
                schedule.updated_at = timezone.now()
                schedule.save(update_fields=["revision", "updated_at"])
            return MutationResult(
                schedule, blocks, changed, value, serialize_schedule_snapshot(schedule, blocks)
            )

    return _retry_write(operation)


def execute_schedule_mutation(
    user_id, schedule_id, expected_revision, mutate, *, precondition=None, date=None
):
    """Run an expected-version write; callbacks must be safe to retry in full.

    A read-only precondition may return a value to complete an idempotent
    operation before version checking (for example, an already-reviewed day).
    """
    return _execute(
        user_id, schedule_id, expected_revision, mutate,
        maintenance=False, precondition=precondition, date=date,
    )


def execute_schedule_maintenance(user_id, schedule_id, mutate):
    """Internal writer deliberately obtaining the latest version under lock."""
    return _execute(user_id, schedule_id, None, mutate, maintenance=True, precondition=None)
