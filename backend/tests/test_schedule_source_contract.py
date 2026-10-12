"""The manual endpoint and AI adapter must agree on shared interval rules."""

import datetime
import json

import pytest
from ai.mutation_planner import plan_mutations
from schedules.commands import BlockSnapshot, ScheduleSnapshot
from schedules.models import TimeBlock, UserScheduleSettings
from schedules.planning import snapshot_from_blocks


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "end", "accepted", "expected"),
    [
        ("09:00", "10:00", True, ("09:00", "10:00")),
        ("05:55", "06:30", True, ("06:00", "06:30")),
        ("22:30", "23:05", True, ("22:30", "23:00")),
        ("09:07", "10:00", False, None),
        ("10:00", "09:00", False, None),
        ("09:00", "09:00", False, None),
        ("23:05", "23:30", False, None),
    ],
)
def test_manual_and_ai_create_share_interval_contract(
    auth_client, schedule, start, end, accepted, expected
):
    action = {
        "type": "add",
        "title": "Contract",
        "category": "work",
        "start_time": start,
        "end_time": end,
    }
    ai_plan = plan_mutations(ScheduleSnapshot(schedule.pk, schedule.date, ()), [action])
    response = auth_client.post(
        f"/api/schedules/{schedule.date}/blocks/",
        json.dumps({key: value for key, value in action.items() if key != "type"}),
        content_type="application/json",
    )
    assert (response.status_code == 201) is accepted
    assert bool(ai_plan.diff.creates) is accepted
    if accepted:
        entry = ai_plan.diff.creates[0]
        assert (entry.start_time.strftime("%H:%M"), entry.end_time.strftime("%H:%M")) == expected
        assert (response.json()["start_time"], response.json()["end_time"]) == expected
    else:
        assert response.status_code == (422 if start == "23:05" else 400)
        assert not schedule.time_blocks.exists()


@pytest.mark.django_db
def test_manual_and_ai_swap_validate_final_state(auth_client, schedule):
    first = TimeBlock.objects.create(
        schedule=schedule,
        title="First",
        category="work",
        start_time=datetime.time(9),
        end_time=datetime.time(10),
    )
    second = TimeBlock.objects.create(
        schedule=schedule,
        title="Second",
        category="work",
        start_time=datetime.time(10),
        end_time=datetime.time(11),
    )
    snapshot = snapshot_from_blocks(schedule, list(schedule.time_blocks.all()))
    updates = [
        {"id": first.pk, "start_time": "10:00", "end_time": "11:00", "sort_order": 1},
        {"id": second.pk, "start_time": "09:00", "end_time": "10:00", "sort_order": 0},
    ]
    ai_plan = plan_mutations(
        snapshot,
        [
            {
                "type": "move",
                "task_id": update["id"],
                "start_time": update["start_time"],
                "end_time": update["end_time"],
            }
            for update in updates
        ],
    )
    response = auth_client.post(
        "/api/blocks/reorder/", json.dumps({"updates": updates}), content_type="application/json"
    )
    assert response.status_code == 200
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.start_time == datetime.time(10)
    assert second.start_time == datetime.time(9)
    assert {entry.block_id: entry.start_time for entry in ai_plan.diff.updates} == {
        first.pk: first.start_time,
        second.pk: second.start_time,
    }
    assert all(outcome.status == "applied" for outcome in ai_plan.outcomes)


@pytest.mark.django_db
def test_manual_and_ai_preserve_inherited_off_grid_outside_narrowed_window(
    auth_client, schedule, user
):
    UserScheduleSettings.objects.create(
        user=user, day_start=datetime.time(10), day_end=datetime.time(20)
    )
    block = TimeBlock.objects.create(
        schedule=schedule,
        title="Imported",
        category="work",
        start_time=datetime.time(8, 7),
        end_time=datetime.time(11, 3),
    )
    snapshot = ScheduleSnapshot(
        schedule.pk,
        schedule.date,
        (BlockSnapshot(block.pk, block.start_time, block.end_time, block.title, "work", False),),
    )
    ai_plan = plan_mutations(
        snapshot,
        [{"type": "resize", "task_id": block.pk, "end_time": "12:00"}],
        day_start="10:00",
        day_end="20:00",
    )
    response = auth_client.patch(
        f"/api/blocks/{block.pk}/",
        json.dumps({"end_time": "12:00"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    block.refresh_from_db()
    assert (block.start_time, block.end_time) == (datetime.time(8, 7), datetime.time(12))
    assert ai_plan.diff.updates[0].start_time == block.start_time
    assert ai_plan.diff.updates[0].end_time == block.end_time
