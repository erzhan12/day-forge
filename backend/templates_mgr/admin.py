from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from templates_mgr.models import Rule, Template, UserPreferences


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "user")
    list_filter = ("type", "user")


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("short_text", "is_active", "priority", "user")
    list_filter = ("user",)
    list_editable = ("is_active", "priority")

    @admin.display(description="Rule")
    def short_text(self, obj):
        return obj.text[:80]


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ("user", "theme")
    list_filter = ("theme",)
    search_fields = ("user__username",)
    readonly_fields = ("created_at", "updated_at")


class UserPreferencesInline(admin.StackedInline):
    """Inline preferences on the User admin so staff can find a user's
    theme where they intuitively look — under Users, not Templates."""

    model = UserPreferences
    can_delete = False
    readonly_fields = ("created_at", "updated_at")


# Re-register the User admin with the preferences inline. Done at import
# time so the inline shows up for any staff user.
User = get_user_model()


class UserAdminWithPreferences(UserAdmin):
    inlines = list(UserAdmin.inlines) + [UserPreferencesInline]


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, UserAdminWithPreferences)
