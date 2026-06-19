from django.contrib import admin

from todoist_sync.models import TodoistAccount


@admin.register(TodoistAccount)
class TodoistAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "last_verified_at", "created_at", "updated_at")
    list_select_related = ("user",)
    # Deliberately omit ``token_encrypted`` from both ``fields`` and
    # ``readonly_fields`` so the ciphertext is never rendered. The admin
    # is for ops visibility only — token rotation goes through the
    # Settings UI (POST /api/todoist/account/).
    readonly_fields = ("user", "last_verified_at", "created_at", "updated_at")
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
