"""Unit tests for ``service.run_draft``.

Monkeypatches the OpenAI client so no network call is made. The draft
flavour shares its exception taxonomy with ``run_command`` — covered there
— so this file focuses on the *differences*: model selection, the
``add``-only validator, and the AIUnavailableError gate.
"""
import datetime
import json

import pytest
from ai.service import (
    AIDraftResult,
    AIParseError,
    AIUnavailableError,
    run_draft,
)
from schedules.models import Schedule
from templates_mgr.models import Template


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeChat:
    def __init__(self, captured: dict, content: str):
        self._captured = captured
        self._content = content

    def create(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, captured: dict, content: str):
        completions = _FakeChat(captured, content)
        self.chat = type("C", (), {"completions": completions})()


@pytest.mark.django_db
def test_run_draft_uses_draft_model_and_returns_result(
    user, monkeypatch, settings
):
    settings.LLM_API_KEY = "sk-test"
    settings.LLM_DRAFT_MODEL = "gpt-4o-test"

    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    template = Template.objects.create(
        user=user, name="WD", type="weekday", blocks=[]
    )

    captured: dict = {}
    fake = _FakeClient(
        captured,
        json.dumps(
            {
                "actions": [
                    {
                        "type": "add",
                        "title": "Block",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "category": "work",
                    }
                ],
                "explanation": "fresh draft",
            }
        ),
    )
    monkeypatch.setattr("ai.service._get_client", lambda: fake)

    result = run_draft(
        schedule, template, [], [], datetime.datetime(2026, 5, 4, 8, 0)
    )

    assert isinstance(result, AIDraftResult)
    assert result.explanation == "fresh draft"
    assert len(result.parsed_actions) == 1
    assert captured["model"] == "gpt-4o-test"
    # System message is the draft variant
    assert captured["messages"][0]["role"] == "system"
    assert "draft" in captured["messages"][0]["content"].lower()


@pytest.mark.django_db
def test_run_draft_raises_unavailable_without_key(user, settings):
    settings.LLM_API_KEY = ""
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    template = Template.objects.create(
        user=user, name="WD", type="weekday", blocks=[]
    )
    with pytest.raises(AIUnavailableError):
        run_draft(
            schedule, template, [], [], datetime.datetime(2026, 5, 4, 8, 0)
        )


@pytest.mark.django_db
def test_run_draft_rejects_non_add(user, monkeypatch, settings):
    settings.LLM_API_KEY = "sk-test"
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    template = Template.objects.create(
        user=user, name="WD", type="weekday", blocks=[]
    )

    fake = _FakeClient(
        {},
        json.dumps(
            {
                "actions": [{"type": "remove", "task_id": 99}],
                "explanation": "should fail",
            }
        ),
    )
    monkeypatch.setattr("ai.service._get_client", lambda: fake)

    with pytest.raises(AIParseError) as exc_info:
        run_draft(
            schedule, template, [], [], datetime.datetime(2026, 5, 4, 8, 0)
        )
    assert "only accept 'add'" in str(exc_info.value)
    # Raw response preserved for the audit log.
    assert "remove" in exc_info.value.raw_response_text
