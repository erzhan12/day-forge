"""Unit tests for ``ai.category_resolution`` (feature 0084, issue #209).

Pure-function tests — no DB, no network. ``resolve_category`` and
``normalize_action_categories`` are exercised directly with hand-built
category catalogs, matching the plan's "Tests" section exactly.
"""

import pytest
from ai.category_resolution import (
    UnresolvedCategory,
    _loggable_task_id,
    normalize_action_categories,
    resolve_category,
)

_DEFAULT = (
    ("work", "Work"),
    ("personal", "Personal"),
    ("health", "Health"),
    ("other", "Other"),
)


class TestResolveCategory:
    def test_exact_slug_matches(self):
        assert resolve_category("work", _DEFAULT) == "work"

    def test_label_case_variants_match(self):
        assert resolve_category("Work", _DEFAULT) == "work"
        assert resolve_category("WORK", _DEFAULT) == "work"
        assert resolve_category(" work ", _DEFAULT) == "work"

    def test_custom_russian_label_matches(self):
        categories = (("work", "Работа"), ("other", "Другое"))
        assert resolve_category("работа", categories) == "work"

    def test_inflected_form_does_not_match(self):
        # "рабочая" (adjectival form) is NOT the label "Работа" — no fuzzy
        # matching, stemming or translation; the prompt's job (§3 of the plan).
        categories = (("work", "Работа"), ("other", "Другое"))
        assert resolve_category("рабочая", categories) is None

    def test_non_str_value_returns_none(self):
        assert resolve_category(123, _DEFAULT) is None
        assert resolve_category(None, _DEFAULT) is None

    def test_empty_string_returns_none(self):
        assert resolve_category("", _DEFAULT) is None

    def test_whitespace_only_returns_none(self):
        assert resolve_category("   ", _DEFAULT) is None

    def test_value_excluded_from_repr(self):
        record = UnresolvedCategory(original_index=0, task_id=5, value="рабочая", dropped=True)
        assert "рабочая" not in repr(record)

    def test_case_fold_collision_first_catalog_entry_wins(self):
        # SQLite's LOWER folds ASCII only; Python casefold is
        # locale-independent, so two Cyrillic labels differing only in case
        # CAN coexist in the DB. Catalog order breaks the tie.
        categories = (("a", "Работа"), ("b", "работа"))
        assert resolve_category("работа", categories) == "a"
        assert resolve_category("РАБОТА", categories) == "a"


class TestNormalizeAdd:
    def test_unresolved_falls_back_to_sink(self):
        action = {"type": "add", "title": "X", "category": "рабочая"}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids=set())
        assert result.actions == [{"type": "add", "title": "X", "category": "other"}]
        assert result.unresolved == ()

    def test_absent_category_falls_back_to_sink(self):
        action = {"type": "add", "title": "X"}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids=set())
        assert result.actions == [{"type": "add", "title": "X", "category": "other"}]
        assert result.unresolved == ()

    def test_null_category_falls_back_to_sink(self):
        action = {"type": "add", "title": "X", "category": None}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids=set())
        assert result.actions == [{"type": "add", "title": "X", "category": "other"}]
        assert result.unresolved == ()

    def test_non_str_category_left_untouched(self):
        action = {"type": "add", "title": "X", "category": 123}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids=set())
        assert result.actions == [action]
        assert result.unresolved == ()

    def test_resolved_label_rewritten_to_slug(self):
        action = {"type": "add", "title": "X", "category": "Health"}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids=set())
        assert result.actions == [{"type": "add", "title": "X", "category": "health"}]
        assert result.unresolved == ()

    def test_empty_catalog_falls_back_to_sink(self):
        action = {"type": "add", "title": "X", "category": "work"}
        result = normalize_action_categories([action], [], "other", known_task_ids=set())
        assert result.actions[0]["category"] == "other"


