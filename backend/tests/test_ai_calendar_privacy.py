"""Calendar provenance survives writes and never contributes a title to SDK context."""

import datetime
import json
from types import SimpleNamespace

import pytest
from ai.service import AIChatResult, run_chat, run_draft
from asgiref.sync import async_to_sync
from schedules.models import Schedule, TimeBlock
from schedules.serialization import serialize_block
from templates_mgr.models import Template

pytestmark = pytest.mark.django_db


class CapturingCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content = (
            {"actions": [], "explanation": "ok", "ask": None}
            if len(kwargs["messages"]) == 3
            else {"actions": [], "explanation": "ok"}
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))]
        )


@pytest.fixture
def sdk(monkeypatch, settings):
    completions = CapturingCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr("ai.service._get_client", lambda: client)
    settings.LLM_API_KEY = "test-key"
    return completions


def post(client, path, **body):
    return client.post(path, json.dumps(body), content_type="application/json")


def imported_block(auth_client, date, title):
    response = post(
        auth_client,
        f"/api/schedules/{date}/blocks/from-event/",
        title=title,
        start_time="09:07",
        end_time="09:43",
        category="work",
        origin="manual",
    )
    assert response.status_code == 201
    block = TimeBlock.objects.get(pk=response.json()["id"])
    assert block.origin == TimeBlock.Origin.CALENDAR
    return block, response.json()


def test_client_origin_field_cannot_reclassify_import_or_manual_create(auth_client):
    imported, _ = imported_block(auth_client, "2026-04-18", "Imported")
    response = post(
        auth_client,
        "/api/schedules/2026-04-18/blocks/",
        title="Typed by user",
        start_time="10:00",
        end_time="10:30",
        category="work",
        origin="calendar",
    )
    assert response.status_code == 201
    assert imported.origin == TimeBlock.Origin.CALENDAR
    assert TimeBlock.objects.get(pk=response.json()["id"]).origin == TimeBlock.Origin.MANUAL


def sdk_text(call):
    return "\n".join(message["content"] for message in call["messages"])


def test_imported_title_is_absent_from_chat_context_and_echoed_transcript(
    auth_client, sdk, user
):
    title = 'Secret "visit"\nnext line'
    block, payload = imported_block(auth_client, "2026-04-18", title)
    assert payload["restore_proof"]
    manual = TimeBlock.objects.create(
        schedule=block.schedule,
        title="My own work",
        start_time=datetime.time(10, 0),
        end_time=datetime.time(10, 30),
        category="work",
    )
    messages = [
        {"role": "user", "content": "What about the morning?"},
        {"role": "assistant", "content": f"I see {title}."},
        {"role": "user", "content": f"Move {title} after {manual.title}."},
    ]
    result = async_to_sync(run_chat)(
        messages,
        block.schedule,
        [block, manual],
        [],
        datetime.datetime(2026, 4, 18, 8, 0),
    )
    assert result.parsed_actions == []
    sent = sdk_text(sdk.calls[-1])
    assert title not in sent
    assert "Secret" not in sent
    assert "[private block]" in sent
    assert "My own work" in sent
    assert "09:07-09:43" in sent
    assert messages[-1]["content"] == f"Move {title} after {manual.title}."


def test_imported_title_is_absent_from_draft_history(auth_client, sdk, user):
    block, _ = imported_block(auth_client, "2026-04-18", "Private imported title")
    block.schedule.status = Schedule.Status.ACTIVE
    block.schedule.save(update_fields=["status"])
    TimeBlock.objects.create(
        schedule=block.schedule,
        title="User-written task",
        start_time=datetime.time(10, 0),
        end_time=datetime.time(10, 30),
        category="work",
    )
    target = Schedule.objects.create(user=user, date=datetime.date(2026, 4, 19))
    template = Template.objects.create(user=user, name="Morning", type="weekend", blocks=[])
    past = (
        Schedule.objects.select_related("daily_review")
        .prefetch_related("time_blocks")
        .get(pk=block.schedule_id)
    )
    result = async_to_sync(run_draft)(
        target,
        template,
        [past],
        [],
        datetime.datetime(2026, 4, 19, 8, 0),
    )
    assert result.parsed_actions == []
    sent = sdk_text(sdk.calls[-1])
    assert "Private imported title" not in sent
    assert "[private block]" in sent
    assert "User-written task" in sent


