"""Integration tests for ``ai_generate_draft``.

Patches ``ai.views.run_draft`` so no network call is made; the view's DB
interactions and the apply path are exercised for real.
"""
import datetime
import json

import pytest
from ai.models import AIInteraction
from ai.service import (
    AIDraftResult,
    AIParseError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
)
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Rule, Template

URL = "/api/ai/schedules/2026-05-04/generate-draft/"


def _post(client, url=URL):
    return client.post(url, "", content_type="application/json")


def _patch_run(monkeypatch, behaviour):
    """``ai.views.run_draft`` is async (feature 0009) — replacement must be ``async def``."""

    async def _run(*args, **kwargs):
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour
    monkeypatch.setattr("ai.views.run_draft", _run)


@pytest.fixture
def template(user):
    return Template.objects.create(
        user=user,
        name="WD",
        type="weekday",
        blocks=[
            {
                "title": "Deep work",
                "start_time": "09:00",
                "end_time": "12:00",
                "category": "work",
            }
        ],
    )


def _ok_result():
    return AIDraftResult(
        raw_response_text='{"actions":[...],"explanation":"ok"}',
        parsed_actions=[
            {
                "type": "add",
                "title": "Standup",
                "start_time": "09:00",
                "end_time": "09:15",
                "category": "work",
            },
            {
                "type": "add",
                "title": "Deep work",
                "start_time": "09:15",
                "end_time": "12:00",
                "category": "work",
            },
        ],
        explanation="Generated draft",
    )


