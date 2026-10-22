"""Durable HTTP outcomes and crash/fencing boundaries, using the real DB."""

import datetime
import json
import uuid
from pathlib import Path

import pytest
from ai.chat_requests import ChatClaim, claim_request, finish_request, request_identity
from ai.models import AIInteraction, ChatRequest
from ai.service import AIChatResult, AIProviderError
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import JsonResponse
from django.test import Client
from django.utils import timezone
from schedules.models import Schedule, TimeBlock

from tests.test_schedule_mutations_sqlite import copied_database, run_on_copy  # noqa: F401

DAY = "2027-01-15"
URL = f"/api/ai/schedules/{DAY}/chat/"


def body(**changes):
    return {
        "request_id": str(uuid.uuid4()), "expected_revision": 0,
        "messages": [{"role": "user", "content": "Add Smoke at 14:00 for 30 minutes"}],
        **changes,
    }


def post(client, payload, url=URL):
    return client.post(url, json.dumps(payload), content_type="application/json")


@pytest.fixture
def chat_provider(monkeypatch):
    calls = []

    async def provider(*args):
        calls.append(args)
        return AIChatResult(
            raw_response_text="{}", explanation="Added Smoke.", ask=None,
            parsed_actions=[{"type": "add", "title": "Smoke", "category": "work",
                             "start_time": "14:00", "end_time": "14:30"}],
        )

    monkeypatch.setattr("ai.views.run_chat", provider)
    return calls


@pytest.mark.django_db
class TestChatRequestHTTP:
    @pytest.mark.parametrize("value", [None, "", 1, {}, "not-a-uuid"])
    def test_invalid_identity_does_not_write_or_charge(self, auth_client, user, value):
        payload = body(request_id=value)
        response = post(auth_client, payload)
        assert response.status_code == 400
        assert not Schedule.objects.filter(user=user).exists()
        assert not ChatRequest.objects.exists()
        assert cache.get(f"ai_chat_rl:{user.id}") is None

    def test_missing_identity_is_rejected_by_real_client(self, user):
        client = Client()
        client.force_login(user)
        payload = body()
        del payload["request_id"]
        assert post(client, payload).status_code == 400
        assert not ChatRequest.objects.exists()

    def test_lost_response_replays_exact_result_before_stale_revision(self, auth_client, user,
                                                                    chat_provider):
        payload = body()
        lost = post(auth_client, payload)
        assert lost.status_code == 200
        schedule = Schedule.objects.get(user=user, date=DAY)
        assert schedule.revision == 1
        # Ignore the first response, then retry the original frozen revision 0.
        recovered = post(auth_client, dict(reversed(list(payload.items()))))
        assert recovered.status_code == lost.status_code
        assert recovered.content == lost.content
        assert len(chat_provider) == 1
        assert schedule.time_blocks.count() == 1
        assert AIInteraction.objects.count() == 1
        assert cache.get(f"ai_chat_rl:{user.id}") == 1
        assert recovered.json()["request_completed"] is True
        assert recovered.json()["request_id"] == payload["request_id"]

    def test_tight_window_result_replays_after_clock_advances(self, auth_client, user, monkeypatch):
        schedule = Schedule.objects.create(user=user, date=DAY)
        TimeBlock.objects.create(schedule=schedule, title="Standup", category="work",
                                 start_time="10:30", end_time="10:55")
        calls = []

        async def provider(*args):
            calls.append(args)
            return AIChatResult(
                "{}", [{"type": "add", "title": "Write report", "category": "work"}],
                "Added Write report.", None,
            )

        monkeypatch.setattr("ai.views.run_chat", provider)
        now = datetime.datetime.combine(datetime.date.fromisoformat(DAY), datetime.time(10, 3))
        monkeypatch.setattr("ai.views.timezone.localtime", lambda *a, **k: now)
        payload = body(messages=[{"role": "user", "content": "add Write report"}])
        first = post(auth_client, payload)
        assert first.status_code == 200, first.content
        assert first.json()["outcomes"][0]["status"] == "applied"
        report = schedule.time_blocks.get(title="Write report")
        assert (report.start_time, report.end_time) == (datetime.time(10, 5), datetime.time(10, 30))
        schedule.refresh_from_db()
        assert schedule.revision == 1
        now = datetime.datetime.combine(datetime.date.fromisoformat(DAY), datetime.time(11))
        replay = post(auth_client, payload)
        assert replay.status_code == first.status_code
        assert replay.content == first.content
        assert len(calls) == 1
        assert schedule.time_blocks.filter(title="Write report").count() == 1
        schedule.refresh_from_db()
        assert schedule.revision == 1

    @pytest.mark.parametrize("ask", [None, "Which slot?"])
    def test_empty_outcomes_are_preserved_in_audit_and_receipt(
        self, auth_client, monkeypatch, ask
    ):
        calls = []

        async def provider(*args):
            calls.append(args)
            return AIChatResult("{}", [], "No changes.", ask)

        monkeypatch.setattr("ai.views.run_chat", provider)
        payload = body()
        response = post(auth_client, payload)
        assert response.status_code == 200
        assert response.json()["outcomes"] == []
        interaction = AIInteraction.objects.get()
        assert interaction.success is True
        assert interaction.outcomes_json == []
        assert post(auth_client, payload).content == response.content
        assert len(calls) == 1
        assert AIInteraction.objects.count() == 1

    @pytest.mark.parametrize("change", [
        {"messages": [{"role": "user", "content": "Different command"}]},
        {"expected_revision": 99}, {"extra": "different payload"},
        {"messages": [{"role": "user", "content": "Earlier"},
                      {"role": "assistant", "content": "Ask?", "is_ask": True},
                      {"role": "user", "content": "Add Smoke at 14:00 for 30 minutes"}]},
    ])
    def test_identity_binds_entire_body(self, auth_client, chat_provider, change):
        payload = body()
        assert post(auth_client, payload).status_code == 200
        response = post(auth_client, {**payload, **change})
        assert response.status_code == 409
        assert response.json()["code"] == "request_id_conflict"
        assert len(chat_provider) == 1

    def test_other_owner_and_date_have_independent_namespaces(self, auth_client, chat_provider):
        payload = body()
        assert post(auth_client, payload).status_code == 200
        assert post(auth_client, payload, "/api/ai/schedules/2027-01-16/chat/").status_code == 200
        other = User.objects.create_user(username="other-owner")
        client = Client()
        client.force_login(other)
        assert post(client, payload).status_code == 200
        assert len(chat_provider) == 3
        assert ChatRequest.objects.count() == 3

    def test_new_uuid_is_an_explicit_new_request(self, auth_client, chat_provider):
        first = body()
        assert post(auth_client, first).status_code == 200
        # Explicit same-title repeat at a different slot is a distinct action.
        second = body(expected_revision=1)
        second["messages"][0]["content"] = "Add Smoke again at 16:00"

        async def repeat(*args):
            chat_provider.append(args)
            return AIChatResult(raw_response_text="{}", explanation="Added again.", ask=None,
                                parsed_actions=[{"type": "add", "title": "Smoke",
                                                 "start_time": "16:00", "end_time": "16:30",
                                                 "category": "work"}])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("ai.views.run_chat", repeat)
            response = post(auth_client, second)
        assert response.status_code == 200
        assert len(chat_provider) == 2
        assert TimeBlock.objects.count() == 2

    def test_provider_error_is_terminal_and_new_id_can_retry(self, auth_client, monkeypatch,
                                                           chat_provider):
        payload = body()
        calls = []

        async def failure(*args):
            calls.append(args)
            raise AIProviderError("Provider offline")

        with monkeypatch.context() as mp:
            mp.setattr("ai.views.run_chat", failure)
            first = post(auth_client, payload)
            second = post(auth_client, payload)
        assert first.status_code >= 500
        assert first.content == second.content
        assert first.json()["request_completed"] is True
        assert len(calls) == 1
        assert not TimeBlock.objects.exists()
        assert post(auth_client, body()).status_code == 200
        assert len(chat_provider) == 1

    def test_receipt_storage_failure_rolls_back_schedule_then_can_recover(
        self, auth_client, monkeypatch, chat_provider
    ):
        payload = body()
        save = ChatRequest.save

        def crash(row, *args, **kwargs):
            if row.completed_at is not None:
                raise RuntimeError("Crash before receipt commit")
            return save(row, *args, **kwargs)

        with monkeypatch.context() as mp:
            mp.setattr(ChatRequest, "save", crash)
            with pytest.raises(RuntimeError, match="receipt commit"):
                post(auth_client, payload)
        assert not TimeBlock.objects.exists()
        assert Schedule.objects.get().revision == 0
        row = ChatRequest.objects.get()
        assert row.completed_at is None
        ChatRequest.objects.update(lease_expires_at=timezone.now()-datetime.timedelta(seconds=1))
        recovered = post(auth_client, payload)
        assert recovered.status_code == 200
        assert TimeBlock.objects.count() == 1
        assert len(chat_provider) == 2

    def test_completed_identity_survives_schedule_deletion(self, auth_client, chat_provider):
        payload = body()
        first = post(auth_client, payload)
        Schedule.objects.all().delete()
        assert post(auth_client, payload).content == first.content
        assert not Schedule.objects.exists()
        assert len(chat_provider) == 1


