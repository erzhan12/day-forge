"""Unit coverage for the Playwright harness's Django seed scripts."""

import datetime
import json

import pytest
from ai.models import AIInteraction
from analytics.models import DailyReview
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Template, UserPreferences
from todoist_sync.models import TodoistAccount

from scripts import (
    seed_analytics_reviewed,
    seed_cleanup,
    seed_prefs,
    seed_schedule,
    seed_template,
    seed_todoist,
)


def _setenv(monkeypatch, **values) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.mark.django_db
def test_schedule_seeder_is_idempotent_and_preserves_marker_contract(user, monkeypatch, capsys):
    specs = [
        {
            "date": "2027-01-15",
            "status": "active",
            "blocks": [
                {
                    "title": "Focus",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "category": "work",
                    "is_completed": True,
                    "sort_order": 4,
                }
            ],
        }
    ]
    _setenv(
        monkeypatch,
        SEED_MODE="schedules",
        SEED_USERNAME=user.username,
        SEED_SCHEDULES_JSON=json.dumps(specs),
        SEED_MARKER="seeded schedule {id}",
    )

    seed_schedule.main()
    schedule = Schedule.objects.get(user=user, date="2027-01-15")
    expected = f"seeded schedule {schedule.id}\n"
    assert capsys.readouterr().out == expected
    block = schedule.time_blocks.get()
    assert block.title == "Focus"
    assert block.is_completed is True
    assert block.sort_order == 4

    seed_schedule.main()
    assert capsys.readouterr().out == expected
    assert Schedule.objects.filter(user=user, date="2027-01-15").count() == 1
    assert TimeBlock.objects.filter(schedule=schedule).count() == 1

    _setenv(
        monkeypatch,
        SEED_MODE="ensure_exists",
        SEED_DATE="2027-01-15",
    )
    seed_schedule.main()
    assert capsys.readouterr().out == "CREATED False\n"
    assert TimeBlock.objects.filter(schedule=schedule).count() == 1


@pytest.mark.django_db
def test_schedule_history_suffix_and_snapshot_modes(user, monkeypatch, capsys):
    _setenv(
        monkeypatch,
        SEED_MODE="history_suffix",
        SEED_USERNAME=user.username,
        SEED_DATE="2027-04-09",
        SEED_HISTORY_WITH_REVIEW="2027-04-07",
        SEED_HISTORY_NO_REVIEW="2027-04-08",
    )
    seed_schedule.main()
    assert capsys.readouterr().out == (
        "seeded with-review=2027-04-07 no-review=2027-04-08 target=2027-04-09\n"
    )
    reviewed = Schedule.objects.get(user=user, date="2027-04-07")
    assert reviewed.daily_review.planned_count == 4
    assert reviewed.daily_review.completed_count == 3
    unreviewed = Schedule.objects.get(user=user, date="2027-04-08")
    assert not DailyReview.objects.filter(schedule=unreviewed).exists()
    assert not Schedule.objects.filter(user=user, date="2027-04-09").exists()

    _setenv(
        monkeypatch,
        SEED_MODE="snapshot",
        SEED_DATE="2027-04-07",
        SEED_SNAPSHOT="chat_titles",
    )
    seed_schedule.main()
    output = capsys.readouterr().out
    assert output.startswith("STATUS active\n")
    assert "BLOCK Standup 09:00:00 09:30:00\n" in output


