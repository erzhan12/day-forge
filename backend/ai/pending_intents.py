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


class IntentScopeError(ValueError):
    """A pending proposal violates its shape or continuation permission."""


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
        raise IntentScopeError("pending_actions must be a bounded array.")
    result = []
    for item in items:
        if not isinstance(item, dict) or set(item) - {
            "type",
            "task_id",
            "target_ids",
            "known_fields",
            "missing_fields",
        }:
            raise IntentScopeError("Invalid pending action shape.")
        kind = item.get("type")
        if isinstance(kind, str) and kind in {"move", "resize"}:
            kind = "update"
        if not isinstance(kind, str) or kind not in {"add", "update", "remove"}:
            raise IntentScopeError("Invalid pending action type.")
        target = item.get("task_id")
        targets = item.get("target_ids", [target] if target is not None else [])
        if (
            not isinstance(targets, list)
            or len(targets) > MAX_ACTIONS_PER_COMMAND
            or any(type(value) is not int or value not in task_ids for value in targets)
        ):
            raise IntentScopeError("Pending targets must belong to this schedule.")
        if target is not None and (type(target) is not int or target not in targets):
            raise IntentScopeError("Invalid pending target.")
        if kind == "add" and (target is not None or targets):
            raise IntentScopeError("An add cannot select existing targets.")
        if kind != "add" and not targets:
            raise IntentScopeError("A pending edit needs bounded target choices.")
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
            raise IntentScopeError("Invalid pending fields.")
        for key, value in known.items():
            if key == "title" and (
                not isinstance(value, str) or not value.strip() or len(value) > MAX_TITLE_LEN
            ):
                raise IntentScopeError("Invalid pending title.")
            if key == "category" and (not isinstance(value, str) or value not in categories):
                raise IntentScopeError("Invalid pending category.")
            if key in {"start_time", "end_time"} and not _is_hhmm(value):
                raise IntentScopeError("Invalid pending time.")
            if key in {"duration_minutes", "duration_delta_minutes"} and (
                type(value) is not int
                or value == 0
                or value % 5
                or (key == "duration_minutes" and value < 0)
            ):
                raise IntentScopeError("Invalid pending duration.")
            if key == "placement_direction" and (
                not isinstance(value, str) or value not in {"exact", "earlier", "later"}
            ):
                raise IntentScopeError("Invalid pending direction.")
        if kind == "add" and "title" not in known and "title" not in missing:
            raise IntentScopeError("A pending add needs a title or an explicit missing title.")
        if "task_id" in missing and (kind == "add" or target is not None):
            raise IntentScopeError("Only an unselected existing target can be missing.")
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
        permitted = set(known) | set(item["missing_fields"])
        if "duration_minutes" in permitted and "start_time" in fields and "end_time" in fields:
            start = datetime.time.fromisoformat(fields["start_time"])
            end = datetime.time.fromisoformat(fields["end_time"])
            duration = (end.hour * 60 + end.minute) - (
                start.hour * 60 + start.minute
            )
            if duration <= 0:
                continue
            if "duration_minutes" in fields and fields["duration_minutes"] != duration:
                continue
            fields["duration_minutes"] = duration
            # An allowed endpoint and duration determine the other endpoint.
            # This grants no independent choice of time or change to locked values.
            if "start_time" in permitted or "end_time" in permitted:
                permitted.update({"start_time", "end_time"})
        elif (
            "duration_minutes" in known
            and "end_time" in fields
            and "duration_minutes" not in fields
        ):
            # An end-only resize cannot prove that a locked duration is preserved.
            continue
        if any(key not in permitted for key in fields):
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
    raise IntentScopeError("Pending question expanded its scope.")


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


def _interval_minutes(action):
    start, end = action.get("start_time"), action.get("end_time")
    if not (_is_hhmm(start) and _is_hhmm(end)):
        return None
    start, end = datetime.time.fromisoformat(start), datetime.time.fromisoformat(end)
    return (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)


def relative_guard_add_items(actions):
    """One add permission per add the relative-add guard interrupted.

    Built only from the parsed actions of a turn the guard blocked: identity
    (title, category) and a derivable duration are known, the placement is
    missing. Transcript text never contributes. The rejected times are dropped.
    """
    items = []
    for action in actions:
        if action.get("type") != "add":
            continue
        known = {"title": action.get("title"), "category": action.get("category")}
        missing = ["end_time", "start_time"]
        duration = action.get("duration_minutes")
        if duration is None:
            duration = _interval_minutes(action)
        if type(duration) is int and duration > 0 and duration % 5 == 0:
            known["duration_minutes"] = duration
        else:
            missing.append("duration_minutes")
        items.append(
            {
                "type": "add",
                "task_id": None,
                "target_ids": [],
                "known_fields": known,
                "missing_fields": sorted(missing),
            }
        )
    return items


