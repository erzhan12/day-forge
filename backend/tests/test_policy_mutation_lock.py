"""Policy APIs retry complete writes and roll back busy failures."""

import json

import pytest
from django.db import OperationalError
from schedules.models import UserScheduleSettings
from templates_mgr.models import Rule, Template


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("model", "url", "method", "body"),
    [
        (
            UserScheduleSettings,
            "/api/user/schedule-settings/",
            "patch",
            {"time_zone": "Asia/Almaty"},
        ),
        (Rule, "/api/rules/", "post", {"text": "Rule"}),
        (Template, "/api/templates/", "post", {"name": "Weekday", "type": "weekday", "blocks": []}),
    ],
)
@pytest.mark.parametrize("exhaust", [False, True])
def test_policy_busy_write_retries_whole_transaction(
    user, auth_client, monkeypatch, model, url, method, body, exhaust
):
    original_save = model.save
    calls = []

    def save_then_busy(instance, *args, **kwargs):
        original_save(instance, *args, **kwargs)
        calls.append(instance.pk)
        if exhaust or len(calls) == 1:
            raise OperationalError("database is locked")

    monkeypatch.setattr(model, "save", save_then_busy)
    response = getattr(auth_client, method)(url, json.dumps(body), content_type="application/json")
    if exhaust:
        assert response.status_code == 409, response.content
        assert response.json()["code"] == "schedule_changed"
        assert len(calls) == 3
        assert not model.objects.filter(user=user).exists()
    else:
        assert response.status_code == (200 if method == "patch" else 201), response.content
        assert len(calls) == 2
        assert model.objects.filter(user=user).count() == 1
    if model is UserScheduleSettings:
        assert response["Cache-Control"] == "private, no-store"
