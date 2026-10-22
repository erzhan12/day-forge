"""Server-owned continuation scopes. All ORM calls run under the User lock."""

import datetime
import json
import uuid
from dataclasses import dataclass

from django.http import JsonResponse
from django.utils import timezone

from ai.models import PendingIntent
from ai.schemas import MAX_ACTIONS_PER_COMMAND, MAX_TITLE_LEN, _is_hhmm

FIELDS = {
    "title",
    "category",
    "start_time",
    "end_time",
    "duration_minutes",
    "duration_delta_minutes",
    "placement_direction",
}
TIME_FIELDS = {
    "start_time",
    "end_time",
    "duration_minutes",
    "duration_delta_minutes",
    "placement_direction",
}


@dataclass(frozen=True)
class IntentReference:
    id: uuid.UUID | None = None
    version: int | None = None
    action: str = "new"


@dataclass
class IntentContext:
    reference: IntentReference
    slot: tuple | None
    row: PendingIntent | None
    error: bool = False
    mark_stale: bool = False


def parse_reference(data):
    identity = data.get("pending_intent_id")
    version = data.get("pending_intent_version")
    action = data.get("intent_action", "continue" if identity is not None else "new")
    if not isinstance(action, str) or action not in {"new", "continue", "cancel"}:
        raise ValueError("intent_action must be new, continue, or cancel.")
    if identity is None and version is None and action == "new":
        return IntentReference()
    if not isinstance(identity, str) or type(version) is not int or not 1 <= version <= 2**31 - 1:
        raise ValueError("A pending intent needs a UUID and a positive integer version.")
    try:
        parsed = uuid.UUID(identity)
    except ValueError as exc:
        raise ValueError("pending_intent_id must be a canonical UUID.") from exc
    if str(parsed) != identity:
        raise ValueError("pending_intent_id must be a canonical UUID.")
    return IntentReference(parsed, version, action)


def wire(row):
    return {
        "id": str(row.pk),
        "version": row.version,
        "expires_at": row.expires_at.isoformat(),
        "ask": row.question,
    }


def capture(schedule, fingerprint, reference):
    active = PendingIntent.objects.filter(
        schedule=schedule, user_id=schedule.user_id, state=PendingIntent.State.OPEN
    ).first()
    slot = (active.pk, active.version) if active else None
    if reference.id is None:
        return IntentContext(reference, slot, active)
    row = PendingIntent.objects.filter(
        pk=reference.id, user_id=schedule.user_id, schedule=schedule
    ).first()
    context = IntentContext(reference, slot, row)
    if row is None or row.state != PendingIntent.State.OPEN or row.version != reference.version:
        context.error = True
    elif row.expires_at <= timezone.now() or (
        reference.action != "cancel"
        and (row.revision != schedule.revision or row.context_fingerprint != fingerprint)
    ):
        context.error = context.mark_stale = True
    return context


def stale_response(context=None):
    if context and context.mark_stale and context.row:
        PendingIntent.objects.filter(
            pk=context.row.pk, version=context.row.version, state="open"
        ).update(state="stale")
    return JsonResponse(
        {
            "code": "pending_intent_stale",
            "pending_intent": None,
            "errors": {"detail": "The pending request changed or expired. Please restate it."},
        },
        status=409,
    )


def check(context):
    """Fence ask-only updates as well as schedule writes."""
    if context.error:
        return False
    row = context.row
    schedule_id = row.schedule_id if row else None
    if row:
        current = PendingIntent.objects.filter(pk=row.pk).first()
        if current is None or current.state != "open" or current.version != row.version:
            return False
        if context.reference.action != "new" and current.expires_at <= timezone.now():
            context.mark_stale = True
            return False
    if context.reference.id is None:
        # Also detect an intent created while a fresh request was in flight.
        return True  # The schedule-specific slot is checked by finish().
    return schedule_id is not None


def canonical_action(action):
    kind = action["type"]
    fields = (
        dict(action.get("changes", {}))
        if kind == "update"
        else {key: value for key, value in action.items() if key in FIELDS}
    )
    if "placement_direction" in action:
        fields["placement_direction"] = action["placement_direction"]
    return {
        "type": kind if kind in {"add", "remove"} else "update",
        "task_id": action.get("task_id"),
        "fields": fields,
    }


