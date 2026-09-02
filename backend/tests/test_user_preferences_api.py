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
from schedules.models import Schedule, TimeBlock, UserScheduleSettings
from templates_mgr import preferences as preferences_module
from templates_mgr.models import UserPreferences
from templates_mgr.preferences import (
    UserPreferencesDTO,
    get_user_preferences,
    normalize_theme,
    ui_preferences_payload,
)

pytestmark = pytest.mark.django_db

DEFAULT_CHAT_SUGGESTIONS = [
    "Plan my remaining day",
    "Add a focused work block",
    "Make room for a break",
]


# 0072 opacity contract. These tests intentionally precede the model/API
# implementation; GET, PATCH and Inertia serializers must stay shape-equal.
def test_focus_indicator_opacity_default_and_dto_shape(user, auth_client):
    dto = get_user_preferences(user)
    assert dto.focus_indicator_opacity == 0.70
    assert ui_preferences_payload(dto)["focus_indicator_opacity"] == 0.70
    assert auth_client.get(reverse("user_preferences")).json()["focus_indicator_opacity"] == 0.70


@pytest.mark.parametrize("value", [0.20, 1.00, 0.42])
def test_focus_indicator_opacity_patch_round_trips(auth_client, user, value):
    response = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"focus_indicator_opacity": value}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["focus_indicator_opacity"] == value
    assert UserPreferences.objects.get(user=user).focus_indicator_opacity == value


@pytest.mark.parametrize(
    "value",
    [".7", None, True, [], {}, float("nan"), float("inf"), 0.19, 1.01, 10**400, -(10**400)],
)
def test_focus_indicator_opacity_invalid_patch_is_structured_and_atomic(auth_client, user, value):
    UserPreferences.objects.create(user=user, theme="classic", chat_suggestions=["Original"])
    response = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "strategic", "focus_indicator_opacity": value}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "focus_indicator_opacity" in response.json()["errors"]
    assert response.headers["Cache-Control"] == "private, no-store"
    row = UserPreferences.objects.get(user=user)
    assert row.theme == "classic"


def test_focus_indicator_opacity_read_normalizes_without_writing(user):
    UserPreferences.objects.create(user=user, theme="classic")
    UserPreferences.objects.filter(user=user).update(focus_indicator_opacity=4.0)
    assert get_user_preferences(user).focus_indicator_opacity == 1.0
    assert UserPreferences.objects.get(user=user).focus_indicator_opacity == 4.0


