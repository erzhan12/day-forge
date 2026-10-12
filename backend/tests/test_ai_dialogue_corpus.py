"""Recorded, synthetic chat dialogues through the real SDK, view and planner seams.

The completions are fixed. These tests measure server behavior for a given model
reply; they cannot establish what a live model would produce with another prompt.
Run with R11_CORPUS_ABLATION=replay_guard_off, category_resolution_off or
implicit_add_off to write a comparable report without changing production code.
"""

import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django.db.models import F
from django.utils import timezone
from schedules.categories import ordered_categories
from schedules.models import Category, Schedule, TimeBlock
from templates_mgr.models import Rule

from tests.revision_client import RevisionClient

CORPUS = Path(__file__).parent / "fixtures" / "ai_dialogues" / "dialogues.json"
MODES = {"baseline", "replay_guard_off", "category_resolution_off", "implicit_add_off"}


def _block_snapshot(schedule):
    return sorted(
        [
            {
                "title": block.title,
                "start_time": block.start_time.strftime("%H:%M"),
                "end_time": block.end_time.strftime("%H:%M"),
                "category": block.category,
            }
            for block in TimeBlock.objects.filter(schedule=schedule)
        ],
        key=lambda row: (row["start_time"], row["end_time"], row["title"]),
    )


def _resolve_refs(value, refs):
    if isinstance(value, str) and value.startswith("$"):
        return refs[value[1:]]
    if isinstance(value, list):
        return [_resolve_refs(item, refs) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_refs(item, refs) for key, item in value.items()}
    return value


def _apply_ablation(monkeypatch, mode):
    if mode == "replay_guard_off":
        monkeypatch.setattr("ai.views.find_replayed_actions", lambda *args, **kwargs: ())
    elif mode == "category_resolution_off":
        monkeypatch.setattr(
            "ai.service.normalize_action_categories",
            lambda actions, *args, **kwargs: SimpleNamespace(
                actions=actions,
                original_indices=tuple(range(len(actions))),
                unresolved=(),
            ),
        )
    elif mode == "implicit_add_off":
        monkeypatch.setattr("ai.service.apply_implicit_add", lambda text, _messages: text)


def _observed_metrics(turn, payload, blocks, before_blocks):
    desired = turn.get("desired", turn["expect"])
    titles = [block["title"] for block in blocks]
    previous_titles = [block["title"] for block in before_blocks]
    forbidden = desired.get("forbidden_titles", turn["expect"].get("forbidden_titles", []))
    return {
        "false_additions": sum(
            max(0, titles.count(title) - previous_titles.count(title)) for title in forbidden
        ),
        "unnecessary_asks": int(desired.get("ask") is None and bool(payload.get("ask"))),
        "missed_apply": int(desired.get("applied") is True and not payload.get("applied")),
    }


