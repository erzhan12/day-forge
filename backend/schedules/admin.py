from django.contrib import admin
from django.db.models import Count

from schedules.models import Schedule, TimeBlock, UserScheduleSettings


class ScheduleInspectionOnly:
    """Day writes require revision validation through the scheduling API."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class TimeBlockInline(ScheduleInspectionOnly, admin.TabularInline):
    model = TimeBlock
    extra = 0
    fields = ("title", "start_time", "end_time", "category", "is_completed", "sort_order")


@admin.register(Schedule)
class ScheduleAdmin(ScheduleInspectionOnly, admin.ModelAdmin):
    list_display = ("date", "status", "revision", "block_count")
    list_filter = ("status",)
    inlines = [TimeBlockInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_block_count=Count("time_blocks"))

    @admin.display(description="Blocks")
    def block_count(self, obj):
        return obj._block_count


@admin.register(TimeBlock)
class TimeBlockAdmin(ScheduleInspectionOnly, admin.ModelAdmin):
    list_display = ("schedule", "title", "start_time", "end_time", "category", "is_completed")
    list_filter = ("category", "is_completed")
    list_select_related = ("schedule",)


@admin.register(UserScheduleSettings)
class UserScheduleSettingsAdmin(ScheduleInspectionOnly, admin.ModelAdmin):
    list_display = ("user", "day_start", "day_end", "updated_at")
    list_select_related = ("user",)
