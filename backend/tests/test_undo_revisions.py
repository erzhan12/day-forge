"""HTTP regressions for historical undo revisions, without revision injection."""

import datetime
import json

import pytest
from django.test import Client
from schedules.categories import ordered_categories
from schedules.models import Schedule, TimeBlock
from schedules.serialization import serialize_block

pytestmark = pytest.mark.django_db


@pytest.fixture
def undo_day(user, schedule):
    schedule.status = Schedule.Status.ACTIVE
    schedule.save(update_fields=["status"])
    ordered_categories(user)
    TimeBlock.objects.create(
        schedule=schedule, title="External event", category="work",
        start_time=datetime.time(9, 7), end_time=datetime.time(9, 43),
    )
    client = Client()
    client.force_login(user)
    return client, schedule


def post(client, url, **body):
    return client.post(url, json.dumps(body), content_type="application/json")


def snapshot(schedule):
    return [serialize_block(block) for block in schedule.time_blocks.order_by("start_time")]


def add(client, schedule, revision, title, hour):
    response = post(
        client, f"/api/schedules/{schedule.date}/blocks/",
        expected_revision=revision, title=title, category="personal",
        start_time=f"{hour:02d}:00", end_time=f"{hour:02d}:30",
    )
    assert response.status_code == 201
    return response.json()


def restore(client, schedule, revision, blocks):
    return post(
        client, f"/api/schedules/{schedule.date}/blocks/restore/",
        expected_revision=revision, blocks=blocks,
    )


def test_contiguous_undo_chain_uses_each_accepted_restore_revision(undo_day):
    client, schedule = undo_day
    initial = snapshot(schedule)
    after_a = add(client, schedule, 0, "A", 14)
    after_b = add(client, schedule, after_a["revision"], "B", 15)
    undo_b = restore(client, schedule, after_b["revision"], after_a["blocks"])
    assert undo_b.status_code == 200
    assert undo_b.json()["revision"] == 3
    assert [b["title"] for b in undo_b.json()["blocks"]] == ["External event", "A"]
    # The historical revision 1 is spent; only the confirmed chain can use 3.
    stale = restore(client, schedule, after_a["revision"], initial)
    assert stale.status_code == 409
    undo_a = restore(client, schedule, undo_b.json()["revision"], initial)
    assert undo_a.status_code == 200
    assert undo_a.json()["revision"] == 4
    def comparable(rows):
        return [
            {k: v for k, v in block.items() if k not in {"id", "restore_proof"}}
            for block in rows
        ]
    assert comparable(undo_a.json()["blocks"]) == comparable(initial)
    assert undo_a.json()["schedule"]["status"] == "active"


@pytest.mark.parametrize("intervening", ["create", "review", "category-delete"])
def test_historical_undo_cannot_erase_an_intervening_write(undo_day, user, intervening):
    client, schedule = undo_day
    initial = snapshot(schedule)
    accepted = add(client, schedule, 0, "A", 14)
    if intervening == "create":
        add(client, schedule, accepted["revision"], "Other tab", 15)
    elif intervening == "review":
        response = post(
            client, f"/api/analytics/schedules/{schedule.date}/mark-reviewed/",
            expected_revision=accepted["revision"],
        )
        assert response.status_code == 200
    else:
        category = next(c for c in ordered_categories(user) if c.slug == "personal")
        assert client.delete(f"/api/user/categories/{category.pk}/").status_code == 200
    schedule.refresh_from_db()
    before_refusal = (schedule.status, schedule.revision, snapshot(schedule))
    response = restore(client, schedule, accepted["revision"], initial)
    assert response.status_code == 409
    assert response.json()["code"] == "schedule_changed"
    schedule.refresh_from_db()
    assert (schedule.status, schedule.revision, snapshot(schedule)) == before_refusal