def _duplicates(derived, model_item):
    """A model pending add that repeats an interrupted add rather than a sibling."""
    if model_item.get("type") != "add":
        return False
    known, other = derived["known_fields"], model_item.get("known_fields", {})
    if (other.get("title"), other.get("category")) != (known["title"], known["category"]):
        return False
    return not (
        "duration_minutes" in known
        and "duration_minutes" in other
        and other["duration_minutes"] != known["duration_minutes"]
    )


def merge_guard_items(derived, model_items):
    """Derived items win over a model copy of the same add: theirs keep the
    placement open, while the model's may lock the time the guard rejected."""
    model_items = list(model_items)
    for item in derived:
        index = next(
            (i for i, other in enumerate(model_items) if _duplicates(item, other)), None
        )
        if index is not None:
            model_items.pop(index)
    return [*derived, *model_items]


def probe_allowed(actions, items):
    """Identity gate for the no-write guard probe on a scope failure.

    Every reply action must be an add naming the title and category of a
    distinct saved add whose placement is still open. Only then can the
    guard's placement question be answered within the saved scope.
    """
    open_adds = [
        item
        for item in items
        if item["type"] == "add" and {"start_time", "end_time"} <= set(item["missing_fields"])
    ]
    if not actions:
        return False
    for action in actions:
        if action.get("type") != "add":
            return False
        index = next(
            (
                i
                for i, item in enumerate(open_adds)
                if item["known_fields"].get("title") == action.get("title")
                and item["known_fields"].get("category") == action.get("category")
            ),
            None,
        )
        if index is None:
            return False
        open_adds.pop(index)
    return True


def finish(context, schedule, result, build_response, reload_context, probe=None):
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
        raise IntentScopeError("A continuation needs an explicit intent decision.")
    if context.reference.action == "cancel" or decision == "cancel":
        # Check schedule/policy freshness through the existing no-op executor.
        response = build_response(cancel=True)
    elif constrain_actions(context, result.parsed_actions):
        response = build_response(cancel=False)
    else:
        # A reply outside the saved scope may still deserve the relative-add
        # guard's question (an untimed add after an anchor answer). The probe
        # never writes; without a question the scope rejection stands.
        response = (
            probe()
            if probe is not None and probe_allowed(result.parsed_actions, context.row.items)
            else None
        )
        if response is None:
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
    if response.status_code != 200:
        if response.status_code == 409 and active:
            active.state = "stale"
            active.save(update_fields=["state"])
        return response
    guard_blocked_turn = getattr(response, "relative_add_guard_blocked", False)
    payload = json.loads(response.content)
    cancelled = context.reference.action == "cancel" or decision == "cancel"
    next_items = unresolved_items(result, payload) if payload.get("ask") else []
    # Structured remaining work survives a missing prose question. Add it after
    # execution so the legacy "ask means no writes" contract stays intact.
    model_items = (
        result.pending_actions or []
        if result.ask is None and decision in {"new", "continue"}
        else []
    )
    if continuing and not cancelled:
        remaining = list(context.row.items)
        attempted = []
        leftovers = []
        outcomes = payload.get("outcomes", [])
        guard_blocked = (
            payload.get("ask") and not payload.get("applied")
            and (not outcomes or all(o.get("reason_code") == "replay_guard" for o in outcomes))
        )
        # A guard question is not evidence that an action consumed its permission.
        actions_to_resolve = [] if guard_blocked else result.parsed_actions
        for action_index, action in enumerate(actions_to_resolve):
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
        # A turn the relative-add guard blocked keeps the saved scope exactly:
        # its proposal must not narrow it, e.g. by locking a rejected start.
        model_items = (
            [] if guard_blocked_turn else [refine_question(item, remaining) for item in model_items]
        )
        next_items = [*next_items, *model_items, *remaining, *leftovers]
    elif guard_blocked_turn and not cancelled:
        derived = relative_guard_add_items(result.parsed_actions)
        next_items.extend(merge_guard_items(derived, model_items))
    else:
        next_items.extend(model_items)
    if next_items and not payload.get("ask"):
        payload["ask"] = (
            "Some requested changes are still pending. Please clarify the remaining request."
        )
    if next_items:
        payload["partial"] = bool(payload.get("applied"))
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
            # Keep the original expiry; follow-ups never extend the 15-minute window.
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
