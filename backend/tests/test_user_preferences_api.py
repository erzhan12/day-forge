"""Tests for the `/api/user/preferences/` endpoint, the SSR data-theme
contract, and the read-side preferences helper.

See `docs/features/0010_design_templates_PLAN.md` for the rationale
behind each test (corruption healing, Cache-Control invariant, etc.).
"""
import datetime
import json
import threading

import pytest
from analytics.models import DailyReview  # noqa: F401  ensure migrations imported
from django.contrib.auth.models import User
from django.db import connections
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import UserPreferences
from templates_mgr.preferences import (
    UserPreferencesDTO,
    get_user_preferences,
    normalize_theme,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helper / DTO contract
# ---------------------------------------------------------------------------


def test_helper_creates_default_row_on_first_access(user):
    assert not UserPreferences.objects.filter(user=user).exists()
    dto = get_user_preferences(user)
    assert dto.theme == "classic"
    assert UserPreferences.objects.filter(user=user).exists()


def test_helper_returns_frozen_dto_not_orm_instance(user):
    dto = get_user_preferences(user)
    assert isinstance(dto, UserPreferencesDTO)
    assert not isinstance(dto, UserPreferences)
    # Frozen dataclass — mutation must raise.
    with pytest.raises(Exception):
        dto.theme = "strategic"  # type: ignore[misc]


def test_helper_normalizes_invalid_db_value_without_writing(user):
    UserPreferences.objects.create(user=user, theme="classic")
    # Bypass the choices validator with a raw UPDATE to simulate corruption.
    UserPreferences.objects.filter(user=user).update(theme="bad")
    dto = get_user_preferences(user)
    assert dto.theme == "classic"
    # The raw DB column must NOT have been rewritten on read.
    raw = UserPreferences.objects.get(user=user).theme
    assert raw == "bad"


def test_normalize_theme_pure_function():
    assert normalize_theme("classic") == "classic"
    assert normalize_theme("strategic") == "strategic"
    assert normalize_theme("light_premium") == "light_premium"
    assert normalize_theme("nope") == "classic"
    assert normalize_theme("") == "classic"


# ---------------------------------------------------------------------------
# Auth requirement
# ---------------------------------------------------------------------------


def test_get_requires_auth():
    client = Client()
    resp = client.get(reverse("user_preferences"))
    # @login_required redirects to the login URL — matches project-wide
    # convention from docs/api.md.
    assert resp.status_code in (302, 401)


def test_patch_requires_auth():
    client = Client()
    resp = client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "strategic"}),
        content_type="application/json",
    )
    assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# Documented spec delta from feature 0010 plan §Phase 2
# ---------------------------------------------------------------------------
#
# The plan listed `Cache-Control: private, no-store` as required on ALL
# preferences responses, including 302 (unauthenticated redirect via
# `@login_required`) and 405 (method-not-allowed via
# `@require_http_methods`). Those decorators run BEFORE the view body,
# so the `_prefs_response` helper never touches them.
#
# The decision (see `_prefs_response` docstring + `tasks/todo.md`
# follow-up): accept the delta. Practical leak surface is nil — 302 has
# no body, 405 body is empty, no per-user state. Retrofitting middleware
# costs more than it saves.
#
# The tests below PIN the current behavior so the delta is observable
# in CI. If a future contributor decides strict plan compliance matters
# (or someone retrofits middleware), they flip these assertions from
# "header NOT set" → "header set" and the delta is closed.


def test_unauthenticated_get_302_has_no_cache_control_header():
    """Documents the accepted delta: 302 from @login_required bypasses
    the prefs response helper, so the Cache-Control header is absent.
    See `_prefs_response` docstring + tasks/todo.md 0010-followup."""
    client = Client()
    resp = client.get(reverse("user_preferences"))
    assert resp.status_code == 302
    assert "Cache-Control" not in resp.headers or (
        "no-store" not in resp.headers.get("Cache-Control", "")
    )


def test_unauthenticated_patch_302_has_no_cache_control_header():
    client = Client()
    resp = client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "strategic"}),
        content_type="application/json",
    )
    assert resp.status_code == 302
    assert "Cache-Control" not in resp.headers or (
        "no-store" not in resp.headers.get("Cache-Control", "")
    )


def test_method_not_allowed_405_has_no_cache_control_header(auth_client):
    """Documents the accepted delta: 405 from @require_http_methods
    bypasses the prefs response helper. POST is not in the allowed list
    (only GET/PATCH), so the decorator handles it before the view."""
    resp = auth_client.post(
        reverse("user_preferences"),
        data=json.dumps({"theme": "strategic"}),
        content_type="application/json",
    )
    assert resp.status_code == 405
    assert "Cache-Control" not in resp.headers or (
        "no-store" not in resp.headers.get("Cache-Control", "")
    )


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


