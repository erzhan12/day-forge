from django.contrib import admin

from analytics.models import DailyReview


@admin.register(DailyReview)
class DailyReviewAdmin(admin.ModelAdmin):
    list_display = ("schedule", "planned_count", "completed_count", "skipped_count")
    list_select_related = ("schedule",)
