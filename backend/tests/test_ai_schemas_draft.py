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


def test_update_shape_accepts_nested_metadata_and_rejects_empty_or_bad_direction():
    assert "update" in ALLOWED_ACTION_TYPES
    assert (
        validate_action_shape({"type": "update", "task_id": 5, "changes": {"title": "X"}}, ALLOWED)
        == []
    )
    assert validate_action_shape({"type": "update", "task_id": 5}, ALLOWED)
    assert validate_action_shape(
        {"type": "update", "task_id": 5, "changes": {"title": "X"}, "direction": "sideways"},
        ALLOWED,
    )


def test_update_without_task_id_rejected():
    # ``task_id`` is required on an update — without it the schema must reject
    # (otherwise the planner's ``action["task_id"]`` raises KeyError -> 500 on a
    # malformed model turn instead of a clean parse rejection).
    errors = validate_action_shape(
        {"type": "update", "changes": {"title": "X"}},
        ALLOWED,
    )
    assert any("requires 'task_id'" in e for e in errors)


def test_bad_direction_value_rejected():
    errors = validate_action_shape(
        {
            "type": "update",
            "task_id": 5,
            "changes": {"start_time": "09:00"},
            "placement_direction": "sideways",
        },
        ALLOWED,
    )
    assert any("placement_direction must be one of" in e for e in errors)


def test_update_empty_title_rejected():
    # The general title check applies to update too (not only add): an empty /
    # whitespace title is caught at the schema layer, never reaching full_clean.
    errors = validate_action_shape(
        {"type": "update", "task_id": 5, "changes": {"title": "   "}},
        ALLOWED,
    )
    assert any("title cannot be empty" in e for e in errors)


def test_update_invalid_category_rejected():
    # An invalid category on an update is a malformed field — caught at the
    # schema layer (whole-turn parse error), not soft-skipped, and never
    # reaching full_clean.
    errors = validate_action_shape(
        {"type": "update", "task_id": 5, "changes": {"category": "not_a_category"}},
        ALLOWED,
    )
    assert any("category must be one of" in e for e in errors)


def test_non_string_direction_rejected_without_crashing():
    # A non-string direction (list/dict) must surface as a clean validation
    # error, not a TypeError from ``in`` on a set of strings (which would
    # escape the AIParseError path and 500).
    for bad in ([], {}, 3, None):
        errors = validate_action_shape(
            {
                "type": "update",
                "task_id": 5,
                "changes": {"start_time": "09:00"},
                "placement_direction": bad,
            },
            ALLOWED,
        )
        assert any("placement_direction must be one of" in e for e in errors)


def test_direction_without_time_rejected():
    # A metadata-only update carrying a valid direction but no time field is a
    # meaningless patch — direction requires an accompanying start/end time.
    errors = validate_action_shape(
        {"type": "update", "task_id": 5, "changes": {"title": "X"}, "placement_direction": "later"},
        ALLOWED,
    )
    assert any("placement_direction requires an accompanying" in e for e in errors)


def test_valid_update_with_time_and_direction_accepted():
    assert (
        validate_action_shape(
            {
                "type": "update",
                "task_id": 5,
                "changes": {"start_time": "09:00", "end_time": "10:00"},
                "placement_direction": "later",
            },
            ALLOWED,
        )
        == []
    )


def test_placement_direction_rejected_on_non_update_types():
    # ``direction`` is placement intent for an update time change only; the
    # planner never reads it on move/resize/add, so it must be rejected there.
    for kind, extra in (
        ("move", {"task_id": 5, "start_time": "09:00"}),
        ("resize", {"task_id": 5, "end_time": "10:00"}),
        ("add", {"title": "X", "start_time": "09:00", "end_time": "10:00", "category": "work"}),
        ("remove", {"task_id": 5}),
    ):
        errors = validate_action_shape(
            {"type": kind, "placement_direction": "later", **extra}, ALLOWED
        )
        assert any("unknown key" in e for e in errors)