@pytest.mark.django_db
def test_schedule_seeder_userless_and_rate_snapshot_contracts(user, monkeypatch, capsys):
    # localdate mode takes no user and echoes the Django-local today.
    _setenv(monkeypatch, SEED_MODE="localdate")
    seed_schedule.main()
    assert capsys.readouterr().out == f"{timezone.localdate().isoformat()}\n"

    # user_exists mode is the harness's pre-flight probe.
    _setenv(monkeypatch, SEED_MODE="user_exists", SEED_USERNAME=user.username)
    seed_schedule.main()
    assert capsys.readouterr().out == "EXISTS True\n"

    _setenv(monkeypatch, SEED_USERNAME="ghost-does-not-exist")
    seed_schedule.main()
    assert capsys.readouterr().out == "EXISTS False\n"

    # rate_before / rate_after snapshots read the ai_draft_rl counter + counts.
    Schedule.objects.create(user=user, date="2027-02-02", status="active")
    cache.set(f"ai_draft_rl:{user.id}", 3)
    try:
        _setenv(
            monkeypatch,
            SEED_MODE="snapshot",
            SEED_USERNAME=user.username,
            SEED_DATE="2027-02-02",
            SEED_SNAPSHOT="rate_before",
        )
        seed_schedule.main()
        assert capsys.readouterr().out == "RATE_BEFORE 3\nAI_BEFORE 0\n"

        monkeypatch.setenv("SEED_SNAPSHOT", "rate_after")
        seed_schedule.main()
        assert capsys.readouterr().out == ("RATE_AFTER 3\nAI_AFTER 0\nBLOCKS 0\nSTATUS active\n")
    finally:
        cache.delete(f"ai_draft_rl:{user.id}")


@pytest.mark.django_db
def test_schedule_seeder_audit_snapshot_contracts(user, monkeypatch, capsys):
    schedule = Schedule.objects.create(user=user, date="2027-03-03", status="active")
    TimeBlock.objects.create(
        schedule=schedule,
        title="Focus",
        start_time="09:00",
        end_time="10:00",
        category="work",
    )
    AIInteraction.objects.create(
        schedule=schedule,
        kind="command",
        success=True,
        actions_json=[{"type": "move"}, {"type": "add"}],
        user_command="move the block",
        ai_response="{}",
    )

    _setenv(
        monkeypatch,
        SEED_MODE="snapshot",
        SEED_USERNAME=user.username,
        SEED_DATE="2027-03-03",
        SEED_SNAPSHOT="categories",
    )
    seed_schedule.main()
    assert capsys.readouterr().out == (
        "STATUS active\n"
        "BLOCKS 1\n"
        "BLOCK work 09:00:00 10:00:00\n"
        "KIND command\n"
        "SUCCESS True\n"
        "ACTIONS_LEN 2\n"
        "USER_COMMAND move the block\n"
    )

    monkeypatch.setenv("SEED_SNAPSHOT", "moves")
    seed_schedule.main()
    assert capsys.readouterr().out == (
        "STATUS active\n"
        "BLOCKS 1\n"
        "BLOCK 09:00 10:00 work | Focus\n"
        "KIND command\n"
        "SUCCESS True\n"
        "ACTIONS_LEN 2\n"
        "MOVE_COUNT 1\n"
        "USER_COMMAND move the block\n"
    )


