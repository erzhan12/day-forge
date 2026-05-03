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

    def mark_active_if_draft(self) -> bool:
        """Promote a freshly-drafted schedule to ``active`` on first user
        engagement. No-op when already ``active`` or ``reviewed``.

        Returns True if the status was flipped (caller may use this for
        logging / cache invalidation; the API layer ignores the return).

        Wiring rule: every **forward-mutating** schedule endpoint (create,
        update, delete, reorder, AI command with ≥1 action) calls this
        right before returning a 200. ``restore_blocks`` (the undo target)
        and ``ai_generate_draft`` are explicitly excluded — restoring is
        not a fresh edit, and a draft staying ``draft`` is the whole
        point of the badge.
        """
        if self.status == self.Status.DRAFT:
            self.status = self.Status.ACTIVE
            self.save(update_fields=["status"])
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
