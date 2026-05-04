"""Prompt builders for the AI command + draft endpoints.

Pure functions so they can be unit-tested without the OpenAI SDK.

Two top-level prompts live here:

* ``SYSTEM_PROMPT`` + ``build_user_message`` — the original Phase-4 command
  bar, where the model translates one natural-language command into add /
  move / remove / resize actions against the existing schedule.
* ``SYSTEM_PROMPT_DRAFT`` + ``build_draft_user_message`` — the Phase-5
  draft generator, where the model fills an empty schedule from a
  weekday/weekend template, the user's last-7-days history, and active
  rules. Only ``add`` actions are valid (no existing blocks → no
  ``task_id``s to reference).
"""
import json

from schedules.models import TimeBlock

# Mirror frontend/src/utils/scheduleTime.ts to avoid coupling the backend
# to the TS module. Update both together if the visible day window changes.
DAY_START = "06:00"
DAY_END = "23:00"

_CATEGORY_VALUES = sorted(c.value for c in TimeBlock.Category)

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


SYSTEM_PROMPT_DRAFT = f"""\
You are the scheduling assistant for Day Forge, generating a fresh daily
schedule for an empty day. Translate the supplied template, last-N-days
history, and active rules into a JSON plan of "add" actions.

Working day window: {DAY_START}-{DAY_END}. Never produce blocks outside it.
All times use 24-hour HH:MM format with 5-minute granularity.

Allowed action type:
- add: type=add, title=str, start_time=HH:MM, end_time=HH:MM,
       category=one of {_CATEGORY_VALUES}

No move/remove/resize actions are valid here — the schedule is empty, so
there are no task_ids to reference. Never include task_id.

Rules:
1. The supplied template (weekday or weekend) is the baseline shape of
   the day. Start there.
2. Look at the recent history. If the user has consistently shifted a
   block (e.g. moved gym from 17:30 to 18:00 every weekday), reflect that
   in the draft. If a block has been routinely skipped, you may drop it.
3. Respect every active rule. Rules may be in English or Russian; obey
   them either way. Higher-priority rules take precedence on conflict.
4. 'category' must be one of {_CATEGORY_VALUES}. Default to "other" if
   unclear.
5. New blocks must not overlap each other.
6. Keep 'explanation' short (one sentence) describing how the draft
   diverges from the template, if at all. English is fine.
7. Return STRICT JSON only — no prose, no code fences.

Response schema:
{{
  "actions": [ {{"type": "add", "title": "...", "start_time": "HH:MM",
                 "end_time": "HH:MM", "category": "..."}}, ... ],
  "explanation": "<short summary>"
}}
"""


def _format_block_line(d: dict) -> str:
    """Render one block dict as a single context line for the prompt.

    Takes a normalised dict (see ``_runtime_block_to_dict`` and
    ``_template_entry_to_dict``) instead of a Django model instance so the
    same formatter feeds both runtime ``TimeBlock`` rows and template JSON
    entries — the latter have no ``id`` / ``is_completed`` and store times
    as strings.
    """
    title = json.dumps(d["title"], ensure_ascii=False)
    return (
        f"id={d['id']} {d['start_time']}-{d['end_time']} {d['category']} "
        f"completed={str(d['is_completed']).lower()} title={title}"
    )


def _runtime_block_to_dict(block) -> dict:
    """Adapter: ``TimeBlock`` model instance → normalised dict."""
    return {
        "id": block.id,
        "start_time": block.start_time.strftime("%H:%M"),
        "end_time": block.end_time.strftime("%H:%M"),
        "category": block.category,
        "is_completed": block.is_completed,
        "title": block.title,
    }


def _template_entry_to_dict(entry: dict, synthetic_id: int) -> dict:
    """Adapter: template JSON entry → normalised dict.

    Templates have no DB-backed id; the model only references ids when
    asking us to act on existing blocks, but a stable synthetic id keeps
    the line shape consistent with runtime blocks for the formatter.
    """
    return {
        "id": synthetic_id,
        "start_time": entry["start_time"],
        "end_time": entry["end_time"],
        "category": entry.get("category", "other"),
        "is_completed": False,
        "title": entry["title"],
    }


def build_user_message(schedule, blocks, now, user_command: str) -> str:
    """Format the per-request context + user command for ``SYSTEM_PROMPT``.

    ``schedule`` provides the date; ``blocks`` is any iterable of TimeBlock
    instances; ``now`` is a timezone-aware ``datetime`` (or naive localtime).
    """
    weekday = schedule.date.strftime("%A")
    block_lines = [_format_block_line(_runtime_block_to_dict(b)) for b in blocks]
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


def build_draft_user_message(
    schedule, template, history_schedules, rules, now
) -> str:
    """Format the per-request context for ``SYSTEM_PROMPT_DRAFT``.

    Pure function. Sections:
      1. Schedule date + weekday
      2. Current local time
      3. Active template (weekday or weekend), block-by-block
      4. Recent history (last N days), each schedule's blocks. Schedules
         with ``status="draft"`` are intentionally skipped — they
         represent the AI's prior un-reviewed output and should not be
         used as training context.
      5. Active rules ordered by priority desc.

    There is no ``User command:`` section — drafts have no per-request
    user input.
    """
    weekday = schedule.date.strftime("%A")
    template_lines = []
    template_blocks = template.blocks if template is not None else []
    for idx, entry in enumerate(template_blocks):
        d = _template_entry_to_dict(entry, synthetic_id=-1 - idx)
        template_lines.append(_format_block_line(d))
    template_section = (
        "\n".join(template_lines) if template_lines else "(no template entries)"
    )

    history_lines: list[str] = []
    for past in history_schedules:
        if getattr(past, "status", None) == "draft":
            continue
        past_weekday = past.date.strftime("%A")
        # Per-day completion ratio is appended when a DailyReview row exists
        # with at least one planned block — gives the LLM a passive signal
        # like "user finishes ~70% of weekday plans" without a structured
        # stats block. Phase 6 only persists reviews via analytics_view, so
        # this is silently a no-op for users who never open the panel.
        review = getattr(past, "daily_review", None)
        if review is not None and review.planned_count > 0:
            suffix = f" (completed: {review.completed_count}/{review.planned_count})"
        else:
            suffix = ""
        history_lines.append(
            f"# {past.date.isoformat()} ({past_weekday}){suffix}"
        )
        past_blocks = list(past.time_blocks.all())
        if past_blocks:
            for b in past_blocks:
                history_lines.append(_format_block_line(_runtime_block_to_dict(b)))
        else:
            history_lines.append("(no blocks)")
    history_section = (
        "\n".join(history_lines) if history_lines else "(no recent history)"
    )

    rule_lines = [
        f"{i + 1}. {json.dumps(r.text, ensure_ascii=False)}"
        for i, r in enumerate(rules)
    ]
    rules_section = "\n".join(rule_lines) if rule_lines else "(no active rules)"

    template_type = template.type if template is not None else "unknown"

    return (
        f"Schedule date: {schedule.date.isoformat()} ({weekday})\n"
        f"Current local time: {now.strftime('%H:%M')}\n"
        f"Active template ({template_type}):\n{template_section}\n\n"
        f"Recent history (last days):\n{history_section}\n\n"
        f"Active rules (priority desc):\n{rules_section}"
    )
