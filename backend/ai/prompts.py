"""Prompt builders for the AI command endpoint.

Pure functions so they can be unit-tested without the OpenAI SDK.
"""
import json

from schedules.models import TimeBlock

# Mirror frontend/src/utils/scheduleTime.ts to avoid coupling the backend
# to the TS module. Update both together if the visible day window changes.
DAY_START = "06:00"
DAY_END = "23:00"

_CATEGORY_VALUES = sorted(c.value for c in TimeBlock.Category)

# TODO(Phase 5): inject template / rules / last-7-days context here.
SYSTEM_PROMPT = f"""\
You are the scheduling assistant for Day Forge, a daily time-blocking app.
Your only job is to translate one user command (English or Russian) into a
strict JSON plan of schedule mutations.

Working day window: {DAY_START}-{DAY_END}. Never produce blocks outside it.
All times use 24-hour HH:MM format with 5-minute granularity.

Valid action types and required fields:
- add:    type=add, title=str, start_time=HH:MM, end_time=HH:MM,
          category=one of {_CATEGORY_VALUES}
- move:   type=move, task_id=int, start_time=HH:MM, end_time=HH:MM (optional;
          omit to keep the original duration)
- remove: type=remove, task_id=int
- resize: type=resize, task_id=int, start_time=HH:MM (optional),
          end_time=HH:MM (optional)

Rules:
1. Every move/remove/resize MUST reference a task_id from the schedule the
   user provides. Never invent an id. If the block the user refers to is
   not present, return zero actions and ask for clarification in
   'explanation'.
2. If the command is ambiguous, return zero actions and explain in
   'explanation' (same language as the user).
3. 'category' must be one of {_CATEGORY_VALUES}. Default to "other" if
   unclear.
4. Keep 'explanation' short (one sentence) and in the same language the
   user wrote in.
5. Return STRICT JSON only — no prose, no code fences.

Response schema:
{{
  "actions": [ <action objects as above> ],
  "explanation": "<short human-readable summary>"
}}
"""


def _format_block_line(block) -> str:
    start = block.start_time.strftime("%H:%M")
    end = block.end_time.strftime("%H:%M")
    # JSON-encode the title to escape quotes / unicode safely.
    title = json.dumps(block.title, ensure_ascii=False)
    return (
        f"id={block.id} {start}-{end} {block.category} "
        f"completed={str(block.is_completed).lower()} title={title}"
    )


def build_user_message(schedule, blocks, now, user_command: str) -> str:
    """Format the per-request context + user command.

    ``schedule`` provides the date; ``blocks`` is any iterable of TimeBlock
    instances; ``now`` is a timezone-aware ``datetime`` (or naive localtime).
    """
    weekday = schedule.date.strftime("%A")
    block_lines = [_format_block_line(b) for b in blocks]
    block_section = "\n".join(block_lines) if block_lines else "(no blocks yet)"

    # JSON-encode the user command so embedded newlines / quotes / fake
    # "User command:" lines are rendered as a single quoted string literal
    # and can't be mistaken by the model for a separate prompt section.
    encoded_command = json.dumps(user_command, ensure_ascii=False)
    return (
        f"Schedule date: {schedule.date.isoformat()} ({weekday})\n"
        f"Current local time: {now.strftime('%H:%M')}\n"
        f"Existing blocks:\n{block_section}\n\n"
        f"User command:\n{encoded_command}"
    )
