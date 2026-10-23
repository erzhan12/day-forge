"""HTTP continuation scope, atomic receipts and post-apply intent fingerprints."""

import datetime
import json
import uuid
from types import SimpleNamespace

import pytest
from ai.models import ChatRequest, PendingIntent
from ai.pending_intents import IntentScopeError
from ai.service import AIChatResult
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Rule

DAY = "2027-01-15"
URL = f"/api/ai/schedules/{DAY}/chat/"
pytestmark = pytest.mark.django_db


def item(title="Gym", **changes):
    return {
        "type": "add",
        "task_id": None,
        "target_ids": [],
        "known_fields": {"title": title, "category": "health"},
        "missing_fields": ["end_time", "start_time"],
        **changes,
    }


def add(title="Gym", start="14:00", end="14:30"):
    return {
        "type": "add",
        "title": title,
        "category": "health",
        "start_time": start,
        "end_time": end,
    }


def provider(monkeypatch, result):
    calls = []

    async def run(*args):
        calls.append(args)
        return result

    monkeypatch.setattr("ai.views.run_chat", run)
    return calls


def send(client, user, text="Add Gym", ref=None, *, revision=None, **extra):
    if revision is None:
        revision = (
            Schedule.objects.filter(user=user, date=DAY).values_list("revision", flat=True).first()
            or 0
        )
    body = {
        "request_id": str(uuid.uuid4()),
        "expected_revision": revision,
        "messages": [{"role": "user", "content": text}],
        **extra,
    }
    if ref:
        body.update(pending_intent_id=ref["id"], pending_intent_version=ref["version"])
    response = client.post(URL, json.dumps(body), content_type="application/json")
    return response, body


def ask(client, user, monkeypatch, items=None):
    provider(
        monkeypatch,
        AIChatResult(
            "{}",
            [],
            "Need a time.",
            "When?",
            intent_decision="new",
            pending_actions=items or [item()],
        ),
    )
    response, body = send(client, user)
    assert response.status_code == 200, response.content
    return response.json()["pending_intent"], body, response


def test_question_is_durable_and_replay_does_not_replace_it(auth_client, user, monkeypatch):
    ref, body, first = ask(auth_client, user, monkeypatch)
    row = PendingIntent.objects.get()
    assert str(row.pk) == ref["id"] and row.version == 1 and row.revision == 0
    assert row.source_message == "Add Gym" and row.items == [item()]
    assert row.accepted_changes == []
    assert (
        datetime.timedelta(minutes=14)
        < row.expires_at - timezone.now()
        <= datetime.timedelta(minutes=15)
    )
    assert (
        auth_client.post(URL, json.dumps(body), content_type="application/json").content
        == first.content
    )
    assert PendingIntent.objects.count() == 1
    assert cache.get(f"ai_chat_rl:{user.pk}") == 1


def test_answer_uses_server_scope_and_resolves_once(auth_client, user, monkeypatch):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    calls = provider(
        monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue")
    )
    response, body = send(auth_client, user, "14:00 for 30 minutes", ref)
    assert response.status_code == 200, response.content
    assert response.json()["pending_intent"] is None
    assert PendingIntent.objects.get().state == "resolved"
    assert TimeBlock.objects.get().title == "Gym"
    assert calls[0][1]._pending_intent_summary["pending_actions"] == [item()]
    assert (
        auth_client.post(URL, json.dumps(body), content_type="application/json").content
        == response.content
    )
    assert len(calls) == 1 and TimeBlock.objects.count() == 1
    assert send(auth_client, user, "Again", ref)[0].status_code == 409


@pytest.mark.parametrize("actions", [[add("Other")], [add(), add("Extra", "16:00", "16:30")]])
def test_expanded_actions_are_rejected_atomically(auth_client, user, monkeypatch, actions):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    provider(monkeypatch, AIChatResult("{}", actions, "Added.", None, intent_decision="continue"))
    response, _ = send(auth_client, user, "14:00", ref)
    assert response.status_code == 409 and response.json()["code"] == "pending_intent_scope"
    assert not TimeBlock.objects.exists()
    assert PendingIntent.objects.get().state == "open"
    assert Schedule.objects.get().revision == 0


