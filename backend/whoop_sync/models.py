from django.conf import settings
from django.db import models

from whoop_sync import crypto


class WhoopAccount(models.Model):
    """One connected WHOOP grant per user (feature 0107).

    Only the Fernet-encrypted tokens and their metadata are stored; WHOOP
    health data is never written here or anywhere else. Plaintext tokens are
    handled only by ``whoop_sync.service``. Deleting the row (admin) is the
    MVP disconnect; it does not revoke the grant at WHOOP.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="whoop_account",
    )
    # Fernet ciphertext. Never serialised, never rendered in __str__ or admin.
    refresh_token_encrypted = models.BinaryField()
    access_token_encrypted = models.BinaryField(null=True, blank=True)
    access_token_expiry = models.DateTimeField(null=True, blank=True)
    # Space-separated scopes WHOOP granted.
    scopes = models.CharField(max_length=255, blank=True, default="")
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"WhoopAccount(user={self.user_id})"

    __repr__ = __str__

    def get_refresh_token(self) -> str:
        """Service-boundary only (``whoop_sync.service``)."""
        return crypto.decrypt_token(bytes(self.refresh_token_encrypted))

    def set_refresh_token(self, plaintext: str) -> None:
        self.refresh_token_encrypted = crypto.encrypt_token(plaintext)

    def get_access_token(self) -> str | None:
        """Service-boundary only. ``None`` when no access token is cached."""
        if not self.access_token_encrypted:
            return None
        return crypto.decrypt_token(bytes(self.access_token_encrypted))

    def set_access_token(self, plaintext: str) -> None:
        self.access_token_encrypted = crypto.encrypt_token(plaintext)
