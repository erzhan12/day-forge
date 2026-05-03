"""Tests for the templates + rules CRUD endpoints."""
import json

import pytest
from django.contrib.auth.models import User
from templates_mgr.models import Rule, Template


def _post(client, url, body):
    return client.post(url, json.dumps(body), content_type="application/json")


def _put(client, url, body):
    return client.put(url, json.dumps(body), content_type="application/json")


def _patch(client, url, body):
    return client.patch(url, json.dumps(body), content_type="application/json")


@pytest.fixture
def good_blocks():
    return [
        {
            "title": "Deep work",
            "start_time": "09:00",
            "end_time": "12:00",
            "category": "work",
        }
    ]


@pytest.mark.django_db
class TestTemplatesList:
    def test_list_per_user_only(self, auth_client, user, good_blocks):
        Template.objects.create(
            user=user, name="A", type="weekday", blocks=good_blocks
        )
        other = User.objects.create_user(username="o", password="x")
        Template.objects.create(
            user=other, name="other", type="weekday", blocks=[]
        )

        resp = auth_client.get("/api/templates/")
        assert resp.status_code == 200
        data = resp.json()
        names = {t["name"] for t in data["templates"]}
        assert names == {"A"}

    def test_requires_auth(self, client):
        resp = client.get("/api/templates/")
        assert resp.status_code == 302


@pytest.mark.django_db
class TestTemplatesCreate:
    def test_creates_for_user(self, auth_client, user, good_blocks):
        resp = _post(
            auth_client,
            "/api/templates/",
            {"name": "Mine", "type": "weekday", "blocks": good_blocks},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Mine"
        assert body["type"] == "weekday"
        # Persisted scoped to current user
        assert Template.objects.filter(user=user, name="Mine").exists()

    def test_unique_user_type_returns_409(
        self, auth_client, user, good_blocks
    ):
        Template.objects.create(
            user=user, name="A", type="weekday", blocks=good_blocks
        )
        resp = _post(
            auth_client,
            "/api/templates/",
            {"name": "B", "type": "weekday", "blocks": good_blocks},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert "type" in body["errors"]

    def test_two_users_can_each_have_weekday(self, auth_client, good_blocks):
        # Current user creates one
        resp = _post(
            auth_client,
            "/api/templates/",
            {"name": "Mine", "type": "weekday", "blocks": good_blocks},
        )
        assert resp.status_code == 201
        # Other user can create one too
        other = User.objects.create_user(username="o2", password="x")
        Template.objects.create(
            user=other, name="Theirs", type="weekday", blocks=good_blocks
        )
        assert Template.objects.filter(type="weekday").count() == 2

    def test_invalid_block_returns_400(self, auth_client):
        resp = _post(
            auth_client,
            "/api/templates/",
            {
                "name": "X",
                "type": "weekday",
                "blocks": [
                    {
                        "title": "",  # empty
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "category": "work",
                    }
                ],
            },
        )
        assert resp.status_code == 400

    def test_overlap_rejected(self, auth_client):
        resp = _post(
            auth_client,
            "/api/templates/",
            {
                "name": "X",
                "type": "weekday",
                "blocks": [
                    {
                        "title": "A",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "category": "work",
                    },
                    {
                        "title": "B",
                        "start_time": "09:30",
                        "end_time": "10:30",
                        "category": "work",
                    },
                ],
            },
        )
        assert resp.status_code == 400

    def test_invalid_category(self, auth_client):
        resp = _post(
            auth_client,
            "/api/templates/",
            {
                "name": "X",
                "type": "weekday",
                "blocks": [
                    {
                        "title": "A",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "category": "nope",
                    }
                ],
            },
        )
        assert resp.status_code == 400

    def test_out_of_window(self, auth_client):
        resp = _post(
            auth_client,
            "/api/templates/",
            {
                "name": "X",
                "type": "weekday",
                "blocks": [
                    {
                        "title": "Late",
                        "start_time": "23:30",
                        "end_time": "23:45",
                        "category": "work",
                    }
                ],
            },
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestTemplateDetail:
    def test_put_updates(self, auth_client, user, good_blocks):
        tpl = Template.objects.create(
            user=user, name="Old", type="weekday", blocks=[]
        )
        resp = _put(
            auth_client,
            f"/api/templates/{tpl.id}/",
            {"name": "New", "type": "weekday", "blocks": good_blocks},
        )
        assert resp.status_code == 200
        tpl.refresh_from_db()
        assert tpl.name == "New"
        assert tpl.blocks == good_blocks

    def test_cross_user_returns_404(self, auth_client, good_blocks):
        other = User.objects.create_user(username="o3", password="x")
        tpl = Template.objects.create(
            user=other, name="Theirs", type="weekday", blocks=[]
        )
        resp = _put(
            auth_client,
            f"/api/templates/{tpl.id}/",
            {"name": "Hacked", "type": "weekday", "blocks": good_blocks},
        )
        assert resp.status_code == 404
        tpl.refresh_from_db()
        assert tpl.name == "Theirs"

    def test_delete(self, auth_client, user):
        tpl = Template.objects.create(
            user=user, name="X", type="weekday", blocks=[]
        )
        resp = auth_client.delete(f"/api/templates/{tpl.id}/")
        assert resp.status_code == 200
        assert not Template.objects.filter(pk=tpl.id).exists()


@pytest.mark.django_db
class TestRulesCRUD:
    def test_list_per_user_only(self, auth_client, user):
        Rule.objects.create(user=user, text="Mine", priority=10)
        other = User.objects.create_user(username="o4", password="x")
        Rule.objects.create(user=other, text="Theirs")

        resp = auth_client.get("/api/rules/")
        assert resp.status_code == 200
        texts = [r["text"] for r in resp.json()["rules"]]
        assert texts == ["Mine"]

    def test_list_orders_by_priority(self, auth_client, user):
        Rule.objects.create(user=user, text="Low", priority=1)
        Rule.objects.create(user=user, text="High", priority=10)
        resp = auth_client.get("/api/rules/")
        texts = [r["text"] for r in resp.json()["rules"]]
        assert texts == ["High", "Low"]

    def test_create_rule(self, auth_client, user):
        resp = _post(
            auth_client,
            "/api/rules/",
            {"text": "No meetings before 9", "priority": 10},
        )
        assert resp.status_code == 201
        assert Rule.objects.filter(
            user=user, text="No meetings before 9"
        ).exists()

    def test_patch_rule(self, auth_client, user):
        r = Rule.objects.create(user=user, text="Old", priority=5)
        resp = _patch(
            auth_client, f"/api/rules/{r.id}/", {"text": "New", "is_active": False}
        )
        assert resp.status_code == 200
        r.refresh_from_db()
        assert r.text == "New"
        assert r.is_active is False

    def test_cross_user_patch_returns_404(self, auth_client):
        other = User.objects.create_user(username="o5", password="x")
        r = Rule.objects.create(user=other, text="Theirs")
        resp = _patch(
            auth_client, f"/api/rules/{r.id}/", {"text": "hacked"}
        )
        assert resp.status_code == 404

    def test_delete(self, auth_client, user):
        r = Rule.objects.create(user=user, text="X")
        resp = auth_client.delete(f"/api/rules/{r.id}/")
        assert resp.status_code == 200
        assert not Rule.objects.filter(pk=r.id).exists()