def _patch_prefs(client, payload):
    return client.patch(
        reverse("user_preferences"),
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_focus_indicator_opacity_partial_patch_preserves_each_field(auth_client, user):
    assert _patch_prefs(auth_client, {"focus_indicator_opacity": 0.33}).status_code == 200
    # A theme-only PATCH must not reset opacity...
    themed = _patch_prefs(auth_client, {"theme": "strategic"})
    assert themed.json()["theme"] == "strategic"
    assert themed.json()["focus_indicator_opacity"] == 0.33
    # ...and an opacity-only PATCH must not reset theme.
    opac = _patch_prefs(auth_client, {"focus_indicator_opacity": 0.88})
    assert opac.json()["theme"] == "strategic"
    assert opac.json()["focus_indicator_opacity"] == 0.88
    assert UserPreferences.objects.get(user=user).focus_indicator_opacity == 0.88


def test_focus_indicator_opacity_is_isolated_per_user(auth_client, user):
    other = User.objects.create_user(username="other0072", password="otherpass123")
    other_client = Client()
    other_client.force_login(other)
    assert _patch_prefs(auth_client, {"focus_indicator_opacity": 0.25}).status_code == 200
    assert _patch_prefs(other_client, {"focus_indicator_opacity": 0.95}).status_code == 200
    assert UserPreferences.objects.get(user=user).focus_indicator_opacity == 0.25
    assert UserPreferences.objects.get(user=other).focus_indicator_opacity == 0.95
    # The reader never bleeds one account's value into the other's response.
    assert auth_client.get(reverse("user_preferences")).json()["focus_indicator_opacity"] == 0.25


def test_focus_indicator_opacity_saved_value_flows_through_shared_payload(auth_client, user):
    # Every Inertia page and the JSON API serialize through ui_preferences_payload;
    # a saved value must survive that shared path (guards serializer drift).
    assert _patch_prefs(auth_client, {"focus_indicator_opacity": 0.37}).status_code == 200
    assert ui_preferences_payload(get_user_preferences(user))["focus_indicator_opacity"] == 0.37


# ---------------------------------------------------------------------------
# Helper / DTO contract
# ---------------------------------------------------------------------------


def test_helper_creates_default_row_on_first_access(user):
    assert not UserPreferences.objects.filter(user=user).exists()
    dto = get_user_preferences(user)
    assert dto.theme == "classic"
    assert list(dto.chat_suggestions) == DEFAULT_CHAT_SUGGESTIONS
    assert UserPreferences.objects.filter(user=user).exists()
    # The created row stores NULL, not a materialized copy of the defaults,
    # so the row keeps tracking DEFAULT_CHAT_SUGGESTIONS until the user
    # explicitly customizes. A create-path that persisted the defaults would
    # otherwise pass every other assertion here.
    assert UserPreferences.objects.get(user=user).chat_suggestions is None


def test_ui_preferences_payload_serializes_dto_shape():
    dto = UserPreferencesDTO(
        theme="strategic",
        chat_suggestions=("First", "Second"),
        focus_indicator_opacity=0.70,
    )

    assert ui_preferences_payload(dto) == {
        "theme": "strategic",
        "chat_suggestions": ["First", "Second"],
        "focus_indicator_opacity": 0.70,
    }


def test_prefs_to_dict_matches_ui_preferences_payload_shape(user):
    # `_prefs_to_dict` (PATCH response) and `ui_preferences_payload`
    # (GET + Inertia props) are parallel serializers. Pin their key sets
    # equal so adding a `UiPreferences` field to one without the other
    # fails the suite immediately instead of silently diverging PATCH from
    # GET/Inertia.
    from templates_mgr.api import _prefs_to_dict

    row, _ = UserPreferences.objects.get_or_create(
        user=user, defaults={"theme": "classic"}
    )
    patch_shape = _prefs_to_dict(row)
    payload_shape = ui_preferences_payload(get_user_preferences(user))
    assert set(patch_shape) == set(payload_shape)


def test_backend_chat_suggestion_constants_are_pinned():
    assert preferences_module.DEFAULT_CHAT_SUGGESTIONS == DEFAULT_CHAT_SUGGESTIONS
    assert preferences_module.MAX_CHAT_SUGGESTIONS == 8
    assert preferences_module.MAX_CHAT_SUGGESTION_LENGTH == 120


def test_helper_null_suggestions_resolve_to_defaults(user):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=None
    )
    dto = get_user_preferences(user)
    assert list(dto.chat_suggestions) == DEFAULT_CHAT_SUGGESTIONS
    assert UserPreferences.objects.get(user=user).chat_suggestions is None


def test_helper_preserves_saved_order(user):
    saved = ["Third", "First", "Second"]
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=saved
    )
    assert list(get_user_preferences(user).chat_suggestions) == saved


def test_helper_preserves_saved_empty_list(user):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=[]
    )
    assert list(get_user_preferences(user).chat_suggestions) == []


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("not-a-list", id="string"),
        pytest.param({"prompt": "x"}, id="object"),
        pytest.param(["valid", 7], id="non-string-entry"),
    ],
)
def test_helper_malformed_suggestions_fall_back_without_writing(
    user, malformed
):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=malformed
    )
    dto = get_user_preferences(user)
    assert list(dto.chat_suggestions) == DEFAULT_CHAT_SUGGESTIONS
    assert UserPreferences.objects.get(user=user).chat_suggestions == malformed


def test_helper_suggestions_are_tuple_copy_not_jsonfield_alias(user):
    saved = ["Original"]
    row = UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=saved
    )
    dto = get_user_preferences(user)
    assert isinstance(dto.chat_suggestions, tuple)
    row.chat_suggestions.append("Mutated later")
    assert dto.chat_suggestions == ("Original",)


