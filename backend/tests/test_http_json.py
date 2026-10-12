"""Shared JSON boundary contracts and endpoint-specific ordering."""

import datetime
import json

import pytest
from analytics.models import DailyReview
from common.http import MAX_REQUEST_BODY_BYTES, parse_json_object
from django.test import RequestFactory
from schedules.models import Schedule


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"", "Invalid JSON."),
        (b" ", "Invalid JSON."),
        (b"{", "Invalid JSON."),
        (b"\xff", "Invalid JSON."),
        (b"[]", "Request body must be a JSON object."),
        (b"null", "Request body must be a JSON object."),
        (b"true", "Request body must be a JSON object."),
        (b"123", "Request body must be a JSON object."),
        (b'"text"', "Request body must be a JSON object."),
    ],
)
def test_parser_rejects_malformed_or_non_object_body(body, message):
    request = RequestFactory().post("/", body, content_type="application/json")
    data, error = parse_json_object(request)
    assert data is None
    assert error.status_code == 400
    assert json.loads(error.content) == {"errors": {"body": message}}


def test_parser_accepts_empty_body_only_when_enabled():
    factory = RequestFactory()
    request = factory.post("/", b"", content_type="application/json")
    assert parse_json_object(request, allow_empty=True) == ({}, None)
    whitespace = factory.post("/", b" ", content_type="application/json")
    data, error = parse_json_object(whitespace, allow_empty=True)
    assert data is None
    assert error.status_code == 400


def test_body_limit_includes_boundary_and_precedes_decode():
    factory = RequestFactory()
    at_limit = b"{}" + b" " * (MAX_REQUEST_BODY_BYTES - 2)
    request = factory.post("/", at_limit, content_type="application/json")
    assert parse_json_object(request) == ({}, None)
    invalid_oversized = b"\xff" * (MAX_REQUEST_BODY_BYTES + 1)
    request = factory.post("/", invalid_oversized, content_type="application/json")
    data, error = parse_json_object(request, error_field="detail")
    assert data is None
    assert error.status_code == 413
    assert json.loads(error.content) == {"errors": {"body": "Request body too large."}}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "url", "field", "private"),
    [
        ("post", "/api/schedules/2026-04-01/blocks/", "body", False),
        ("post", "/api/schedules/2026-04-01/blocks/from-event/", "body", False),
        ("post", "/api/schedules/2026-04-01/blocks/restore/", "body", False),
        ("post", "/api/blocks/reorder/", "body", False),
        ("post", "/api/user/categories/", "body", False),
        ("post", "/api/user/categories/swap/", "body", False),
        ("patch", "/api/user/schedule-settings/", "body", True),
        ("patch", "/api/user/preferences/", "body", True),
        ("post", "/api/templates/", "body", False),
        ("post", "/api/rules/", "body", False),
        ("post", "/api/rules/swap/", "body", False),
        ("post", "/api/calendar/travel-rules/", "body", False),
        ("post", "/api/calendar/travel-rules/swap/", "body", False),
        ("post", "/api/calendar/account/", "detail", False),
        ("post", "/api/habitica/account/", "detail", False),
        ("post", "/api/todoist/account/", "detail", False),
        ("post", "/api/ai/schedules/2026-04-01/chat/", "body", False),
        ("patch", "/api/analytics/reviews/999999/notes/", "body", False),
    ],
)
def test_invalid_encoding_uses_existing_endpoint_envelope(
    auth_client, method, url, field, private
):
    response = getattr(auth_client, method)(url, b"\xff", content_type="application/json")
    assert response.status_code == 400
    assert response.json() == {"errors": {field: "Invalid JSON."}}
    if private:
        assert response.headers["Cache-Control"] == "private, no-store"
    assert not Schedule.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("body", [b"\xff", b"[]", b""])
def test_reviewed_retry_skips_parser(auth_client, user, monkeypatch, body):
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 4, 1), status=Schedule.Status.REVIEWED
    )
    review = DailyReview.objects.create(schedule=schedule, notes="Frozen")

    def unexpected_parse(*args, **kwargs):
        pytest.fail("A reviewed retry must not parse its body")

    monkeypatch.setattr("analytics.views.parse_json_object", unexpected_parse)
    response = auth_client.post(
        "/api/analytics/schedules/2026-04-01/mark-reviewed/",
        body,
        content_type="application/json",
    )
    assert response.status_code == 200
    review.refresh_from_db()
    assert review.notes == "Frozen"


@pytest.mark.django_db
def test_reviewed_retry_still_applies_early_body_limit(auth_client, user):
    Schedule.objects.create(
        user=user, date=datetime.date(2026, 4, 1), status=Schedule.Status.REVIEWED
    )
    response = auth_client.post(
        "/api/analytics/schedules/2026-04-01/mark-reviewed/",
        b"\xff" * (MAX_REQUEST_BODY_BYTES + 1),
        content_type="application/json",
    )
    assert response.status_code == 413
    assert not DailyReview.objects.exists()


@pytest.mark.django_db
def test_active_review_rejects_invalid_encoding_without_freezing(auth_client, user):
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 4, 1), status=Schedule.Status.ACTIVE
    )
    response = auth_client.post(
        "/api/analytics/schedules/2026-04-01/mark-reviewed/",
        b"\xff",
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json() == {"errors": {"body": "Invalid JSON."}}
    schedule.refresh_from_db()
    assert schedule.status == Schedule.Status.ACTIVE
    assert not DailyReview.objects.exists()
