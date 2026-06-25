from django.conf import settings
from django.db import models

from gcal_sync import crypto


class GoogleCalendarAccount(models.Model):
    """A single connected Google account for a user.

    The central divergence from ``CalDAVAccount`` / ``TodoistAccount`` is
    that this is **multi-row per user** (``ForeignKey``, not ``OneToOne``):
    a user can connect several Google accounts and the merged panel renders
    all of them. The ``(user, google_account_id)`` uniqueness constraint
    makes reconnecting the same Google account **update** the existing row
    instead of duplicating.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_calendar_accounts",
    )
    # Google's stable account identifier (``sub`` from the ID token /
    # ``id`` from the userinfo endpoint). The upsert key.
    google_account_id = models.CharField(max_length=255)
    # The connected Google account email; doubles as the panel account label.
    email = models.EmailField()
    # Fernet ciphertext. Never serialised to JSON; never rendered in
    # __str__/__repr__; never exposed via the admin form (see admin.py).
    refresh_token_encrypted = models.BinaryField()
    # Cached access token (Fernet ciphertext) + its UTC expiry, so the
    # common path skips the token-endpoint refresh round-trip.
    access_token_encrypted = models.BinaryField(null=True, blank=True)
    access_token_expiry = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Drives the cache-key version (same auto_now footgun as CalDAV/Todoist:
    # any partial ``save(update_fields=...)`` omitting ``updated_at`` leaves
    # stale events readable; prefer plain ``save()``).
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "google_account_id"],
                name="uniq_user_google_account",
            )
        ]

    def __str__(self) -> str:
        # Never leaks any token.
        return f"GoogleCalendarAccount(user={self.user_id}, email={self.email})"

    def get_refresh_token(self) -> str:
        """Decrypt and return the stored plaintext refresh token.

        Called only from ``gcal_sync.service._ensure_access_token`` — the
        views never invoke this. See the plan's service-boundary note.
        """
        return crypto.decrypt_token(bytes(self.refresh_token_encrypted))

    def set_refresh_token(self, plaintext: str) -> None:
        """Encrypt ``plaintext`` and store on ``refresh_token_encrypted``.

        Caller must ``save()`` afterward. **auto_now footgun**: the cache
        is keyed by ``updated_at.isoformat()``, so any partial save that
        omits ``updated_at`` from ``update_fields`` will leave stale events
        readable. Either call ``account.save()`` with no ``update_fields``
        (preferred) or include ``"updated_at"`` explicitly.
        """
        self.refresh_token_encrypted = crypto.encrypt_token(plaintext)

    def get_access_token(self) -> str | None:
        """Decrypt and return the cached plaintext access token, or ``None``.

        Service-boundary only (``_ensure_access_token`` /
        ``_persist_refreshed_tokens``); views never call this.
        """
        if not self.access_token_encrypted:
            return None
        return crypto.decrypt_token(bytes(self.access_token_encrypted))

    def set_access_token(self, plaintext: str) -> None:
        """Encrypt ``plaintext`` and store on ``access_token_encrypted``.

        Same caller-must-save / auto_now footgun as ``set_refresh_token``.
        """
        self.access_token_encrypted = crypto.encrypt_token(plaintext)