@pytest.mark.django_db
def test_schedule_seeder_remaining_audit_snapshots_and_unknown_mode(user, monkeypatch, capsys):
    schedule = Schedule.objects.create(user=user, date="2027-05-05", status="active")
    TimeBlock.objects.create(
        schedule=schedule,
        title="Focus",
        start_time="09:00",
        end_time="10:00",
        category="work",
    )
    AIInteraction.objects.create(
        schedule=schedule,
        kind="chat",
        success=True,
        actions_json=[{"type": "add"}],
        user_command="hello",
        ai_response=json.dumps(
            {
                "turn_count": 2,
                "transcript_sha256": "abcdef0123456789",
                "raw": "txt",
            }
        ),
    )

    def _run(snapshot: str) -> str:
        _setenv(
            monkeypatch,
            SEED_MODE="snapshot",
            SEED_USERNAME=user.username,
            SEED_DATE="2027-05-05",
            SEED_SNAPSHOT=snapshot,
        )
        seed_schedule.main()
        return capsys.readouterr().out

    assert _run("titles") == (
        "STATUS active\n"
        "BLOCKS 1\n"
        "BLOCK Focus 09:00:00 10:00:00\n"
        "KIND chat\n"
        "SUCCESS True\n"
        "ACTIONS_LEN 1\n"
        "USER_COMMAND hello\n"
    )
    # `overlap` intentionally omits USER_COMMAND (the mass-move/overlap parsers
    # don't read it).
    assert _run("overlap") == (
        "STATUS active\n"
        "BLOCKS 1\n"
        "BLOCK Focus 09:00:00 10:00:00\n"
        "KIND chat\n"
        "SUCCESS True\n"
        "ACTIONS_LEN 1\n"
    )
    assert _run("draft") == (
        "STATUS active\n"
        "BLOCKS 1\n"
        "KIND chat\n"
        "SUCCESS True\n"
        "ACTIONS_LEN 1\n"
        "USER_COMMAND hello\n"
    )
    assert _run("chat") == (
        "STATUS active\n"
        "BLOCKS 1\n"
        "KIND chat\n"
        "SUCCESS True\n"
        "ACTIONS_LEN 1\n"
        "USER_COMMAND hello\n"
        "AI_RESPONSE_KEYS ['raw', 'transcript_sha256', 'turn_count']\n"
        "TURN_COUNT 2\n"
        "HASH_PREFIX abcdef012345\n"
        "HAS_RAW True\n"
    )

    # An unrecognised block-detail snapshot fails loud rather than emitting
    # partial output; "draft"/"chat" (asserted above) still fall through.
    _setenv(
        monkeypatch,
        SEED_MODE="snapshot",
        SEED_USERNAME=user.username,
        SEED_DATE="2027-05-05",
        SEED_SNAPSHOT="bogus-snapshot",
    )
    with pytest.raises(RuntimeError, match="Unknown SEED_SNAPSHOT"):
        seed_schedule.main()

    _setenv(monkeypatch, SEED_MODE="bogus-mode", SEED_USERNAME=user.username)
    with pytest.raises(RuntimeError, match="Unknown SEED_MODE"):
        seed_schedule.main()


@pytest.mark.django_db
def test_schedule_seeder_schedules_mode_input_guards(user, monkeypatch):
    # Missing SEED_SCHEDULES_JSON fails via _required, not a bare TypeError.
    _setenv(monkeypatch, SEED_MODE="schedules", SEED_USERNAME=user.username)
    with pytest.raises(RuntimeError, match="SEED_SCHEDULES_JSON is required"):
        seed_schedule.main()

    # An empty spec list fails loud instead of an IndexError on schedules[-1].
    monkeypatch.setenv("SEED_SCHEDULES_JSON", "[]")
    with pytest.raises(RuntimeError, match="produced no schedules"):
        seed_schedule.main()


@pytest.mark.django_db
def test_analytics_reviewed_seeder_recomputes_and_freezes(user, monkeypatch, capsys):
    blocks = [
        {
            "title": "Done",
            "start_time": "09:00",
            "end_time": "10:00",
            "category": "work",
            "is_completed": True,
        },
        {
            "title": "Open",
            "start_time": "10:00",
            "end_time": "11:00",
            "category": "work",
            "is_completed": False,
        },
    ]
    _setenv(
        monkeypatch,
        SEED_USERNAME=user.username,
        SEED_DATE="2026-05-05",
        SEED_BLOCKS_JSON=json.dumps(blocks),
    )
    seed_analytics_reviewed.main()
    schedule = Schedule.objects.get(user=user, date="2026-05-05")
    assert capsys.readouterr().out == (f"seeded schedule {schedule.id} blocks 2\n")
    assert schedule.status == Schedule.Status.REVIEWED
    assert schedule.daily_review.planned_count == 2
    assert schedule.daily_review.completed_count == 1


