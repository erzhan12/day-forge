from django.contrib import admin

from gcal_sync.models import GoogleCalendarAccount


@admin.register(GoogleCalendarAccount)
class GoogleCalendarAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "email", "last_verified_at", "access_token_expiry")
    list_select_related = ("user",)
    # Deliberately omit ``refresh_token_encrypted`` / ``access_token_encrypted``
    # from both ``fields`` and ``readonly_fields`` so the ciphertext is never
    # rendered. The admin is for ops visibility only — (re)connect goes through
    # the Settings UI (GET /api/calendar/google/connect/).
    readonly_fields = (
        "user",
        "google_account_id",
        "email",
        "last_verified_at",
        "access_token_expiry",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