@pytest.mark.parametrize(
    "change", ["expiry", "revision", "rule", "version", "unknown", "other_date"]
)
def test_stale_or_foreign_scope_does_not_call_provider(auth_client, user, monkeypatch, change):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    row = PendingIntent.objects.get()
    if change == "expiry":
        row.expires_at = timezone.now() - datetime.timedelta(seconds=1)
        row.save()
    elif change == "revision":
        Schedule.objects.update(revision=1)
    elif change == "rule":
        Rule.objects.create(user=user, text="Changed policy")
    elif change == "version":
        ref["version"] += 1
    elif change == "unknown":
        ref["id"] = str(uuid.uuid4())
    elif change == "other_date":
        other = Schedule.objects.create(user=user, date="2027-01-16")
        row.schedule = other
        row.save()
    calls = provider(monkeypatch, AIChatResult("{}", [add()], "Added.", None))
    before = cache.get(f"ai_chat_rl:{user.pk}")
    response, _ = send(auth_client, user, "14:00", ref)
    assert response.status_code == 409 and response.json()["code"] == "pending_intent_stale"
    assert not calls and not TimeBlock.objects.exists()
    assert cache.get(f"ai_chat_rl:{user.pk}") == before
    row.refresh_from_db()
    if change in {"expiry", "revision", "rule"}:
        assert row.state == "stale"


def test_explicit_cancel_is_provider_independent_and_replayable(auth_client, user, monkeypatch):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    calls = provider(monkeypatch, RuntimeError("Must not call"))
    response, body = send(auth_client, user, "Cancel pending request.", ref, intent_action="cancel")
    assert response.status_code == 200 and response.json()["pending_intent"] is None
    assert not calls and not TimeBlock.objects.exists()
    assert PendingIntent.objects.get().state == "cancelled"
    assert Schedule.objects.get().revision == 0
    assert (
        auth_client.post(URL, json.dumps(body), content_type="application/json").content
        == response.content
    )


def test_free_text_cancel_discards_even_incorrect_model_actions(auth_client, user, monkeypatch):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    provider(monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="cancel"))
    response, _ = send(auth_client, user, "No, don't add Gym", ref)
    assert response.status_code == 200
    assert response.json()["applied"] is False
    assert PendingIntent.objects.get().state == "cancelled"
    assert not TimeBlock.objects.exists()


def test_ask_only_turn_advances_version_without_extending_expiry(auth_client, user, monkeypatch):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    expiry = PendingIntent.objects.get().expires_at
    provider(
        monkeypatch,
        AIChatResult(
            "{}",
            [],
            "Need a time.",
            "What time?",
            intent_decision="continue",
            pending_actions=[item()],
        ),
    )
    response, _ = send(auth_client, user, "Later", ref)
    assert response.status_code == 200, response.content
    assert response.json()["pending_intent"]["version"] == 2
    assert Schedule.objects.get().revision == 0
    assert PendingIntent.objects.get().expires_at == expiry
    calls = provider(
        monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue")
    )
    assert send(auth_client, user, "14:00", ref)[0].status_code == 409
    assert not calls


def test_remaining_sibling_is_retained_after_one_answer(auth_client, user, monkeypatch):
    ref, _, _ = ask(auth_client, user, monkeypatch, [item("Gym"), item("Walk")])
    provider(
        monkeypatch, AIChatResult("{}", [add()], "Added Gym.", None, intent_decision="continue")
    )
    first, _ = send(auth_client, user, "Gym at 14:00", ref)
    assert first.status_code == 200, first.content
    next_ref = first.json()["pending_intent"]
    row = PendingIntent.objects.get()
    assert row.items == [item("Walk")]
    assert row.revision == 1 and row.version == 2
    assert row.accepted_changes[0]["block_id"] == TimeBlock.objects.get().pk
    provider(
        monkeypatch,
        AIChatResult(
            "{}", [add(), add("Walk", "16:00", "16:30")], "Added.", None, intent_decision="continue"
        ),
    )
    assert send(auth_client, user, "Walk at 16:00", next_ref)[0].status_code == 409
    assert TimeBlock.objects.count() == 1
    provider(
        monkeypatch,
        AIChatResult(
            "{}", [add("Walk", "16:00", "16:30")], "Added.", None, intent_decision="continue"
        ),
    )
    assert send(auth_client, user, "Walk at 16:00", next_ref)[0].status_code == 200
    assert TimeBlock.objects.count() == 2 and PendingIntent.objects.get().state == "resolved"


