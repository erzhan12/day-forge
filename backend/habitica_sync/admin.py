from django.contrib import admin

from habitica_sync.models import HabiticaAccount


@admin.register(HabiticaAccount)
class HabiticaAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "api_user_id", "last_verified_at", "created_at", "updated_at")
    list_select_related = ("user",)
    # Deliberately omit ``api_token_encrypted`` from both ``fields`` and
    # ``readonly_fields`` so the ciphertext is never rendered. The admin
    # is for ops visibility only — token rotation goes through the
    # Settings UI (POST /api/habitica/account/).
    readonly_fields = (
        "user",
        "api_user_id",
        "last_verified_at",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
