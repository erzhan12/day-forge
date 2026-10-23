import uuid

from django.conf import settings
from django.db import models


class ChatRequest(models.Model):
    """Durable chat identity, retained until its owner is deleted.

    The namespace is (owner, civil date, chat endpoint). Never prune completed
    rows and accept their UUIDs again: a replay could otherwise apply twice.
    No schedule FK: deleting/recreating a day must not erase its identities.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()
    request_id = models.UUIDField()
    body_hash = models.CharField(max_length=64)
    lease_token = models.UUIDField()
    lease_expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True)
    response_status = models.PositiveSmallIntegerField(null=True)
    # Full private HTTP body, retained with the identity until account deletion.
    # See docs/DURABLE_AI_CHAT_REQUESTS.md for retention and rollback constraints.
    response_body = models.TextField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "date", "request_id"), name="unique_chat_request_identity"
            ),
        ]


class PendingIntent(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        CANCELLED = "cancelled", "Cancelled"
        STALE = "stale", "Stale"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    schedule = models.ForeignKey("schedules.Schedule", on_delete=models.CASCADE)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN)
    version = models.PositiveIntegerField(default=1)
    revision = models.PositiveBigIntegerField()
    context_fingerprint = models.CharField(max_length=64)
    source_message = models.TextField()
    question = models.TextField()
    items = models.JSONField(default=list)
    accepted_changes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "schedule"),
                condition=models.Q(state="open"),
                name="one_open_intent_per_schedule",
            ),
        ]


class AIInteraction(models.Model):
    class Kind(models.TextChoices):
        # COMMAND is retained for historical rows written before the /command/
        # endpoint was removed (feature 0044); no new command rows are produced.
        COMMAND = "command", "Command"
        DRAFT = "draft", "Draft"
        CHAT = "chat", "Chat"

    schedule = models.ForeignKey(
        "schedules.Schedule", related_name="ai_interactions", on_delete=models.CASCADE
    )
    user_command = models.TextField()
    ai_response = models.TextField()
    actions_json = models.JSONField(default=list)
    # Execution outcomes are structured separately from the bounded raw model
    # response, which may be truncated for audit storage.
    outcomes_json = models.JSONField(null=True, default=None)
    # Pessimistic default: row is created before mutations apply, then
    # flipped to True only if apply succeeds. Lets audit dashboards query
    # failures without correlating against Django's application log.
    success = models.BooleanField(default=False)
    # Distinguishes chat interactions from auto/manual draft generations so
    # audit reports don't have to overload ``user_command`` (which is a
    # synthetic ``"[DRAFT]"`` placeholder for draft rows). Defaults to CHAT —
    # the only interactive producer since the /command/ endpoint was removed.
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CHAT)
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
