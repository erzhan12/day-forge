from django.contrib import admin
from django.db.models import Count

from schedules.models import Schedule, TimeBlock


class TimeBlockInline(admin.TabularInline):
    model = TimeBlock
    extra = 1
    fields = ("title", "start_time", "end_time", "category", "is_completed", "sort_order")


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("date", "status", "block_count")
    list_filter = ("status",)
    inlines = [TimeBlockInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_block_count=Count("time_blocks"))

    @admin.display(description="Blocks")
    def block_count(self, obj):
        return obj._block_count


@admin.register(TimeBlock)
class TimeBlockAdmin(admin.ModelAdmin):
    list_display = ("schedule", "title", "start_time", "end_time", "category", "is_completed")
    list_filter = ("category", "is_completed")
    list_select_related = ("schedule",)
