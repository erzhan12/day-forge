from django.contrib import admin

from templates_mgr.models import Rule, Template


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
