from django.contrib import admin

from ai.models import AIInteraction


@admin.register(AIInteraction)
class AIInteractionAdmin(admin.ModelAdmin):
    list_display = ("schedule", "short_command", "created_at")
    list_select_related = ("schedule",)
    readonly_fields = ("schedule", "user_command", "ai_response", "actions_json", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Command")
    def short_command(self, obj):
        return obj.user_command[:60]