@pytest.mark.django_db
def test_template_seeder_keeps_timed_operations_distinct(user, monkeypatch, capsys):
    template = {
        "type": "weekday",
        "name": "A weekday",
        "blocks": [],
    }
    _setenv(
        monkeypatch,
        SEED_USERNAME=user.username,
        SEED_TEMPLATE_JSON=json.dumps(template),
        SEED_DATES_JSON=json.dumps(["2026-09-21", "2026-09-28"]),
        SEED_MODE="template_seed_initial",
    )
    seed_template.main()
    assert capsys.readouterr().out == "seeded\n"
    assert Template.objects.filter(user=user, type="weekday").count() == 1
    assert Schedule.objects.filter(user=user).count() == 2

    monkeypatch.setenv("SEED_MODE", "template_delete")
    seed_template.main()
    assert capsys.readouterr().out == "deleted\n"
    assert not Template.objects.filter(user=user).exists()

    monkeypatch.setenv("SEED_MODE", "template_create")
    seed_template.main()
    assert capsys.readouterr().out == "re-created\n"
    assert Template.objects.filter(user=user, type="weekday").count() == 1


@pytest.mark.django_db
def test_preferences_seeder_resets_existing_rows_in_both_modes(user, monkeypatch, capsys):
    UserPreferences.objects.create(user=user, theme="strategic")
    _setenv(
        monkeypatch,
        SEED_USERNAME=user.username,
        SEED_MODE="preflight",
    )
    seed_prefs.main()
    assert capsys.readouterr().out == (f"reset theme to classic for {user.username}\n")
    assert UserPreferences.objects.get(user=user).theme == (UserPreferences.Theme.CLASSIC)

    UserPreferences.objects.filter(user=user).update(theme="strategic")
    monkeypatch.setenv("SEED_MODE", "postflight")
    seed_prefs.main()
    assert capsys.readouterr().out == "postflight: theme reset to classic\n"
    assert UserPreferences.objects.get(user=user).theme == "classic"

    UserPreferences.objects.filter(user=user).delete()
    seed_prefs.main()
    assert capsys.readouterr().out == "postflight: theme reset to classic\n"
    assert not UserPreferences.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_todoist_seeder_preserves_strict_ensure_and_disconnect_markers(user, monkeypatch, capsys):
    _setenv(
        monkeypatch,
        SEED_USERNAME=user.username,
        SEED_MODE="reset-strict",
    )
    seed_todoist.main()
    assert capsys.readouterr().out == "deleted todoist accounts: 0\n"

    ensured_name = "playwright-ensured"
    _setenv(
        monkeypatch,
        SEED_USERNAME=ensured_name,
        SEED_PASSWORD="pw-test",
        SEED_MODE="reset-ensure",
    )
    seed_todoist.main()
    assert capsys.readouterr().out == ("user created: True | deleted todoist accounts: 0\n")
    ensured = User.objects.get(username=ensured_name)
    assert ensured.check_password("pw-test")

    # Re-running reset-ensure for an existing user skips set_password (created=False).
    seed_todoist.main()
    assert capsys.readouterr().out == ("user created: False | deleted todoist accounts: 0\n")

    # First-ever creation without SEED_PASSWORD fails loud via _required.
    _setenv(monkeypatch, SEED_USERNAME="playwright-nopw", SEED_MODE="reset-ensure")
    monkeypatch.delenv("SEED_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="SEED_PASSWORD is required"):
        seed_todoist.main()

    _setenv(monkeypatch, SEED_USERNAME=ensured_name, SEED_MODE="disconnect")
    seed_todoist.main()
    assert capsys.readouterr().out == ("disconnected playwright todoist account\n")
    assert not TodoistAccount.objects.filter(user=ensured).exists()


@pytest.mark.django_db
def test_cleanup_seeder_deletes_only_requested_dates(user, monkeypatch, capsys):
    kept = Schedule.objects.create(user=user, date=datetime.date(2027, 1, 2))
    removed = Schedule.objects.create(user=user, date=datetime.date(2027, 1, 1))
    _setenv(
        monkeypatch,
        SEED_USERNAME=user.username,
        SEED_DATES_JSON=json.dumps(["2027-01-01"]),
    )
    seed_cleanup.main()
    assert capsys.readouterr().out == "cleanup deleted rows: 1\n"
    assert not Schedule.objects.filter(pk=removed.pk).exists()
    assert Schedule.objects.filter(pk=kept.pk).exists()