@pytest.mark.django_db
class TestRouting:
    def test_requires_auth(self, client):
        resp = _post(client)
        assert resp.status_code == 302

    def test_invalid_date(self, auth_client):
        resp = _post(
            auth_client, url="/api/ai/schedules/not-a-date/generate-draft/"
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestHappyPath:
    def test_generates_draft_and_keeps_status_draft(
        self, auth_client, user, template, monkeypatch
    ):
        _patch_run(monkeypatch, _ok_result())
        resp = _post(auth_client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["explanation"] == "Generated draft"
        assert len(data["blocks"]) == 2

        schedule = Schedule.objects.get(user=user, date="2026-05-04")
        assert schedule.status == Schedule.Status.DRAFT
        assert TimeBlock.objects.filter(schedule=schedule).count() == 2

        log = AIInteraction.objects.get(schedule=schedule)
        assert log.kind == AIInteraction.Kind.DRAFT
        assert log.success is True


@pytest.mark.django_db
class TestPreconditions:
    def test_409_when_schedule_has_blocks(
        self, auth_client, user, template, monkeypatch
    ):
        schedule = Schedule.objects.create(
            user=user, date=datetime.date(2026, 5, 4)
        )
        TimeBlock.objects.create(
            schedule=schedule,
            title="Existing",
            start_time="08:00",
            end_time="09:00",
            category="work",
        )
        called = {"v": False}

        async def _should_not_run(*a, **k):
            called["v"] = True
            return _ok_result()

        monkeypatch.setattr("ai.views.run_draft", _should_not_run)
        resp = _post(auth_client)
        assert resp.status_code == 409
        assert called["v"] is False
        assert AIInteraction.objects.count() == 0

    def test_422_when_no_template(self, auth_client, user, monkeypatch):
        called = {"v": False}

        async def _should_not_run(*a, **k):
            called["v"] = True
            return _ok_result()

        monkeypatch.setattr("ai.views.run_draft", _should_not_run)
        resp = _post(auth_client)
        assert resp.status_code == 422
        assert called["v"] is False
        assert AIInteraction.objects.count() == 0

    def test_cross_user_template_does_not_satisfy_lookup(
        self, auth_client, user, monkeypatch
    ):
        other = User.objects.create_user(username="other-tpl", password="x")
        Template.objects.create(
            user=other, name="WD", type="weekday", blocks=[]
        )
        # The current user has no template — should still 422.
        called = {"v": False}

        async def _should_not_run(*a, **k):
            called["v"] = True
            return _ok_result()

        monkeypatch.setattr("ai.views.run_draft", _should_not_run)
        resp = _post(auth_client)
        assert resp.status_code == 422
        assert called["v"] is False


@pytest.mark.django_db
class TestProviderErrors:
    @pytest.mark.parametrize(
        ("exc", "status"),
        [
            (AIUnavailableError("no key"), 503),
            (AITimeoutError("slow"), 504),
            (AIProviderError("bad"), 502),
            (AIParseError("bad json", raw_response_text="<raw>"), 502),
        ],
    )
    def test_errors_mapped(
        self, auth_client, user, template, monkeypatch, exc, status
    ):
        _patch_run(monkeypatch, exc)
        resp = _post(auth_client)
        assert resp.status_code == status
        # Failure is logged as a draft interaction.
        log = AIInteraction.objects.get()
        assert log.kind == AIInteraction.Kind.DRAFT
        assert log.success is False


@pytest.mark.django_db
class TestApplyLocksScheduleRow:
    """Regression: the apply phase MUST acquire its row lock on the
    ``Schedule`` row, not on the (typically empty) ``TimeBlock``
    queryset. An empty queryset locks zero rows; two concurrent draft
    requests would both pass the in-lock emptiness check and both
    insert.

    SQLite silently strips ``FOR UPDATE`` from the executed SQL (see
    ``schedules.W001``), so we can't grep ``connection.queries``. Instead
    we spy on the manager's ``select_for_update`` method and assert it
    was invoked on the ``Schedule`` manager during the apply phase.
    """

    def test_locks_schedule_row(
        self, auth_client, user, template, monkeypatch
    ):
        from schedules.models import Schedule as _Schedule

        _patch_run(monkeypatch, _ok_result())

        original = _Schedule.objects.select_for_update
        called = {"v": False}

        def _spy(*args, **kwargs):
            called["v"] = True
            return original(*args, **kwargs)

        monkeypatch.setattr(
            _Schedule.objects, "select_for_update", _spy, raising=True
        )

        resp = _post(auth_client)
        assert resp.status_code == 200, resp.content
        assert called["v"], (
            "ai_generate_draft must call Schedule.objects.select_for_update() "
            "during the apply phase to lock the parent row. Locking only the "
            "child TimeBlock queryset acquires zero locks on an empty "
            "schedule and lets concurrent drafts both insert."
        )


@pytest.mark.django_db
class TestRateLimitDoesNotFireOnPreconditionFailure:
    """Regression: 422 / 409 / 413 / 400 must not consume the draft
    budget. The plan explicitly calls this out — drafts use a heavier
    model and a small (default 10/hr) budget, so a misconfigured account
    or a stale page must not be able to drain it without any LLM call.
    """

    def _draft_count(self, user_id: int) -> int:
        from django.core.cache import cache

        return cache.get(f"ai_draft_rl:{user_id}") or 0

    def test_422_no_template_does_not_increment(
        self, auth_client, user, monkeypatch
    ):
        # No template fixture → 422.
        called = {"v": False}

        async def _fail(*a, **k):
            called["v"] = True
            return _ok_result()

        monkeypatch.setattr("ai.views.run_draft", _fail)
        resp = _post(auth_client)
        assert resp.status_code == 422
        assert called["v"] is False
        assert self._draft_count(user.id) == 0

    def test_409_existing_blocks_does_not_increment(
        self, auth_client, user, template, monkeypatch
    ):
        schedule = Schedule.objects.create(
            user=user, date=datetime.date(2026, 5, 4)
        )
        TimeBlock.objects.create(
            schedule=schedule,
            title="Existing",
            start_time="08:00",
            end_time="09:00",
            category="work",
        )
        monkeypatch.setattr(
            "ai.views.run_draft", lambda *a, **k: _ok_result()
        )
        resp = _post(auth_client)
        assert resp.status_code == 409
        assert self._draft_count(user.id) == 0

    def test_invalid_date_does_not_increment(
        self, auth_client, user, template
    ):
        resp = _post(
            auth_client,
            url="/api/ai/schedules/not-a-date/generate-draft/",
        )
        assert resp.status_code == 400
        assert self._draft_count(user.id) == 0

    def test_oversized_body_does_not_increment(
        self, auth_client, user, template
    ):
        # 100 KB cap is in ``schedules.http``; send 200 KB.
        resp = auth_client.post(
            URL,
            "x" * 200_000,
            content_type="application/json",
        )
        assert resp.status_code == 413
        assert self._draft_count(user.id) == 0

    def test_provider_failure_does_increment(
        self, auth_client, user, template, monkeypatch
    ):
        # 503 / 502 / 504 represent a real LLM call attempt — they
        # SHOULD increment the counter, otherwise a flapping provider
        # lets clients retry without limit.
        _patch_run(monkeypatch, AIUnavailableError("disabled"))
        resp = _post(auth_client)
        assert resp.status_code == 503
        assert self._draft_count(user.id) == 1


@pytest.mark.django_db
class TestRateLimit:
    def test_separate_counter_from_command(
        self, auth_client, user, template, monkeypatch, settings
    ):
        settings.LLM_DRAFT_RATE_LIMIT_PER_HOUR = 2
        settings.LLM_RATE_LIMIT_PER_HOUR = 100
        _patch_run(monkeypatch, _ok_result())

        # Two successes — but the first one creates blocks, so subsequent
        # calls should hit 409. We need to delete blocks between calls
        # to actually reach the rate-limit boundary. Simpler: monkeypatch
        # the run_draft to *raise* AIUnavailableError so no blocks get
        # created and the apply path is skipped, which lets us bump the
        # counter in a clean loop.
        _patch_run(monkeypatch, AIUnavailableError("disabled"))

        for i in range(2):
            resp = _post(auth_client)
            assert resp.status_code == 503, f"call {i}: {resp.status_code}"

        # Third call exceeds the budget.
        resp = _post(auth_client)
        assert resp.status_code == 429

    def test_command_counter_unaffected_by_draft(
        self, auth_client, user, template, monkeypatch, settings
    ):
        settings.LLM_DRAFT_RATE_LIMIT_PER_HOUR = 1
        settings.LLM_RATE_LIMIT_PER_HOUR = 5
        _patch_run(monkeypatch, AIUnavailableError("disabled"))

        # Burn the draft budget.
        _post(auth_client)
        resp = _post(auth_client)
        assert resp.status_code == 429

        # Command bar should still be available — patching ai_command's
        # path is overkill here; we just confirm the rate-limit decorator
        # uses different keys by checking ai_command's first call doesn't
        # 429. Bypass the LLM by leaving LLM_API_KEY empty.
        settings.LLM_API_KEY = ""
        resp = auth_client.post(
            "/api/ai/schedules/2026-05-04/command/",
            json.dumps({"command": "hi"}),
            content_type="application/json",
        )
        assert resp.status_code == 503  # AIUnavailableError, NOT 429


@pytest.mark.django_db
class TestStatusFlow:
    def test_ai_command_with_empty_actions_does_not_flip_status(
        self, auth_client, user, monkeypatch
    ):
        # ``ai_command`` with actions=[] is a successful no-op per
        # RULES.md. Status must stay ``draft``.
        from ai.service import AICommandResult

        schedule = Schedule.objects.create(
            user=user, date=datetime.date(2026, 5, 4)
        )

        async def _run(*args, **kwargs):
            return AICommandResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="nothing to do",
            )

        monkeypatch.setattr("ai.views.run_command", _run)
        resp = auth_client.post(
            "/api/ai/schedules/2026-05-04/command/",
            json.dumps({"command": "hi"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        schedule.refresh_from_db()
        assert schedule.status == Schedule.Status.DRAFT

    def test_ai_command_with_actions_flips_status(
        self, auth_client, user, monkeypatch
    ):
        from ai.service import AICommandResult

        schedule = Schedule.objects.create(
            user=user, date=datetime.date(2026, 5, 4)
        )

        async def _run(*args, **kwargs):
            return AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Standup",
                        "start_time": "10:00",
                        "end_time": "10:15",
                        "category": "work",
                    }
                ],
                explanation="added",
            )

        monkeypatch.setattr("ai.views.run_command", _run)
        resp = auth_client.post(
            "/api/ai/schedules/2026-05-04/command/",
            json.dumps({"command": "add standup"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        schedule.refresh_from_db()
        assert schedule.status == Schedule.Status.ACTIVE


class TestActiveRulesWiring:
    """Feature 0012: ``ai_generate_draft`` must pass only the
    authenticated user's ACTIVE rules to ``run_draft``, ordered by
    ``-priority``. Same shape as the command and chat view assertions so
    the three endpoints can't drift on the rule-loading contract — the
    refactor moved the inline query into the shared
    ``_load_active_rules`` helper, and this test pins the invariant for
    the draft side.
    """

    @pytest.mark.django_db
    def test_only_authenticated_users_active_rules_are_passed(
        self, auth_client, user, template, monkeypatch
    ):
        Rule.objects.create(
            user=user, text="HIGH rule", priority=10, is_active=True
        )
        Rule.objects.create(
            user=user, text="LOW rule", priority=1, is_active=True
        )
        Rule.objects.create(
            user=user, text="INACTIVE", priority=99, is_active=False
        )
        other_user = User.objects.create_user(username="other", password="x")
        Rule.objects.create(
            user=other_user, text="OTHER USER", priority=99, is_active=True
        )

        captured = {}

        async def _capture(schedule, tmpl, history, rules, now):
            captured["rules_texts"] = [r.text for r in rules]
            return AIDraftResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="ok",
            )

        monkeypatch.setattr("ai.views.run_draft", _capture)
        resp = _post(auth_client)
        assert resp.status_code == 200
        assert captured["rules_texts"] == ["HIGH rule", "LOW rule"]
