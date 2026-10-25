from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from templates_mgr.models import Rule, Template, UserPreferences


class PolicyInspectionMixin:
    """Inspect AI policy; account Settings owns serialized policy writes."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PolicyInspectionAdmin(PolicyInspectionMixin, admin.ModelAdmin):
    pass


@admin.register(Template)
class TemplateAdmin(PolicyInspectionAdmin):
    list_display = ("name", "type", "user")
    list_filter = ("type", "user")


@admin.register(Rule)
class RuleAdmin(PolicyInspectionAdmin):
    list_display = ("short_text", "is_active", "priority", "user")
    list_filter = ("user",)

    @admin.display(description="Rule")
    def short_text(self, obj):
        return obj.text[:80]


@admin.register(UserPreferences)
class UserPreferencesAdmin(PolicyInspectionAdmin):
    list_display = ("user", "theme", "default_block_gap_minutes")
    list_filter = ("theme",)
    search_fields = ("user__username",)
    readonly_fields = ("created_at", "updated_at")


class UserPreferencesInline(PolicyInspectionMixin, admin.StackedInline):
    """Inspect preferences under Users; Settings owns policy writes."""

    model = UserPreferences
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "updated_at")


# Re-register the User admin with the preferences inline. Done at import
# time so the inline shows up for any staff user.
User = get_user_model()


class UserAdminWithPreferences(UserAdmin):
    inlines = UserAdmin.inlines + (UserPreferencesInline,)


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, UserAdminWithPreferences)
