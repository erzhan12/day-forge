from django.db import models


class AIInteraction(models.Model):
    schedule = models.ForeignKey(
        "schedules.Schedule", related_name="ai_interactions", on_delete=models.CASCADE
    )
    user_command = models.TextField()
    ai_response = models.TextField()
    actions_json = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.schedule.date}: {self.user_command[:50]}"
