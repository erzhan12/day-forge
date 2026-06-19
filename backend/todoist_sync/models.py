from django.conf import settings
from django.db import models

from todoist_sync import crypto


class TodoistAccount(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="todoist_account",
    )
    # Fernet ciphertext. Never serialised to JSON; never rendered in
    # __str__/__repr__; never exposed via the admin form (see admin.py).
    token_encrypted = models.BinaryField()
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"TodoistAccount(user={self.user_id})"

    def get_token(self) -> str:
        """Decrypt and return the stored plaintext token.

        Called only from ``todoist_sync.service.fetch_tasks_for_date`` —
        the views never invoke this. See the plan's service-boundary note.
        """
        return crypto.decrypt_token(bytes(self.token_encrypted))

    def set_token(self, plaintext: str) -> None:
        """Encrypt ``plaintext`` and store on ``token_encrypted``.

        Caller must ``save()`` afterward. **auto_now footgun**: the cache
        is keyed by ``updated_at.isoformat()``, so any partial save that
        omits ``updated_at`` from ``update_fields`` will leave stale
        tasks readable. Either call ``account.save()`` with no
        ``update_fields`` (preferred) or include ``"updated_at"``
        explicitly.
        """
        self.token_encrypted = crypto.encrypt_token(plaintext)
