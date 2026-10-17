"""R11 evaluation primitives. No provider calls or production database setup."""

import datetime
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ai.models import AIInteraction
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from schedules.categories import ordered_categories
from schedules.models import Category, Schedule, TimeBlock, UserScheduleSettings
from templates_mgr.models import Rule

from tests.revision_client import RevisionClient

CASES = Path(__file__).parent / "fixtures/ai_dialogues/live_cases.json"
NOW = datetime.datetime(2026, 4, 18, 8, tzinfo=datetime.UTC)
FIELDS = ("id", "title", "start_time", "end_time", "category", "origin", "is_completed")
METRICS = (
    "false_additions", "missed_actions", "wrong_fields", "unexpected_existing_changes",
    "excess_asks", "invalid_responses",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def resolve_refs(value, refs):
    if isinstance(value, str) and value.startswith("$"):
        return refs[value[1:]]
    if isinstance(value, list):
        return [resolve_refs(item, refs) for item in value]
    if isinstance(value, dict):
        return {key: resolve_refs(item, refs) for key, item in value.items()}
    return value


def snapshot(schedule):
    rows = list(TimeBlock.objects.filter(schedule=schedule).order_by("id").values(*FIELDS))
    for row in rows:
        for name in ("start_time", "end_time"):
            row[name] = row[name].strftime("%H:%M")
    return rows


def field_errors(expected, observed):
    errors = []
    for name, value in expected.items():
        if name == "title" and isinstance(value, list):
            if observed["title"] not in value:
                errors.append(f"title: expected one of {value!r}, observed {observed['title']!r}")
            continue
        if name == "duration_minutes":
            start = datetime.time.fromisoformat(observed["start_time"])
            end = datetime.time.fromisoformat(observed["end_time"])
            actual = (end.hour - start.hour) * 60 + end.minute - start.minute
        else:
            actual = observed.get(name)
        if actual != value:
            errors.append(f"{name}: expected {value!r}, observed {actual!r}")
    return errors


def score(expected, before, after, status, payload):
    """Score authorized state changes, never recorded-response text or applied flags.

    Only explicitly constrained fields are checked on new blocks. Every existing
    block must survive unchanged except for the named fields of an allowed update.
    A question is excessive only when the fixture authorizes a complete mutation.
    """
    metrics = dict.fromkeys(METRICS, 0)
    errors = []
    old = {row["id"]: row for row in before}
    current = {row["id"]: row for row in after}
    added = [row for row in after if row["id"] not in old]
    intended = expected.get("add", [])
    updates = {row["id"]: row for row in expected.get("update", [])}
    if not updates.keys() <= old.keys():
        raise ValueError("Expected update target is absent from the fixture snapshot")
    metrics["invalid_responses"] = int(status != 200)
    metrics["excess_asks"] = int(
        status == 200 and bool(intended or updates) and bool(payload.get("ask"))
    )
    # Match additions one-to-one: duplicates and wrong titles cannot hide behind applied=True.
    for spec in intended:
        titles = spec["title"] if isinstance(spec["title"], list) else [spec["title"]]
        match = next((row for row in added if row["title"] in titles), None)
        if match is None:
            metrics["missed_actions"] += 1
            errors.append(f"Missing new block: {spec['title']}")
        else:
            added.remove(match)
            mismatches = field_errors(spec, match)
            metrics["wrong_fields"] += len(mismatches)
            errors.extend(f"{spec['title']}: {error}" for error in mismatches)
    metrics["false_additions"] = len(added)
    errors.extend(f"Unauthorized new block: {row['title']}" for row in added)

    for block_id, previous in old.items():
        observed = current.get(block_id)
        permitted = updates.get(block_id, {})
        if observed is None:
            metrics["unexpected_existing_changes"] += 1
            errors.append(f"Deleted existing block: {previous['title']}")
        else:
            extra_fields = {
                name for name in previous
                if previous[name] != observed.get(name) and name not in permitted
            }
            if extra_fields:
                metrics["unexpected_existing_changes"] += 1
                errors.append(f"Unexpected edits to {previous['title']}: {sorted(extra_fields)}")
        if permitted:
            mismatches = field_errors(permitted, observed) if observed else ["target deleted"]
            metrics["wrong_fields"] += len(mismatches)
            metrics["missed_actions"] += int(bool(mismatches))
            errors.extend(f"Update {block_id}: {error}" for error in mismatches)
    return {**metrics, "passed": not any(metrics.values()), "details": errors}


def run_case(case):
    """Use a rolled-back snapshot for each arm, with stable IDs and canonical history.

    The caller must run under pytest-django's disposable database. The runner's
    opt-in test is the only live entrypoint; this function never initializes Django.
    """
    cache.clear()
    with transaction.atomic():
        user = User.objects.create_user(username="r11_evaluation")
        UserScheduleSettings.objects.create(user=user, time_zone="UTC")
        schedule = Schedule.objects.create(user=user, date=NOW.date())
        refs = {}
        for row in case.get("blocks", []):
            block = TimeBlock.objects.create(
                schedule=schedule, **{k: v for k, v in row.items() if k != "ref"}
            )
            if "ref" in row:
                refs[row["ref"]] = block.id
        ordered_categories(user)
        for slug, label in case.get("categories", {}).items():
            Category.objects.filter(user=user, slug=slug).update(label=label)
        for priority, rule in enumerate(case.get("rules", [])):
            Rule.objects.create(user=user, text=rule, priority=priority, is_active=True)
        messages = resolve_refs(case["messages"], refs)
        expected = resolve_refs(case["expected"], refs)
        before = snapshot(schedule)
        client = RevisionClient()
        client.force_login(user)
        response = client.post(
            f"/api/ai/schedules/{NOW.date()}/chat/",
            json.dumps({"messages": messages}), content_type="application/json",
        )
        after = snapshot(schedule)
        payload = response.json()
        interaction = AIInteraction.objects.filter(schedule=schedule).last()
        result = {
            "input": {"messages": messages, "blocks": before},
            "expected": expected, "status": response.status_code, "payload": payload,
            "after": after,
            "parsed_actions": interaction.actions_json if interaction else None,
            "score": score(expected, before, after, response.status_code, payload),
        }
        transaction.set_rollback(True)
    return result


@dataclass
class Budget:
    limit: float
    spent: float = 0
    reserve_per_call: float = 0.03

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in (self.limit, self.reserve_per_call)):
            raise ValueError("Budget and call reserve must be positive finite USD amounts")

    def reserve(self):
        if self.spent + self.reserve_per_call > self.limit:
            raise RuntimeError("R11 spend cap reached before the next provider request")

    def charge(self, usage):
        cost = usage.get("cost") if usage else None
        if not valid_cost(cost):
            # Unknown usage must stop the run, never be silently treated as a free call.
            self.spent += self.reserve_per_call
            raise RuntimeError("Provider omitted a valid billed cost; stopping the comparison")
        self.spent += cost


def summarize(rows):
    summary = {}
    for arm in ("baseline", "implicit_add_off"):
        arm_rows = [row for row in rows if row["arm"] == arm]
        costs = [(row.get("usage") or {}).get("cost") for row in arm_rows]
        known_costs = [cost for cost in costs if valid_cost(cost)]
        summary[arm] = {
            "cases": len(arm_rows),
            "passes": sum(row["score"]["passed"] for row in arm_rows),
            **{name: sum(row["score"][name] for row in arm_rows) for name in METRICS},
            "billed_cost_usd": sum(known_costs),
            "unknown_cost_calls": len(costs) - len(known_costs),
        }
    return summary


def valid_cost(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def prompt_stability(rows):
    """Compare full request hashes within each arm, not JSON wording between responses."""
    keys = [(row["case"], row["arm"]) for row in rows]
    return all(
        len({row["request_sha256"] for row in rows if (row["case"], row["arm"]) == key}) == 1
        for key in Counter(keys)
    )
