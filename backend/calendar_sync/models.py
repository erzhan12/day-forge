from django.conf import settings
from django.core.exceptions import ValidationError
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


class TravelRule(models.Model):
    """Per-user travel-time rule for the "add external event to schedule"
    flow (feature 0026). Keyword matches are case-insensitive substrings of
    event titles; calendar-only matches use a calendar name. Keyword rules
    take precedence, with ascending ``order`` within each class.

    Provider-agnostic (applies to CalDAV and Google events alike), hence
    it lives here rather than in ``gcal_sync``. No cache is keyed off
    ``updated_at``, so the ``auto_now`` cache footgun does not apply.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="travel_rules",
    )
    keyword = models.CharField(max_length=100, blank=True, default="")
    # Empty string means no calendar constraint for a keyword rule. A rule
    # with an empty keyword instead matches this source calendar exactly.
    calendar_name = models.CharField(max_length=200, blank=True, default="")
    travel_there_minutes = models.PositiveIntegerField(default=0)
    travel_back_minutes = models.PositiveIntegerField(default=0)
    # Empty string means "no override" — the created block falls back to
    # the ``other`` category.
    category = models.CharField(max_length=32, blank=True, default="")
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def clean(self) -> None:
        super().clean()
        if not (self.keyword or "").strip() and not (self.calendar_name or "").strip():
            raise ValidationError("At least one of keyword or calendar name is required.")

    def __str__(self) -> str:
        return (
            f"TravelRule(user={self.user_id}, keyword={self.keyword!r}, "
            f"calendar_name={self.calendar_name!r})"
        )
