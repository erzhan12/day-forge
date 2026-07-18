from django.contrib import admin

from calendar_sync.models import CalDAVAccount, TravelRule


@admin.register(CalDAVAccount)
class CalDAVAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "apple_id", "base_url", "last_verified_at")
    list_select_related = ("user",)
    # Deliberately omit ``password_encrypted`` from both ``fields`` and
    # ``readonly_fields`` so the ciphertext is never rendered. The admin
    # is for ops visibility only — password rotation goes through the
    # Settings UI (POST /api/calendar/account/).
    readonly_fields = ("user", "apple_id", "base_url", "last_verified_at",
                       "created_at", "updated_at")
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TravelRule)
class TravelRuleAdmin(admin.ModelAdmin):
    list_display = (
        "user", "keyword", "travel_there_minutes", "travel_back_minutes",
        "category", "order",
    )
    list_select_related = ("user",)
    ordering = ("user", "order", "id")
