import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from schedules.validators import validate_five_minute_granularity


class Schedule(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        REVIEWED = "reviewed", "Reviewed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_user_date"),
        ]

    def __str__(self):
        return f"{self.date} ({self.status})"

    def mark_active_on_edit(self) -> bool:
        """Promote a schedule to ``active`` on a forward-mutating edit.

        Flips ``draft → active`` (first user engagement after auto-draft)
        OR ``reviewed → active`` (any edit on a reviewed day unfreezes
        the analytics snapshot). No-op when already ``active``.

        Returns True if the status was flipped.

        Wiring rule: every **forward-mutating** schedule endpoint (create,
        update, delete, reorder, AI command with ≥1 action) calls this
        right before returning a 200. ``restore_blocks`` (the undo target)
        and ``ai_generate_draft`` are explicitly excluded — restoring is
        not a fresh edit, and a draft staying ``draft`` is the whole
        point of the badge.

        **Implementation must be a DB-conditional UPDATE, not a
        Python-side check on ``self.status``.** During Phase 6 a
        concurrent ``mark_reviewed`` may have flipped the row to
        ``reviewed`` between the time this instance was loaded and the
        time we're called — the in-memory ``self.status`` would still
        say ``active`` and a Python-side guard would short-circuit the
        flip, leaving the DB row frozen-reviewed with stale snapshot
        data. The conditional UPDATE evaluates its WHERE clause against
        the current DB state at lock-acquisition time, so it correctly
        re-flips the row regardless of what the Python instance thinks.
        """
        updated = type(self).objects.filter(
            pk=self.pk,
            status__in=[self.Status.DRAFT, self.Status.REVIEWED],
        ).update(status=self.Status.ACTIVE)
        if updated:
            # Sync in-memory copy so any caller that re-reads ``self.status``
            # without a refetch sees the new value.
            self.status = self.Status.ACTIVE
            return True
        return False

    def mark_reviewed_if_active(self) -> bool:
        """Flip ``active → reviewed`` to freeze the analytics snapshot.

        Refuses on ``draft`` (a never-edited day cannot be reviewed —
        analytics would be meaningless on auto-draft data the user never
        touched) and is a no-op on already-reviewed.

        Symmetric with ``mark_active_on_edit``: also a DB-conditional
        UPDATE for consistency. Although mark_reviewed's caller holds
        ``select_for_update`` so staleness isn't a risk here in practice,
        keeping a single transition pattern across both helpers reduces
        cognitive load and prevents future call sites from accidentally
        bypassing the lock.
        """
        updated = type(self).objects.filter(
            pk=self.pk,
            status=self.Status.ACTIVE,
        ).update(status=self.Status.REVIEWED)
        if updated:
            self.status = self.Status.REVIEWED
            return True
        return False


class TimeBlock(models.Model):
    class Category(models.TextChoices):
        WORK = "work", "Work"
        PERSONAL = "personal", "Personal"
        HEALTH = "health", "Health"
        OTHER = "other", "Other"

    schedule = models.ForeignKey(Schedule, related_name="time_blocks", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    start_time = models.TimeField(validators=[validate_five_minute_granularity])
    end_time = models.TimeField(validators=[validate_five_minute_granularity])
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.OTHER)
    is_completed = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_time", "sort_order"]
        indexes = [
            models.Index(fields=["schedule", "start_time", "end_time", "sort_order"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.start_time}-{self.end_time})"

    def clean(self):
        super().clean()
        if (
            self.start_time
            and self.end_time
            and isinstance(self.start_time, datetime.time)
            and isinstance(self.end_time, datetime.time)
            and self.start_time >= self.end_time
        ):
            raise ValidationError("start_time must be before end_time.")
