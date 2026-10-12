"""Block payloads must survive API updates and Inertia page reloads unchanged."""

import json

import pytest


@pytest.mark.django_db
def test_api_block_payload_matches_schedule_and_analytics_pages(auth_client, schedule):
    response = auth_client.post(
        f"/api/schedules/{schedule.date}/blocks/",
        json.dumps(
            {
                "title": "Проверка payload",
                "start_time": "09:05",
                "end_time": "10:10",
                "category": "work",
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 201
    block = response.json()
    response = auth_client.patch(
        f"/api/blocks/{block['id']}/",
        json.dumps({"is_completed": True, "sort_order": 7}),
        content_type="application/json",
    )
    assert response.status_code == 200
    result = response.json()
    block = result["blocks"][0]
    assert result["revision"] == result["schedule"]["revision"] == 2
    assert block == {
        "id": block["id"],
        "title": "Проверка payload",
        "start_time": "09:05",
        "end_time": "10:10",
        "category": "work",
        "is_completed": True,
        "sort_order": 7,
        "restore_proof": block["restore_proof"],
    }
    for page in ("schedule", "analytics"):
        response = auth_client.get(
            f"/{page}/{schedule.date}/", HTTP_X_INERTIA="true"
        )
        assert response.status_code == 200
        assert response.json()["props"]["blocks"] == [block]
