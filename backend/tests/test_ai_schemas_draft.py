"""Unit tests for ``validate_draft_response``."""

from ai.schemas import ALLOWED_ACTION_TYPES, validate_action_shape, validate_draft_response

ALLOWED = {"work", "personal", "health", "other"}


def _good_action():
    return {
        "type": "add",
        "title": "Standup",
        "start_time": "09:00",
        "end_time": "09:15",
        "category": "work",
    }


def test_valid_payload_passes():
    parsed = {"actions": [_good_action()], "explanation": "ok"}
    assert validate_draft_response(parsed, ALLOWED) == []


def test_rejects_move():
    parsed = {
        "actions": [
            {"type": "move", "task_id": 1, "start_time": "09:00"},
        ],
        "explanation": "x",
    }
    errors = validate_draft_response(parsed, ALLOWED)
    assert any("only accept 'add' actions" in e for e in errors)


def test_rejects_remove_and_resize():
    for kind in ("remove", "resize"):
        parsed = {
            "actions": [{"type": kind, "task_id": 1}],
            "explanation": "x",
        }
        errors = validate_draft_response(parsed, ALLOWED)
        assert any("only accept 'add'" in e for e in errors)


def test_envelope_check_runs_first():
    parsed = "not a dict"
    errors = validate_draft_response(parsed, ALLOWED)
    assert errors == ["response must be a JSON object"]


def test_invalid_add_action_per_action_check_fires():
    parsed = {
        "actions": [
            {
                "type": "add",
                # missing title
                "start_time": "09:00",
                "end_time": "09:15",
                "category": "work",
            }
        ],
        "explanation": "x",
    }
    errors = validate_draft_response(parsed, ALLOWED)
    assert any("title" in e for e in errors)


def test_update_shape_accepts_metadata_and_rejects_empty_or_bad_direction():
    assert "update" in ALLOWED_ACTION_TYPES
    assert validate_action_shape({"type": "update", "task_id": 5, "title": "X"}, ALLOWED) == []
    assert validate_action_shape({"type": "update", "task_id": 5}, ALLOWED)
    assert validate_action_shape(
        {"type": "update", "task_id": 5, "title": "X", "direction": "sideways"}, ALLOWED
    )


def test_bad_direction_value_rejected():
    errors = validate_action_shape(
        {"type": "update", "task_id": 5, "start_time": "09:00", "direction": "sideways"},
        ALLOWED,
    )
    assert any("direction must be one of" in e for e in errors)


def test_update_empty_title_rejected():
    # The general title check applies to update too (not only add): an empty /
    # whitespace title is caught at the schema layer, never reaching full_clean.
    errors = validate_action_shape(
        {"type": "update", "task_id": 5, "title": "   "},
        ALLOWED,
    )
    assert any("title cannot be empty" in e for e in errors)


def test_update_invalid_category_rejected():
    # An invalid category on an update is a malformed field — caught at the
    # schema layer (whole-turn parse error), not soft-skipped, and never
    # reaching full_clean.
    errors = validate_action_shape(
        {"type": "update", "task_id": 5, "category": "not_a_category"},
        ALLOWED,
    )
    assert any("category must be one of" in e for e in errors)


def test_non_string_direction_rejected_without_crashing():
    # A non-string direction (list/dict) must surface as a clean validation
    # error, not a TypeError from ``in`` on a set of strings (which would
    # escape the AIParseError path and 500).
    for bad in ([], {}, 3, None):
        errors = validate_action_shape(
            {"type": "update", "task_id": 5, "start_time": "09:00", "direction": bad},
            ALLOWED,
        )
        assert any("direction must be one of" in e for e in errors)


def test_direction_without_time_rejected():
    # A metadata-only update carrying a valid direction but no time field is a
    # meaningless patch — direction requires an accompanying start/end time.
    errors = validate_action_shape(
        {"type": "update", "task_id": 5, "title": "X", "direction": "later"},
        ALLOWED,
    )
    assert any("direction requires an accompanying" in e for e in errors)


def test_valid_update_with_time_and_direction_accepted():
    assert (
        validate_action_shape(
            {
                "type": "update",
                "task_id": 5,
                "start_time": "09:00",
                "end_time": "10:00",
                "direction": "later",
            },
            ALLOWED,
        )
        == []
    )


def test_direction_rejected_on_non_update_types():
    # ``direction`` is placement intent for an update time change only; the
    # planner never reads it on move/resize/add, so it must be rejected there.
    for kind, extra in (
        ("move", {"task_id": 5, "start_time": "09:00"}),
        ("resize", {"task_id": 5, "end_time": "10:00"}),
        ("add", {"title": "X", "start_time": "09:00", "end_time": "10:00",
                 "category": "work"}),
    ):
        errors = validate_action_shape(
            {"type": kind, "direction": "later", **extra}, ALLOWED
        )
        assert any("'direction' is not valid on a" in e for e in errors)
