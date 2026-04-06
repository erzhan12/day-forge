from django.contrib import admin

from templates_mgr.models import Rule, Template


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "type")
    list_filter = ("type",)


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("short_text", "is_active", "priority")
    list_editable = ("is_active", "priority")

    @admin.display(description="Rule")
    def short_text(self, obj):
        return obj.text[:80]
