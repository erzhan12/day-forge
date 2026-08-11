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

    def test_create_without_priority_defaults_to_top(self, auth_client, user):
        first_resp = _post(auth_client, "/api/rules/", {"text": "Rule A"})
        assert first_resp.status_code == 201
        assert first_resp.json()["priority"] == 0

        second_resp = _post(auth_client, "/api/rules/", {"text": "Rule B"})
        assert second_resp.status_code == 201

        first = Rule.objects.get(user=user, text="Rule A")
        assert second_resp.json()["priority"] > first.priority
        listed = auth_client.get("/api/rules/").json()["rules"]
        assert [rule["text"] for rule in listed] == ["Rule B", "Rule A"]

    def test_create_compacts_priorities(self, auth_client, user):
        Rule.objects.create(user=user, text="Priority five", priority=5)
        Rule.objects.create(user=user, text="Priority nine", priority=9)

        resp = _post(auth_client, "/api/rules/", {"text": "New top rule"})

        assert resp.status_code == 201
        assert resp.json()["priority"] == 2
        listed = auth_client.get("/api/rules/").json()["rules"]
        assert [rule["text"] for rule in listed] == [
            "New top rule",
            "Priority nine",
            "Priority five",
        ]
        assert [rule["priority"] for rule in listed] == [2, 1, 0]

    def test_compaction_does_not_touch_other_users_rules(self, auth_client, user):
        # User-scoping is load-bearing: compaction must renumber only the
        # requesting user's rules, never another user's rows.
        other = User.objects.create_user(username="o_compact", password="x")
        theirs = Rule.objects.create(user=other, text="Theirs", priority=42)

        resp = _post(auth_client, "/api/rules/", {"text": "Mine"})

        assert resp.status_code == 201
        theirs.refresh_from_db()
        assert theirs.priority == 42  # untouched by our compaction

    def test_compaction_preserves_id_tiebreak_for_equal_priorities(
        self, auth_client, user
    ):
        # Two rules share a priority; the canonical order_by("-priority", "id")
        # tiebreak (lower id first) must survive compaction deterministically.
        older = Rule.objects.create(user=user, text="Older", priority=3)
        newer = Rule.objects.create(user=user, text="Newer", priority=3)
        assert older.id < newer.id

        resp = _post(auth_client, "/api/rules/", {"text": "Top"})

        assert resp.status_code == 201
        listed = auth_client.get("/api/rules/").json()["rules"]
        assert [rule["text"] for rule in listed] == ["Top", "Older", "Newer"]
        assert [rule["priority"] for rule in listed] == [2, 1, 0]

    def test_patch_rule(self, auth_client, user):
        r = Rule.objects.create(user=user, text="Old", priority=5)
        resp = _patch(
            auth_client, f"/api/rules/{r.id}/", {"text": "New", "is_active": False}
        )
        assert resp.status_code == 200
        r.refresh_from_db()
        assert r.text == "New"
        assert r.is_active is False

    def test_patch_does_not_compact_priorities(self, auth_client, user):
        # PATCH must NOT renumber to 0..N-1 — that would fight the
        # RulesList.vue bumpPriority two-PATCH swap mid-reorder. Compaction
        # runs on create/delete only. Non-contiguous priorities left as-is.
        low = Rule.objects.create(user=user, text="Low", priority=0)
        high = Rule.objects.create(user=user, text="High", priority=5)

        resp = _patch(auth_client, f"/api/rules/{high.id}/", {"text": "High edited"})

        assert resp.status_code == 200
        low.refresh_from_db()
        high.refresh_from_db()
        assert low.priority == 0
        assert high.priority == 5  # not compacted to 1

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

    def test_delete_compacts_priorities(self, auth_client, user):
        bottom = Rule.objects.create(user=user, text="Bottom", priority=0)
        Rule.objects.create(user=user, text="Middle", priority=1)
        Rule.objects.create(user=user, text="Top", priority=2)

        resp = auth_client.delete(f"/api/rules/{bottom.id}/")

        assert resp.status_code == 200
        listed = auth_client.get("/api/rules/").json()["rules"]
        assert [rule["text"] for rule in listed] == ["Top", "Middle"]
        assert [rule["priority"] for rule in listed] == [1, 0]

    def test_add_delete_cycle_keeps_priorities_small(self, auth_client):
        first_resp = _post(auth_client, "/api/rules/", {"text": "Rule one"})
        second_resp = _post(auth_client, "/api/rules/", {"text": "Rule two"})
        assert first_resp.status_code == second_resp.status_code == 201

        delete_resp = auth_client.delete(
            f"/api/rules/{first_resp.json()['id']}/"
        )
        assert delete_resp.status_code == 200
        third_resp = _post(auth_client, "/api/rules/", {"text": "Rule three"})
        assert third_resp.status_code == 201

        listed = auth_client.get("/api/rules/").json()["rules"]
        assert [rule["text"] for rule in listed] == ["Rule three", "Rule two"]
        assert {rule["priority"] for rule in listed} == {0, 1}

    def test_rule_post_locks_user_before_count_and_create(
        self, auth_client, user, monkeypatch
    ):
        """Slice 7: Rule POST acquires the user row lock before count/create."""
        events: list[str] = []
        original_user_sfu = User.objects.select_for_update
        original_filter = Rule.objects.filter
        original_create = Rule.objects.create

        def user_sfu_spy(*args, **kwargs):
            events.append("user_lock")
            return original_user_sfu(*args, **kwargs)

        def filter_spy(*args, **kwargs):
            qs = original_filter(*args, **kwargs)
            original_count = qs.count

            def count_spy():
                events.append("count")
                return original_count()

            qs.count = count_spy
            return qs

        def create_spy(*args, **kwargs):
            events.append("create")
            return original_create(*args, **kwargs)

        monkeypatch.setattr(
            User.objects, "select_for_update", user_sfu_spy, raising=True
        )
        monkeypatch.setattr(Rule.objects, "filter", filter_spy, raising=True)
        monkeypatch.setattr(Rule.objects, "create", create_spy, raising=True)

        resp = _post(
            auth_client,
            "/api/rules/",
            {"text": "Lock order", "priority": 1},
        )
        assert resp.status_code == 201
        assert events == ["user_lock", "count", "create"]

    def test_rule_patch_locks_user_before_refetch_and_save(
        self, auth_client, user, monkeypatch
    ):
        """Slice 7: Rule PATCH locks the user row before target re-fetch."""
        r = Rule.objects.create(user=user, text="Old", priority=1)
        call_order: list[str] = []
        original_user_sfu = User.objects.select_for_update
        original_get = Rule.objects.get

        def user_sfu_spy(*args, **kwargs):
            call_order.append("user_lock")
            return original_user_sfu(*args, **kwargs)

        def get_spy(*args, **kwargs):
            call_order.append("get")
            return original_get(*args, **kwargs)

        monkeypatch.setattr(
            User.objects, "select_for_update", user_sfu_spy, raising=True
        )
        monkeypatch.setattr(Rule.objects, "get", get_spy, raising=True)

        resp = _patch(auth_client, f"/api/rules/{r.id}/", {"text": "New"})
        assert resp.status_code == 200
        assert call_order == ["user_lock", "get"]

    def test_rule_delete_locks_user_before_refetch(
        self, auth_client, user, monkeypatch
    ):
        """Slice 7: Rule DELETE locks the user row before target re-fetch."""
        r = Rule.objects.create(user=user, text="Gone")
        call_order: list[str] = []
        original_user_sfu = User.objects.select_for_update
        original_get = Rule.objects.get

        def user_sfu_spy(*args, **kwargs):
            call_order.append("user_lock")
            return original_user_sfu(*args, **kwargs)

        def get_spy(*args, **kwargs):
            call_order.append("get")
            return original_get(*args, **kwargs)

        monkeypatch.setattr(
            User.objects, "select_for_update", user_sfu_spy, raising=True
        )
        monkeypatch.setattr(Rule.objects, "get", get_spy, raising=True)

        resp = auth_client.delete(f"/api/rules/{r.id}/")
        assert resp.status_code == 200
        assert call_order == ["user_lock", "get"]

    def test_rule_patch_404_when_target_deleted_under_lock(
        self, auth_client, user, monkeypatch
    ):
        """Slice 7: a delete between user lock and re-fetch returns uniform 404."""
        r = Rule.objects.create(user=user, text="Vanish")
        original_user_sfu = User.objects.select_for_update

        def user_sfu_spy(*args, **kwargs):
            Rule.objects.filter(pk=r.pk).delete()
            return original_user_sfu(*args, **kwargs)

        monkeypatch.setattr(
            User.objects, "select_for_update", user_sfu_spy, raising=True
        )

        resp = _patch(auth_client, f"/api/rules/{r.id}/", {"text": "Too late"})
        assert resp.status_code == 404
        assert resp.json() == {"errors": {"detail": "Not found."}}