class TestNormalizeUpdate:
    def test_resolved_rewritten_to_slug(self):
        action = {
            "type": "update",
            "task_id": 5,
            "changes": {"start_time": "14:00", "end_time": "15:00", "category": "Work"},
        }
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == [
            {
                "type": "update",
                "task_id": 5,
                "changes": {"start_time": "14:00", "end_time": "15:00", "category": "work"},
            }
        ]
        assert result.unresolved == ()

    def test_unresolved_with_other_changes_drops_category_keeps_action(self):
        action = {
            "type": "update",
            "task_id": 5,
            "changes": {"start_time": "14:00", "end_time": "15:00", "category": "рабочая"},
        }
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == [
            {
                "type": "update",
                "task_id": 5,
                "changes": {"start_time": "14:00", "end_time": "15:00"},
            }
        ]
        assert result.unresolved == (
            UnresolvedCategory(original_index=0, task_id=5, value="рабочая", dropped=False),
        )

    def test_unresolved_category_only_drops_whole_action(self):
        action = {"type": "update", "task_id": 5, "changes": {"category": "рабочая"}}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == []
        assert result.unresolved == (
            UnresolvedCategory(original_index=0, task_id=5, value="рабочая", dropped=True),
        )

    def test_unresolved_category_only_pins_correct_original_index(self):
        actions = [
            {"type": "add", "title": "A", "category": "work"},
            {"type": "update", "task_id": 5, "changes": {"category": "рабочая"}},
        ]
        result = normalize_action_categories(actions, _DEFAULT, "other", known_task_ids={5})
        assert len(result.actions) == 1
        assert result.actions[0]["type"] == "add"
        assert result.unresolved == (
            UnresolvedCategory(original_index=1, task_id=5, value="рабочая", dropped=True),
        )

    def test_guard_kept_untouched_when_task_id_not_an_int(self):
        action = {"type": "update", "task_id": "abc", "changes": {"category": "рабочая"}}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == [action]
        assert result.unresolved == ()

    def test_guard_kept_untouched_when_unknown_top_level_key(self):
        action = {
            "type": "update",
            "task_id": 5,
            "changes": {"category": "рабочая"},
            "bogus": True,
        }
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == [action]
        assert result.unresolved == ()

    def test_guard_kept_untouched_when_task_id_unknown(self):
        action = {"type": "update", "task_id": 999, "changes": {"category": "рабочая"}}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == [action]
        assert result.unresolved == ()

    def test_non_dict_changes_left_untouched(self):
        action = {"type": "update", "task_id": 5, "changes": "not-a-dict"}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == [action]
        assert result.unresolved == ()

    def test_empty_string_category_only_update_dropped_and_recorded(self):
        action = {"type": "update", "task_id": 5, "changes": {"category": ""}}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == []
        assert result.unresolved == (
            UnresolvedCategory(original_index=0, task_id=5, value="", dropped=True),
        )

    def test_non_str_category_left_untouched(self):
        action = {"type": "update", "task_id": 5, "changes": {"category": None}}
        result = normalize_action_categories([action], _DEFAULT, "other", known_task_ids={5})
        assert result.actions == [action]
        assert result.unresolved == ()


class TestNormalizePassThroughAndPurity:
    def test_move_remove_resize_pass_through_unchanged(self):
        actions = [
            {"type": "move", "task_id": 1, "start_time": "09:00"},
            {"type": "remove", "task_id": 2},
            {"type": "resize", "task_id": 3, "duration_minutes": 20},
        ]
        result = normalize_action_categories(actions, _DEFAULT, "other", known_task_ids={1, 2, 3})
        assert result.actions == actions
        assert result.unresolved == ()

    def test_non_dict_entries_pass_through_unchanged(self):
        actions = ["not-a-dict", 42, None]
        result = normalize_action_categories(actions, _DEFAULT, "other", known_task_ids=set())
        assert result.actions == actions
        assert result.unresolved == ()

    def test_input_list_and_dicts_not_mutated(self):
        original_action = {
            "type": "update",
            "task_id": 5,
            "changes": {"start_time": "14:00", "category": "рабочая"},
        }
        original_changes = original_action["changes"]
        actions = [original_action]
        result = normalize_action_categories(actions, _DEFAULT, "other", known_task_ids={5})
        # The input list itself is untouched.
        assert actions == [original_action]
        assert original_action["changes"] is original_changes
        assert original_changes == {"start_time": "14:00", "category": "рабочая"}
        # The returned list is a different object.
        assert result.actions is not actions


class TestOriginalIndices:
    """``original_indices[i]`` names the model's own index for ``actions[i]``
    (feature 0084 follow-up, issue #209 error_detail numbering fix) — the
    two tuples stay aligned 1:1, including when an earlier dropped action
    shrinks both lists together."""

    def test_no_drops_indices_match_position(self):
        actions = [
            {"type": "add", "title": "A", "category": "work"},
            {"type": "move", "task_id": 1, "start_time": "09:00"},
        ]
        result = normalize_action_categories(actions, _DEFAULT, "other", known_task_ids={1})
        assert result.original_indices == (0, 1)

    def test_dropped_action_shifts_later_indices(self):
        actions = [
            {"type": "update", "task_id": 5, "changes": {"category": "рабочая"}},
            {"type": "add", "title": "A", "category": "work"},
        ]
        result = normalize_action_categories(actions, _DEFAULT, "other", known_task_ids={5})
        # action[0] was dropped (category-only, unresolved); the surviving
        # add is actions[0] but must still be reported as the model's [1].
        assert len(result.actions) == 1
        assert result.original_indices == (1,)


class TestLoggableTaskId:
    """Debug logs run before schema validation, so only plain ints are logged."""

    @pytest.mark.parametrize("value", ["drop table", 7.0, True, None, {"x": 1}])
    def test_non_int_is_redacted(self, value):
        assert _loggable_task_id(value) == "<invalid>"

    def test_plain_int_passes_through(self):
        assert _loggable_task_id(7) == 7
