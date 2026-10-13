import datetime
import json

import pytest
from django.http import JsonResponse
from schedules.models import Schedule, TimeBlock
from schedules.mutations import (
    MutationRejected,
    ScheduleChanged,
    execute_schedule_maintenance,
    execute_schedule_mutation,
    parse_expected_revision,
    schedule_changed_response,
)


@pytest.mark.django_db
def test_mutation_bumps_once_and_captures_committed_state(schedule):
    def write(context):
        TimeBlock.objects.create(
            schedule=context.schedule, title="Focus", start_time="09:00", end_time="10:00"
        )
        context.schedule.mark_active_on_edit()
        return {"source": "manual"}

    result = execute_schedule_mutation(schedule.user_id, schedule.pk, 0, write)
    assert result.changed is True
    assert result.value == {"source": "manual"}
    assert result.snapshot["revision"] == 1
    assert result.snapshot["schedule"]["status"] == "active"
    assert result.snapshot["blocks"][0]["title"] == "Focus"
    # A subsequent writer cannot change the already captured response.
    execute_schedule_mutation(
        schedule.user_id, schedule.pk, 1,
        lambda context: context.schedule.time_blocks.update(title="Later"),
    )
    assert result.snapshot["revision"] == 1
    assert result.snapshot["blocks"][0]["title"] == "Focus"
    schedule.refresh_from_db()
    assert schedule.revision == 2


@pytest.mark.django_db
def test_noop_and_status_only_change(schedule):
    result = execute_schedule_mutation(schedule.user_id, schedule.pk, 0, lambda context: None)
    assert result.changed is False
    assert result.snapshot["revision"] == 0
    result = execute_schedule_mutation(
        schedule.user_id, schedule.pk, 0, lambda context: context.schedule.mark_active_on_edit()
    )
    assert result.changed is True
    assert result.snapshot["revision"] == 1
    result = execute_schedule_mutation(
        schedule.user_id, schedule.pk, 1, lambda context: context.schedule.mark_active_on_edit()
    )
    assert result.changed is False
    assert result.snapshot["revision"] == 1


@pytest.mark.django_db
def test_stale_request_never_calls_writer(schedule):
    execute_schedule_mutation(
        schedule.user_id, schedule.pk, 0, lambda context: context.schedule.mark_active_on_edit()
    )

    def rejected(context):
        pytest.fail("A stale request must not reach the callback")

    with pytest.raises(ScheduleChanged):
        execute_schedule_mutation(schedule.user_id, schedule.pk, 0, rejected)
    schedule.refresh_from_db()
    assert schedule.revision == 1


@pytest.mark.django_db
@pytest.mark.parametrize("fail_with_response", [False, True])
def test_callback_failure_rolls_back_blocks_status_and_revision(schedule, fail_with_response):
    def reject(context):
        TimeBlock.objects.create(
            schedule=context.schedule, title="Discard", start_time="09:00", end_time="10:00"
        )
        context.schedule.mark_active_on_edit()
        if fail_with_response:
            return JsonResponse({"errors": {"detail": "Rejected"}}, status=400)
        raise RuntimeError("status persistence failed")

    exception = MutationRejected if fail_with_response else RuntimeError
    with pytest.raises(exception):
        execute_schedule_mutation(schedule.user_id, schedule.pk, 0, reject)
    schedule.refresh_from_db()
    assert schedule.revision == 0
    assert schedule.status == "draft"
    assert not schedule.time_blocks.exists()


@pytest.mark.django_db
def test_maintenance_explicitly_uses_latest_revision(schedule):
    Schedule.objects.filter(pk=schedule.pk).update(revision=8)
    result = execute_schedule_maintenance(
        schedule.user_id, schedule.pk, lambda context: context.schedule.mark_active_on_edit()
    )
    assert result.snapshot["revision"] == 9


@pytest.mark.django_db
def test_idempotent_precondition_defers_revision_parse(schedule):
    Schedule.objects.filter(pk=schedule.pk).update(status="reviewed", revision=5)

    def parse(context):
        pytest.fail("An idempotent precondition must run before request parsing")

    result = execute_schedule_mutation(
        schedule.user_id, schedule.pk, parse, lambda context: pytest.fail("Already done"),
        precondition=lambda context: {"already_reviewed": True},
    )
    assert result.changed is False
    assert result.snapshot["revision"] == 5


@pytest.mark.parametrize("revision", [None, True, -1, "0", 1.0, [], {}, 2**100])
def test_invalid_revision_requires_refresh(revision):
    with pytest.raises(ScheduleChanged) as caught:
        parse_expected_revision({"expected_revision": revision})
    response = schedule_changed_response(caught.value)
    assert response.status_code == 409
    body = json.loads(response.content)
    assert body["code"] == "schedule_changed"
    assert "Refresh" in body["errors"]["detail"]


@pytest.mark.django_db
def test_stale_first_day_creation_leaves_no_row(user):
    with pytest.raises(ScheduleChanged):
        execute_schedule_mutation(
            user.pk, None, 1, lambda context: None, date=datetime.date(2026, 10, 10)
        )
    assert not Schedule.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_rejected_first_day_creation_leaves_no_row(user):
    with pytest.raises(MutationRejected):
        execute_schedule_mutation(
            user.pk, None, 0, lambda context: JsonResponse({}, status=400),
            date=datetime.date(2026, 10, 10),
        )
    assert not Schedule.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_first_day_creation_is_an_atomic_versioned_mutation(user):
    result = execute_schedule_mutation(
        user.pk, None, 0, lambda context: context.schedule.mark_active_on_edit(),
        date=datetime.date(2026, 10, 10),
    )
    assert result.snapshot["revision"] == 1
    assert Schedule.objects.get(user=user).status == "active"


@pytest.mark.django_db
def test_category_remapping_bumps_only_affected_days(user):
    from schedules.categories import delete_category, ordered_categories

    catalog = ordered_categories(user)
    target = next(row for row in catalog if row.slug == "work")
    affected = Schedule.objects.create(user=user, date=datetime.date(2026, 10, 9), revision=3)
    unchanged = Schedule.objects.create(user=user, date=datetime.date(2026, 10, 10), revision=7)
    TimeBlock.objects.create(
        schedule=affected, title="Work", start_time="09:00", end_time="10:00", category="work"
    )
    TimeBlock.objects.create(
        schedule=affected, title="More work", start_time="10:00", end_time="11:00", category="work"
    )
    TimeBlock.objects.create(
        schedule=unchanged, title="Other", start_time="09:00", end_time="10:00", category="other"
    )
    delete_category(user, target)
    affected.refresh_from_db()
    unchanged.refresh_from_db()
    assert affected.revision == 4
    assert unchanged.revision == 7
    assert set(affected.time_blocks.values_list("category", flat=True)) == {"other"}
