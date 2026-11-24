from django.contrib import admin

from whoop_sync.models import WhoopAccount


@admin.register(WhoopAccount)
class WhoopAccountAdmin(admin.ModelAdmin):
    """Ops visibility plus delete-to-disconnect (feature 0107, D4).

    The ciphertext fields are deliberately absent from ``fields`` and
    ``readonly_fields`` so they are never rendered. Connect goes through
    ``/api/whoop/connect/``; deleting a row does not revoke the WHOOP grant.
    """

    list_display = ("user", "scopes", "last_verified_at", "access_token_expiry")
    list_select_related = ("user",)
    readonly_fields = (
        "user",
        "scopes",
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