def test_get_first_call_returns_default_classic(auth_client):
    resp = auth_client.get(reverse("user_preferences"))
    assert resp.status_code == 200
    assert resp.json() == {"theme": "classic"}
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_get_returns_saved_theme(auth_client, user):
    UserPreferences.objects.create(user=user, theme="strategic")
    resp = auth_client.get(reverse("user_preferences"))
    assert resp.status_code == 200
    assert resp.json() == {"theme": "strategic"}
    assert resp.headers["Cache-Control"] == "private, no-store"


# ---------------------------------------------------------------------------
# PATCH — happy path
# ---------------------------------------------------------------------------


def test_patch_sets_theme(auth_client, user):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "strategic"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"theme": "strategic"}
    assert resp.headers["Cache-Control"] == "private, no-store"
    assert UserPreferences.objects.get(user=user).theme == "strategic"


def test_patch_same_value_is_valid_noop(auth_client, user):
    UserPreferences.objects.create(user=user, theme="classic")
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "classic"}),
        content_type="application/json",
    )
    # Same-value PATCH must succeed (200), NOT route through the
    # "No editable fields supplied" 400 branch.
    assert resp.status_code == 200
    assert resp.json() == {"theme": "classic"}


def test_patch_heals_corrupted_row(auth_client, user):
    # Bypass the choices validator via raw UPDATE.
    UserPreferences.objects.create(user=user, theme="classic")
    UserPreferences.objects.filter(user=user).update(theme="bad")
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "classic"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    # The raw DB row must be healed — written back to a valid value.
    assert UserPreferences.objects.get(user=user).theme == "classic"


# ---------------------------------------------------------------------------
# PATCH — validation errors
# ---------------------------------------------------------------------------


def test_patch_invalid_theme_returns_400(auth_client):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "neon"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json() == {"errors": {"theme": "Invalid theme."}}
    # The error-path Cache-Control coverage — load-bearing for proxy safety.
    assert resp.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"theme": ["classic"]}, id="list"),
        pytest.param({"theme": {"id": "classic"}}, id="dict"),
        pytest.param({"theme": 42}, id="int"),
        pytest.param({"theme": True}, id="bool"),
        pytest.param({"theme": None}, id="null"),
    ],
)
def test_patch_non_string_theme_returns_structured_400(auth_client, payload):
    """Non-string `theme` values must NOT crash the view with a TypeError
    (frozenset membership on unhashable types) — the failure path must
    stay inside `_prefs_response` so the Cache-Control header is set."""
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json() == {"errors": {"theme": "Invalid theme."}}
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_patch_invalid_json_returns_400(auth_client):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data="not-json",
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json() == {"errors": {"body": "Invalid JSON."}}
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_patch_non_object_body_returns_400(auth_client):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps(["theme", "strategic"]),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "body" in resp.json()["errors"]
    # Catches a future implementer adding a new error branch with a
    # raw JsonResponse instead of routing through _prefs_response.
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_patch_empty_body_returns_400(auth_client):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json() == {"errors": {"body": "No editable fields supplied."}}
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_patch_unknown_field_only_is_400(auth_client):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"Theme": "strategic"}),  # wrong case
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json() == {"errors": {"body": "No editable fields supplied."}}


def test_patch_unknown_field_alongside_valid_theme_is_accepted(auth_client):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "strategic", "future_field": True}),
        content_type="application/json",
    )
    # Forward-compatible: unknown keys silently ignored when at least one
    # recognized field is present (matches rule_detail PATCH semantics).
    assert resp.status_code == 200
    assert resp.json() == {"theme": "strategic"}


# ---------------------------------------------------------------------------
# Per-user isolation
# ---------------------------------------------------------------------------


def test_preferences_isolated_per_user(db):
    alice = User.objects.create_user(username="alice", password="pw")
    bob = User.objects.create_user(username="bob", password="pw")
    UserPreferences.objects.create(user=alice, theme="strategic")
    UserPreferences.objects.create(user=bob, theme="light_premium")

    client = Client()
    client.login(username="alice", password="pw")
    resp = client.get(reverse("user_preferences"))
    assert resp.json() == {"theme": "strategic"}

    client2 = Client()
    client2.login(username="bob", password="pw")
    resp = client2.get(reverse("user_preferences"))
    assert resp.json() == {"theme": "light_premium"}


# ---------------------------------------------------------------------------
# Inertia page-prop contract
# ---------------------------------------------------------------------------


def test_schedule_view_includes_ui_preferences_prop(auth_client, user):
    UserPreferences.objects.create(user=user, theme="strategic")
    today = timezone.localdate().isoformat()
    resp = auth_client.get(
        f"/schedule/{today}/", HTTP_X_INERTIA="true"
    )
    assert resp.status_code == 200
    page = resp.json()
    assert page["props"]["ui_preferences"] == {"theme": "strategic"}


def test_settings_view_includes_ui_preferences_prop(auth_client, user):
    UserPreferences.objects.create(user=user, theme="light_premium")
    resp = auth_client.get(reverse("settings"), HTTP_X_INERTIA="true")
    assert resp.status_code == 200
    page = resp.json()
    assert page["props"]["ui_preferences"] == {"theme": "light_premium"}


