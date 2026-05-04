from django.contrib import admin

from analytics.models import DailyReview


@admin.register(DailyReview)
class DailyReviewAdmin(admin.ModelAdmin):
    list_display = (
        "schedule",
        "planned_count",
        "completed_count",
        "skipped_count",
        "completion_rate_pct",
        "notes_excerpt",
        "updated_at",
    )
    list_select_related = ("schedule", "schedule__user")
    list_filter = ("schedule__user",)
    readonly_fields = (
        "schedule",
        "planned_count",
        "completed_count",
        "skipped_count",
        "planned_minutes_by_category",
        "completed_minutes_by_category",
        "created_at",
        "updated_at",
    )

    @admin.display(description="completion %")
    def completion_rate_pct(self, obj: DailyReview) -> str:
        rate = obj.completion_rate
        if rate is None:
            return "—"
        return f"{rate * 100:.0f}%"

    @admin.display(description="notes")
    def notes_excerpt(self, obj: DailyReview) -> str:
        if not obj.notes:
            return "—"
        return obj.notes[:80] + ("…" if len(obj.notes) > 80 else "")
