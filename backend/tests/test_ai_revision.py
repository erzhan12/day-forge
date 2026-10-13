"""Revision and prompt-policy boundaries for AI and frozen review writes."""

import json

import pytest
from ai.models import AIInteraction
from ai.service import AIChatResult, AIDraftResult
from analytics.models import DailyReview
from asgiref.sync import sync_to_async
from django.test import Client
from schedules.models import Category, Schedule, TimeBlock, UserScheduleSettings
from schedules.mutations import execute_schedule_mutation
from templates_mgr.models import Rule, Template

CHAT = "/api/ai/schedules/2026-04-18/chat/"
DRAFT = "/api/ai/schedules/2026-04-18/generate-draft/"
REVIEW = "/api/analytics/schedules/2026-04-18/mark-reviewed/"


@pytest.fixture
def revision_client(user):
    client = Client()
    client.force_login(user)
    return client


def post(client, url, body):
    return client.post(url, json.dumps(body), content_type="application/json")


def draft_template(user):
    return Template.objects.create(user=user, name="Weekend", type="weekend", blocks=[])


def result(draft=False):
    actions = [
        {
            "type": "add",
            "title": "Work",
            "category": "work",
            "start_time": "09:00",
            "end_time": "10:00",
        }
    ]
    return (
        AIDraftResult("{}", actions, "Ready")
        if draft
        else AIChatResult("{}", actions, "Ready", None)
    )


@pytest.mark.django_db
@pytest.mark.parametrize("url", [CHAT, DRAFT, REVIEW])
@pytest.mark.parametrize("revision", [None, True, -1, "0", 0.5])
def test_ai_and_active_review_require_valid_revision(user, revision_client, url, revision):
    schedule = Schedule.objects.create(user=user, date="2026-04-18", status="active")
    body = {"messages": [{"role": "user", "content": "Add work"}]}
    if revision is not None:
        body["expected_revision"] = revision
    response = post(revision_client, url, body)
    assert response.status_code == 409
    assert response.json()["code"] == "schedule_changed"
    assert "Refresh" in response.json()["errors"]["detail"]
    schedule.refresh_from_db()
    assert schedule.revision == 0
    assert schedule.status == "active"
    assert not TimeBlock.objects.exists()
    assert not AIInteraction.objects.exists()
    assert not DailyReview.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("draft", [False, True])
@pytest.mark.parametrize("policy", ["rule", "window", "timezone", "category"])
def test_ai_rejects_prompt_policy_changes(user, revision_client, monkeypatch, draft, policy):
    schedule = Schedule.objects.create(user=user, date="2026-04-18")
    draft_template(user)
    rule = Rule.objects.create(user=user, text="Original", priority=1)

    def change_policy():
        if policy == "rule":
            Rule.objects.filter(pk=rule.pk).update(text="Changed")
        elif policy == "window":
            UserScheduleSettings.objects.filter(user=user).update(day_end="22:00")
        elif policy == "timezone":
            UserScheduleSettings.objects.filter(user=user).update(time_zone="Asia/Almaty")
        else:
            Category.objects.filter(user=user, slug="work").update(label="Changed")

    async def run(*args):
        await sync_to_async(change_policy, thread_sensitive=True)()
        return result(draft)

    monkeypatch.setattr("ai.views.run_draft" if draft else "ai.views.run_chat", run)
    body = {"expected_revision": 0, "messages": [{"role": "user", "content": "Add work"}]}
    response = post(revision_client, DRAFT if draft else CHAT, body)
    assert response.status_code == 409, response.content
    assert response.json()["code"] == "schedule_changed"
    schedule.refresh_from_db()
    assert schedule.revision == 0
    assert not TimeBlock.objects.exists()
    assert not AIInteraction.objects.get().success


@pytest.mark.django_db
def test_draft_rejects_template_changed_during_provider(user, revision_client, monkeypatch):
    schedule = Schedule.objects.create(user=user, date="2026-04-18")
    template = draft_template(user)

    async def run(*args):
        await sync_to_async(Template.objects.filter(pk=template.pk).update)(name="Changed")
        return result(True)

    monkeypatch.setattr("ai.views.run_draft", run)
    response = post(revision_client, DRAFT, {"expected_revision": 0})
    assert response.status_code == 409
    schedule.refresh_from_db()
    assert schedule.revision == 0
    assert not TimeBlock.objects.exists()