def test_manual_block_with_same_title_remains_visible_in_context(auth_client, sdk):
    imported, _ = imported_block(auth_client, "2026-04-18", "Shared title")
    manual = TimeBlock.objects.create(
        schedule=imported.schedule,
        title="Shared title",
        start_time=datetime.time(10, 0),
        end_time=datetime.time(10, 30),
        category="work",
    )
    async_to_sync(run_chat)(
        [{"role": "user", "content": "Plan the day"}],
        imported.schedule,
        [imported, manual],
        [],
        datetime.datetime(2026, 4, 18, 8, 0),
    )
    context = sdk.calls[-1]["messages"][1]["content"]
    assert context.count('title="Shared title"') == 1
    assert context.count('title="[private block]"') == 1


def test_restore_proof_preserves_import_after_delete_and_rejects_tampering(
    auth_client, sdk
):
    block, payload = imported_block(auth_client, "2026-04-18", "Appointment source")
    original = serialize_block(block)
    response = auth_client.delete(f"/api/blocks/{block.id}/")
    assert response.status_code == 200
    assert not TimeBlock.objects.filter(pk=block.id).exists()

    bad = {**original, "title": "Changed title"}
    response = post(
        auth_client,
        "/api/schedules/2026-04-18/blocks/restore/",
        blocks=[bad],
    )
    assert response.status_code == 400
    wrong_id = {**original, "id": original["id"] + 1000}
    response = post(
        auth_client,
        "/api/schedules/2026-04-18/blocks/restore/",
        blocks=[wrong_id],
    )
    assert response.status_code == 400
    response = post(
        auth_client,
        "/api/schedules/2026-04-18/blocks/restore/",
        blocks=[original],
    )
    assert response.status_code == 200
    restored = TimeBlock.objects.get(schedule=block.schedule)
    assert restored.origin == TimeBlock.Origin.CALENDAR
    assert restored.title == payload["title"]

    # An old tab without authenticated provenance can still Undo, but its
    # reconstructed title is conservatively excluded from later AI context.
    response = post(
        auth_client,
        "/api/schedules/2026-04-18/blocks/restore/",
        blocks=[{key: value for key, value in original.items() if key != "restore_proof"}],
    )
    assert response.status_code == 200
    unknown = TimeBlock.objects.get(schedule=block.schedule)
    assert unknown.origin == TimeBlock.Origin.UNKNOWN
    async_to_sync(run_chat)(
        [{"role": "user", "content": "What is planned?"}],
        block.schedule,
        [unknown],
        [],
        datetime.datetime(2026, 4, 18, 8, 0),
    )
    assert "Appointment source" not in sdk_text(sdk.calls[-1])


def test_restore_proof_cannot_cross_schedule(auth_client):
    block, _ = imported_block(auth_client, "2026-04-18", "Private title")
    other, _ = imported_block(auth_client, "2026-04-19", "Other private title")
    payload = serialize_block(block)
    response = post(
        auth_client,
        "/api/schedules/2026-04-19/blocks/restore/",
        blocks=[payload],
    )
    assert response.status_code == 400
    other.refresh_from_db()
    assert other.origin == TimeBlock.Origin.CALENDAR


def test_ai_move_keeps_import_classification(auth_client, monkeypatch):
    block, _ = imported_block(auth_client, "2026-04-18", "Move protected title")

    async def move(*args, **kwargs):
        return AIChatResult(
            raw_response_text="{}",
            parsed_actions=[{"type": "move", "task_id": block.id, "start_time": "11:00"}],
            explanation="Moved",
            ask=None,
        )

    monkeypatch.setattr("ai.views.run_chat", move)
    response = post(
        auth_client,
        "/api/ai/schedules/2026-04-18/chat/",
        messages=[{"role": "user", "content": "Move the morning block"}],
    )
    assert response.status_code == 200
    block.refresh_from_db()
    assert block.start_time == datetime.time(11, 0)
    assert block.origin == TimeBlock.Origin.CALENDAR
