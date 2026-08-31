"""Tests for the ``/api/user/schedule-settings/`` endpoint (feature 0053,
Slice 3).

Covers the coupled per-user day-window GET/PATCH contract:
GET default, PATCH valid persist + normalized echo, PATCH invalid (each
window rule) -> 400 structured field errors with the stored row unchanged,
the ``Cache-Control: private, no-store`` invariant, the unauthenticated
path, and multi-user isolation on both GET and PATCH.

Conventions mirror ``test_user_preferences_api.py`` (the sibling
``/api/user/preferences/`` endpoint): Django test ``Client``, the shared
``user`` / ``auth_client`` conftest fixtures, ``reverse()`` for the URL,
``resp.json()`` assertions, and no CSRF enforcement (the default ``Client``
bypasses CSRF).

NOTE: diverges from plan -- 0053_PLAN.md's "Skip signal contract" (a 422
with a top-level ``outside_window`` / ``skipped`` shape) is for *block
create/from-event* placement, NOT for the schedule-settings PATCH. The
real ``schedule_settings`` view returns a plain ``400 {"errors": {...}}``
for every window-rule violation, so these tests assert 400 (per the Slice 3
spec line "PATCH invalid (each rule) -> 400 structured errors").
"""
import datetime
import json

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from schedules.models import UserScheduleSettings

pytestmark = pytest.mark.django_db

URL_NAME = "schedule_settings"


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


def test_get_first_call_returns_default_window(auth_client, user):
    """A fresh user with no stored row gets the canonical default window."""
    assert not UserScheduleSettings.objects.filter(user=user).exists()
    resp = auth_client.get(reverse(URL_NAME))
    assert resp.status_code == 200
    assert resp.json() == {"day_start": "06:00", "day_end": "23:00", "time_zone": "UTC"}
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_get_returns_saved_window(auth_client, user):
    UserScheduleSettings.objects.create(
        user=user, day_start=datetime.time(8, 0), day_end=datetime.time(22, 30)
    )
    resp = auth_client.get(reverse(URL_NAME))
    assert resp.status_code == 200
    assert resp.json() == {"day_start": "08:00", "day_end": "22:30", "time_zone": "UTC"}
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_get_returns_persisted_non_utc_time_zone(auth_client, user):
    """GET must serialize the stored zone rather than a response default."""
    UserScheduleSettings.objects.create(user=user, time_zone="Asia/Almaty")
    resp = auth_client.get(reverse(URL_NAME))
    assert resp.status_code == 200
    assert resp.json()["time_zone"] == "Asia/Almaty"


# ---------------------------------------------------------------------------
# PATCH — happy path
# ---------------------------------------------------------------------------


