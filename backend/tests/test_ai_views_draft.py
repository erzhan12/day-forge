"""Integration tests for ``ai_generate_draft``.

Patches ``ai.views.run_draft`` so no network call is made; the view's DB
interactions and the apply path are exercised for real.
"""
import datetime
import json
from zoneinfo import ZoneInfo

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
from django.core.cache import cache
from schedules.models import Schedule, TimeBlock, UserScheduleSettings
from templates_mgr.models import Rule, Template

URL = "/api/ai/schedules/2026-05-04/generate-draft/"


def _post(client, url=URL, body=""):
    return client.post(url, body, content_type="application/json")


def _set_window(user, day_start, day_end):
    """Seed the per-user schedule window (feature 0053).

    ``_apply_draft_sync`` resolves the window under its ``select_for_update``
    lock via ``get_schedule_window`` → ``UserScheduleSettings`` and threads it
    into ``_apply_add`` → ``_check_day_window``. Seeding a row is how a
    non-default window reaches the draft guard in these integration tests.
    """
    UserScheduleSettings.objects.update_or_create(
        user=user, defaults={"day_start": day_start, "day_end": day_end}
    )


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

    def test_draft_bucket_independent_of_chat_bucket(
        self, auth_client, user, template, monkeypatch
    ):
        # A draft call increments ONLY ai_draft_rl, never the chat bucket —
        # guards against the two key literals being swapped in
        # ai_generate_draft. Reverse direction of
        # test_ai_views_chat.py::test_chat_bucket_independent_of_draft_bucket.
        _patch_run(monkeypatch, _ok_result())
        resp = _post(auth_client)
        assert resp.status_code == 200
        assert cache.get(f"ai_draft_rl:{user.id}") == 1
        assert cache.get(f"ai_chat_rl:{user.id}") in (None, 0)


@pytest.mark.django_db
class TestDraftStoredTimezone:
    """Draft prompt context derives solely from persisted user settings."""

    FIXED_UTC = datetime.datetime(2026, 4, 18, 4, 2, 30, tzinfo=datetime.UTC)

    def test_draft_prompt_uses_stored_timezone(self, auth_client, user, template, monkeypatch):
        import ai.views as views

        captured = {}

        async def _capture(schedule, tmpl, history, rules, now):
            captured["now"] = now
            return AIDraftResult("{}", [], "ok")

        monkeypatch.setattr(views.timezone, "now", lambda: self.FIXED_UTC)
        monkeypatch.setattr(views, "run_draft", _capture)

        UserScheduleSettings.objects.create(user=user, time_zone="Asia/Almaty")
        resp = _post(auth_client, body=json.dumps({"client_tz": "Pacific/Kiritimati"}))
        assert resp.status_code == 200, resp.content
        assert captured["now"].tzinfo == ZoneInfo("Asia/Almaty")
        assert captured["now"].strftime("%Y-%m-%d %H:%M:%S") == "2026-04-18 09:02:30"

    def test_applying_draft_looks_up_settings_once_for_prompt_and_once_for_apply(
        self, auth_client, user, template, monkeypatch
    ):
        import ai.views as views

        original_settings = views.get_schedule_settings
        original_window = views.get_schedule_window
        lookups = []

        def _settings_spy(subject):
            lookups.append(("prompt", subject.pk))
            return original_settings(subject)

        def _window_spy(subject):
            lookups.append(("apply", subject.pk))
            return original_window(subject)

        monkeypatch.setattr(views, "get_schedule_settings", _settings_spy)
        monkeypatch.setattr(views, "get_schedule_window", _window_spy)
        _patch_run(monkeypatch, _ok_result())

        response = _post(auth_client)

        assert response.status_code == 200, response.content
        assert lookups == [("prompt", user.pk), ("apply", user.pk)]

    def test_next_draft_uses_timezone_changed_via_settings_api(
        self, auth_client, user, template, monkeypatch
    ):
        import ai.views as views

        captured = []

        async def _capture(schedule, tmpl, history, rules, now):
            captured.append(now)
            return AIDraftResult("{}", [], "ok")

        monkeypatch.setattr(views.timezone, "now", lambda: self.FIXED_UTC)
        monkeypatch.setattr(views, "run_draft", _capture)

        first = _post(auth_client)
        changed = auth_client.patch(
            "/api/user/schedule-settings/",
            data=json.dumps({"time_zone": "Asia/Almaty"}),
            content_type="application/json",
        )
        second = _post(auth_client)

        assert first.status_code == 200
        assert changed.status_code == 200
        assert second.status_code == 200
        assert captured[0].tzinfo == ZoneInfo("UTC")
        assert captured[1].tzinfo == ZoneInfo("Asia/Almaty")

    @pytest.mark.parametrize(
        "body",
        ["", "{}", '{"client_tz":"Not/AZone"}', '{"client_tz":[]}', "{", "[]"],
    )
    def test_optional_timezone_body_is_ignored_in_favor_of_stored_zone(
        self, auth_client, user, template, monkeypatch, body
    ):
        import ai.views as views

        captured = {}

        async def _capture(schedule, tmpl, history, rules, now):
            captured["now"] = now
            return AIDraftResult("{}", [], "ok")

        monkeypatch.setattr(views.timezone, "now", lambda: self.FIXED_UTC)
        monkeypatch.setattr(views, "run_draft", _capture)

        UserScheduleSettings.objects.create(user=user, time_zone="Asia/Almaty")
        resp = _post(auth_client, body=body)
        assert resp.status_code == 200, resp.content
        assert captured["now"].tzinfo == ZoneInfo("Asia/Almaty")
        assert captured["now"].strftime("%Y-%m-%d %H:%M:%S") == "2026-04-18 09:02:30"

    def test_invalidly_encoded_optional_body_falls_back_without_error(
        self, auth_client, template, monkeypatch
    ):
        import ai.views as views

        captured = {}

        async def _capture(schedule, tmpl, history, rules, now):
            captured["now"] = now
            return AIDraftResult("{}", [], "ok")

        monkeypatch.setattr(views, "run_draft", _capture)
        # Pin the instant so the UTC assertion is self-documenting and immune
        # to the real wall clock rather than relying on it.
        monkeypatch.setattr(
            views.timezone,
            "now",
            lambda: datetime.datetime(2026, 4, 18, 4, 2, 30, tzinfo=datetime.UTC),
        )

        resp = _post(auth_client, body=b"\xff\xfe")
        assert resp.status_code == 200, resp.content
        # Draft bodies are no longer parsed for a timezone at all.
        assert captured["now"].tzinfo == ZoneInfo("UTC")
        assert captured["now"].strftime("%Y-%m-%d %H:%M:%S") == "2026-04-18 04:02:30"


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