def validate_items(items, task_ids, categories):
    """Bound a proposal before storing it; it never grants new target ownership."""
    if not isinstance(items, list) or len(items) > MAX_ACTIONS_PER_COMMAND:
        raise ValueError("pending_actions must be a bounded array.")
    result = []
    for item in items:
        if not isinstance(item, dict) or set(item) - {
            "type",
            "task_id",
            "target_ids",
            "known_fields",
            "missing_fields",
        }:
            raise ValueError("Invalid pending action shape.")
        kind = item.get("type")
        if isinstance(kind, str) and kind in {"move", "resize"}:
            kind = "update"
        if not isinstance(kind, str) or kind not in {"add", "update", "remove"}:
            raise ValueError("Invalid pending action type.")
        target = item.get("task_id")
        targets = item.get("target_ids", [target] if target is not None else [])
        if (
            not isinstance(targets, list)
            or len(targets) > MAX_ACTIONS_PER_COMMAND
            or any(type(value) is not int or value not in task_ids for value in targets)
        ):
            raise ValueError("Pending targets must belong to this schedule.")
        if target is not None and (type(target) is not int or target not in targets):
            raise ValueError("Invalid pending target.")
        if kind == "add" and (target is not None or targets):
            raise ValueError("An add cannot select existing targets.")
        if kind != "add" and not targets:
            raise ValueError("A pending edit needs bounded target choices.")
        known, missing = item.get("known_fields", {}), item.get("missing_fields")
        allowed = FIELDS | {"task_id", "confirmation"}
        if (
            not isinstance(known, dict)
            or set(known) - FIELDS
            or not isinstance(missing, list)
            or not missing
            or any(not isinstance(key, str) or key not in allowed for key in missing)
            or set(known) & set(missing)
        ):
            raise ValueError("Invalid pending fields.")
        for key, value in known.items():
            if key == "title" and (
                not isinstance(value, str) or not value.strip() or len(value) > MAX_TITLE_LEN
            ):
                raise ValueError("Invalid pending title.")
            if key == "category" and (not isinstance(value, str) or value not in categories):
                raise ValueError("Invalid pending category.")
            if key in {"start_time", "end_time"} and not _is_hhmm(value):
                raise ValueError("Invalid pending time.")
            if key in {"duration_minutes", "duration_delta_minutes"} and (
                type(value) is not int
                or value == 0
                or value % 5
                or (key == "duration_minutes" and value < 0)
            ):
                raise ValueError("Invalid pending duration.")
            if key == "placement_direction" and (
                not isinstance(value, str) or value not in {"exact", "earlier", "later"}
            ):
                raise ValueError("Invalid pending direction.")
        if kind == "add" and "title" not in known and "title" not in missing:
            raise ValueError("A pending add needs a title or an explicit missing title.")
        if "task_id" in missing and (kind == "add" or target is not None):
            raise ValueError("Only an unselected existing target can be missing.")
        result.append(
            {
                "type": kind,
                "task_id": target,
                "target_ids": list(dict.fromkeys(targets)),
                "known_fields": known.copy(),
                "missing_fields": sorted(set(missing)),
            }
        )
    return result


def matching_item(action, items):
    candidate = canonical_action(action)
    for index, item in enumerate(items):
        if candidate["type"] != item["type"]:
            continue
        target = candidate["task_id"]
        if target != item["task_id"] and not (
            "task_id" in item["missing_fields"] and target in item["target_ids"]
        ):
            continue
        fields = candidate["fields"]
        known = item["known_fields"]
        if "duration_minutes" in known and "start_time" in fields and "end_time" in fields:
            start = datetime.time.fromisoformat(fields["start_time"])
            end = datetime.time.fromisoformat(fields["end_time"])
            fields["duration_minutes"] = (end.hour * 60 + end.minute) - (
                start.hour * 60 + start.minute
            )
        elif (
            "duration_minutes" in known
            and "end_time" in fields
            and "duration_minutes" not in fields
        ):
            # An end-only resize cannot prove that a locked duration is preserved.
            continue
        if any(key not in known and key not in item["missing_fields"] for key in fields):
            continue
        if any(key in fields and fields[key] != value for key, value in known.items()):
            continue
        # Adds must preserve the entire known identity, not merely a subset.
        if candidate["type"] == "add" and any(
            fields.get(key) != value for key, value in known.items()
        ):
            continue
        answered = answered_fields(action, item)
        if not set(item["missing_fields"]) & answered:
            continue
        if candidate["type"] == "add" and not set(item["missing_fields"]) <= answered:
            continue
        return index
    return None


