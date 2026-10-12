"""R07 HTTP contracts that depend on final-state planning and shared persistence."""

import datetime
import json

import pytest
from django.db import connection
from django.db.utils import OperationalError
from django.test.utils import CaptureQueriesContext
from schedules.models import Schedule, TimeBlock
from schedules.window import get_schedule_window

pytestmark = pytest.mark.django_db


def _post(client, path, body):
    return client.post(path, json.dumps(body), content_type="application/json")


def _block(schedule, index):
    start_minutes = 8 * 60 + index * 15
    end_minutes = start_minutes + 10
    return TimeBlock.objects.create(
        schedule=schedule,
        title=f"Block {index}",
        start_time=datetime.time(start_minutes // 60, start_minutes % 60),
        end_time=datetime.time(end_minutes // 60, end_minutes % 60),
        category="work",
        sort_order=index,
    )


def _select_count(queries):
    return sum(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)


def test_reorder_accepts_atomic_swap(auth_client, schedule):
    first, second = _block(schedule, 0), _block(schedule, 1)
    response = _post(
        auth_client,
        "/api/blocks/reorder/",
        {
            "updates": [
                {"id": first.pk, "start_time": "08:15", "end_time": "08:25", "sort_order": 1},
                {"id": second.pk, "start_time": "08:00", "end_time": "08:10", "sort_order": 0},
            ]
        },
    )
    assert response.status_code == 200, response.content
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.start_time, second.start_time) == (datetime.time(8, 15), datetime.time(8))
    schedule.refresh_from_db()
    assert schedule.revision == 1


def test_reorder_select_count_does_not_scale_with_blocks(auth_client, user):
    get_schedule_window(user)
    counts = []
    for count in (1, 12):
        schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 7, count))
        blocks = [_block(schedule, index) for index in range(count)]
        updates = [
            {
                "id": block.pk,
                "start_time": block.start_time.strftime("%H:%M"),
                "end_time": block.end_time.strftime("%H:%M"),
                "sort_order": block.sort_order + 100,
            }
            for block in blocks
        ]
        with CaptureQueriesContext(connection) as captured:
            response = _post(auth_client, "/api/blocks/reorder/", {"updates": updates})
        assert response.status_code == 200, response.content
        counts.append(_select_count(captured))
    # A per-row full_clean constraint query would add eleven SELECTs.
    assert counts[1] <= counts[0] + 1, counts


def test_restore_select_count_does_not_scale_with_blocks(auth_client, user):
    counts = []
    for count in (1, 12):
        schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 8, count))
        _block(schedule, 0)
        entries = [
            {
                "title": f"Restored {index}",
                "start_time": f"{8 + index // 4:02d}:{(index % 4) * 15:02d}",
                "end_time": f"{8 + index // 4:02d}:{(index % 4) * 15 + 10:02d}",
                "category": "work",
                "is_completed": False,
                "sort_order": index,
            }
            for index in range(count)
        ]
        with CaptureQueriesContext(connection) as captured:
            response = _post(
                auth_client, f"/api/schedules/{schedule.date}/blocks/restore/", {"blocks": entries}
            )
        assert response.status_code == 200, response.content
        counts.append(_select_count(captured))
    assert counts[1] <= counts[0] + 1, counts


def test_busy_persistence_write_uses_r04_conflict_mapping(
    auth_client, schedule, monkeypatch
):
    block = _block(schedule, 0)

    def locked_save(self, *args, **kwargs):
        raise OperationalError("database is locked")

    monkeypatch.setattr(TimeBlock, "save", locked_save)
    response = auth_client.patch(
        f"/api/blocks/{block.pk}/",
        json.dumps({"title": "Changed"}),
        content_type="application/json",
    )
    assert response.status_code == 409
    assert response.json()["code"] == "schedule_changed"
    block.refresh_from_db()
    schedule.refresh_from_db()
    assert block.title == "Block 0"
    assert schedule.revision == 0
