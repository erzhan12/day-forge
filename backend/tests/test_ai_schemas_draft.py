"""Unit tests for ``validate_draft_response``."""
from ai.schemas import validate_draft_response

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