def test_rejected_plan_keeps_post_commit_fingerprint_and_accepted_ids(
    auth_client, user, monkeypatch
):
    provider(
        monkeypatch,
        AIChatResult(
            "{}",
            [add("Accepted"), add("Outside", "23:00", "23:30")],
            "Part applied.",
            None,
            intent_decision="new",
        ),
    )
    response, _ = send(auth_client, user)
    assert response.status_code == 200, response.content
    ref = response.json()["pending_intent"]
    row = PendingIntent.objects.get()
    assert row.revision == 1
    assert row.items[0]["known_fields"] == {
        "title": "Outside",
        "category": "health",
        "duration_minutes": 30,
    }
    assert row.accepted_changes[0]["block_id"] == TimeBlock.objects.get().pk
    provider(
        monkeypatch,
        AIChatResult(
            "{}", [add("Outside", "16:00", "16:30")], "Added.", None, intent_decision="continue"
        ),
    )
    answer, _ = send(auth_client, user, "Use 16:00", ref)
    assert answer.status_code == 200, answer.content
    assert set(TimeBlock.objects.values_list("title", flat=True)) == {"Accepted", "Outside"}


def test_scope_error_after_apply_rolls_back_schedule_and_stores_receipt(
    auth_client, user, monkeypatch
):
    ref, _, _ = ask(auth_client, user, monkeypatch, [item("Gym"), item("Walk")])
    provider(monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue"))
    monkeypatch.setattr(
        "ai.pending_intents.validate_items",
        lambda *args: (_ for _ in ()).throw(IntentScopeError("late failure")),
    )
    response, body = send(auth_client, user, "Gym at 14:00", ref)
    assert response.status_code == 409
    assert not TimeBlock.objects.exists() and Schedule.objects.get().revision == 0
    assert PendingIntent.objects.get().version == 1
    receipt = ChatRequest.objects.get(request_id=body["request_id"])
    assert receipt.response_status == 409 and receipt.completed_at is not None


@pytest.mark.parametrize("error_type", [ValueError, TypeError])
def test_executor_programming_error_propagates_and_rolls_back(
    auth_client, user, monkeypatch, error_type
):
    from ai import views

    ref, _, _ = ask(auth_client, user, monkeypatch)
    provider(monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue"))
    original = views._finish_chat_sync

    def fail_after_apply(*args, **kwargs):
        response = original(*args, **kwargs)
        assert response.status_code == 200
        raise error_type("executor programming error")

    monkeypatch.setattr(views, "_finish_chat_sync", fail_after_apply)
    with pytest.raises(error_type, match="executor programming error"):
        send(auth_client, user, "14:00", ref)
    assert not TimeBlock.objects.exists()
    assert Schedule.objects.get().revision == 0
    row = PendingIntent.objects.get()
    assert row.state == "open" and row.version == ref["version"]
    assert ChatRequest.objects.filter(completed_at__isnull=True).count() == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"pending_intent_id": "bad", "pending_intent_version": 1},
        {"pending_intent_id": str(uuid.uuid4())},
        {"pending_intent_version": 1},
        {"intent_action": "cancel"},
        {"pending_intent_id": str(uuid.uuid4()), "pending_intent_version": True},
    ],
)
def test_invalid_reference_does_not_write(auth_client, user, extra):
    response, _ = send(auth_client, user, **extra)
    assert response.status_code == 400
    assert not Schedule.objects.exists() and not ChatRequest.objects.exists()