@pytest.mark.django_db
class TestRulePriorityBounds:
    """Bounds-check on the ``priority`` field. Without this the API would
    accept arbitrary-precision Python ints and let them propagate to the
    DB, where Django's ``IntegerField`` (32-bit signed) would reject them
    with a ``DataError`` and surface as a 500. Bounding at the API layer
    turns that into a structured 400."""

    def test_create_rejects_priority_above_max(self, auth_client):
        resp = _post(
            auth_client,
            "/api/rules/",
            {"text": "X", "priority": 10**12},
        )
        assert resp.status_code == 400
        assert "priority" in resp.json()["errors"]

    def test_create_rejects_priority_below_min(self, auth_client):
        resp = _post(
            auth_client,
            "/api/rules/",
            {"text": "X", "priority": -10**12},
        )
        assert resp.status_code == 400
        assert "priority" in resp.json()["errors"]

    def test_create_accepts_priority_at_max_and_places_rule_on_top(
        self, auth_client, user
    ):
        from templates_mgr.api import MAX_PRIORITY

        Rule.objects.create(user=user, text="Existing", priority=0)
        resp = _post(
            auth_client,
            "/api/rules/",
            {"text": "X", "priority": MAX_PRIORITY},
        )
        assert resp.status_code == 201
        assert resp.json()["priority"] == 1
        listed = auth_client.get("/api/rules/").json()["rules"]
        assert [rule["text"] for rule in listed] == ["X", "Existing"]
        assert [rule["priority"] for rule in listed] == [1, 0]

    def test_patch_rejects_out_of_range_priority(self, auth_client, user):
        r = Rule.objects.create(user=user, text="X", priority=5)
        resp = _patch(
            auth_client, f"/api/rules/{r.id}/", {"priority": 10**12}
        )
        assert resp.status_code == 400
        r.refresh_from_db()
        assert r.priority == 5  # unchanged

    def test_patch_accepts_priority_at_min(self, auth_client, user):
        from templates_mgr.api import MIN_PRIORITY

        r = Rule.objects.create(user=user, text="X", priority=0)
        resp = _patch(
            auth_client, f"/api/rules/{r.id}/", {"priority": MIN_PRIORITY}
        )
        assert resp.status_code == 200
        r.refresh_from_db()
        assert r.priority == MIN_PRIORITY
