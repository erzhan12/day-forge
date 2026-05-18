from django.conf import settings
from django.db import models


class UserPreferences(models.Model):
    """Per-user UI preferences (theme, future settings).

    Co-located in ``templates_mgr`` for v1 since there is no dedicated
    users/preferences app and `/settings/` already routes here. If
    preferences grow beyond UI theme, split into a dedicated app (see
    feature 0010 plan for the cleanup path).

    Schema notes:
      * ``user`` is a ``OneToOneField`` which Django implements as a
        ``ForeignKey`` with ``unique=True``. The unique constraint
        creates an implicit index — no explicit ``db_index=True`` or
        ``UniqueConstraint`` is needed (would be a no-op duplicate).
    """

    class Theme(models.TextChoices):
        # SYNC ALERT: when adding/renaming a theme id, also update
        # `frontend/src/types/index.ts:ThemeId` and the registry in
        # `frontend/src/utils/themes.ts`.
        CLASSIC = "classic", "Classic"
        STRATEGIC = "strategic", "Strategic"
        LIGHT_PREMIUM = "light_premium", "Light Premium"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    # max_length=32 leaves headroom for future theme ids without a schema
    # migration; the longest current value (light_premium) is 13 chars.
    theme = models.CharField(
        max_length=32, choices=Theme.choices, default=Theme.CLASSIC
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User preferences"
        verbose_name_plural = "User preferences"

    def __str__(self):
        return f"{self.user} preferences"


class Template(models.Model):
    class Type(models.TextChoices):
        WEEKDAY = "weekday", "Weekday"
        WEEKEND = "weekend", "Weekend"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="templates",
    )
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=10, choices=Type.choices)
    blocks = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "type"], name="unique_user_template_type"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.type})"

    @classmethod
    def slot_type_for_date(cls, d) -> str:
        """Map a calendar date to its template slot type.

        ``datetime.date.weekday()`` returns Monday=0..Sunday=6, so values
        5 and 6 are Saturday and Sunday respectively (NOT to be confused
        with ``isoweekday()`` which uses Monday=1..Sunday=7).

        Used by ``schedules.views.schedule_view`` and
        ``ai.views.ai_generate_draft`` so the weekday/weekend split is
        defined in exactly one place.
        """
        return cls.Type.WEEKEND if d.weekday() >= 5 else cls.Type.WEEKDAY


class Rule(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rules",
    )
    text = models.TextField()
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-priority"]

    def __str__(self):
        return self.text[:80]