def answered_fields(action, item):
    candidate = canonical_action(action)
    fields = set(candidate["fields"]) | {"confirmation"}
    if {"start_time", "end_time"} <= fields:
        fields.add("duration_minutes")
    if candidate["task_id"] in item["target_ids"]:
        fields.add("task_id")
    return fields


def constrain_actions(context, actions):
    if context.reference.id is None or context.reference.action == "new":
        return True
    remaining = list(context.row.items)
    for action in actions:
        index = matching_item(action, remaining)
        if index is None:
            return False
        remaining.pop(index)
    return True


def refine_question(item, originals, *, derived=False):
    """Consume one old permission per unresolved item, including repeated asks."""
    for index, original in enumerate(originals):
        if item["type"] != original["type"]:
            continue
        target = item["task_id"]
        if target != original["task_id"] and not (
            "task_id" in original["missing_fields"] and target in original["target_ids"]
        ):
            continue
        if not set(item["target_ids"]) <= set(original["target_ids"]):
            continue
        known = original["known_fields"]
        permitted = set(known) | set(original["missing_fields"])
        if derived and item["type"] == "add":
            # The rejected interval supplies a narrower, fixed duration.
            permitted.add("duration_minutes")
        if any(
            key not in permitted or (key in known and value != known[key])
            for key, value in item["known_fields"].items()
        ):
            continue
        missing = set(item["missing_fields"])
        if not derived and not missing <= set(original["missing_fields"]):
            continue
        originals.pop(index)
        return {
            **item,
            "known_fields": {**known, **item["known_fields"]},
            "missing_fields": sorted(missing & set(original["missing_fields"])),
        }
    raise ValueError("Pending question expanded its scope.")


def provider_context(context):
    if context.reference.id is None or context.reference.action == "new":
        return None
    row = context.row
    return {
        "source_message": row.source_message,
        "question": row.question,
        "pending_actions": row.items,
        "accepted_changes": row.accepted_changes,
    }


def unresolved_items(result, payload):
    if result.ask is not None:
        return result.pending_actions or []
    items = []
    for outcome in payload.get("outcomes", []):
        if not outcome.get("skipped_fields"):
            continue
        if outcome.get("reason_code") == "replay_guard":
            continue
        action = result.parsed_actions[outcome["action_index"]]
        candidate = canonical_action(action)
        fields = candidate["fields"]
        # A rejected create still has a known identity; only its placement is open.
        missing = set(outcome["skipped_fields"]) & FIELDS
        if candidate["type"] == "add":
            missing = {"start_time", "end_time"}
            if "duration_minutes" not in fields:
                if "start_time" in fields and "end_time" in fields:
                    start = datetime.time.fromisoformat(fields["start_time"])
                    end = datetime.time.fromisoformat(fields["end_time"])
                    fields["duration_minutes"] = (end.hour * 60 + end.minute) - (
                        start.hour * 60 + start.minute
                    )
                else:
                    missing.add("duration_minutes")
        elif missing & TIME_FIELDS:
            missing |= TIME_FIELDS
        items.append(
            {
                "type": candidate["type"],
                "task_id": candidate["task_id"],
                "target_ids": [candidate["task_id"]] if candidate["task_id"] else [],
                "known_fields": {key: value for key, value in fields.items() if key not in missing},
                "missing_fields": sorted(missing),
            }
        )
    for unresolved in result.unresolved_categories:
        if not any(
            item["task_id"] == unresolved.task_id and "category" in item["missing_fields"]
            for item in items
        ):
            items.append(
                {
                    "type": "update",
                    "task_id": unresolved.task_id,
                    "target_ids": [unresolved.task_id],
                    "known_fields": {},
                    "missing_fields": ["category"],
                }
            )
    return items


