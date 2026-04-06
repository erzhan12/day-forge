from django.db import models


class DailyReview(models.Model):
    schedule = models.OneToOneField(
        "schedules.Schedule", related_name="daily_review", on_delete=models.CASCADE
    )
    planned_count = models.IntegerField(default=0)
    completed_count = models.IntegerField(default=0)
    skipped_count = models.IntegerField(default=0)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.schedule.date}: {self.completed_count}/{self.planned_count}"
