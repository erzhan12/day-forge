"""Tests for the ``TravelRule`` atomic reorder-swap endpoint (feature 0047).

Relocated from ``test_from_event.py`` — the swap suite is semantically
unrelated to that file's "create block from event" subject. Mirrors
``test_templates_api.py::TestRuleSwap`` (the sibling ``Rule`` swap suite).
"""
import json

import pytest
from calendar_sync.models import TravelRule
from django.contrib.auth.models import User


class TestTravelRuleSwap:
    URL = "/api/calendar/travel-rules/swap/"

    @pytest.mark.django_db
    def test_unauthenticated_redirects(self, client, user):
        first = TravelRule.objects.create(user=user, keyword="First", order=0)
        second = TravelRule.objects.create(user=user, keyword="Second", order=1)

        resp = client.post(
            self.URL,
            json.dumps({"a": first.id, "b": second.id}),
            content_type="application/json",
        )

        assert resp.status_code == 302

    @pytest.mark.django_db
    def test_swap_two_rules_swaps_order(
        self, auth_client, user, monkeypatch
    ):
        first = TravelRule.objects.create(user=user, keyword="First", order=0)
        second = TravelRule.objects.create(user=user, keyword="Second", order=1)
        lock_calls: list[str] = []
        original_select_for_update = User.objects.select_for_update

        def select_for_update_spy(*args, **kwargs):
            lock_calls.append("user_lock")
            return original_select_for_update(*args, **kwargs)

        monkeypatch.setattr(
            User.objects,
            "select_for_update",
            select_for_update_spy,
            raising=True,
        )

        resp = auth_client.post(
            self.URL,
            json.dumps({"a": first.id, "b": second.id}),
            content_type="application/json",
        )

        assert resp.status_code == 200
        assert lock_calls == ["user_lock"]
        first.refresh_from_db()
        second.refresh_from_db()
        assert (first.order, second.order) == (1, 0)
        # Response envelope carries the swapped values, not just the ids.
        by_id = {r["id"]: r["order"] for r in resp.json()["travel_rules"]}
        assert by_id == {first.id: 1, second.id: 0}

    @pytest.mark.django_db
    def test_swap_missing_id_returns_404(self, auth_client, user):
        rule = TravelRule.objects.create(user=user, keyword="Mine", order=0)

        resp = auth_client.post(
            self.URL,
            json.dumps({"a": rule.id, "b": 999_999}),
            content_type="application/json",
        )

        assert resp.status_code == 404
        rule.refresh_from_db()
        assert rule.order == 0

    @pytest.mark.django_db
    def test_swap_cross_user_id_returns_404(self, auth_client, user):
        mine = TravelRule.objects.create(user=user, keyword="Mine", order=0)
        other = User.objects.create_user(username="travel-swap-other", password="x")
        theirs = TravelRule.objects.create(user=other, keyword="Theirs", order=1)

        resp = auth_client.post(
            self.URL,
            json.dumps({"a": mine.id, "b": theirs.id}),
            content_type="application/json",
        )

        assert resp.status_code == 404
        mine.refresh_from_db()
        theirs.refresh_from_db()
        assert (mine.order, theirs.order) == (0, 1)

    @pytest.mark.django_db
    def test_swap_equal_ids_returns_400(self, auth_client, user):
        rule = TravelRule.objects.create(user=user, keyword="Mine", order=0)

        resp = auth_client.post(
            self.URL,
            json.dumps({"a": rule.id, "b": rule.id}),
            content_type="application/json",
        )

        assert resp.status_code == 400
        assert "body" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_swap_non_int_id_returns_400(self, auth_client, user):
        rule = TravelRule.objects.create(user=user, keyword="Mine", order=0)

        resp = auth_client.post(
            self.URL,
            json.dumps({"a": "x", "b": rule.id}),
            content_type="application/json",
        )

        assert resp.status_code == 400
        assert "body" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_swap_invalid_json_returns_400(self, auth_client):
        # Malformed (non-JSON) body must hit parse_swap_body's
        # json.JSONDecodeError branch before any id validation.
        resp = auth_client.post(
            self.URL,
            "not json{",
            content_type="application/json",
        )

        assert resp.status_code == 400
        assert resp.json()["errors"]["body"] == "Invalid JSON."

    @pytest.mark.django_db
    def test_non_dict_body_returns_400(self, auth_client):
        # A JSON array body must hit the isinstance(data, dict) guard.
        resp = auth_client.post(
            self.URL,
            json.dumps([1, 2]),
            content_type="application/json",
        )

        assert resp.status_code == 400
        assert "body" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_swap_bool_id_returns_400(self, auth_client, user):
        # bool subclasses int; is_plain_int must reject it.
        rule = TravelRule.objects.create(user=user, keyword="Mine", order=0)

        resp = auth_client.post(
            self.URL,
            json.dumps({"a": True, "b": rule.id}),
            content_type="application/json",
        )

        assert resp.status_code == 400
        assert "body" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_swap_oversized_body_returns_413(self, auth_client, user):
        first = TravelRule.objects.create(user=user, keyword="First", order=0)
        second = TravelRule.objects.create(user=user, keyword="Second", order=1)

        # Pad the body past the 100 KB cap; rejected before json.loads.
        resp = auth_client.post(
            self.URL,
            json.dumps({"a": first.id, "b": second.id, "pad": "x" * 200_000}),
            content_type="application/json",
        )

        assert resp.status_code == 413
        first.refresh_from_db()
        second.refresh_from_db()
        assert (first.order, second.order) == (0, 1)  # unchanged

    @pytest.mark.django_db
    def test_swap_rolls_back_on_bulk_update_failure(
        self, auth_client, user, monkeypatch
    ):
        first = TravelRule.objects.create(user=user, keyword="First", order=0)
        second = TravelRule.objects.create(user=user, keyword="Second", order=1)

        # Perform the real write, THEN raise: proves transaction.atomic()
        # rolls back a write that actually landed, not just that an early
        # failure skipped the write.
        original_bulk_update = TravelRule.objects.bulk_update

        def write_then_raise(*args, **kwargs):
            original_bulk_update(*args, **kwargs)
            raise RuntimeError("db write failed mid-swap")

        monkeypatch.setattr(TravelRule.objects, "bulk_update", write_then_raise)

        with pytest.raises(RuntimeError):
            auth_client.post(
                self.URL,
                json.dumps({"a": first.id, "b": second.id}),
                content_type="application/json",
            )

        first.refresh_from_db()
        second.refresh_from_db()
        assert (first.order, second.order) == (0, 1)  # both-or-neither