@pytest.mark.parametrize(
    "saved",
    [
        pytest.param([f"Prompt {i}" for i in range(9)], id="over-count"),
        pytest.param(["x" * 121], id="over-length"),
    ],
)
def test_helper_returns_structurally_valid_over_cap_values_without_writing(
    user, saved
):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=saved
    )
    dto = get_user_preferences(user)
    assert list(dto.chat_suggestions) == saved
    assert UserPreferences.objects.get(user=user).chat_suggestions == saved


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        pytest.param(["", "x"], ["x"], id="drop-empty"),
        pytest.param(["   "], [], id="whitespace-only-is-empty-list"),
    ],
)
def test_helper_trims_and_drops_empty_entries_without_writing(
    user, saved, expected
):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=saved
    )
    dto = get_user_preferences(user)
    assert list(dto.chat_suggestions) == expected
    assert UserPreferences.objects.get(user=user).chat_suggestions == saved


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
    assert resp.json() == {
        "theme": "classic",
        "chat_suggestions": DEFAULT_CHAT_SUGGESTIONS,
        "focus_indicator_opacity": 0.70,
    }
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_get_returns_saved_theme(auth_client, user):
    UserPreferences.objects.create(user=user, theme="strategic")
    resp = auth_client.get(reverse("user_preferences"))
    assert resp.status_code == 200
    assert resp.json() == {
        "theme": "strategic",
        "chat_suggestions": DEFAULT_CHAT_SUGGESTIONS,
        "focus_indicator_opacity": 0.70,
    }
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_get_returns_saved_ordered_suggestions(auth_client, user):
    saved = ["Second", "First"]
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=saved
    )
    resp = auth_client.get(reverse("user_preferences"))
    assert resp.status_code == 200
    assert resp.json() == {
        "theme": "classic",
        "chat_suggestions": saved,
        "focus_indicator_opacity": 0.70,
    }


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
    assert resp.json() == {
        "theme": "strategic",
        "chat_suggestions": DEFAULT_CHAT_SUGGESTIONS,
        "focus_indicator_opacity": 0.70,
    }
    assert resp.headers["Cache-Control"] == "private, no-store"
    assert UserPreferences.objects.get(user=user).theme == "strategic"


def test_patch_sets_dark_4a_theme(auth_client, user):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "dark_4a"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "theme": "dark_4a",
        "chat_suggestions": DEFAULT_CHAT_SUGGESTIONS,
        "focus_indicator_opacity": 0.70,
    }
    assert UserPreferences.objects.get(user=user).theme == "dark_4a"


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
    assert resp.json() == {
        "theme": "classic",
        "chat_suggestions": DEFAULT_CHAT_SUGGESTIONS,
        "focus_indicator_opacity": 0.70,
    }


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


def test_patch_chat_suggestions_round_trip_trims_and_preserves_order(
    auth_client, user
):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps(
            {"chat_suggestions": ["  Second  ", "First", "  Third"]}
        ),
        content_type="application/json",
    )
    assert resp.status_code == 200
    expected = ["Second", "First", "Third"]
    assert resp.json() == {
        "theme": "classic",
        "chat_suggestions": expected,
        "focus_indicator_opacity": 0.70,
    }
    assert UserPreferences.objects.get(user=user).chat_suggestions == expected
    assert auth_client.get(reverse("user_preferences")).json()[
        "chat_suggestions"
    ] == expected


def test_patch_empty_suggestions_is_valid_and_stays_empty(auth_client, user):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"chat_suggestions": []}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["chat_suggestions"] == []
    assert UserPreferences.objects.get(user=user).chat_suggestions == []
    assert auth_client.get(reverse("user_preferences")).json()[
        "chat_suggestions"
    ] == []


def test_patch_accepts_120_code_point_emoji_boundary(auth_client, user):
    # The cap is Python str length (Unicode code points), so exactly 120
    # astral emoji is accepted even though it is 240 UTF-16 code units — the
    # backend must not measure UTF-16 units. Pins the documented boundary
    # opposite the "x" * 121 rejection case.
    emoji = "😀" * 120
    assert len(emoji) == 120
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"chat_suggestions": [emoji]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["chat_suggestions"] == [emoji]
    assert UserPreferences.objects.get(user=user).chat_suggestions == [emoji]


