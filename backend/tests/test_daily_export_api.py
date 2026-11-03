"""HTTP tests for ``GET /api/export/daily/<date>/`` (feature 0088).

Covers Markdown/JSON parity, session and Bearer authentication precedence,
missing/malformed/invalid/revoked credentials, inactive owners, date and
format validation, ownership, unsupported methods, and the parameterized
matrix proving a Bearer export token authenticates no other ``/api/`` route.
"""

import datetime
import re
import zoneinfo

import pytest
from django.contrib.auth.models import User
from django.urls import get_resolver
from schedules import window
from schedules.export_tokens import create_token
from schedules.models import Schedule, TimeBlock, UserScheduleSettings

pytestmark = pytest.mark.django_db


def _freeze(monkeypatch, fixed_utc):
    monkeypatch.setattr(window.timezone, "now", lambda: fixed_utc)


def _url(date: str) -> str:
    return f"/api/export/daily/{date}/"


@pytest.fixture
def owner(user):
    return user


@pytest.fixture
def raw_token(owner):
    token, _ = create_token(owner.pk)
    return token


def _bearer(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# --------------------------------------------------------------------------
# Markdown / JSON parity, basic shape
# --------------------------------------------------------------------------


class TestMarkdownAndJsonParity:
    def _make_day(self, owner):
        schedule = Schedule.objects.create(user=owner, date=datetime.date(2026, 8, 29))
        TimeBlock.objects.create(
            schedule=schedule, title="Gym", category="health",
            start_time="09:00", end_time="10:00", is_completed=True,
        )
        return schedule

    def test_default_response_is_markdown_with_charset(self, client, owner, raw_token):
        self._make_day(owner)
        response = client.get(_url("2026-08-29"), **_bearer(raw_token))
        assert response.status_code == 200
        assert response["Content-Type"] == "text/markdown; charset=utf-8"
        assert response.content.decode("utf-8") == (
            "## day-forge · 2026-08-29\n\nblocks: 1/1 done\n\n- [x] 09:00 Gym (health) 1h"
        )

    def test_explicit_markdown_format_matches_default(self, client, owner, raw_token):
        self._make_day(owner)
        default_resp = client.get(_url("2026-08-29"), **_bearer(raw_token))
        explicit_resp = client.get(_url("2026-08-29"), {"format": "markdown"}, **_bearer(raw_token))
        assert explicit_resp.content == default_resp.content
        assert explicit_resp["Content-Type"] == default_resp["Content-Type"]

    def test_json_format_contains_expected_fields_and_matches_markdown(
        self, client, owner, raw_token
    ):
        self._make_day(owner)
        response = client.get(_url("2026-08-29"), {"format": "json"}, **_bearer(raw_token))
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        body = response.json()
        assert body["date"] == "2026-08-29"
        assert body["completed_count"] == 1
        assert body["planned_count"] == 1
        assert body["note"] == ""
        assert body["blocks"] == [
            {
                "title": "Gym", "start_time": "09:00", "end_time": "10:00",
                "category": "health", "is_completed": True, "sort_order": 0,
            }
        ]
        assert "restore_proof" not in body["blocks"][0]
        assert "id" not in body["blocks"][0]
        assert body["markdown"] == (
            "## day-forge · 2026-08-29\n\nblocks: 1/1 done\n\n- [x] 09:00 Gym (health) 1h"
        )

    def test_invalid_format_rejected(self, client, owner, raw_token):
        self._make_day(owner)
        response = client.get(_url("2026-08-29"), {"format": "yaml"}, **_bearer(raw_token))
        assert response.status_code == 400
        assert response.json()["errors"]["detail"]

    def test_absent_day_returns_empty_report_without_creating_schedule(
        self, client, owner, raw_token
    ):
        response = client.get(_url("2026-08-29"), {"format": "json"}, **_bearer(raw_token))
        assert response.status_code == 200
        body = response.json()
        assert body["blocks"] == []
        assert body["completed_count"] == 0
        assert body["planned_count"] == 0
        assert not Schedule.objects.filter(user=owner, date=datetime.date(2026, 8, 29)).exists()
        markdown_resp = client.get(_url("2026-08-29"), **_bearer(raw_token))
        assert markdown_resp.content.decode() == "## day-forge · 2026-08-29\n\nblocks: 0/0 done"

    def test_counts_reflect_current_blocks_on_a_draft_day(self, client, owner, raw_token):
        schedule = Schedule.objects.create(
            user=owner, date=datetime.date(2026, 8, 29), status=Schedule.Status.DRAFT
        )
        TimeBlock.objects.create(
            schedule=schedule, title="Draft task", start_time="09:00", end_time="09:30"
        )
        response = client.get(_url("2026-08-29"), {"format": "json"}, **_bearer(raw_token))
        body = response.json()
        assert body["planned_count"] == 1
        assert body["completed_count"] == 0

    def test_response_is_private_no_store(self, client, owner, raw_token):
        response = client.get(_url("2026-08-29"), **_bearer(raw_token))
        assert response["Cache-Control"] == "private, no-store"


# --------------------------------------------------------------------------
# Authentication: session, Bearer, precedence, failure modes
# --------------------------------------------------------------------------


class TestAuthentication:
    def test_session_without_bearer_authenticates(self, auth_client, user):
        response = auth_client.get(_url("2026-08-29"))
        assert response.status_code == 200

    def test_bearer_without_session_authenticates(self, client, owner, raw_token):
        response = client.get(_url("2026-08-29"), **_bearer(raw_token))
        assert response.status_code == 200

    def test_no_authorization_header_and_no_session_returns_401_json(self, client):
        response = client.get(_url("2026-08-29"))
        assert response.status_code == 401
        assert response.json()["errors"]["detail"]
        assert response["Cache-Control"] == "private, no-store"
        # No login redirect.
        assert response.get("Location") is None

    def test_malformed_authorization_header_returns_401_even_with_session(self, auth_client):
        response = auth_client.get(_url("2026-08-29"), HTTP_AUTHORIZATION="Basic garbage")
        assert response.status_code == 401

    def test_invalid_bearer_token_returns_401_even_with_session(self, auth_client):
        response = auth_client.get(_url("2026-08-29"), HTTP_AUTHORIZATION="Bearer not-a-real-token")
        assert response.status_code == 401

    def test_revoked_bearer_token_returns_401(self, client, owner, raw_token):
        from schedules.export_tokens import revoke_token

        revoke_token(owner.pk)
        response = client.get(_url("2026-08-29"), **_bearer(raw_token))
        assert response.status_code == 401

    def test_valid_bearer_takes_precedence_over_a_different_users_session(
        self, client, owner, raw_token
    ):
        other = User.objects.create_user(username="other-session-owner", password="pw")
        other_day = Schedule.objects.create(user=other, date=datetime.date(2026, 8, 29))
        TimeBlock.objects.create(
            schedule=other_day, title="Other's block", start_time="09:00", end_time="10:00"
        )
        client.force_login(other)
        response = client.get(_url("2026-08-29"), {"format": "json"}, **_bearer(raw_token))
        assert response.status_code == 200
        # Bearer owner (``owner``) has no blocks; the session owner's block
        # must not leak through just because a session also exists.
        assert response.json()["blocks"] == []

    def test_inactive_bearer_owner_rejected(self, client, owner, raw_token):
        owner.is_active = False
        owner.save(update_fields=["is_active"])
        response = client.get(_url("2026-08-29"), **_bearer(raw_token))
        assert response.status_code == 401

    def test_inactive_session_owner_rejected(self, auth_client, user):
        user.is_active = False
        user.save(update_fields=["is_active"])
        response = auth_client.get(_url("2026-08-29"))
        assert response.status_code == 401

    def test_query_string_cannot_authenticate(self, client, owner, raw_token):
        response = client.get(_url("2026-08-29"), {"token": raw_token})
        assert response.status_code == 401


# --------------------------------------------------------------------------
# Ownership
# --------------------------------------------------------------------------


class TestOwnership:
    def test_two_owners_same_date_see_only_their_own_blocks(self, client):
        alice = User.objects.create_user(username="alice-export")
        bob = User.objects.create_user(username="bob-export")
        alice_token, _ = create_token(alice.pk)
        bob_token, _ = create_token(bob.pk)
        alice_day = Schedule.objects.create(user=alice, date=datetime.date(2026, 8, 29))
        TimeBlock.objects.create(
            schedule=alice_day, title="Alice block", start_time="09:00", end_time="10:00"
        )
        Schedule.objects.create(user=bob, date=datetime.date(2026, 8, 29))

        alice_resp = client.get(_url("2026-08-29"), {"format": "json"}, **_bearer(alice_token))
        bob_resp = client.get(_url("2026-08-29"), {"format": "json"}, **_bearer(bob_token))

        assert [b["title"] for b in alice_resp.json()["blocks"]] == ["Alice block"]
        assert bob_resp.json()["blocks"] == []

    def test_foreign_only_day_is_invisible_to_the_requesting_owner(self, client, owner, raw_token):
        other = User.objects.create_user(username="foreign-day-owner")
        other_day = Schedule.objects.create(user=other, date=datetime.date(2026, 8, 29))
        TimeBlock.objects.create(
            schedule=other_day, title="Not yours", start_time="09:00", end_time="10:00"
        )
        response = client.get(_url("2026-08-29"), {"format": "json"}, **_bearer(raw_token))
        assert response.json()["blocks"] == []


# --------------------------------------------------------------------------
# Date parsing: strict YYYY-MM-DD, 'today', invalid calendar dates
# --------------------------------------------------------------------------


class TestDateParsing:
    @pytest.mark.parametrize("raw", [
        "2026-13-01",  # impossible month
        "2026-02-30",  # impossible day
        "20260829",  # compact ISO
        "2026-W35-6",  # week date
        "not-a-date",
        "2026-8-29",  # non-zero-padded
    ])
    def test_invalid_dates_rejected_with_400(self, client, owner, raw_token, raw):
        # Each case is a single path segment (no "/"), so it still matches
        # the <str:date> URL converter and reaches the view's own date
        # parsing — unlike a literal "/" in the segment, which 404s at the
        # URL-routing layer before the view ever runs.
        response = client.get(_url(raw), **_bearer(raw_token))
        assert response.status_code == 400
        assert response.json()["errors"]["detail"]

    def test_today_resolves_using_saved_time_zone(self, client, owner, raw_token, monkeypatch):
        UserScheduleSettings.objects.create(
            user=owner, day_start=datetime.time(6), day_end=datetime.time(23),
            time_zone="Pacific/Kiritimati",  # UTC+14 — always a different calendar date than UTC
        )
        aware_utc_midnight = datetime.datetime(2026, 8, 29, 23, 30, tzinfo=datetime.UTC)
        _freeze(monkeypatch, aware_utc_midnight)
        response = client.get(_url("today"), {"format": "json"}, **_bearer(raw_token))
        assert response.status_code == 200
        local_date = aware_utc_midnight.astimezone(zoneinfo.ZoneInfo("Pacific/Kiritimati")).date()
        assert response.json()["date"] == local_date.isoformat()
        assert local_date != aware_utc_midnight.date()

    def test_today_falls_back_to_utc_without_a_settings_row(
        self, client, owner, raw_token, monkeypatch
    ):
        assert not UserScheduleSettings.objects.filter(user=owner).exists()
        fixed_instant = datetime.datetime(2026, 8, 29, 12, 0, tzinfo=datetime.UTC)
        _freeze(monkeypatch, fixed_instant)
        response = client.get(_url("today"), {"format": "json"}, **_bearer(raw_token))
        assert response.status_code == 200
        assert response.json()["date"] == "2026-08-29"
        assert not UserScheduleSettings.objects.filter(user=owner).exists()

    def test_today_falls_back_to_utc_for_an_invalid_stored_zone(
        self, client, owner, raw_token, monkeypatch
    ):
        UserScheduleSettings.objects.create(user=owner)
        # Bypass model validation (`.update()` skips `full_clean()`) — this
        # simulates a historically corrupted row, which `validate_time_zone`
        # would otherwise reject on write.
        UserScheduleSettings.objects.filter(user=owner).update(time_zone="Not/AZone")
        fixed_instant = datetime.datetime(2026, 8, 29, 12, 0, tzinfo=datetime.UTC)
        _freeze(monkeypatch, fixed_instant)
        response = client.get(_url("today"), {"format": "json"}, **_bearer(raw_token))
        assert response.json()["date"] == "2026-08-29"

    def test_today_creates_no_schedule_or_settings_rows(self, client, owner, raw_token):
        client.get(_url("today"), **_bearer(raw_token))
        assert not Schedule.objects.filter(user=owner).exists()
        assert not UserScheduleSettings.objects.filter(user=owner).exists()

    def test_today_succeeds_while_an_independent_writer_holds_the_sqlite_reservation(
        self, copied_database_for_export
    ):
        from tests.test_schedule_mutations_sqlite import run_on_copy

        run_on_copy(copied_database_for_export, """
import sqlite3
from django.contrib.auth.models import User
from django.test import Client
from schedules.export_tokens import create_token
from schedules.models import UserScheduleSettings
user = User.objects.create_user(username='export-today-busy')
raw_token, _ = create_token(user.pk)
client = Client()
holder = sqlite3.connect(sys.argv[1], timeout=0.1, isolation_level=None)
holder.execute('BEGIN IMMEDIATE')
try:
    response = client.get(
        '/api/export/daily/today/', HTTP_AUTHORIZATION=f'Bearer {raw_token}'
    )
    assert response.status_code == 200, response.content
finally:
    holder.rollback()
    holder.close()
assert not UserScheduleSettings.objects.filter(user=user).exists()
""")


@pytest.fixture
def copied_database_for_export(tmp_path, transactional_db):
    import sqlite3

    from django.db import connection

    if connection.vendor != "sqlite":
        pytest.skip("SQLite concurrency contract")
    connection.ensure_connection()
    copy_path = tmp_path / "export-today-concurrency.sqlite3"
    destination = sqlite3.connect(copy_path)
    try:
        connection.connection.backup(destination)
    finally:
        destination.close()
    return copy_path


# --------------------------------------------------------------------------
# Unsupported methods
# --------------------------------------------------------------------------


class TestUnsupportedMethods:
    @pytest.mark.parametrize("method", ["post", "patch", "put", "delete"])
    def test_non_get_methods_rejected(self, client, owner, raw_token, method):
        response = getattr(client, method)(_url("2026-08-29"), **_bearer(raw_token))
        assert response.status_code == 405


# --------------------------------------------------------------------------
# Matrix: a Bearer export token must not authenticate any other /api/ route.
# --------------------------------------------------------------------------


_INT_PLACEHOLDER = "999999999"
_STR_PLACEHOLDER = "placeholder-value"
_EXCLUDED_ROUTE_NAMES = {"daily_export"}


def _concrete_api_paths():
    """Discover every ``/api/...`` route (except the export route itself)
    directly from the live urlconf, substituting safe placeholder values
    for path converters. Automatically covers new routes — nothing to
    update here when a route is added, only ``_EXCLUDED_ROUTE_NAMES`` for an
    intentionally Bearer-authenticated one (e.g. slice 5's token-management
    route, once introduced)."""
    resolver = get_resolver()
    paths = []
    for pattern in resolver.url_patterns:
        route = str(pattern.pattern)
        if not route.startswith("api/") or pattern.name in _EXCLUDED_ROUTE_NAMES:
            continue
        concrete = route
        for name, converter in pattern.pattern.converters.items():
            if "date" in name:
                value = "2026-08-29"
            elif type(converter).__name__ == "IntConverter":
                value = _INT_PLACEHOLDER
            else:
                value = _STR_PLACEHOLDER
            concrete = re.sub(rf"<[^:>]+:{name}>", value, concrete)
        paths.append((pattern.name, "/" + concrete))
    return paths


API_PATHS = _concrete_api_paths()


def test_matrix_covers_every_other_api_route_in_the_urlconf():
    names = {name for name, _ in API_PATHS}
    # Spot-check a representative sample from each integration area, proving
    # the dynamic discovery actually walked the real urlconf rather than
    # silently returning an empty list.
    assert {
        "create_block", "schedule_settings", "templates_collection", "rules_collection",
        "user_preferences", "categories_collection", "ai_generate_draft", "caldav_account",
        "gcal_connect", "todoist_account", "habitica_account", "mark_reviewed",
    } <= names
    assert "daily_export" not in names


@pytest.mark.parametrize("method", ["get", "post", "patch", "put", "delete"])
@pytest.mark.parametrize("name,path", API_PATHS, ids=[p[0] for p in API_PATHS])
def test_bearer_only_request_behaves_like_an_unauthenticated_request(client, method, name, path):
    matrix_owner = User.objects.create_user(username=f"matrix-{name}-{method}"[:150])
    token, _ = create_token(matrix_owner.pk)

    anonymous_response = getattr(client, method)(path)
    bearer_response = getattr(client, method)(path, **_bearer(token))

    assert bearer_response.status_code == anonymous_response.status_code
    # A Bearer-only request must never flip a rejected anonymous request
    # into a success it would not otherwise get.
    success_codes = {200, 201, 204}
    if bearer_response.status_code in success_codes:
        assert anonymous_response.status_code in success_codes