@pytest.mark.django_db
def test_draft_rejects_concurrent_create_with_expected_revision(user, revision_client, monkeypatch):
    schedule = Schedule.objects.create(user=user, date="2026-04-18")
    draft_template(user)

    def create(ctx):
        TimeBlock.objects.create(
            schedule=ctx.schedule,
            title="Concurrent",
            category="work",
            start_time="11:00",
            end_time="12:00",
        )
        ctx.schedule.mark_active_on_edit()

    async def run(*args):
        await sync_to_async(execute_schedule_mutation, thread_sensitive=True)(
            user.pk, schedule.pk, 0, create
        )
        return result(True)

    monkeypatch.setattr("ai.views.run_draft", run)
    response = post(revision_client, DRAFT, {"expected_revision": 0})
    assert response.status_code == 409
    schedule.refresh_from_db()
    assert schedule.revision == 1
    assert list(TimeBlock.objects.values_list("title", flat=True)) == ["Concurrent"]


@pytest.mark.django_db
@pytest.mark.parametrize("draft", [False, True])
def test_ai_response_snapshot_precedes_later_audit_boundary_write(
    user, revision_client, monkeypatch, draft
):
    schedule = Schedule.objects.create(user=user, date="2026-04-18")
    draft_template(user)

    async def run(*args):
        return result(draft)

    def rename(ctx):
        TimeBlock.objects.filter(schedule=ctx.schedule).update(title="Later edit")

    async def mark_success(*args):
        await sync_to_async(execute_schedule_mutation, thread_sensitive=True)(
            user.pk, schedule.pk, 1, rename
        )

    monkeypatch.setattr("ai.views.run_draft" if draft else "ai.views.run_chat", run)
    monkeypatch.setattr("ai.views._mark_success", mark_success)
    response = post(
        revision_client,
        DRAFT if draft else CHAT,
        {"expected_revision": 0, "messages": [{"role": "user", "content": "Add work"}]},
    )
    assert response.status_code == 200, response.content
    assert response.json()["revision"] == response.json()["schedule"]["revision"] == 1
    assert response.json()["blocks"][0]["title"] == "Work"
    schedule.refresh_from_db()
    assert schedule.revision == 2
    assert TimeBlock.objects.get().title == "Later edit"


@pytest.mark.django_db
def test_review_revision_retry_and_notes(user, revision_client):
    schedule = Schedule.objects.create(user=user, date="2026-04-18", status="active")
    first = post(revision_client, REVIEW, {"expected_revision": 0, "notes": "Original"})
    retry = revision_client.post(REVIEW, "{", content_type="application/json")
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert first.json()["revision"] == 1
    review = DailyReview.objects.get(schedule=schedule)
    notes = revision_client.patch(
        f"/api/analytics/reviews/{review.pk}/notes/",
        json.dumps({"notes": "Changed"}),
        content_type="application/json",
    )
    assert notes.status_code == 200
    schedule.refresh_from_db()
    assert schedule.revision == 1


@pytest.mark.django_db
def test_review_failure_rolls_back_review_status_and_revision(user, revision_client, monkeypatch):
    schedule = Schedule.objects.create(user=user, date="2026-04-18", status="active")
    original = Schedule.mark_reviewed_if_active

    def fail(instance):
        original(instance)
        raise RuntimeError("status save failed")

    monkeypatch.setattr(Schedule, "mark_reviewed_if_active", fail)
    with pytest.raises(RuntimeError, match="status save failed"):
        post(revision_client, REVIEW, {"expected_revision": 0})
    schedule.refresh_from_db()
    assert schedule.status == "active"
    assert schedule.revision == 0
    assert not DailyReview.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("url", [CHAT, DRAFT])
@pytest.mark.parametrize("revision", [None, 1, True])
def test_ai_conflict_on_absent_day_does_not_create_any_context(
    user, revision_client, url, revision
):
    body = {"messages": [{"role": "user", "content": "Hi"}]}
    if revision is not None:
        body["expected_revision"] = revision
    response = post(revision_client, url, body)
    assert response.status_code == 409
    assert not Schedule.objects.filter(user=user).exists()
    assert not UserScheduleSettings.objects.filter(user=user).exists()
    assert not Category.objects.filter(user=user).exists()
    assert not AIInteraction.objects.exists()
