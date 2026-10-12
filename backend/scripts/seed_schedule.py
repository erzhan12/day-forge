"""Seed and inspect schedule scenarios for Playwright smoke scripts.

Run through ``manage.py shell -c`` with ``runpy.run_path(...,
run_name='__main__')``. Parameters are passed as ``SEED_*`` environment
variables so JavaScript never has to interpolate Python source.
"""

import datetime
import json
import os

from analytics.models import DailyReview
from analytics.services import freeze_review_snapshot
from django.contrib.auth.models import User
from django.core.cache import cache
from schedules.models import Schedule, TimeBlock
from schedules.mutations import execute_schedule_maintenance, run_user_maintenance
from schedules.window import user_local_date
from templates_mgr.models import Template

from scripts import _json, _required, _user


def _replace_blocks_locked(schedule: Schedule, blocks: list[dict]) -> None:
    schedule.time_blocks.all().delete()
    for block in blocks:
        TimeBlock.objects.create(schedule=schedule, **block)


def _replace_blocks(schedule: Schedule, blocks: list[dict]) -> None:
    execute_schedule_maintenance(
        schedule.user_id, schedule.pk,
        lambda context: _replace_blocks_locked(context.schedule, blocks),
    )


def _upsert_schedule(user: User, spec: dict) -> Schedule:
    def seed(_user):
        schedule, _ = Schedule.objects.get_or_create(
            user=user, date=datetime.date.fromisoformat(spec["date"])
        )

        def replace(context):
            _replace_blocks_locked(context.schedule, spec.get("blocks", []))
            context.schedule.status = spec.get("status", Schedule.Status.DRAFT)
            context.schedule.save(update_fields=["status"])

        return execute_schedule_maintenance(user.pk, schedule.pk, replace).schedule

    return run_user_maintenance(user.pk, seed)


def _clear_schedules(user: User, dates) -> int:
    """Retain day identity/version so an old date-based request cannot match a reset."""
    def clear(_user):
        schedules = list(Schedule.objects.filter(user=user, date__in=dates).order_by("pk"))
        for schedule in schedules:
            def reset(context):
                context.schedule.time_blocks.all().delete()
                context.schedule.status = Schedule.Status.DRAFT
                context.schedule.save(update_fields=["status"])
                DailyReview.objects.filter(schedule=context.schedule).delete()

            execute_schedule_maintenance(user.pk, schedule.pk, reset)
        return len(schedules)

    return run_user_maintenance(user.pk, clear)


def _print_audit(schedule: Schedule, snapshot: str) -> None:
    blocks = schedule.time_blocks.order_by("start_time")
    print("STATUS", schedule.status)
    print("BLOCKS", blocks.count())
    if snapshot in {"titles", "overlap"}:
        for block in blocks:
            print("BLOCK", block.title, block.start_time, block.end_time)
    elif snapshot == "categories":
        for block in blocks:
            print("BLOCK", block.category, block.start_time, block.end_time)
    elif snapshot == "moves":
        for block in blocks:
            print(
                "BLOCK",
                block.start_time.strftime("%H:%M"),
                block.end_time.strftime("%H:%M"),
                block.category,
                "|",
                block.title,
            )
    elif snapshot not in {"draft", "chat"}:
        # "draft" and "chat" deliberately emit no BLOCK-detail rows; anything
        # else reaching here is an unrecognised snapshot — fail loud rather
        # than emit partial output that trips a .mjs parser with a cryptic
        # assertion (mirrors main()'s "Unknown SEED_MODE" guard).
        raise RuntimeError(f"Unknown SEED_SNAPSHOT: {snapshot!r}")

    interaction = schedule.ai_interactions.order_by("-created_at").first()
    if interaction is None:
        print("NO_AI_ROW")
        return
    print("KIND", interaction.kind)
    print("SUCCESS", interaction.success)
    print("ACTIONS_LEN", len(interaction.actions_json))
    if snapshot == "moves":
        move_count = sum(action.get("type") == "move" for action in interaction.actions_json)
        print("MOVE_COUNT", move_count)
        print("USER_COMMAND", interaction.user_command)
    elif snapshot != "overlap":
        print("USER_COMMAND", interaction.user_command)
    if snapshot == "chat":
        try:
            payload = json.loads(interaction.ai_response)
            print("AI_RESPONSE_KEYS", sorted(payload.keys()))
            print("TURN_COUNT", payload.get("turn_count"))
            transcript_hash = payload.get("transcript_sha256") or ""
            print("HASH_PREFIX", transcript_hash[:12])
            print(
                "HAS_RAW",
                isinstance(payload.get("raw"), str) and len(payload["raw"]) > 0,
            )
        except Exception as exc:  # pragma: no cover - diagnostic contract
            print("AI_RESPONSE_PARSE_ERROR", repr(exc))