class TestActiveRulesWiring:
    """Feature 0012: ``ai_generate_draft`` must pass only the
    authenticated user's ACTIVE rules to ``run_draft``, ordered by
    ``-priority``. Same shape as the chat view assertion so the two
    endpoints can't drift on the rule-loading contract — the
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


@pytest.mark.django_db
class TestDraftDayWindow:
    """Feature 0053: the draft apply path threads the per-user window (resolved
    under the apply lock in ``_apply_draft_sync``) into ``_apply_add`` →
    ``_check_day_window``. The guard REJECTS out-of-window draft adds and names
    the user's bound, not the stale default 23:00.
    """

    def _draft_add(self, start, end):
        return AIDraftResult(
            raw_response_text='{"actions":[...],"explanation":"ok"}',
            parsed_actions=[
                {
                    "type": "add",
                    "title": "Draft block",
                    "start_time": start,
                    "end_time": end,
                    "category": "work",
                }
            ],
            explanation="Generated draft",
        )

    def test_draft_add_rejected_under_narrowed_window_names_narrowed_bound(
        self, auth_client, user, template, monkeypatch
    ):
        # 22:00–22:30 is inside the default 06:00–23:00 but outside a narrowed
        # 08:00–21:00 → rejected with 21:00 in the detail (not 23:00), and no
        # block persisted.
        _set_window(user, datetime.time(8, 0), datetime.time(21, 0))
        _patch_run(monkeypatch, self._draft_add("22:00", "22:30"))
        resp = _post(auth_client)
        assert resp.status_code == 400
        detail = resp.json()["errors"]["detail"]
        assert "21:00" in detail
        assert "23:00" not in detail
        schedule = Schedule.objects.get(user=user, date="2026-05-04")
        assert TimeBlock.objects.filter(schedule=schedule).count() == 0

    def test_draft_add_rejected_under_default_window(
        self, auth_client, user, template, monkeypatch
    ):
        # Same 23:00–23:30 add is rejected under the DEFAULT window — proving the
        # widened-window acceptance below is genuinely window-driven.
        _set_window(user, datetime.time(6, 0), datetime.time(23, 0))
        _patch_run(monkeypatch, self._draft_add("23:00", "23:30"))
        resp = _post(auth_client)
        assert resp.status_code == 400
        assert "23:00" in resp.json()["errors"]["detail"]

    def test_draft_add_accepted_under_widened_window(
        self, auth_client, user, template, monkeypatch
    ):
        # A draft add ending 23:30 is accepted under a widened 06:00–23:55
        # window (23:55, not 23:59 — 5-minute-valid).
        _set_window(user, datetime.time(6, 0), datetime.time(23, 55))
        _patch_run(monkeypatch, self._draft_add("23:00", "23:30"))
        resp = _post(auth_client)
        assert resp.status_code == 200, resp.content
        schedule = Schedule.objects.get(user=user, date="2026-05-04")
        blocks = list(TimeBlock.objects.filter(schedule=schedule))
        assert len(blocks) == 1
        assert blocks[0].start_time.strftime("%H:%M") == "23:00"
        assert blocks[0].end_time.strftime("%H:%M") == "23:30"