def test_update_rejects_flat_and_unknown_keys_at_both_levels():
    for key, value in (
        ("title", "X"),
        ("category", "work"),
        ("start_time", "09:00"),
        ("end_time", "10:00"),
        ("direction", "later"),
        ("is_completed", True),
        ("sort_order", 1),
    ):
        errors = validate_action_shape(
            {"type": "update", "task_id": 5, "changes": {"title": "X"}, key: value}, ALLOWED
        )
        assert any("unknown top-level" in e for e in errors), key
    for key, value in (("is_completed", True), ("sort_order", 1), ("bogus", "x")):
        errors = validate_action_shape(
            {"type": "update", "task_id": 5, "changes": {"title": "X", key: value}}, ALLOWED
        )
        assert any("inside changes" in e for e in errors), key


def test_update_changes_is_required_nonempty_object_and_validates_nested_times():
    class DictSubclass(dict):
        pass

    for changes in (None, [], {}, "title", DictSubclass(title="X")):
        errors = validate_action_shape(
            {"type": "update", "task_id": 5, "changes": changes}, ALLOWED
        )
        assert errors
    for field, value in (("start_time", "9:00"), ("end_time", "09:03")):
        errors = validate_action_shape(
            {"type": "update", "task_id": 5, "changes": {field: value}}, ALLOWED
        )
        assert any(field in e for e in errors)


def test_non_update_actions_reject_unknown_keys():
    valid = {
        "move": {"task_id": 5, "start_time": "09:00"},
        "resize": {"task_id": 5, "end_time": "10:00"},
        "remove": {"task_id": 5},
    }
    for kind, action in valid.items():
        assert validate_action_shape({"type": kind, **action}, ALLOWED) == []
        errors = validate_action_shape({"type": kind, **action, "changes": {}}, ALLOWED)
        assert any("unknown key" in e for e in errors)


# ---------------------------------------------------------------------------
# Feature 0067: chat untimed-add schema (allow_untimed_add=True).
# ---------------------------------------------------------------------------


def _untimed_add(**extra):
    action = {"type": "add", "title": "LeverX", "category": "work"}
    action.update(extra)
    return action


class TestChatUntimedAdd:
    def test_untimed_add_passes_with_flag(self):
        assert validate_action_shape(_untimed_add(), ALLOWED, allow_untimed_add=True) == []

    def test_both_times_still_pass_with_flag(self):
        action = _untimed_add(start_time="09:00", end_time="09:30")
        assert validate_action_shape(action, ALLOWED, allow_untimed_add=True) == []

    def test_untimed_add_rejected_without_flag(self):
        # Draft path (default False) still requires both times.
        errors = validate_action_shape(_untimed_add(), ALLOWED)
        assert any("start_time" in e for e in errors)
        assert any("end_time" in e for e in errors)

    def test_start_only_produces_paired_time_error(self):
        errors = validate_action_shape(
            _untimed_add(start_time="09:00"), ALLOWED, allow_untimed_add=True
        )
        assert any("both" in e and "neither" in e for e in errors)

    def test_end_only_produces_paired_time_error(self):
        errors = validate_action_shape(
            _untimed_add(end_time="09:30"), ALLOWED, allow_untimed_add=True
        )
        assert any("both" in e and "neither" in e for e in errors)

    def test_duration_minutes_accepts_positive_multiple_of_five(self):
        for d in (5, 25, 30, 120):
            assert (
                validate_action_shape(
                    _untimed_add(duration_minutes=d), ALLOWED, allow_untimed_add=True
                )
                == []
            )

    def test_duration_minutes_rejects_bad_values(self):
        for bad in (0, -5, 7, True, False, "25", 25.0, None):
            errors = validate_action_shape(
                _untimed_add(duration_minutes=bad), ALLOWED, allow_untimed_add=True
            )
            assert errors, f"expected rejection for duration_minutes={bad!r}"

    def test_duration_minutes_bool_rejected_by_is_plain_int_guard(self):
        # bool is an int subclass, so True/False must be caught by the
        # is_plain_int guard *before* the numeric (<=0 / %5) checks could
        # short-circuit. Assert the integer-type error specifically.
        errors = validate_action_shape(
            _untimed_add(duration_minutes=True), ALLOWED, allow_untimed_add=True
        )
        assert any("must be an integer" in e for e in errors), errors

    def test_duration_minutes_rejected_on_explicit_add(self):
        errors = validate_action_shape(
            _untimed_add(start_time="09:00", end_time="09:30", duration_minutes=25),
            ALLOWED,
            allow_untimed_add=True,
        )
        assert any("duration_minutes" in e for e in errors)

    def test_duration_minutes_rejected_on_move_resize_update_remove(self):
        for kind, extra in (
            ("move", {"task_id": 5, "start_time": "09:00"}),
            ("resize", {"task_id": 5, "end_time": "10:00"}),
            ("update", {"task_id": 5, "changes": {"title": "X"}}),
            ("remove", {"task_id": 5}),
        ):
            action = {"type": kind, "duration_minutes": 25, **extra}
            errors = validate_action_shape(action, ALLOWED, allow_untimed_add=True)
            assert any("duration_minutes" in e for e in errors), kind

    def test_unknown_key_on_add_rejected(self):
        # A misspelled ``start``/``end`` key must NOT masquerade as an untimed add.
        for bad_key in ("start", "end", "when", "time"):
            errors = validate_action_shape(
                {"type": "add", "title": "X", "category": "work", bad_key: "09:00"},
                ALLOWED,
                allow_untimed_add=True,
            )
            assert errors, f"expected rejection for unknown add key {bad_key!r}"