def _history_suffix(user: User) -> None:
    template_blocks = [
        {
            "title": "Standup",
            "start_time": "09:00",
            "end_time": "09:30",
            "category": "work",
        }
    ]
    run_user_maintenance(
        user.pk,
        lambda _user: Template.objects.get_or_create(
            user=user, type="weekday",
            defaults={"name": "Auto-test weekday", "blocks": template_blocks},
        )
    )

    with_review = datetime.date.fromisoformat(_required("SEED_HISTORY_WITH_REVIEW"))
    without_review = datetime.date.fromisoformat(_required("SEED_HISTORY_NO_REVIEW"))
    target = datetime.date.fromisoformat(_required("SEED_DATE"))

    def seed_reviewed(_user):
        schedule = _upsert_schedule(
            user,
            {
                "date": with_review.isoformat(),
                "status": "reviewed",
                "blocks": [
                    {
                        "title": "Standup",
                        "start_time": "09:00",
                        "end_time": "09:30",
                        "category": "work",
                        "is_completed": True,
                        "sort_order": 0,
                    },
                    {
                        "title": "Deep work",
                        "start_time": "10:00",
                        "end_time": "12:00",
                        "category": "work",
                        "is_completed": True,
                        "sort_order": 1,
                    },
                    {
                        "title": "Lunch",
                        "start_time": "12:30",
                        "end_time": "13:30",
                        "category": "personal",
                        "is_completed": True,
                        "sort_order": 2,
                    },
                    {
                        "title": "Email",
                        "start_time": "14:00",
                        "end_time": "15:00",
                        "category": "work",
                        "is_completed": False,
                        "sort_order": 3,
                    },
                ],
            },
        )
        freeze_review_snapshot(schedule, revision=schedule.revision)
        return schedule

    run_user_maintenance(user.pk, seed_reviewed)
    unreviewed = _upsert_schedule(
        user,
        {
            "date": without_review.isoformat(),
            "status": "active",
            "blocks": [
                {
                    "title": "Sunday run",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "category": "health",
                    "is_completed": True,
                    "sort_order": 0,
                },
                {
                    "title": "Plan week",
                    "start_time": "11:00",
                    "end_time": "12:00",
                    "category": "personal",
                    "is_completed": False,
                    "sort_order": 1,
                },
            ],
        },
    )
    DailyReview.objects.filter(schedule=unreviewed).delete()
    _clear_schedules(user, [target])
    print(f"seeded with-review={with_review} no-review={without_review} target={target}")


def _snapshot(user: User) -> None:
    schedule = Schedule.objects.get(
        user=user, date=datetime.date.fromisoformat(_required("SEED_DATE"))
    )
    snapshot = _required("SEED_SNAPSHOT")
    if snapshot == "chat_titles":
        print("STATUS", schedule.status)
        for block in schedule.time_blocks.all():
            print("BLOCK", block.title, block.start_time, block.end_time)
    elif snapshot == "rate_before":
        print("RATE_BEFORE", cache.get(f"ai_draft_rl:{user.id}", 0))
        print("AI_BEFORE", schedule.ai_interactions.count())
    elif snapshot == "rate_after":
        print("RATE_AFTER", cache.get(f"ai_draft_rl:{user.id}", 0))
        print("AI_AFTER", schedule.ai_interactions.count())
        print("BLOCKS", schedule.time_blocks.count())
        print("STATUS", schedule.status)
    else:
        _print_audit(schedule, snapshot)


def main() -> None:
    mode = _required("SEED_MODE")
    if mode == "localdate":
        print(user_local_date(_user()).isoformat())
        return
    if mode == "user_exists":
        username = _required("SEED_USERNAME")
        print("EXISTS", User.objects.filter(username=username).exists())
        return

    user = _user()
    if mode == "ensure_exists":
        _schedule, created = run_user_maintenance(
            user.pk, lambda _user: Schedule.objects.get_or_create(
                user=user, date=datetime.date.fromisoformat(_required("SEED_DATE"))
            )
        )
        print("CREATED", created)
    elif mode == "schedules":
        specs = json.loads(_required("SEED_SCHEDULES_JSON"))
        schedules = [_upsert_schedule(user, spec) for spec in specs]
        if not schedules:
            raise RuntimeError("SEED_SCHEDULES_JSON produced no schedules")
        template = _json("SEED_TEMPLATE_JSON")
        if template is not None:
            run_user_maintenance(
                user.pk,
                lambda _user: Template.objects.update_or_create(
                    user=user,
                    type=template["type"],
                    defaults={
                        "name": template["name"], "blocks": template.get("blocks", []),
                    },
                ),
            )
        marker = os.environ.get("SEED_MARKER", "seeded {id}")
        print(marker.format(id=schedules[-1].id, count=len(schedules)))
    elif mode == "snapshot":
        _snapshot(user)
    elif mode == "history_suffix":
        _history_suffix(user)
    else:
        raise RuntimeError(f"Unknown SEED_MODE: {mode}")


if __name__ == "__main__":
    main()