def test_foreign_owner_and_old_client_revision_are_rejected_before_ai(
    auth_client, user, monkeypatch
):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    foreign = User.objects.create_user(username="foreign-intent")
    row = PendingIntent.objects.get()
    row.user = foreign
    row.save()
    calls = provider(
        monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue")
    )
    response, _ = send(auth_client, user, "14:00", ref)
    assert response.status_code == 409 and not calls
    row.user = user
    row.save()
    Schedule.objects.update(revision=1)
    response, _ = send(auth_client, user, "14:00", ref, revision=0)
    assert response.json()["code"] == "pending_intent_stale" and not calls
    row.refresh_from_db()
    assert row.state == "stale"


@pytest.mark.parametrize("change", ["revision", "policy", "expiry", "version"])
def test_context_changed_during_provider_call_cannot_commit(auth_client, user, monkeypatch, change):
    from asgiref.sync import sync_to_async

    ref, _, _ = ask(auth_client, user, monkeypatch)

    def race():
        if change == "revision":
            Schedule.objects.update(revision=1)
        elif change == "policy":
            Rule.objects.create(user=user, text="Policy edited during network call")
        elif change == "expiry":
            PendingIntent.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
        else:
            PendingIntent.objects.update(version=2)

    async def run(*args):
        await sync_to_async(race, thread_sensitive=True)()
        return AIChatResult("{}", [add()], "Added.", None, intent_decision="continue")

    monkeypatch.setattr("ai.views.run_chat", run)
    response, _ = send(auth_client, user, "14:00", ref)
    assert response.status_code == 409
    assert not TimeBlock.objects.exists()


def test_explicit_new_command_is_reinterpreted_without_pending_or_transcript(
    auth_client, user, monkeypatch
):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    calls = []

    async def run(messages, schedule, *args):
        calls.append((messages, getattr(schedule, "_pending_intent_summary", None)))
        return AIChatResult("{}", [add("Walk")], "Added Walk.", None, intent_decision="new")

    monkeypatch.setattr("ai.views.run_chat", run)
    response, _ = send(auth_client, user, "Add Walk at 14:00", ref)
    assert response.status_code == 200, response.content
    assert len(calls) == 2 and calls[0][1] and calls[1][1] is None
    assert calls[1][0] == [{"role": "user", "content": "Add Walk at 14:00"}]
    assert TimeBlock.objects.get().title == "Walk"
    assert PendingIntent.objects.get().state == "cancelled"


def test_read_classification_discards_actions_but_retains_unresolved_work(
    auth_client, user, monkeypatch
):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    provider(
        monkeypatch, AIChatResult("{}", [add()], "There is room.", None, intent_decision="read")
    )
    response, _ = send(auth_client, user, "Is there room?", ref)
    assert response.status_code == 200 and not response.json()["applied"]
    assert not TimeBlock.objects.exists()
    next_ref = response.json()["pending_intent"]
    assert next_ref is not None
    assert next_ref["version"] == ref["version"] + 1
    row = PendingIntent.objects.get()
    assert row.state == "open"
    assert row.items == [item()]


@pytest.mark.parametrize("duration", [30, 45])
def test_known_duration_is_preserved_for_explicit_intervals(
    auth_client, user, monkeypatch, duration
):
    scope = item(known_fields={"title": "Gym", "category": "health", "duration_minutes": 30})
    ref, _, _ = ask(auth_client, user, monkeypatch, [scope])
    provider(
        monkeypatch,
        AIChatResult(
            "{}", [add(end=f"14:{duration:02d}")], "Added.", None, intent_decision="continue"
        ),
    )
    response, _ = send(auth_client, user, "14:00", ref)
    assert response.status_code == (200 if duration == 30 else 409), response.content
    assert TimeBlock.objects.count() == (1 if duration == 30 else 0)


