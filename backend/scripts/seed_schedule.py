"""Seed and inspect schedule scenarios for Playwright smoke scripts.

Run through ``manage.py shell -c`` with ``runpy.run_path(...,
run_name='__main__')``. Parameters are passed as ``SEED_*`` environment
variables so JavaScript never has to interpolate Python source.
"""

import datetime
import json
import os

from analytics.models import DailyReview
from analytics.services import recompute_review_from_schedule
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Template


def _required(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"{name} is required")
    return value


def _json(name: str, default=None):
    value = os.environ.get(name)
    return default if value is None else json.loads(value)


def _user() -> User:
    return User.objects.get(username=_required("SEED_USERNAME"))


def _replace_blocks(schedule: Schedule, blocks: list[dict]) -> None:
    schedule.time_blocks.all().delete()
    for block in blocks:
        TimeBlock.objects.create(schedule=schedule, **block)


def _upsert_schedule(user: User, spec: dict) -> Schedule:
    schedule, _ = Schedule.objects.update_or_create(
        user=user,
        date=datetime.date.fromisoformat(spec["date"]),
        defaults={"status": spec.get("status", Schedule.Status.DRAFT)},
    )
    _replace_blocks(schedule, spec.get("blocks", []))
    return schedule


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

    interaction = schedule.ai_interactions.order_by("-created_at").first()
    if interaction is None:
        print("NO_AI_ROW")
        return
    print("KIND", interaction.kind)
    print("SUCCESS", interaction.success)
    if snapshot == "draft":
        print("USER_COMMAND", interaction.user_command)
        print("ACTIONS_LEN", len(interaction.actions_json))
    else:
        print("ACTIONS_LEN", len(interaction.actions_json))
    if snapshot == "moves":
        move_count = sum(action.get("type") == "move" for action in interaction.actions_json)
        print("MOVE_COUNT", move_count)
        print("USER_COMMAND", interaction.user_command)
    elif snapshot not in {"draft", "overlap"}:
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
    if not Template.objects.filter(user=user, type="weekday").exists():
        Template.objects.create(
            user=user,
            type="weekday",
            name="Auto-test weekday",
            blocks=template_blocks,
        )

    with_review = datetime.date.fromisoformat(_required("SEED_HISTORY_WITH_REVIEW"))
    without_review = datetime.date.fromisoformat(_required("SEED_HISTORY_NO_REVIEW"))
    target = datetime.date.fromisoformat(_required("SEED_DATE"))
    reviewed = _upsert_schedule(
        user,
        {
            "date": with_review.isoformat(),
            "status": "active",
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
    recompute_review_from_schedule(reviewed)
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
    Schedule.objects.filter(user=user, date=target).delete()
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
        print(timezone.localdate().isoformat())
        return
    if mode == "user_exists":
        username = _required("SEED_USERNAME")
        print("EXISTS", User.objects.filter(username=username).exists())
        return

    user = _user()
    if mode == "ensure_exists":
        _schedule, created = Schedule.objects.get_or_create(
            user=user,
            date=datetime.date.fromisoformat(_required("SEED_DATE")),
        )
        print("CREATED", created)
    elif mode == "schedules":
        specs = _json("SEED_SCHEDULES_JSON")
        schedules = [_upsert_schedule(user, spec) for spec in specs]
        template = _json("SEED_TEMPLATE_JSON")
        if template is not None:
            Template.objects.update_or_create(
                user=user,
                type=template["type"],
                defaults={
                    "name": template["name"],
                    "blocks": template.get("blocks", []),
                },
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
