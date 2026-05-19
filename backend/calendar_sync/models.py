from django.conf import settings
from django.db import models

from calendar_sync import crypto


class CalDAVAccount(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="caldav_account",
    )
    apple_id = models.EmailField()
    # Fernet ciphertext. Never serialised to JSON; never rendered in
    # __str__/__repr__; never exposed via the admin form (see admin.py).
    password_encrypted = models.BinaryField()
    base_url = models.URLField(default="https://caldav.icloud.com/")
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"CalDAVAccount(user={self.user_id}, apple_id={self.apple_id})"

    def get_password(self) -> str:
        """Decrypt and return the stored plaintext password.

        Called only from ``calendar_sync.service.fetch_events_for_date`` —
        the views never invoke this. See the plan's service-boundary note.
        """
        return crypto.decrypt_password(bytes(self.password_encrypted))

    def set_password(self, plaintext: str) -> None:
        """Encrypt ``plaintext`` and store on ``password_encrypted``.

        Caller must ``save()`` afterward. **auto_now footgun**: the cache
        is keyed by ``updated_at.isoformat()``, so any partial save that
        omits ``updated_at`` from ``update_fields`` will leave stale
        events readable. Either call ``account.save()`` with no
        ``update_fields`` (preferred) or include ``"updated_at"``
        explicitly.
        """
        self.password_encrypted = crypto.encrypt_password(plaintext)