@pytest.mark.django_db
def test_expired_worker_cannot_apply_after_takeover(user):
    payload = body()
    identity, digest = request_identity(payload)
    first = claim_request(user.id, DAY, identity, digest)
    assert isinstance(first, ChatClaim)
    waiting = claim_request(user.id, DAY, identity, digest)
    assert waiting.status_code == 409
    assert waiting["Retry-After"] == "2"
    ChatRequest.objects.update(lease_expires_at=timezone.now()-datetime.timedelta(seconds=1))
    second = claim_request(user.id, DAY, identity, digest)
    assert second.token != first.token

    def must_not_run():
        pytest.fail("Stale worker entered the apply transaction")

    assert finish_request(first, must_not_run).status_code == 409
    winner = finish_request(second, lambda: JsonResponse({"winner": True}))
    assert finish_request(first, must_not_run).content == winner.content


def test_two_processes_send_same_http_request(copied_database):  # noqa: F811 (imported fixture)
    run_on_copy(copied_database, r'''
import json, os, subprocess, sys, uuid
from django.contrib.auth.models import User
from ai.models import ChatRequest
user = User.objects.create_user(username='process-chat')
identity = str(uuid.uuid4())
worker = WORKER_PATH
processes=[subprocess.Popen([sys.executable,worker,sys.argv[1],str(user.pk),identity],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
           for _ in range(2)]
results=[]
for process in processes:
    out,err=process.communicate(timeout=15)
    assert process.returncode==0,err
    results.append(out.strip())
assert '200' in results,results
assert all(value in ('200','409') for value in results),results
from pathlib import Path
from schedules.models import TimeBlock, Schedule
assert (Path(sys.argv[1]).parent/'provider-calls').read_text().splitlines()==['call']
assert TimeBlock.objects.count()==1
assert Schedule.objects.get().revision==1
assert ChatRequest.objects.count()==1
assert ChatRequest.objects.get().completed_at is not None
'''.replace('WORKER_PATH', repr(str(Path(__file__).parent / 'helpers/parallel_chat_worker.py'))))