@pytest.mark.django_db
def test_recorded_ai_dialogue_corpus(monkeypatch, settings):
    cases = json.loads(CORPUS.read_text(encoding="utf-8"))
    mode = os.environ.get("R11_CORPUS_ABLATION", "baseline")
    assert mode in MODES
    _apply_ablation(monkeypatch, mode)
    settings.LLM_API_KEY = "synthetic-corpus-key"
    report = {
        "mode": mode,
        "cases": [],
        "totals": {
            group: {"false_additions": 0, "unnecessary_asks": 0, "missed_apply": 0}
            for group in ("all", "known_gaps", "regressions")
        },
        "fixed_completions_limit": "Prompt ablations change SDK input, not recorded SDK output.",
    }
    failures = []

    for case in cases:
        assert case["source_tests"] and all(
            (Path(__file__).parent / source).is_file() for source in case["source_tests"]
        )
        user = User.objects.create_user(username=f"corpus_{case['id']}", password="testpass123")
        client = RevisionClient()
        client.force_login(user)
        today = datetime.datetime.fromisoformat(case["now"])
        monkeypatch.setattr(timezone, "now", lambda fixed=today: fixed)
        schedules = {case["date"]: Schedule.objects.create(user=user, date=case["date"])}
        refs = {}
        for row in case["schedule"]:
            block = TimeBlock.objects.create(
                schedule=schedules[case["date"]],
                title=row["title"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                category=row["category"],
            )
            if "ref" in row:
                refs[row["ref"]] = block.id
        foreign_schedule = None
        if case.get("foreign_schedule"):
            foreign = User.objects.create_user(
                username=f"foreign_{case['id']}", password="testpass123"
            )
            foreign_schedule = Schedule.objects.create(user=foreign, date=case["date"])
            for row in case["foreign_schedule"]:
                block = TimeBlock.objects.create(
                    schedule=foreign_schedule,
                    title=row["title"],
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    category=row["category"],
                )
                refs[row["ref"]] = block.id
        for priority, text in enumerate(case["rules"]):
            Rule.objects.create(user=user, text=text, priority=priority, is_active=True)
        ordered_categories(user)
        for slug, label in case["categories"].items():
            Category.objects.filter(user=user, slug=slug).update(label=label)

        transcript = []
        case_result = {"id": case["id"], "turns": []}
        for index, turn in enumerate(case["turns"]):
            if turn.get("reset_transcript"):
                transcript = []
            if index and case["turns"][index - 1]["expect"].get("partial"):
                assert transcript[-1].get("is_ask") is True
                assert transcript[-1].get("applied_add_block_ids")
            day = turn.get("date", case["date"])
            if day not in schedules:
                schedules[day] = Schedule.objects.create(user=user, date=day)
            schedule = schedules[day]
            if turn.get("before", {}).get("bump_revision"):
                Schedule.objects.filter(pk=schedule.pk).update(revision=F("revision") + 1)
            before_refs = {
                ref: _block_snapshot(schedules[case["date"]])
                for ref in turn["expect"].get("unchanged_refs", [])
            }
            before_blocks = _block_snapshot(schedule)
            before_ids = set(
                TimeBlock.objects.filter(schedule=schedule).values_list("id", flat=True)
            )
            raw = turn["recorded_response"]
            raw = _resolve_refs(raw, refs)
            raw = json.dumps(raw, ensure_ascii=False) if isinstance(raw, dict) else raw
            calls = []

            async def complete(**kwargs):
                calls.append(kwargs)
                if raw is None:
                    raise AssertionError("The stale request reached the SDK")
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]
                )

            monkeypatch.setattr(
                "ai.service._get_client",
                lambda: SimpleNamespace(
                    chat=SimpleNamespace(completions=SimpleNamespace(create=complete))
                ),
            )
            transcript.append({"role": "user", "content": turn["user"]})
            body = {"messages": transcript}
            if "expected_revision" in turn:
                body["expected_revision"] = turn["expected_revision"]
            response = client.post(
                f"/api/ai/schedules/{day}/chat/",
                json.dumps(body),
                content_type="application/json",
            )
            payload = response.json()
            blocks = _block_snapshot(schedule)
            expected = turn["expect"]
            metrics = _observed_metrics(turn, payload, blocks, before_blocks)
            group = "known_gaps" if turn.get("known_gap") else "regressions"
            for name, value in metrics.items():
                report["totals"]["all"][name] += value
                report["totals"][group][name] += value
            result = {
                "turn": index + 1,
                "status": response.status_code,
                "applied": payload.get("applied"),
                "ask": payload.get("ask"),
                "blocks": blocks,
                "provider_user": calls[-1]["messages"][-1]["content"] if calls else None,
                "known_gap": turn.get("known_gap"),
                "desired_actions": turn["desired_actions"],
                "outcomes": payload.get("outcomes", []),
                **metrics,
            }
            if foreign_schedule is not None:
                result["foreign_blocks"] = _block_snapshot(foreign_schedule)
            case_result["turns"].append(result)

            if mode == "baseline":
                label = f"{case['id']} turn {index + 1}"
                if calls:
                    sent = calls[-1]["messages"]
                    if [message["role"] for message in sent] != ["system", "user", "user"]:
                        failures.append(f"{label}: SDK message roles changed")
                    context = sent[1]["content"]
                    if (
                        f"Schedule date: {day}" not in context
                        or "Current local time: 08:00" not in context
                    ):
                        failures.append(f"{label}: date or current time absent from SDK context")
                    if any(rule not in context for rule in case["rules"]):
                        failures.append(f"{label}: active rule absent from SDK context")
                    if any(block["title"] not in context for block in before_blocks):
                        failures.append(f"{label}: a current block is absent from SDK context")
                if response.status_code != expected["status"]:
                    failures.append(
                        f"{label}: status {response.status_code} != {expected['status']}"
                    )
                for key in ("applied", "partial"):
                    if key in expected and payload.get(key) != expected[key]:
                        failures.append(f"{label}: {key} {payload.get(key)!r} != {expected[key]!r}")
                if "ask" in expected:
                    ask_ok = (
                        bool(payload.get("ask"))
                        if expected["ask"] == "present"
                        else payload.get("ask") is None
                    )
                    if not ask_ok:
                        failures.append(f"{label}: unexpected ask {payload.get('ask')!r}")
                if "reason_codes" in expected:
                    codes = [outcome.get("reason_code") for outcome in payload.get("outcomes", [])]
                    if codes != expected["reason_codes"]:
                        failures.append(f"{label}: reason codes {codes!r}")
                applied_indices = [
                    outcome["action_index"]
                    for outcome in payload.get("outcomes", [])
                    if outcome["status"] in {"applied", "partial"}
                ]
                if applied_indices != expected["applied_action_indices"]:
                    failures.append(
                        f"{label}: applied action indices {applied_indices!r}"
                    )
                if "blocks" in expected and blocks != expected["blocks"]:
                    failures.append(f"{label}: blocks {blocks!r} != {expected['blocks']!r}")
                if (
                    "foreign_blocks" in expected
                    and result["foreign_blocks"] != expected["foreign_blocks"]
                ):
                    failures.append(f"{label}: foreign blocks changed")
                if "provider_calls" in expected and len(calls) != expected["provider_calls"]:
                    failures.append(f"{label}: provider calls {len(calls)}")
                if (
                    "provider_user" in expected
                    and result["provider_user"] != expected["provider_user"]
                ):
                    failures.append(f"{label}: provider latest user {result['provider_user']!r}")
                if any(block["title"] in expected.get("forbidden_titles", []) for block in blocks):
                    failures.append(f"{label}: forbidden title appeared")
                for ref in expected.get("unchanged_refs", []):
                    block = TimeBlock.objects.get(pk=refs[ref])
                    if {
                        "title": block.title,
                        "start_time": block.start_time.strftime("%H:%M"),
                        "end_time": block.end_time.strftime("%H:%M"),
                        "category": block.category,
                    } not in before_refs[ref]:
                        failures.append(f"{label}: block {ref} changed")

            if turn.get("client_error_after_commit"):
                assistant = {
                    "role": "assistant",
                    "content": "The response was lost.",
                    "is_error": True,
                }
            elif response.status_code == 200:
                assistant_text = payload.get("ask") or payload.get("explanation") or "Done."
                assistant = {"role": "assistant", "content": assistant_text}
                if payload.get("ask") is not None:
                    assistant["is_ask"] = True
                    assistant["applied_add_block_ids"] = sorted(
                        set(
                            TimeBlock.objects.filter(schedule=schedule).values_list("id", flat=True)
                        )
                        - before_ids
                    )
            else:
                assistant = {
                    "role": "assistant",
                    "content": "The request failed.",
                    "is_error": True,
                }
            transcript.append(assistant)

        for day, expected_blocks in case.get("final_days", {}).items():
            if _block_snapshot(schedules[day]) != expected_blocks and mode == "baseline":
                failures.append(f"{case['id']}: final day {day} changed")
        report["cases"].append(case_result)

    report_dir = Path(os.environ.get("R11_CORPUS_REPORT_DIR", "/tmp/day-forge-r11"))
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"corpus-{mode}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert not failures, "\n".join(failures)