def test_patch_combined_theme_and_suggestions(auth_client, user):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps(
            {"theme": "dark_4a", "chat_suggestions": ["  Focus now  "]}
        ),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "theme": "dark_4a",
        "chat_suggestions": ["Focus now"],
        "focus_indicator_opacity": 0.70,
    }


def test_theme_only_patch_preserves_saved_suggestions(auth_client, user):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=["Keep me"]
    )
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "strategic"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["chat_suggestions"] == ["Keep me"]
    assert UserPreferences.objects.get(user=user).chat_suggestions == ["Keep me"]


def test_theme_only_patch_with_null_suggestions_returns_defaults(
    auth_client, user
):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=None
    )
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "strategic"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["chat_suggestions"] == DEFAULT_CHAT_SUGGESTIONS
    assert resp.headers["Cache-Control"] == "private, no-store"
    assert UserPreferences.objects.get(user=user).chat_suggestions is None


def test_suggestions_only_patch_preserves_theme(auth_client, user):
    UserPreferences.objects.create(
        user=user, theme="strategic", chat_suggestions=None
    )
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"chat_suggestions": ["Focus"]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["theme"] == "strategic"
    assert UserPreferences.objects.get(user=user).theme == "strategic"


def test_restore_defaults_is_idempotent_replace_not_append(auth_client, user):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=["Custom"]
    )
    for _ in range(2):
        resp = auth_client.patch(
            reverse("user_preferences"),
            data=json.dumps({"chat_suggestions": DEFAULT_CHAT_SUGGESTIONS}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["chat_suggestions"] == DEFAULT_CHAT_SUGGESTIONS
    assert (
        UserPreferences.objects.get(user=user).chat_suggestions
        == DEFAULT_CHAT_SUGGESTIONS
    )


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


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("bare string", id="bare-string"),
        pytest.param(None, id="null"),
        pytest.param({"prompt": "nested"}, id="object"),
        pytest.param(42, id="integer"),
    ],
)
def test_patch_non_array_suggestions_returns_400(auth_client, value):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"chat_suggestions": value}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "chat_suggestions" in resp.json()["errors"]
    assert resp.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(
    "suggestions",
    [
        pytest.param(["valid", 42], id="non-string"),
        pytest.param([["nested"]], id="nested-list"),
        pytest.param([{"prompt": "nested"}], id="nested-object"),
        pytest.param(["   "], id="whitespace-only"),
        pytest.param(["x" * 121], id="over-length"),
        pytest.param([str(i) for i in range(9)], id="over-count"),
    ],
)
def test_patch_invalid_suggestion_entries_return_400(
    auth_client, suggestions
):
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps({"chat_suggestions": suggestions}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "chat_suggestions" in resp.json()["errors"]
    assert resp.headers["Cache-Control"] == "private, no-store"


def test_combined_invalid_payload_writes_neither_field(auth_client, user):
    UserPreferences.objects.create(
        user=user, theme="classic", chat_suggestions=["Original"]
    )
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=json.dumps(
            {"theme": "strategic", "chat_suggestions": ["   "]}
        ),
        content_type="application/json",
    )
    assert resp.status_code == 400
    row = UserPreferences.objects.get(user=user)
    assert row.theme == "classic"
    assert row.chat_suggestions == ["Original"]


def test_patch_oversized_body_returns_413_with_cache_control(auth_client):
    """The 413 path goes through `reject_oversized_body` and is rewrapped
    via `_prefs_response` so the Cache-Control invariant holds even when
    the body is rejected without parsing. Pins that re-wrap."""
    # MAX_REQUEST_BODY_BYTES = 100_000 in schedules.http; build a payload
    # ~100 KB+ via a padding key (silently ignored by the field extractor,
    # but counts toward the body-size check).
    huge_body = json.dumps({"theme": "classic", "padding": "x" * 100_001})
    resp = auth_client.patch(
        reverse("user_preferences"),
        data=huge_body,
        content_type="application/json",
    )
    assert resp.status_code == 413
    assert resp.json() == {"errors": {"body": "Request body too large."}}
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
    assert resp.json() == {
        "theme": "strategic",
        "chat_suggestions": DEFAULT_CHAT_SUGGESTIONS,
        "focus_indicator_opacity": 0.70,
    }


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
    assert resp.json() == {
        "theme": "strategic",
        "chat_suggestions": DEFAULT_CHAT_SUGGESTIONS,
        "focus_indicator_opacity": 0.70,
    }

    client2 = Client()
    client2.login(username="bob", password="pw")
    resp = client2.get(reverse("user_preferences"))
    assert resp.json() == {
        "theme": "light_premium",
        "chat_suggestions": DEFAULT_CHAT_SUGGESTIONS,
        "focus_indicator_opacity": 0.70,
    }


