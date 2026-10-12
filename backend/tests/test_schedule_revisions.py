"""Public mutation version contract, using a client that never inserts revisions."""

import datetime
import json

import pytest
from django.test import Client
from schedules.models import Schedule, TimeBlock
from schedules.serialization import serialize_block

pytestmark = pytest.mark.django_db


@pytest.fixture
def revision_case(user, schedule):
    schedule.status = Schedule.Status.ACTIVE
    schedule.save(update_fields=["status"])
    block = TimeBlock.objects.create(
        schedule=schedule,
        title="Original",
        start_time=datetime.time(9),
        end_time=datetime.time(10),
        category="work",
        sort_order=3,
    )
    client = Client()
    client.force_login(user)
    return client, schedule, block


def request_for(writer, schedule, block):
    date_url = f"/api/schedules/{schedule.date}/blocks/"
    if writer in {"create", "from-event"}:
        return (
            "post",
            date_url + ("from-event/" if writer == "from-event" else ""),
            {
                "title": "Added",
                "start_time": "14:00",
                "end_time": "15:00",
                "category": "work",
            },
        )
    if writer == "patch":
        return "patch", f"/api/blocks/{block.pk}/", {"title": "Edited"}
    if writer == "delete":
        return "delete", f"/api/blocks/{block.pk}/", {}
    if writer == "reorder":
        return (
            "post",
            "/api/blocks/reorder/",
            {
                "updates": [
                    {
                        "id": block.pk,
                        "start_time": "11:00",
                        "end_time": "12:00",
                        "sort_order": 0,
                    }
                ]
            },
        )
    return "post", date_url + "restore/", {"blocks": []}


def send(client, method, url, body):
    return getattr(client, method)(url, json.dumps(body), content_type="application/json")


@pytest.mark.parametrize(
    "writer", ["create", "from-event", "patch", "delete", "reorder", "restore"]
)
def test_all_manual_writers_require_revision(revision_case, writer):
    client, schedule, block = revision_case
    method, url, body = request_for(writer, schedule, block)
    response = send(client, method, url, body)
    assert response.status_code == 409
    assert response.json()["code"] == "schedule_changed"
    assert "Refresh" in response.json()["errors"]["detail"]
    schedule.refresh_from_db()
    block.refresh_from_db()
    assert schedule.revision == 0
    assert block.title == "Original"
    assert schedule.time_blocks.count() == 1


@pytest.mark.parametrize(
    "writer", ["create", "from-event", "patch", "delete", "reorder", "restore"]
)
def test_all_manual_writers_reject_stale_revision(revision_case, writer):
    client, schedule, block = revision_case
    first = send(
        client,
        "patch",
        f"/api/blocks/{block.pk}/",
        {
            "title": "First writer",
            "expected_revision": 0,
        },
    )
    assert first.status_code == 200
    assert first.json()["revision"] == 1
    method, url, body = request_for(writer, schedule, block)
    response = send(client, method, url, {**body, "expected_revision": 0})
    assert response.status_code == 409
    assert response.json()["code"] == "schedule_changed"
    schedule.refresh_from_db()
    block.refresh_from_db()
    assert schedule.revision == 1
    assert block.title == "First writer"
    assert schedule.time_blocks.count() == 1


@pytest.mark.parametrize("revision", [None, True, False, "0", -1, 0.0])
def test_invalid_revision_is_controlled_conflict(revision_case, revision):
    client, schedule, block = revision_case
    method, url, body = request_for("create", schedule, block)
    response = send(client, method, url, {**body, "expected_revision": revision})
    assert response.status_code == 409
    assert response.json()["code"] == "schedule_changed"
    assert schedule.time_blocks.count() == 1


def test_noop_patch_reorder_and_restore_do_not_bump_or_replace_ids(revision_case):
    client, schedule, block = revision_case
    snapshot = serialize_block(block)
    requests = [
        ("patch", f"/api/blocks/{block.pk}/", {"title": "Original"}),
        ("post", "/api/blocks/reorder/", {"updates": [snapshot]}),
        ("post", f"/api/schedules/{schedule.date}/blocks/restore/", {"blocks": [snapshot]}),
    ]
    for method, url, body in requests:
        response = send(client, method, url, {**body, "expected_revision": 0})
        assert response.status_code == 200
        assert response.json()["revision"] == 0
        assert response.json()["blocks"] == [snapshot]
    schedule.refresh_from_db()
    assert schedule.revision == 0


@pytest.mark.parametrize("writer", ["create", "from-event", "patch", "delete", "reorder"])
def test_status_failure_rolls_back_blocks_and_revision(revision_case, monkeypatch, writer):
    client, schedule, block = revision_case

    def fail_status(self):
        raise RuntimeError("status save failed")

    monkeypatch.setattr(Schedule, "mark_active_on_edit", fail_status)
    method, url, body = request_for(writer, schedule, block)
    with pytest.raises(RuntimeError, match="status save failed"):
        send(client, method, url, {**body, "expected_revision": 0})
    schedule.refresh_from_db()
    block.refresh_from_db()
    assert schedule.revision == 0
    assert block.title == "Original"
    assert block.start_time == datetime.time(9)
    assert schedule.time_blocks.count() == 1


def test_response_snapshot_is_from_its_own_commit(revision_case, monkeypatch):
    from schedules import api
    from schedules.mutations import execute_schedule_maintenance

    client, schedule, block = revision_case
    execute = api.execute_schedule_mutation

    def followed_by_another_write(*args, **kwargs):
        result = execute(*args, **kwargs)

        def next_write(ctx):
            ctx.blocks[0].title = "Later writer"
            ctx.blocks[0].save(update_fields=["title"])

        execute_schedule_maintenance(schedule.user_id, schedule.pk, next_write)
        return result

    monkeypatch.setattr(api, "execute_schedule_mutation", followed_by_another_write)
    response = send(
        client,
        "patch",
        f"/api/blocks/{block.pk}/",
        {
            "title": "This response",
            "expected_revision": 0,
        },
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert response.json()["schedule"]["revision"] == 1
    assert response.json()["blocks"][0]["title"] == "This response"
    assert response.json()["title"] == "This response"
    schedule.refresh_from_db()
    block.refresh_from_db()
    assert schedule.revision == 2
    assert block.title == "Later writer"
