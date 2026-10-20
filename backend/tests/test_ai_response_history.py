"""Provider replies must remain valid when the browser sends them as chat history."""

import json
from types import SimpleNamespace

import pytest
from ai.models import AIInteraction
from ai.views import AI_PARSE_ERROR_DETAIL
from schedules.models import Schedule, TimeBlock

URL = "/api/ai/schedules/2026-04-18/chat/"
ADD = {
    "type": "add",
    "title": "Private test block",
    "start_time": "14:00",
    "end_time": "15:00",
    "category": "work",
}


def _provider(monkeypatch, replies):
    calls = []
    remaining = iter(replies)

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(next(remaining))))]
        )

    monkeypatch.setattr(
        "ai.service._get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "test-key")
    return calls


def _post(client, messages):
    return client.post(URL, json.dumps({"messages": messages}), content_type="application/json")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": " \t"}],
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": " \n"},
            {"role": "user", "content": "again"},
        ],
    ],
)
def test_blank_transcript_content_rejected_before_provider(auth_client, user, messages):
    response = _post(auth_client, messages)
    assert response.status_code == 400
    assert "cannot be blank" in response.json()["errors"]["messages"]
    assert not Schedule.objects.filter(user=user, date="2026-04-18").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("actions", [[], [ADD]], ids=["no-op", "action"])
@pytest.mark.parametrize("explanation", ["", " \t\n"], ids=["empty", "whitespace"])
def test_blank_no_ask_reply_rejected_before_mutation(
    auth_client, user, monkeypatch, actions, explanation
):
    schedule = Schedule.objects.create(user=user, date="2026-04-18")
    raw = {"actions": actions, "explanation": explanation, "ask": None}
    calls = _provider(monkeypatch, [raw, {"actions": [], "explanation": "Ready.", "ask": None}])

    first = _post(auth_client, [{"role": "user", "content": "add a block"}])
    assert first.status_code == 502
    assert first.json()["errors"] == {"detail": AI_PARSE_ERROR_DETAIL}
    assert first.json()["request_completed"] is True
    assert "Private test block" not in first.content.decode()
    schedule.refresh_from_db()
    assert schedule.revision == 0
    assert not TimeBlock.objects.filter(schedule=schedule).exists()
    failure = AIInteraction.objects.get(schedule=schedule)
    audit = json.loads(failure.ai_response)
    assert "explanation" in audit["error_detail"]
    assert audit["raw"] == json.dumps(raw)

    # The browser's synthetic error bubble is nonblank and marked as a
    # failure. A fresh user turn can still carry that history to the SDK.
    second = _post(
        auth_client,
        [
            {"role": "user", "content": "add a block"},
            {"role": "assistant", "content": "The assistant failed.", "is_error": True},
            {"role": "user", "content": "try again"},
        ],
    )
    assert second.status_code == 200, second.content
    assert second.json()["explanation"] == "Ready."
    assert len(calls) == 2
    assert "The assistant failed." in calls[1]["messages"][1]["content"]


@pytest.mark.django_db
@pytest.mark.parametrize("ask", [" ", "\t\n"])
def test_blank_ask_rejected_even_with_explanation(auth_client, user, monkeypatch, ask):
    schedule = Schedule.objects.create(user=user, date="2026-04-18")
    _provider(monkeypatch, [{"actions": [], "explanation": "I need a time.", "ask": ask}])

    response = _post(auth_client, [{"role": "user", "content": "add a block"}])
    assert response.status_code == 502
    assert response.json()["errors"] == {"detail": AI_PARSE_ERROR_DETAIL}
    assert response.json()["request_completed"] is True
    assert not TimeBlock.objects.filter(schedule=schedule).exists()


@pytest.mark.django_db
def test_valid_ask_with_blank_explanation_round_trips_to_next_turn(
    auth_client, user, monkeypatch
):
    Schedule.objects.create(user=user, date="2026-04-18")
    calls = _provider(
        monkeypatch,
        [
            {"actions": [], "explanation": " \t", "ask": "What time should it start?"},
            {"actions": [ADD], "explanation": "Added the block.", "ask": None},
            {"actions": [], "explanation": "You have one block.", "ask": None},
        ],
    )

    messages = [{"role": "user", "content": "add a block"}]
    first = _post(auth_client, messages)
    assert first.status_code == 200, first.content
    first_data = first.json()
    assert first_data["ask"] == "What time should it start?"
    assert first_data["explanation"] == " \t"
    assert first_data["applied"] is False

    # These are the fields the browser sends for an assistant ask. Its
    # content comes from ask, so the blank explanation does not enter history.
    messages.extend(
        [
            {
                "role": "assistant",
                "content": first_data["ask"],
                "is_ask": True,
                "applied_add_block_ids": [],
            },
            {"role": "user", "content": "14:00"},
        ]
    )
    second = _post(auth_client, messages)
    assert second.status_code == 200, second.content
    second_data = second.json()
    assert second_data["ask"] is None
    assert second_data["applied"] is True
    assert TimeBlock.objects.filter(schedule__user=user, title="Private test block").count() == 1

    messages.extend(
        [
            {"role": "assistant", "content": second_data["explanation"]},
            {"role": "user", "content": "what is on the schedule?"},
        ]
    )
    third = _post(auth_client, messages)
    assert third.status_code == 200, third.content
    assert third.json()["explanation"] == "You have one block."
    assert len(calls) == 3
    assert "What time should it start?" in calls[1]["messages"][1]["content"]
    assert "Added the block." in calls[2]["messages"][1]["content"]