@pytest.mark.parametrize(
    "known,missing",
    [
        ({"duration_minutes": 30}, ["start_time"]),
        ({"duration_minutes": 30}, ["end_time"]),
        ({"start_time": "14:00"}, ["duration_minutes"]),
        ({"end_time": "14:30"}, ["duration_minutes"]),
    ],
)
def test_answer_accepts_only_time_fields_derived_from_permitted_operand(
    auth_client, user, monkeypatch, known, missing
):
    scope = item(
        known_fields={"title": "Gym", "category": "health", **known}, missing_fields=missing
    )
    ref, _, _ = ask(auth_client, user, monkeypatch, [scope])
    provider(monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue"))
    response, body = send(auth_client, user, "14:00 for 30 minutes", ref)
    assert response.status_code == 200, response.content
    assert response.json()["pending_intent"] is None
    block = TimeBlock.objects.get()
    assert (str(block.start_time), str(block.end_time)) == ("14:00:00", "14:30:00")
    assert PendingIntent.objects.get().state == "resolved"
    replay = auth_client.post(URL, json.dumps(body), content_type="application/json")
    assert replay.content == response.content
    assert TimeBlock.objects.count() == 1 and Schedule.objects.get().revision == 1


@pytest.mark.parametrize(
    "known,action",
    [
        ({"duration_minutes": 30}, add(end="14:45")),
        ({"duration_minutes": 30}, {**add(), "duration_minutes": 45}),
        ({"start_time": "13:00"}, add()),
        ({"end_time": "15:00"}, add()),
        ({"start_time": "14:00"}, add(end="13:30")),
        ({"start_time": "14:00"}, add(end="14:00")),
        ({}, add()),
    ],
)
def test_derived_interval_cannot_change_a_locked_time_or_duration(
    auth_client, user, monkeypatch, known, action
):
    missing = ["start_time"] if "duration_minutes" in known else ["duration_minutes"]
    ref, _, _ = ask(
        auth_client,
        user,
        monkeypatch,
        [
            item(
                known_fields={"title": "Gym", "category": "health", **known},
                missing_fields=missing,
            )
        ],
    )
    provider(monkeypatch, AIChatResult("{}", [action], "Added.", None, intent_decision="continue"))
    response, _ = send(auth_client, user, "14:00", ref)
    assert response.status_code == 409
    assert not TimeBlock.objects.exists() and Schedule.objects.get().revision == 0
    row = PendingIntent.objects.get()
    assert row.state == "open" and row.version == ref["version"]


def test_partial_plan_without_model_question_keeps_scope_and_accepted_ids(
    auth_client, user, monkeypatch
):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        payload = {"actions": [add()], "explanation": "Added Gym; Walk still pending.",
                   "ask": None, "intent_decision": "new", "pending_actions": [
                       item("Walk", known_fields={"title": "Walk", "category": "health",
                                                  "duration_minutes": 30},
                            missing_fields=["start_time"]),
                   ]}
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
        ])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "test-key")
    monkeypatch.setattr("ai.service._get_client", lambda: client)
    response, body = send(auth_client, user, "Add Gym at 14:00 and ask when Walk starts")
    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["applied"] and payload["partial"] and payload["ask"]
    row = PendingIntent.objects.get()
    accepted_id = TimeBlock.objects.get(title="Gym").pk
    assert row.state == "open" and row.accepted_changes[0]["block_id"] == accepted_id
    replay = auth_client.post(URL, json.dumps(body), content_type="application/json")
    assert replay.content == response.content and len(calls) == 1
    provider(monkeypatch, AIChatResult(
        "{}", [add("Walk", start="15:00", end="15:30")], "Added.", None,
        intent_decision="continue",
    ))
    completed, _ = send(auth_client, user, "15:00", payload["pending_intent"])
    assert completed.status_code == 200 and completed.json()["pending_intent"] is None
    assert list(TimeBlock.objects.filter(title="Gym").values_list("id", flat=True)) == [accepted_id]
    assert TimeBlock.objects.count() == 2