def test_patch_valid_persists_and_echoes_normalized_window(auth_client, user):
    resp = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps({"day_start": "07:00", "day_end": "21:15"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"day_start": "07:00", "day_end": "21:15", "time_zone": "UTC"}
    assert resp.headers["Cache-Control"] == "private, no-store"
    # Persisted to the DB.
    row = UserScheduleSettings.objects.get(user=user)
    assert row.day_start == datetime.time(7, 0)
    assert row.day_end == datetime.time(21, 15)


def test_patch_updates_existing_row(auth_client, user):
    UserScheduleSettings.objects.create(
        user=user, day_start=datetime.time(6, 0), day_end=datetime.time(23, 0)
    )
    resp = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps({"day_start": "09:00", "day_end": "18:00"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"day_start": "09:00", "day_end": "18:00", "time_zone": "UTC"}
    # Exactly one row — the update did not create a duplicate.
    assert UserScheduleSettings.objects.filter(user=user).count() == 1
    row = UserScheduleSettings.objects.get(user=user)
    assert (row.day_start, row.day_end) == (datetime.time(9, 0), datetime.time(18, 0))


def test_patch_first_time_with_time_zone_persists_zone_via_defaults(auth_client, user):
    """A first PATCH on a no-prior-row user that includes ``time_zone`` must
    persist that zone through ``get_or_create`` ``defaults`` — not silently fall
    back to the model's ``"UTC"`` default (guards the create-path drop)."""
    assert not UserScheduleSettings.objects.filter(user=user).exists()
    resp = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps({"day_start": "07:00", "day_end": "21:00", "time_zone": "Asia/Almaty"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"day_start": "07:00", "day_end": "21:00", "time_zone": "Asia/Almaty"}
    row = UserScheduleSettings.objects.get(user=user)
    assert row.time_zone == "Asia/Almaty"
    assert (row.day_start, row.day_end) == (datetime.time(7, 0), datetime.time(21, 0))


def test_patch_all_fields_and_timezone_only_are_partial_updates(auth_client, user):
    UserScheduleSettings.objects.create(
        user=user, day_start=datetime.time(8, 0), day_end=datetime.time(20, 0), time_zone="UTC"
    )
    response = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps({"time_zone": "Asia/Almaty"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json() == {
        "day_start": "08:00",
        "day_end": "20:00",
        "time_zone": "Asia/Almaty",
    }
    response = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps({"day_start": "09:00", "day_end": "19:00"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["time_zone"] == "Asia/Almaty"


@pytest.mark.parametrize("value", ["", "Not/AZone", "..", "/UTC", 1])
def test_patch_invalid_time_zone_has_stable_error(auth_client, user, value):
    response = auth_client.patch(
        reverse(URL_NAME), data=json.dumps({"time_zone": value}), content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["errors"]["time_zone"] == "Must be a valid IANA time zone."
    assert not UserScheduleSettings.objects.filter(user=user).exists()


def test_patch_invalid_window_and_time_zone_reports_both_errors_and_keeps_row(auth_client, user):
    _seed_baseline(user)
    response = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps({"day_start": "22:00", "day_end": "08:00", "time_zone": "Not/AZone"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    errors = response.json()["errors"]
    assert "day_end" in errors
    assert "time_zone" in errors
    assert response.headers["Cache-Control"] == "private, no-store"
    _assert_row_unchanged(user)


# ---------------------------------------------------------------------------
# PATCH — validation errors (one per window rule)
#
# Each case asserts: 400, a structured ``{"errors": {field: msg}}`` envelope,
# the Cache-Control invariant, AND that the stored row is UNCHANGED (a fresh
# baseline is seeded first so "no write" is provable by re-query).
# ---------------------------------------------------------------------------

# The stable baseline every invalid-PATCH test seeds and then re-asserts.
_BASELINE_START = datetime.time(6, 0)
_BASELINE_END = datetime.time(23, 0)


def _seed_baseline(user):
    return UserScheduleSettings.objects.create(
        user=user, day_start=_BASELINE_START, day_end=_BASELINE_END
    )


def _assert_row_unchanged(user):
    row = UserScheduleSettings.objects.get(user=user)
    assert row.day_start == _BASELINE_START
    assert row.day_end == _BASELINE_END


@pytest.mark.parametrize(
    ("payload", "error_field", "case_id"),
    [
        pytest.param(
            {"day_start": "6am", "day_end": "23:00"},
            "day_start",
            "bad-format",
            id="bad-format",
        ),
        pytest.param(
            {"day_start": "06:03", "day_end": "23:00"},
            "day_start",
            "off-grid",
            id="off-grid",
        ),
        pytest.param(
            {"day_start": "23:00", "day_end": "23:00"},
            "day_end",
            "start-eq-end",
            id="start-equals-end",
        ),
        pytest.param(
            {"day_start": "22:00", "day_end": "08:00"},
            "day_end",
            "start-gt-end",
            id="start-after-end",
        ),
        pytest.param(
            {"day_start": "20:00", "day_end": "04:00"},
            "day_end",
            "overnight",
            id="overnight",
        ),
    ],
)
def test_patch_invalid_window_returns_400_and_leaves_row_unchanged(
    auth_client, user, payload, error_field, case_id
):
    _seed_baseline(user)
    resp = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "errors" in body
    # Structured field error keyed on the offending window bound.
    assert error_field in body["errors"]
    assert isinstance(body["errors"][error_field], str)
    assert resp.headers["Cache-Control"] == "private, no-store"
    # The stored window must NOT have been rewritten on the failed PATCH.
    _assert_row_unchanged(user)


@pytest.mark.parametrize(
    ("payload", "case_id"),
    [
        pytest.param({"day_end": "23:00"}, "missing-day_start", id="missing-day_start"),
        pytest.param({"day_start": "06:00"}, "missing-day_end", id="missing-day_end"),
        pytest.param({}, "missing-both", id="missing-both"),
    ],
)
def test_patch_missing_field_returns_400_and_leaves_row_unchanged(
    auth_client, user, payload, case_id
):
    _seed_baseline(user)
    resp = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "errors" in body
    # Every absent required field is reported.
    for field in ("day_start", "day_end"):
        if field not in payload:
            assert field in body["errors"]
    assert resp.headers["Cache-Control"] == "private, no-store"
    _assert_row_unchanged(user)


def test_patch_invalid_json_returns_400_and_leaves_row_unchanged(auth_client, user):
    _seed_baseline(user)
    resp = auth_client.patch(
        reverse(URL_NAME),
        data="not-json",
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "body" in resp.json()["errors"]
    assert resp.headers["Cache-Control"] == "private, no-store"
    _assert_row_unchanged(user)


def test_patch_non_object_body_returns_400_and_leaves_row_unchanged(auth_client, user):
    _seed_baseline(user)
    resp = auth_client.patch(
        reverse(URL_NAME),
        data=json.dumps(["06:00", "23:00"]),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "body" in resp.json()["errors"]
    assert resp.headers["Cache-Control"] == "private, no-store"
    _assert_row_unchanged(user)


# ---------------------------------------------------------------------------
# Auth requirement
# ---------------------------------------------------------------------------


def test_get_requires_auth():
    client = Client()
    resp = client.get(reverse(URL_NAME))
    # @login_required redirects to the login URL — matches the project-wide
    # convention pinned in test_user_preferences_api.py.
    assert resp.status_code in (302, 403)


def test_patch_requires_auth():
    client = Client()
    resp = client.patch(
        reverse(URL_NAME),
        data=json.dumps({"day_start": "07:00", "day_end": "21:00"}),
        content_type="application/json",
    )
    assert resp.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Multi-user isolation
# ---------------------------------------------------------------------------


def test_get_isolated_per_user(db):
    alice = User.objects.create_user(username="alice_sw", password="pw")
    bob = User.objects.create_user(username="bob_sw", password="pw")
    UserScheduleSettings.objects.create(
        user=alice, day_start=datetime.time(7, 0), day_end=datetime.time(19, 0)
    )
    UserScheduleSettings.objects.create(
        user=bob, day_start=datetime.time(5, 0), day_end=datetime.time(22, 0)
    )

    client_a = Client()
    client_a.login(username="alice_sw", password="pw")
    assert client_a.get(reverse(URL_NAME)).json() == {
        "day_start": "07:00",
        "day_end": "19:00",
        "time_zone": "UTC",
    }

    client_b = Client()
    client_b.login(username="bob_sw", password="pw")
    assert client_b.get(reverse(URL_NAME)).json() == {
        "day_start": "05:00",
        "day_end": "22:00",
        "time_zone": "UTC",
    }


def test_patch_does_not_leak_across_users(db):
    """A PATCH from user A must never rewrite user B's window row."""
    alice = User.objects.create_user(username="alice_sw2", password="pw")
    bob = User.objects.create_user(username="bob_sw2", password="pw")
    UserScheduleSettings.objects.create(
        user=alice, day_start=datetime.time(6, 0), day_end=datetime.time(23, 0)
    )
    UserScheduleSettings.objects.create(
        user=bob, day_start=datetime.time(8, 0), day_end=datetime.time(20, 0)
    )

    client_a = Client()
    client_a.login(username="alice_sw2", password="pw")
    resp = client_a.patch(
        reverse(URL_NAME),
        data=json.dumps({"day_start": "09:00", "day_end": "17:00"}),
        content_type="application/json",
    )
    assert resp.status_code == 200

    # Alice's row updated.
    alice_row = UserScheduleSettings.objects.get(user=alice)
    assert (alice_row.day_start, alice_row.day_end) == (
        datetime.time(9, 0),
        datetime.time(17, 0),
    )
    # Bob's row UNTOUCHED — via re-GET and via DB re-query.
    bob_row = UserScheduleSettings.objects.get(user=bob)
    assert (bob_row.day_start, bob_row.day_end) == (
        datetime.time(8, 0),
        datetime.time(20, 0),
    )

    client_b = Client()
    client_b.login(username="bob_sw2", password="pw")
    assert client_b.get(reverse(URL_NAME)).json() == {
        "day_start": "08:00",
        "day_end": "20:00",
        "time_zone": "UTC",
    }


def test_custom_time_zone_patch_does_not_leak_across_users(db):
    alice = User.objects.create_user(username="alice_tz", password="pw")
    bob = User.objects.create_user(username="bob_tz", password="pw")
    UserScheduleSettings.objects.create(user=alice, time_zone="UTC")
    UserScheduleSettings.objects.create(user=bob, time_zone="Europe/Berlin")
    client_a = Client()
    client_a.login(username="alice_tz", password="pw")

    response = client_a.patch(
        reverse(URL_NAME),
        data=json.dumps({"time_zone": "Asia/Almaty"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert UserScheduleSettings.objects.get(user=alice).time_zone == "Asia/Almaty"
    assert UserScheduleSettings.objects.get(user=bob).time_zone == "Europe/Berlin"