# ---------------------------------------------------------------------------
# Feature 0068: chat duration-based resize schema.
# ---------------------------------------------------------------------------


class TestChatDurationResize:
    @staticmethod
    def _resize(**extra):
        action = {"type": "resize", "task_id": 5}
        action.update(extra)
        return action

    def test_resize_accepts_absolute_duration_minutes(self):
        assert validate_action_shape(self._resize(duration_minutes=20), ALLOWED) == []

    def test_resize_accepts_signed_duration_delta_minutes(self):
        for delta in (5, 30, -5, -15):
            assert validate_action_shape(self._resize(duration_delta_minutes=delta), ALLOWED) == []

    def test_resize_requires_a_boundary_or_duration_operand(self):
        errors = validate_action_shape(self._resize(), ALLOWED)
        assert any("requires exactly one" in error for error in errors)

    def test_resize_duration_modes_are_mutually_exclusive(self):
        invalid = (
            self._resize(duration_minutes=20, duration_delta_minutes=5),
            self._resize(duration_minutes=20, end_time="10:00"),
            self._resize(duration_delta_minutes=5, start_time="09:00"),
        )
        for action in invalid:
            errors = validate_action_shape(action, ALLOWED)
            assert any("exactly one" in error for error in errors), action

    def test_resize_duration_minutes_rejects_invalid_values(self):
        for value in (0, -5, "20", 20.0, None, 7):
            errors = validate_action_shape(self._resize(duration_minutes=value), ALLOWED)
            assert errors, value

    def test_resize_duration_minutes_bool_uses_plain_int_guard(self):
        for value in (True, False):
            errors = validate_action_shape(self._resize(duration_minutes=value), ALLOWED)
            assert any("duration_minutes must be an integer" in error for error in errors)

    def test_resize_duration_delta_rejects_invalid_values(self):
        for value in (0, "5", 5.0, None, 7, -7):
            errors = validate_action_shape(self._resize(duration_delta_minutes=value), ALLOWED)
            assert errors, value

    def test_resize_duration_delta_bool_uses_plain_int_guard(self):
        for value in (True, False):
            errors = validate_action_shape(self._resize(duration_delta_minutes=value), ALLOWED)
            assert any("duration_delta_minutes must be an integer" in error for error in errors)

    def test_duration_delta_minutes_is_rejected_outside_resize(self):
        for action in (
            _untimed_add(duration_delta_minutes=5),
            {"type": "move", "task_id": 5, "start_time": "09:00", "duration_delta_minutes": 5},
            {
                "type": "update",
                "task_id": 5,
                "changes": {"title": "X"},
                "duration_delta_minutes": 5,
            },
            {"type": "remove", "task_id": 5, "duration_delta_minutes": 5},
        ):
            errors = validate_action_shape(action, ALLOWED, allow_untimed_add=True)
            assert any("duration_delta_minutes" in error for error in errors), action