def finish(context, schedule, result, build_response, reload_context):
    """Called by finish_request: intent state and schedule diff share its transaction."""
    active = PendingIntent.objects.filter(
        user_id=schedule.user_id, schedule=schedule, state="open"
    ).first()
    slot = (active.pk, active.version) if active else None
    if not check(context) or slot != context.slot:
        return stale_response(context)
    decision = result.intent_decision
    continuing = context.reference.id is not None and context.reference.action == "continue"
    if continuing and decision not in {"continue", "cancel", "read"}:
        raise ValueError("A continuation needs an explicit intent decision.")
    if context.reference.action == "cancel" or decision == "cancel":
        # Check schedule/policy freshness through the existing no-op executor.
        response = build_response(cancel=True)
    else:
        if not constrain_actions(context, result.parsed_actions):
            return JsonResponse(
                {
                    "code": "pending_intent_scope",
                    "pending_intent": wire(active),
                    "errors": {
                        "detail": "The reply changed the pending request. Please restate it."
                    },
                },
                status=409,
            )
        response = build_response(cancel=False)
    if response.status_code != 200:
        if response.status_code == 409 and active:
            active.state = "stale"
            active.save(update_fields=["state"])
        return response
    payload = json.loads(response.content)
    cancelled = context.reference.action == "cancel" or decision == "cancel"
    next_items = unresolved_items(result, payload) if payload.get("ask") else []
    if continuing and not cancelled:
        remaining = list(context.row.items)
        attempted = []
        leftovers = []
        for action_index, action in enumerate(result.parsed_actions):
            index = matching_item(action, remaining)
            if index is not None:
                original = remaining.pop(index)
                attempted.append(original)
                unanswered = set(original["missing_fields"]) - answered_fields(action, original)
                if unanswered:
                    skipped = next(
                        (
                            set(outcome["skipped_fields"])
                            for outcome in payload.get("outcomes", [])
                            if outcome["action_index"] == action_index
                        ),
                        set(),
                    )
                    candidate = canonical_action(action)
                    target = candidate["task_id"]
                    leftovers.append(
                        {
                            **original,
                            "task_id": target,
                            "target_ids": [target] if target is not None else [],
                            "known_fields": {
                                **original["known_fields"],
                                **{
                                    key: value
                                    for key, value in candidate["fields"].items()
                                    if key not in skipped and key not in unanswered
                                },
                            },
                            "missing_fields": sorted(unanswered),
                        }
                    )
        # The model may refine remaining work; a rejected planner action may
        # only reuse its consumed permission. Neither can clone a permission.
        pool = remaining if result.ask is not None else attempted
        next_items = [
            refine_question(item, pool, derived=result.ask is None) for item in next_items
        ]
        next_items = [*next_items, *remaining, *leftovers]
        if next_items and not payload.get("ask"):
            payload["ask"] = (
                "Some requested changes are still pending. Please clarify the remaining request."
            )
    if cancelled:
        payload.update(
            explanation="Pending request cancelled.",
            ask=None,
            applied=False,
            partial=False,
            outcomes=[],
            pending_intent=None,
        )
        if active:
            active.state = "cancelled"
            active.save(update_fields=["state"])
    elif payload.get("ask"):
        after_schedule, after_blocks, fingerprint = reload_context()
        categories = {category.slug for category in after_schedule._categories}
        items = validate_items(next_items, {block.pk for block in after_blocks}, categories)
        accepted = list(context.row.accepted_changes) if continuing else []
        # Identity comes from committed rows, never assistant text or title matching.
        if payload.get("applied"):
            accepted.extend(
                {**change, "revision": after_schedule.revision}
                for change in result.accepted_changes
            )
        if active and context.reference.id is not None and context.reference.action != "new":
            row = active
            row.version += 1
            row.items, row.accepted_changes = items, accepted
            row.question, row.revision, row.context_fingerprint = (
                payload["ask"],
                after_schedule.revision,
                fingerprint,
            )
            row.save(
                update_fields=[
                    "version",
                    "items",
                    "accepted_changes",
                    "question",
                    "revision",
                    "context_fingerprint",
                ]
            )
        else:
            if active:
                active.state = "cancelled"
                active.save(update_fields=["state"])
            row = PendingIntent.objects.create(
                user_id=schedule.user_id,
                schedule=schedule,
                revision=after_schedule.revision,
                context_fingerprint=fingerprint,
                source_message=result.source_message,
                question=payload["ask"],
                items=items,
                accepted_changes=accepted,
                expires_at=timezone.now() + datetime.timedelta(minutes=15),
            )
        payload["pending_intent"] = wire(row)
    else:
        if active:
            active.state = "resolved" if continuing else "cancelled"
            active.save(update_fields=["state"])
        payload["pending_intent"] = None
    response.content = JsonResponse(payload).content
    return response
