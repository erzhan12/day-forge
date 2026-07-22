from django.conf import settings
from django.db import models

from habitica_sync import crypto


class HabiticaAccount(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="habitica_account",
    )
    api_user_id = models.CharField(max_length=128)
    # Fernet ciphertext. Never serialised to JSON; never rendered in
    # __str__/__repr__; never exposed via the admin form (see admin.py).
    api_token_encrypted = models.BinaryField()
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"HabiticaAccount(user={self.user_id}, api_user_id={self.api_user_id})"

    def get_token(self) -> str:
        """Decrypt and return the stored plaintext token.

        Called only from ``habitica_sync.service.fetch_tasks_for_date`` and
        ``habitica_sync.service.complete_task``; views never invoke this.
        """
        return crypto.decrypt_token(bytes(self.api_token_encrypted))

    def set_token(self, plaintext: str) -> None:
        """Encrypt ``plaintext`` and store on ``api_token_encrypted``.

        Caller must ``save()`` afterward. **auto_now footgun**: the cache
        is keyed by ``updated_at.isoformat()``, so any partial save that
        omits ``updated_at`` from ``update_fields`` will leave stale
        tasks readable. Either call ``account.save()`` with no
        ``update_fields`` (preferred) or include ``"updated_at"``
        explicitly.
        """
        self.api_token_encrypted = crypto.encrypt_token(plaintext)
