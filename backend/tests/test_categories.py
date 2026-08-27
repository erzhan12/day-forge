"""Feature 0063 — user-customizable time-block categories.

Covers the plan-mandated RED matrix: seed-on-first-read (+ race fallback),
CRUD + immutability guards, the 8-row cap, reorder/swap, cross-user isolation,
the delete-remap transaction across every storage form, per-request slug
validation/defaults, and the analytics unknown-slug fold.
"""

import datetime
import json
from unittest import mock

import pytest
from analytics.models import DailyReview
from analytics.services import compute_review_stats
from analytics.views import _normalized_category_minutes
from calendar_sync.models import TravelRule
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError, OperationalError
from django.test import Client
from schedules.categories import (
    create_category,
    default_category,
    delete_category,
    ordered_categories,
    sink_category,
    validate_slug,
)
from schedules.models import Category, Schedule, TimeBlock
from templates_mgr.models import Template

User = get_user_model()

COLLECTION = "/api/user/categories/"
SWAP = "/api/user/categories/swap/"


def _detail(pk):
    return f"/api/user/categories/{pk}/"


def _post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def _patch(client, url, payload):
    return client.patch(url, data=json.dumps(payload), content_type="application/json")


def _slugs(rows):
    return [r["slug"] for r in rows]


# --------------------------------------------------------------------------- #
# Seed on first read
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestSeedOnFirstRead:
    def test_first_read_seeds_exact_four_rows(self, user):
        rows = ordered_categories(user)
        assert [(r.slug, r.label, r.color_id, r.sort_order) for r in rows] == [
            ("work", "Work", "blue", 0),
            ("personal", "Personal", "violet", 1),
            ("health", "Health", "emerald", 2),
            ("other", "Other", "gray", 3),
        ]
        assert sink_category(rows).slug == "other"
        assert default_category(rows).slug == "work"

    def test_repeated_reads_are_idempotent(self, user):
        first = ordered_categories(user)
        second = ordered_categories(user)
        assert [r.pk for r in first] == [r.pk for r in second]
        assert Category.objects.filter(user=user).count() == 4

    def test_no_repair_when_catalog_non_empty(self, user):
        # A single valid sink row (the check constraint binds is_sink to slug "other").
        Category.objects.create(user=user, slug="other", label="Solo", color_id="gray",
                                is_sink=True)
        rows = ordered_categories(user)
        assert [r.slug for r in rows] == ["other"]
        assert Category.objects.filter(user=user).count() == 1

    def test_catalogs_are_isolated_between_users(self, user):
        other = User.objects.create_user(username="u2", password="x")
        ordered_categories(user)
        ordered_categories(other)
        assert Category.objects.filter(user=user).count() == 4
        assert Category.objects.filter(user=other).count() == 4
        assert set(Category.objects.filter(user=user).values_list("pk", flat=True)).isdisjoint(
            Category.objects.filter(user=other).values_list("pk", flat=True)
        )

    def test_seed_recovers_from_integrityerror(self, user):
        """A transient IntegrityError on the first seed attempt (a concurrent
        seeder committing between our re-query and insert) must be retried,
        not surfaced as a 500."""
        real = Category.objects.get_or_create
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            if calls["n"] == 0:
                calls["n"] += 1
                raise IntegrityError("duplicate key (user, slug)")
            return real(*args, **kwargs)

        with mock.patch.object(Category.objects, "get_or_create", side_effect=flaky):
            rows = ordered_categories(user)
        assert [r.slug for r in rows] == ["work", "personal", "health", "other"]
        assert Category.objects.filter(user=user).count() == 4

    def test_seed_recovers_from_operationalerror(self, user):
        """SQLite's deferred-transaction lock-upgrade race can raise
        OperationalError('database is locked'); the retry loop must recover."""
        real = Category.objects.get_or_create
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            if calls["n"] == 0:
                calls["n"] += 1
                raise OperationalError("database is locked")
            return real(*args, **kwargs)

        with mock.patch.object(Category.objects, "get_or_create", side_effect=flaky):
            rows = ordered_categories(user)
        assert [r.slug for r in rows] == ["work", "personal", "health", "other"]


