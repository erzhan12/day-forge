from django.db import models


class DailyReview(models.Model):
    schedule = models.OneToOneField(
        "schedules.Schedule", related_name="daily_review", on_delete=models.CASCADE
    )
    planned_count = models.IntegerField(default=0)
    completed_count = models.IntegerField(default=0)
    skipped_count = models.IntegerField(default=0)
    # ``{category: minutes}`` maps. Sum of (end - start) per category across
    # all blocks. The ``completed_*`` variant is restricted to is_completed
    # blocks. Both default to ``{}`` so existing rows survive the
    # 0002_review_aggregates migration without back-fill.
    planned_minutes_by_category = models.JSONField(default=dict)
    completed_minutes_by_category = models.JSONField(default=dict)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    # Distinguishes "fresh recompute" rows (advances on every analytics_view
    # visit while the schedule is ``active``) from frozen review snapshots
    # (stable after Mark reviewed). Tested via ``test_analytics_views``
    # idempotency cases.
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def completion_rate(self) -> float | None:
        """Pure derived data — no DB column. Returns ``None`` when no blocks
        were planned (avoids a divide-by-zero ``0/0`` and lets callers
        distinguish "rest day" from "0% completed"). Lives on the model
        rather than in services.py to keep callers (admin, prompts,
        streak) free of service deps."""
        if self.planned_count == 0:
            return None
        return self.completed_count / self.planned_count

    def __str__(self):
        return f"{self.schedule.date}: {self.completed_count}/{self.planned_count}"