def test_old_format_question_has_no_executable_scope(auth_client, user, monkeypatch):
    provider(monkeypatch, AIChatResult("{}", [], "Need a time.", "When?"))
    first, _ = send(auth_client, user)
    ref = first.json()["pending_intent"]
    assert PendingIntent.objects.get().items == []
    provider(monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue"))
    response, _ = send(auth_client, user, "14:00", ref)
    assert response.status_code == 409 and not TimeBlock.objects.exists()


def test_procedural_before_clause_does_not_block_a_concrete_continuation(
    auth_client, user, monkeypatch
):
    command = "Add Gym for 30 minutes. Ask for its start time before adding it."
    scope = item(known_fields={"title": "Gym", "category": "health", "duration_minutes": 30},
                 missing_fields=["start_time"])
    provider(monkeypatch, AIChatResult("{}", [], "Need time.", "When?",
                                      intent_decision="new", pending_actions=[scope]))
    first, _ = send(auth_client, user, command)
    ref = first.json()["pending_intent"]
    provider(monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue"))
    body = {"request_id": str(uuid.uuid4()), "expected_revision": 0,
            "pending_intent_id": ref["id"], "pending_intent_version": ref["version"],
            "messages": [{"role": "user", "content": command},
                         {"role": "assistant", "content": "When?", "is_ask": True},
                         {"role": "user", "content": "14:00"}]}
    response = auth_client.post(URL, json.dumps(body), content_type="application/json")
    assert response.status_code == 200 and response.json()["applied"]
    assert response.json()["pending_intent"] is None and TimeBlock.objects.count() == 1


@pytest.mark.parametrize("omit_outcomes", [False, True], ids=["empty-outcomes", "no-outcomes"])
@pytest.mark.parametrize("title", ["Walk", "Walk after lunch"])
def test_relative_guard_rejection_preserves_permission_for_a_corrected_answer(
    auth_client, user, monkeypatch, omit_outcomes, title
):
    schedule = Schedule.objects.create(user=user, date=DAY)
    TimeBlock.objects.create(schedule=schedule, title="Gym", category="health",
                             start_time="09:00", end_time="09:30", sort_order=0)
    command = f'Add "{title}" after Gym'
    scope = item(title)
    provider(monkeypatch, AIChatResult("{}", [], "Need time.", "When?",
                                      intent_decision="new", pending_actions=[scope]))
    first, _ = send(auth_client, user, command)
    ref = first.json()["pending_intent"]
    if omit_outcomes:
        from ai import views

        original = views._finish_chat_sync

        def without_outcomes(*args, **kwargs):
            response = original(*args, **kwargs)
            payload = json.loads(response.content)
            if payload.get("ask") and not payload.get("applied"):
                assert payload.pop("outcomes") == []
                response.content = json.dumps(payload)
            return response

        monkeypatch.setattr(views, "_finish_chat_sync", without_outcomes)
    history = [{"role": "user", "content": command},
               {"role": "assistant", "content": "When?", "is_ask": True}]
    for hour, applied in [("08", False), ("10", True)]:
        provider(monkeypatch, AIChatResult(
            "{}", [add(title, f"{hour}:00", f"{hour}:30")], "Added.", None,
            intent_decision="continue",
        ))
        response, _ = send(auth_client, user, ref=ref,
                           messages=[*history, {"role": "user", "content": f"{hour}:00"}])
        assert response.status_code == 200 and response.json()["applied"] is applied
        if not applied:
            assert ("outcomes" not in response.json()) is omit_outcomes
            row = PendingIntent.objects.get()
            assert row.items == [scope] and row.version == 2
            assert Schedule.objects.get(pk=schedule.pk).revision == 0
            assert not TimeBlock.objects.filter(title=title).exists()
            ref = response.json()["pending_intent"]
        else:
            assert response.json()["pending_intent"] is None
            assert TimeBlock.objects.get(title=title).start_time == datetime.time(10)


def test_conflicting_answer_keeps_original_permission_scope(auth_client, user, monkeypatch):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    provider(
        monkeypatch,
        AIChatResult(
            "{}", [add(start="23:00", end="23:30")], "Added.", None, intent_decision="continue"
        ),
    )
    response, _ = send(auth_client, user, "23:00", ref)
    assert response.status_code == 200, response.content
    assert not TimeBlock.objects.exists()
    expected = item()
    expected["known_fields"]["duration_minutes"] = 30
    assert PendingIntent.objects.get().items == [expected]


@pytest.mark.parametrize("expansion", ["fields", "duplicate"])
def test_repeated_question_cannot_expand_target_or_fields(
    auth_client, user, monkeypatch, expansion
):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    expanded = item(
        missing_fields=["start_time", "end_time", "title"], known_fields={"category": "health"}
    )
    provider(
        monkeypatch,
        AIChatResult(
            "{}",
            [],
            "Which task?",
            "Which task?",
            intent_decision="continue",
            pending_actions=[expanded] if expansion == "fields" else [item(), item()],
        ),
    )
    response, _ = send(auth_client, user, "Later", ref)
    assert response.status_code == 409 and PendingIntent.objects.get().version == 1


@pytest.mark.parametrize("selection", ["allowed", "outside", "known_field"])
def test_target_choices_and_known_fields_are_bounded(auth_client, user, monkeypatch, selection):
    schedule = Schedule.objects.create(user=user, date=DAY, status="active")
    blocks = [
        TimeBlock.objects.create(
            schedule=schedule,
            title=f"Gym {index}",
            category="health",
            start_time=f"{9 + index}:00",
            end_time=f"{9 + index}:30",
        )
        for index in range(3)
    ]
    scope = {
        "type": "update",
        "task_id": None,
        "target_ids": [blocks[0].pk, blocks[1].pk],
        "known_fields": {"category": "health"},
        "missing_fields": ["task_id", "start_time"],
    }
    ref, _, _ = ask(auth_client, user, monkeypatch, [scope])
    target = blocks[2] if selection == "outside" else blocks[1]
    original_start = target.start_time
    changes = {"start_time": "14:00"}
    if selection == "known_field":
        changes["category"] = "work"
    provider(
        monkeypatch,
        AIChatResult(
            "{}",
            [{"type": "update", "task_id": target.pk, "changes": changes}],
            "Moved.",
            None,
            intent_decision="continue",
        ),
    )
    response, _ = send(auth_client, user, "The second one at 14:00", ref)
    assert response.status_code == (200 if selection == "allowed" else 409), response.content
    target.refresh_from_db()
    assert target.category == "health"
    assert target.start_time == (
        datetime.time(14) if selection == "allowed" else datetime.time.fromisoformat(original_start)
    )


def test_answer_to_one_field_retains_other_fields(auth_client, user, monkeypatch):
    schedule = Schedule.objects.create(user=user, date=DAY, status="active")
    block = TimeBlock.objects.create(
        schedule=schedule, title="Gym", category="health", start_time="09:00", end_time="09:30"
    )
    scope = {
        "type": "update",
        "task_id": block.pk,
        "target_ids": [block.pk],
        "known_fields": {},
        "missing_fields": ["category", "start_time"],
    }
    ref, _, _ = ask(auth_client, user, monkeypatch, [scope])
    provider(
        monkeypatch,
        AIChatResult(
            "{}",
            [{"type": "update", "task_id": block.pk, "changes": {"category": "work"}}],
            "Changed category.",
            None,
            intent_decision="continue",
        ),
    )
    response, _ = send(auth_client, user, "Work category", ref)
    assert response.status_code == 200, response.content
    row = PendingIntent.objects.get()
    assert row.items[0]["missing_fields"] == ["start_time"]
    assert row.items[0]["known_fields"] == {"category": "work"}
    assert row.revision == 1 and row.version == 2
    provider(
        monkeypatch,
        AIChatResult(
            "{}",
            [{"type": "move", "task_id": block.pk, "start_time": "14:00"}],
            "Moved.",
            None,
            intent_decision="continue",
        ),
    )
    response, _ = send(auth_client, user, "14:00", response.json()["pending_intent"])
    assert response.status_code == 200, response.content
    block.refresh_from_db()
    assert block.start_time == datetime.time(14) and block.category == "work"


def test_missing_placement_cannot_be_bypassed_by_an_untimed_add(auth_client, user, monkeypatch):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    action = {"type": "add", "title": "Gym", "category": "health"}
    provider(monkeypatch, AIChatResult("{}", [action], "Added.", None, intent_decision="continue"))
    response, _ = send(auth_client, user, "Not sure yet", ref)
    assert response.status_code == 409 and not TimeBlock.objects.exists()


def test_deleted_schedule_is_not_recreated_by_an_old_intent(auth_client, user, monkeypatch):
    ref, _, _ = ask(auth_client, user, monkeypatch)
    Schedule.objects.get().delete()
    calls = provider(
        monkeypatch, AIChatResult("{}", [add()], "Added.", None, intent_decision="continue")
    )
    response, _ = send(auth_client, user, "14:00", ref, revision=0)
    assert response.status_code == 409 and response.json()["code"] == "pending_intent_stale"
    assert not calls and not Schedule.objects.exists() and not PendingIntent.objects.exists()


@pytest.mark.parametrize("malformed", [False, True])
def test_quoted_title_can_continue_after_rejected_provider_reply(
    auth_client, user, monkeypatch, malformed
):
    schedule = Schedule.objects.create(user=user, date=DAY)
    TimeBlock.objects.create(schedule=schedule, title="Gym", category="health",
                             start_time="09:00", end_time="09:30", sort_order=0)
    title = "Walk after lunch"
    command = f'Add "{title}" after Gym for 30 minutes. Ask for its start time first.'
    scope = item(title, known_fields={"title": title, "category": "health", "duration_minutes": 30},
                 missing_fields=["start_time"])
    replies = [
        {"actions": [], "ask": "What time?", "intent_decision": "new", "pending_actions": [scope]},
        {"actions": [{**add(title, "08:00", "08:30"), "task_id": 123 if malformed else None}],
         "ask": None,
         "intent_decision": "continue", "pending_actions": []},
        {"actions": [{**add(title, "10:00", "10:30"), "task_id": None}], "ask": None,
         "intent_decision": "continue", "pending_actions": []},
    ]
    calls = []

    async def completion(**kwargs):
        payload = {"explanation": "Plan.", **replies[len(calls)]}
        calls.append(kwargs)
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
        ])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "test-key")
    monkeypatch.setattr("ai.service._get_client", lambda: client)
    first, _ = send(auth_client, user, command)
    assert first.status_code == 200
    ref = first.json()["pending_intent"]
    history = [{"role": "user", "content": command},
               {"role": "assistant", "content": "What time?", "is_ask": True}]
    rejected, _ = send(auth_client, user, ref=ref,
                       messages=[*history, {"role": "user", "content": "08:00"}])
    assert rejected.status_code == (502 if malformed else 200)
    assert rejected.json()["request_completed"]
    assert PendingIntent.objects.get().items == [scope]
    assert PendingIntent.objects.get().version == ref["version"] + (0 if malformed else 1)
    assert TimeBlock.objects.count() == 1 and Schedule.objects.get().revision == 0
    question = rejected.json()["errors"]["detail"] if malformed else rejected.json()["ask"]
    history += [
        {"role": "user", "content": "08:00"},
        {"role": "assistant", "content": question, "is_error" if malformed else "is_ask": True},
    ]
    if not malformed:
        ref = rejected.json()["pending_intent"]
    applied, body = send(auth_client, user, ref=ref,
                         messages=[*history, {"role": "user", "content": "10:00"}])
    assert applied.status_code == 200 and applied.json()["applied"]
    assert applied.json()["pending_intent"] is None
    assert TimeBlock.objects.get(title=title).start_time == datetime.time(10)
    assert TimeBlock.objects.get(title="Gym").start_time == datetime.time(9)
    replay = auth_client.post(URL, json.dumps(body), content_type="application/json")
    assert replay.content == applied.content and len(calls) == 3 and TimeBlock.objects.count() == 2