def test_suggestions_are_isolated_per_user(db):
    alice = User.objects.create_user(username="suggest-alice", password="pw")
    bob = User.objects.create_user(username="suggest-bob", password="pw")
    UserPreferences.objects.create(
        user=alice, theme="classic", chat_suggestions=["Alice only"]
    )
    UserPreferences.objects.create(
        user=bob, theme="classic", chat_suggestions=["Bob only"]
    )
    client = Client()
    client.login(username="suggest-alice", password="pw")
    resp = client.patch(
        reverse("user_preferences"),
        data=json.dumps({"chat_suggestions": ["Alice updated"]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert UserPreferences.objects.get(user=alice).chat_suggestions == [
        "Alice updated"
    ]
    assert UserPreferences.objects.get(user=bob).chat_suggestions == ["Bob only"]


def test_patch_does_not_leak_across_users(db):
    """Write isolation: a PATCH from one user must NOT modify another
    user's preferences row. The endpoint is scoped by request.user and
    there's no path param exposing another user's id, but a regression
    here would silently let any authenticated user reshape every other
    user's theme — pin it explicitly.
    """
    alice = User.objects.create_user(username="alice2", password="pw")
    bob = User.objects.create_user(username="bob2", password="pw")
    UserPreferences.objects.create(user=alice, theme="classic")
    UserPreferences.objects.create(user=bob, theme="strategic")

    client = Client()
    client.login(username="alice2", password="pw")
    resp = client.patch(
        reverse("user_preferences"),
        data=json.dumps({"theme": "light_premium"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    # Alice's row updated.
    assert UserPreferences.objects.get(user=alice).theme == "light_premium"
    # Bob's row UNTOUCHED.
    assert UserPreferences.objects.get(user=bob).theme == "strategic"


# ---------------------------------------------------------------------------
# Inertia page-prop contract
# ---------------------------------------------------------------------------


def test_schedule_view_includes_ui_preferences_prop(auth_client, user):
    UserPreferences.objects.create(
        user=user,
        theme="strategic",
        chat_suggestions=["Schedule prompt"],
    )
    today = timezone.localdate().isoformat()
    resp = auth_client.get(
        f"/schedule/{today}/", HTTP_X_INERTIA="true"
    )
    assert resp.status_code == 200
    page = resp.json()
    assert page["props"]["ui_preferences"] == {
        "theme": "strategic",
        "chat_suggestions": ["Schedule prompt"],
        "focus_indicator_opacity": 0.70,
    }


def test_settings_view_includes_ui_preferences_prop(auth_client, user):
    UserPreferences.objects.create(
        user=user,
        theme="light_premium",
        chat_suggestions=["Settings prompt"],
    )
    resp = auth_client.get(reverse("settings"), HTTP_X_INERTIA="true")
    assert resp.status_code == 200
    page = resp.json()
    assert page["props"]["ui_preferences"] == {
        "theme": "light_premium",
        "chat_suggestions": ["Settings prompt"],
        "focus_indicator_opacity": 0.70,
    }


def test_settings_view_includes_schedule_time_zone(auth_client, user):
    UserScheduleSettings.objects.create(user=user, time_zone="Asia/Almaty")
    response = auth_client.get(reverse("settings"), HTTP_X_INERTIA="true")
    assert response.json()["props"]["schedule_window"]["time_zone"] == "Asia/Almaty"


def test_analytics_view_includes_ui_preferences_prop(auth_client, user):
    UserPreferences.objects.create(
        user=user,
        theme="strategic",
        chat_suggestions=["Analytics prompt"],
    )
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
    assert page["props"]["ui_preferences"] == {
        "theme": "strategic",
        "chat_suggestions": ["Analytics prompt"],
        "focus_indicator_opacity": 0.70,
    }


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