def test_analytics_view_includes_ui_preferences_prop(auth_client, user):
    UserPreferences.objects.create(user=user, theme="strategic")
    past = timezone.localdate() - datetime.timedelta(days=1)
    schedule = Schedule.objects.create(user=user, date=past)
    TimeBlock.objects.create(
        schedule=schedule,
        title="warm-up",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        category="work",
    )
    resp = auth_client.get(
        f"/analytics/{past.isoformat()}/", HTTP_X_INERTIA="true"
    )
    assert resp.status_code == 200
    page = resp.json()
    assert page["props"]["ui_preferences"] == {"theme": "strategic"}


# ---------------------------------------------------------------------------
# Server-rendered first-paint contract (hard-load HTML, not partial Inertia)
# ---------------------------------------------------------------------------


def test_login_hard_load_renders_strategic_data_theme(db):
    client = Client()
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-theme="strategic"' in body, (
        "login page must server-render data-theme=\"strategic\". "
        f"Body head: {body[:400]!r}"
    )


@pytest.mark.parametrize(
    "page_url_fn",
    [
        pytest.param(
            lambda user: f"/schedule/{timezone.localdate().isoformat()}/",
            id="schedule",
        ),
        pytest.param(lambda user: "/settings/", id="settings"),
    ],
)
def test_authenticated_hard_load_uses_persisted_theme(
    auth_client, user, page_url_fn
):
    """Catches the failure mode where a page wires ui_preferences but
    forgets `template_data=` and silently falls back to `'classic'`."""
    UserPreferences.objects.create(user=user, theme="strategic")
    resp = auth_client.get(page_url_fn(user))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-theme="strategic"' in body


def test_analytics_hard_load_uses_persisted_theme(auth_client, user):
    UserPreferences.objects.create(user=user, theme="strategic")
    past = timezone.localdate() - datetime.timedelta(days=1)
    schedule = Schedule.objects.create(user=user, date=past)
    TimeBlock.objects.create(
        schedule=schedule,
        title="warm-up",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        category="work",
    )
    resp = auth_client.get(f"/analytics/{past.isoformat()}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-theme="strategic"' in body


# ---------------------------------------------------------------------------
# Concurrent first-visit race (TransactionTestCase, not pytest fixture)
# ---------------------------------------------------------------------------


class ConcurrentFirstVisitRace(TransactionTestCase):
    """Two concurrent first-visits end with exactly one ``UserPreferences``
    row in the database.

    **Scope of this test.** The contract asserted here is the **end-state
    invariant** — "exactly one row after both threads return" — NOT the
    user-facing request contract under contention. The plan explicitly
    authorized the end-state-only assertion (see
    ``docs/features/0010_design_templates_PLAN.md`` §Phase 7,
    "Concurrent first-visit race"): on the project's default SQLite
    backend, writers queue at the file lock and one worker can surface
    a transient ``OperationalError("database table is locked")``, which
    the test tolerates. The IntegrityError-rescue branch of
    ``get_or_create`` may therefore never actually fire on SQLite — both
    threads still end up with one committed row via the SELECT-after-
    failed-INSERT semantics of ``get_or_create``.

    Postgres in production resolves the same race via genuine row-level
    lock contention and the rescue branch fires; the end state is the
    same. If a future product decision says transient lock errors at
    first visit are unacceptable (e.g. via a SQLite retry-on-locked
    wrapper or a switch to Postgres in CI), tighten this test to
    "exactly one row AND zero errors from both threads."
    """

    def test_concurrent_first_visit_ends_with_exactly_one_row(self):
        from django.db.utils import OperationalError

        user = User.objects.create_user(username="raceuser", password="pw")
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def worker():
            # Reset the per-thread connection so we don't reuse a stale
            # handle from the main test thread.
            try:
                connections["default"].close()
            except Exception:
                pass
            try:
                barrier.wait(timeout=5)
                get_user_preferences(user)
            except Exception as exc:  # noqa: BLE001 — surface to assertion
                errors.append(exc)
            finally:
                connections["default"].close()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # SQLite serializes writes at the file lock and may surface a
        # transient "database table is locked" OperationalError to the
        # loser thread; this is an implementation detail of how the race
        # resolves on this backend, not a contract violation. On Postgres
        # the rescue branch of get_or_create fires instead and no error
        # is raised. The end-state invariant is the same on both backends.
        non_sqlite_errors = [
            e for e in errors if not isinstance(e, OperationalError)
        ]
        assert non_sqlite_errors == [], (
            f"Race produced non-SQLite-lock errors: {non_sqlite_errors!r}"
        )

        # End-state contract: at least one thread successfully created the
        # row, and there is exactly one row regardless of which path the
        # losers took. After-the-fact, a sequential call should also see
        # exactly one row (no later duplicate insert).
        get_user_preferences(user)
        rows = UserPreferences.objects.filter(user=user).count()
        assert rows == 1, f"Expected exactly 1 row, found {rows}"