# --------------------------------------------------------------------------- #
# Model field enlargement (32-char slug via full_clean — the RED vehicle)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestModelValidation:
    def test_long_slug_passes_full_clean(self, user):
        """>10 chars (old max_length) and no choices — proves the field
        enlargement/choice-drop landed."""
        row = Category(user=user, slug="deep-work-strategy", label="Deep Work Strategy",
                       color_id="blue")
        row.full_clean()  # must not raise

    def test_oversized_label_fails_full_clean(self, user):
        row = Category(user=user, slug="x", label="z" * 65, color_id="blue")
        with pytest.raises(ValidationError):
            row.full_clean()


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestCreate:
    def test_create_trims_and_slugifies(self, auth_client):
        resp = _post(auth_client, COLLECTION, {"label": "  Deep  Work  ", "color_id": "amber"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["label"] == "Deep  Work"
        assert body["slug"] == "deep-work"
        assert body["color_id"] == "amber"
        assert body["is_sink"] is False
        assert body["is_new_block_default"] is False

    def test_slug_collision_gets_suffix(self, auth_client):
        # Distinct labels that slugify to the same base.
        first = _post(auth_client, COLLECTION, {"label": "Deep Work", "color_id": "blue"})
        second = _post(auth_client, COLLECTION, {"label": "Deep-Work", "color_id": "blue"})
        assert first.json()["slug"] == "deep-work"
        assert second.status_code == 201
        assert second.json()["slug"] == "deep-work-2"

    def test_duplicate_label_case_insensitive_rejected(self, auth_client):
        _post(auth_client, COLLECTION, {"label": "Focus", "color_id": "blue"})
        resp = _post(auth_client, COLLECTION, {"label": "  focus ", "color_id": "rose"})
        assert resp.status_code == 400
        assert "already exists" in resp.json()["errors"]["category"]

    def test_shared_color_is_allowed(self, auth_client):
        a = _post(auth_client, COLLECTION, {"label": "A", "color_id": "cyan"})
        b = _post(auth_client, COLLECTION, {"label": "B", "color_id": "cyan"})
        assert a.status_code == 201 and b.status_code == 201

    def test_empty_label_rejected(self, auth_client):
        resp = _post(auth_client, COLLECTION, {"label": "   ", "color_id": "blue"})
        assert resp.status_code == 400

    def test_invalid_color_rejected(self, auth_client):
        resp = _post(auth_client, COLLECTION, {"label": "X", "color_id": "chartreuse"})
        assert resp.status_code == 400
        assert resp.json()["errors"]["category"] == "Invalid color_id."

    def test_non_string_color_returns_400_not_500(self, auth_client):
        resp = _post(auth_client, COLLECTION, {"label": "X", "color_id": []})
        assert resp.status_code == 400

    def test_cap_of_eight_enforced(self, auth_client):
        # Seed (4) + 4 more = 8, then the 9th is rejected.
        for i in range(4):
            assert _post(auth_client, COLLECTION,
                         {"label": f"Extra {i}", "color_id": "blue"}).status_code == 201
        resp = _post(auth_client, COLLECTION, {"label": "Ninth", "color_id": "blue"})
        assert resp.status_code == 400
        assert "maximum" in resp.json()["errors"]["category"]


# --------------------------------------------------------------------------- #
# Update / immutability guards
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestUpdate:
    def _seed_and_get(self, auth_client, slug):
        rows = auth_client.get(COLLECTION).json()["categories"]
        return next(r for r in rows if r["slug"] == slug)

    def test_rename_keeps_slug(self, auth_client):
        work = self._seed_and_get(auth_client, "work")
        resp = _patch(auth_client, _detail(work["id"]), {"label": "Deep Work"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "Deep Work"
        assert resp.json()["slug"] == "work"

    def test_slug_edit_rejected(self, auth_client):
        work = self._seed_and_get(auth_client, "work")
        resp = _patch(auth_client, _detail(work["id"]), {"slug": "hacked"})
        assert resp.status_code == 400
        assert "immutable" in resp.json()["errors"]["category"]

    def test_clear_is_sink_rejected(self, auth_client):
        sink = self._seed_and_get(auth_client, "other")
        resp = _patch(auth_client, _detail(sink["id"]), {"is_sink": False})
        assert resp.status_code == 400

    def test_sink_label_and_color_remain_editable(self, auth_client):
        sink = self._seed_and_get(auth_client, "other")
        resp = _patch(auth_client, _detail(sink["id"]), {"label": "Misc", "color_id": "indigo"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "Misc"
        assert resp.json()["color_id"] == "indigo"
        assert resp.json()["is_sink"] is True

    def test_non_string_color_patch_returns_400_not_500(self, auth_client):
        work = self._seed_and_get(auth_client, "work")
        resp = _patch(auth_client, _detail(work["id"]), {"color_id": {}})
        assert resp.status_code == 400

    def test_default_promotion_leaves_exactly_one_default(self, auth_client):
        personal = self._seed_and_get(auth_client, "personal")
        resp = _patch(auth_client, _detail(personal["id"]), {"is_new_block_default": True})
        assert resp.status_code == 200
        rows = auth_client.get(COLLECTION).json()["categories"]
        defaults = [r for r in rows if r["is_new_block_default"]]
        assert [r["slug"] for r in defaults] == ["personal"]

    def test_unset_only_default_rejected(self, auth_client):
        work = self._seed_and_get(auth_client, "work")
        resp = _patch(auth_client, _detail(work["id"]), {"is_new_block_default": False})
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Delete / delete-remap (the highest-risk path)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestDeleteRemap:
    def _make_focus(self, user):
        ordered_categories(user)
        return create_category(user, "Focus", "rose")

    def test_sink_cannot_be_deleted(self, auth_client, user):
        sink = sink_category(ordered_categories(user))
        resp = auth_client.delete(_detail(sink.pk))
        assert resp.status_code == 400
        assert "sink" in resp.json()["errors"]["category"].lower()
        assert Category.objects.filter(pk=sink.pk).exists()

    def test_delete_remaps_every_storage_form(self, user):
        focus = self._make_focus(user)
        sched = Schedule.objects.create(date="2026-05-01", user=user)
        TimeBlock.objects.create(schedule=sched, title="F", start_time="08:00",
                                 end_time="09:00", category="focus")
        tmpl = Template.objects.create(
            user=user, name="T", type="daily",
            blocks=[{"title": "F", "category": "focus"}, {"title": "W", "category": "work"}],
        )
        rule = TravelRule.objects.create(user=user, keyword="gym", category="focus")
        empty_rule = TravelRule.objects.create(user=user, keyword="none", category="")
        review = DailyReview.objects.create(
            schedule=sched,
            planned_minutes_by_category={"focus": 30, "other": 10},
            completed_minutes_by_category={"focus": 15},
        )

        delete_category(user, focus)

        assert TimeBlock.objects.get(title="F").category == "other"
        tmpl.refresh_from_db()
        assert tmpl.blocks[0]["category"] == "other"
        assert tmpl.blocks[1]["category"] == "work"
        rule.refresh_from_db()
        assert rule.category == "other"
        empty_rule.refresh_from_db()
        assert empty_rule.category == ""  # "no override" untouched
        review.refresh_from_db()
        assert "focus" not in review.planned_minutes_by_category
        assert review.planned_minutes_by_category["other"] == 40  # 10 + 30
        assert review.completed_minutes_by_category["other"] == 15  # 0 + 15
        assert not Category.objects.filter(pk=focus.pk).exists()

    def test_delete_folds_into_malformed_sink_value(self, user):
        focus = self._make_focus(user)
        sched = Schedule.objects.create(date="2026-05-02", user=user)
        review = DailyReview.objects.create(
            schedule=sched,
            planned_minutes_by_category={"focus": 30, "other": None},
            completed_minutes_by_category={},
        )
        delete_category(user, focus)
        review.refresh_from_db()
        assert review.planned_minutes_by_category["other"] == 30  # None coerced to 0

    def test_delete_of_default_promotes_sink(self, user):
        focus = self._make_focus(user)
        focus.is_new_block_default = True
        Category.objects.filter(user=user, is_new_block_default=True).exclude(pk=focus.pk).update(
            is_new_block_default=False
        )
        focus.save()
        delete_category(user, focus)
        defaults = list(Category.objects.filter(user=user, is_new_block_default=True))
        assert [c.slug for c in defaults] == ["other"]

    def test_delete_isolated_from_other_user(self, user):
        focus_a = self._make_focus(user)
        other = User.objects.create_user(username="u2", password="x")
        ordered_categories(other)
        create_category(other, "Focus", "rose")
        sched_b = Schedule.objects.create(date="2026-05-03", user=other)
        TimeBlock.objects.create(schedule=sched_b, title="B", start_time="08:00",
                                 end_time="09:00", category="focus")
        delete_category(user, focus_a)
        # Other user's block + category untouched.
        assert TimeBlock.objects.get(title="B").category == "focus"
        assert Category.objects.filter(user=other, slug="focus").exists()

    def test_delete_rolls_back_on_injected_failure(self, user):
        focus = self._make_focus(user)
        sched = Schedule.objects.create(date="2026-05-04", user=user)
        TimeBlock.objects.create(schedule=sched, title="F", start_time="08:00",
                                 end_time="09:00", category="focus")
        with mock.patch(
            "schedules.categories.TravelRule.objects.filter",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                delete_category(user, focus)
        # Nothing committed: block not remapped, category row still present.
        assert TimeBlock.objects.get(title="F").category == "focus"
        assert Category.objects.filter(pk=focus.pk).exists()


# --------------------------------------------------------------------------- #
# Reorder / swap + cross-user
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestSwapAndOwnership:
    def test_swap_exchanges_sort_order(self, auth_client, user):
        rows = auth_client.get(COLLECTION).json()["categories"]
        work, personal = rows[0], rows[1]
        resp = _post(auth_client, SWAP, {"a": work["id"], "b": personal["id"]})
        assert resp.status_code == 200
        after = {r["slug"]: r["sort_order"] for r in resp.json()["categories"]}
        assert after["work"] == 1
        assert after["personal"] == 0

    def test_swap_cross_user_id_rejected(self, auth_client, user):
        rows = auth_client.get(COLLECTION).json()["categories"]
        other = User.objects.create_user(username="u2", password="x")
        foreign = Category.objects.create(user=other, slug="x", label="X", color_id="blue")
        resp = _post(auth_client, SWAP, {"a": rows[0]["id"], "b": foreign.pk})
        assert resp.status_code == 404

    def test_patch_cross_user_returns_404(self, auth_client):
        other = User.objects.create_user(username="u2", password="x")
        foreign = Category.objects.create(user=other, slug="x", label="X", color_id="blue")
        resp = _patch(auth_client, _detail(foreign.pk), {"label": "Y"})
        assert resp.status_code == 404
        foreign.refresh_from_db()
        assert foreign.label == "X"

    def test_delete_cross_user_returns_404(self, auth_client):
        other = User.objects.create_user(username="u2", password="x")
        foreign = Category.objects.create(user=other, slug="x", label="X", color_id="blue")
        resp = auth_client.delete(_detail(foreign.pk))
        assert resp.status_code == 404
        assert Category.objects.filter(pk=foreign.pk).exists()


# --------------------------------------------------------------------------- #
# Per-request slug validation / defaults
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestValidateSlug:
    def test_non_string_rejected(self, user):
        with pytest.raises(ValueError):
            validate_slug(["work"], ordered_categories(user))

    def test_unknown_rejected_by_default(self, user):
        with pytest.raises(ValueError):
            validate_slug("nope", ordered_categories(user))

    def test_unknown_folds_to_sink_when_lenient(self, user):
        assert validate_slug("nope", ordered_categories(user), unknown_to_sink=True) == "other"

    def test_known_slug_passthrough(self, user):
        assert validate_slug("health", ordered_categories(user)) == "health"


@pytest.mark.django_db
class TestCatalogInvariantGuards:
    def test_sink_category_raises_on_missing_sink(self):
        rows = [
            Category(slug="work", label="Work", color_id="blue", is_sink=False),
            Category(slug="focus", label="Focus", color_id="rose", is_sink=False),
        ]
        with pytest.raises(RuntimeError):
            sink_category(rows)

    def test_default_category_raises_on_missing_default(self):
        rows = [
            Category(slug="other", label="Other", color_id="gray", is_sink=True,
                     is_new_block_default=False),
        ]
        with pytest.raises(RuntimeError):
            default_category(rows)

    def test_category_str(self, user):
        row = ordered_categories(user)[0]
        assert str(row) == f"{user}:work"


# --------------------------------------------------------------------------- #
# Analytics unknown-slug fold
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestAnalyticsFold:
    def test_unknown_block_slug_folds_into_sink_not_keyerror(self, user):
        sched = Schedule.objects.create(date=datetime.date(2026, 5, 5), user=user)
        TimeBlock.objects.create(schedule=sched, title="ghost", start_time="08:00",
                                 end_time="09:00", category="deleted-slug", is_completed=True)
        stats = compute_review_stats(sched, now=datetime.date(2026, 5, 6),
                                     categories=ordered_categories(user))
        assert "deleted-slug" not in stats["planned_minutes_by_category"]
        assert stats["planned_minutes_by_category"]["other"] == 60

    def test_normalized_minutes_folds_stale_keys(self, user):
        cats = ordered_categories(user)
        folded = _normalized_category_minutes({"deleted": 30, "other": 10, "work": 5}, cats)
        assert "deleted" not in folded
        assert folded["other"] == 40  # 10 + 30
        assert folded["work"] == 5

    def test_normalized_minutes_coerces_malformed(self, user):
        cats = ordered_categories(user)
        folded = _normalized_category_minutes({"work": None, "deleted": "x"}, cats)
        assert folded["work"] == 0
        assert folded["other"] == 0


# --------------------------------------------------------------------------- #
# Per-request defaults + mid-request-delete hardening (HTTP)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestPerRequestDefaults:
    def test_create_block_omitted_category_uses_default(self, auth_client, user):
        # Regression guard: omitted category must resolve to the user's
        # new-block default (seeded "work"), not a hardcoded "other".
        resp = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({"title": "X", "start_time": "08:00", "end_time": "09:00"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["category"] == "work"

    def test_create_block_in_txn_deleted_slug_returns_400_not_500(self, auth_client):
        # The in-transaction revalidation rejects a slug deleted after the
        # pre-check; it must surface as a clean 400, never a 500.
        with mock.patch(
            "schedules.api.validate_slug",
            side_effect=["work", ValueError("Category must be a string.")],
        ):
            resp = auth_client.post(
                "/api/schedules/2026-04-07/blocks/",
                json.dumps({"title": "X", "start_time": "08:00", "end_time": "09:00",
                            "category": "work"}),
                content_type="application/json",
            )
        assert resp.status_code == 400
        assert "category" in resp.json()["errors"]


@pytest.mark.django_db
class TestConcurrencyHardening:
    def test_create_category_maps_integrityerror_to_clean_error(self, user):
        # A concurrent same-slug insert (unique constraint) must not surface
        # as a 500 — create_category retries then raises a clean ValueError.
        ordered_categories(user)
        with mock.patch.object(
            Category.objects, "create", side_effect=IntegrityError("dup (user, slug)")
        ):
            with pytest.raises(ValueError):
                create_category(user, "Focus", "rose")

    def test_create_category_integrityerror_returns_400_over_http(self, auth_client, user):
        ordered_categories(user)
        with mock.patch.object(
            Category.objects, "create", side_effect=IntegrityError("dup (user, slug)")
        ):
            resp = _post(auth_client, COLLECTION, {"label": "Focus", "color_id": "rose"})
        assert resp.status_code == 400

    def test_delete_racing_concurrent_delete_returns_404(self, auth_client, user):
        # The endpoint fetch succeeds, then a concurrent DELETE removes the row
        # before the service re-fetches it under the transaction → 404, not 500.
        focus = create_category(user, "Focus", "rose")
        with mock.patch(
            "schedules.category_api.delete_category", side_effect=Category.DoesNotExist
        ):
            resp = auth_client.delete(_detail(focus.pk))
        assert resp.status_code == 404

    def test_patch_racing_concurrent_delete_returns_404(self, auth_client, user):
        focus = create_category(user, "Focus", "rose")
        with mock.patch(
            "schedules.category_api.update_category", side_effect=Category.DoesNotExist
        ):
            resp = _patch(auth_client, _detail(focus.pk), {"label": "Renamed"})
        assert resp.status_code == 404

    def test_patch_label_race_integrityerror_returns_400(self, auth_client, user):
        focus = create_category(user, "Focus", "rose")
        with mock.patch(
            "schedules.category_api.update_category",
            side_effect=IntegrityError("dup label ci"),
        ):
            resp = _patch(auth_client, _detail(focus.pk), {"label": "Personal"})
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Per-user mutation rate limit (feature 0064)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestCategoryMutationRateLimit:
    """One shared per-user counter gates create/update/delete/swap; GET
    reads are never counted. Backed by ``schedules.ratelimit`` — the same
    fixed-window helper as the connect endpoints. ``_clear_cache`` (autouse)
    resets the counter between tests; the budget is pinned to 2 here.
    """

    @pytest.fixture(autouse=True)
    def _pin_budget(self, settings):
        settings.CATEGORY_MUTATION_RATE_LIMIT_PER_HOUR = 2

    def _ids(self, client):
        """Return category ids via a GET (a read — never counted)."""
        return [row["id"] for row in client.get(COLLECTION).json()["categories"]]

    def _create(self, client, label, color):
        return _post(client, COLLECTION, {"label": label, "color_id": color})

    def _second_client(self):
        User.objects.create_user(username="other", password="pw12345678")
        client = Client()
        client.login(username="other", password="pw12345678")
        return client

    def test_create_blocked_after_budget_spent(self, auth_client):
        assert self._create(auth_client, "A", "blue").status_code == 201
        assert self._create(auth_client, "B", "cyan").status_code == 201
        resp = self._create(auth_client, "C", "amber")
        assert resp.status_code == 429
        assert resp.json() == {"errors": {"detail": "Rate limit exceeded. Try again later."}}
        assert resp["Retry-After"] == "3600"

    def test_get_reads_never_counted(self, auth_client):
        for _ in range(5):
            assert auth_client.get(COLLECTION).status_code == 200
        # Budget untouched by reads → both writes still land before the block.
        assert self._create(auth_client, "A", "blue").status_code == 201
        assert self._create(auth_client, "B", "cyan").status_code == 201
        assert self._create(auth_client, "C", "amber").status_code == 429

    def test_all_verbs_share_one_counter(self, auth_client):
        a, b = self._ids(auth_client)[:2]
        # Verb 1 — swap. Verb 2 — create. Both under the budget of 2.
        assert _post(auth_client, SWAP, {"a": a, "b": b}).status_code != 429
        assert self._create(auth_client, "New", "amber").status_code != 429
        # Budget spent; a DELETE (guard fires before the row fetch) → 429,
        # not the 404 an over-budget request would otherwise get.
        assert auth_client.delete(_detail(999999)).status_code == 429

    def test_swap_gated_after_budget(self, auth_client):
        a, b = self._ids(auth_client)[:2]
        assert _post(auth_client, SWAP, {"a": a, "b": b}).status_code != 429
        assert _post(auth_client, SWAP, {"a": a, "b": b}).status_code != 429
        assert _post(auth_client, SWAP, {"a": a, "b": b}).status_code == 429

    def test_budget_is_per_user(self, auth_client):
        self._create(auth_client, "A", "blue")
        self._create(auth_client, "B", "cyan")
        assert self._create(auth_client, "C", "amber").status_code == 429
        # A second user's counter is independent and still full.
        other = self._second_client()
        assert self._create(other, "X", "blue").status_code == 201
