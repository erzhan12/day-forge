from django.db import models


class AIInteraction(models.Model):
    class Kind(models.TextChoices):
        COMMAND = "command", "Command"
        DRAFT = "draft", "Draft"

    schedule = models.ForeignKey(
        "schedules.Schedule", related_name="ai_interactions", on_delete=models.CASCADE
    )
    user_command = models.TextField()
    ai_response = models.TextField()
    actions_json = models.JSONField(default=list)
    # Pessimistic default: row is created before mutations apply, then
    # flipped to True only if apply succeeds. Lets audit dashboards query
    # failures without correlating against Django's application log.
    success = models.BooleanField(default=False)
    # Distinguishes user-issued commands from auto/manual draft generations
    # so audit reports don't have to overload ``user_command`` (which is a
    # synthetic ``"[DRAFT]"`` placeholder for draft rows).
    kind = models.CharField(
        max_length=10, choices=Kind.choices, default=Kind.COMMAND
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["schedule", "-created_at"],
                name="ai_interact_sched_created_idx",
            ),
        ]

    def __str__(self):
        return f"{self.schedule.date}: {self.user_command[:50]}"
