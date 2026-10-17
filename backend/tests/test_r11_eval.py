"""Behavioral checks for the evaluation, with no external provider access."""

import copy
import gzip
import itertools
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from ai import service
from django.contrib.auth.models import User
from django.utils import timezone
from schedules.models import TimeBlock

from tests.r11_eval import CASES, NOW, Budget, digest, prompt_stability, run_case, score, summarize


def block(block_id=1, **changes):
    return {
        "id": block_id, "title": "Gym", "category": "health",
        "start_time": "12:00", "end_time": "12:30",
        "origin": "manual", "is_completed": False, **changes,
    }


def test_automatic_add_does_not_inherit_a_recorded_question_or_invented_time():
    expected = {"add": [{"title": "Gym", "duration_minutes": 30}]}
    observed = block(start_time="15:00", end_time="15:30", category="other")
    assert score(expected, [], [observed], 200, {"applied": True})["passed"]


def test_allowed_suffix_spacing_is_not_a_false_addition_but_an_old_title_is():
    expected = {"add": [{"title": ["Gym[2]", "Gym [2]"], "duration_minutes": 30}]}
    assert score(expected, [], [block(title="Gym [2]")], 200, {})["passed"]
    result = score(expected, [], [block(title="Momentum[2]")], 200, {})
    assert result["false_additions"] == 1
    assert result["missed_actions"] == 1


def test_unquoted_activity_duration_in_title_is_not_an_unauthorized_activity():
    expected = {"add": [{
        "title": ["Reading emails", "Reading emails 30 min"], "duration_minutes": 30,
    }]}
    observed = block(title="Reading emails 30 min")
    assert score(expected, [], [observed], 200, {})["passed"]
    wrong_duration = {**observed, "end_time": "12:45"}
    result = score(expected, [], [wrong_duration], 200, {})
    assert result["wrong_fields"] == 1
    assert result["false_additions"] == 0


@pytest.mark.parametrize(("after", "metric", "value"), [
    ([block(), block(2)], "false_additions", 1),
    ([block(category="work")], "wrong_fields", 1),
    ([block(end_time="12:45")], "wrong_fields", 1),
    ([block(title="Lunch")], "missed_actions", 1),
    ([], "missed_actions", 1),
])
def test_score_checks_result_instead_of_applied_flag(after, metric, value):
    result = score(
        {"add": [{"title": "Gym", "category": "health", "duration_minutes": 30}]},
        [], after, 200, {"applied": True},
    )
    assert not result["passed"]
    assert result[metric] == value


def test_refusal_forbids_additions_and_preserves_existing_blocks():
    before = [block()]
    result = score({}, before, [block(category="work"), block(2)], 200, {})
    assert result["false_additions"] == 1
    assert result["unexpected_existing_changes"] == 1
    assert not result["passed"]


def test_partial_followup_cannot_reapply_or_edit_accepted_siblings():
    expected = {"add": [{"title": "Lunch"}]}
    result = score(expected, [block()], [block(), block(2, title="Lunch"), block(3)], 200, {})
    assert result["false_additions"] == 1
    assert not result["passed"]


def test_wrong_target_or_extra_update_field_fails():
    before = [block(), block(2, title="Lunch")]
    result = score(
        {"update": [{"id": 1, "category": "personal"}]},
        before, [block(title="Renamed"), block(2, title="Lunch", category="personal")], 200, {},
    )
    assert result["missed_actions"] == 1
    assert result["wrong_fields"] == 1
    assert result["unexpected_existing_changes"] == 2


def test_invalid_expected_update_cannot_pass_silently():
    with pytest.raises(ValueError, match="fixture snapshot"):
        score({"update": [{"id": 99, "category": "work"}]}, [], [], 200, {})


def test_error_is_not_a_successful_cancellation_and_question_needs_intent():
    assert not score({}, [], [], 502, {})["passed"]
    assert score({}, [], [], 200, {"ask": "Anything else?"})["excess_asks"] == 0
    expected = {"add": [{"title": "Gym"}]}
    result = score(expected, [], [], 200, {"ask": "When?"})
    assert result["excess_asks"] == 1
    assert result["missed_actions"] == 1


def test_prompt_hashes_detect_drift_not_different_json_wording():
    rows = [
        {"case": "c", "arm": "a", "request_sha256": digest({"id": 1})} for _ in range(2)
    ]
    assert prompt_stability(rows)
    changed = copy.deepcopy(rows)
    changed[-1]["request_sha256"] = digest({"id": 2})
    assert not prompt_stability(changed)


@pytest.mark.parametrize("limit", [-1, 0, float("nan"), float("inf")])
def test_budget_rejects_invalid_limits(limit):
    with pytest.raises(ValueError):
        Budget(limit)


def test_budget_stops_before_overspending_and_unknown_usage_is_not_free():
    budget = Budget(0.05)
    budget.reserve()
    budget.charge({"cost": 0.025})
    with pytest.raises(RuntimeError, match="spend cap"):
        budget.reserve()
    with pytest.raises(RuntimeError, match="billed cost"):
        budget.charge(None)
    assert budget.spent == pytest.approx(0.055)


@pytest.mark.parametrize("usage", [None, {}, {"cost": None}, {"cost": float("nan")}])
def test_unavailable_usage_can_be_saved_without_claiming_a_free_provider_call(usage):
    budget = Budget(0.1)
    with pytest.raises(RuntimeError, match="billed cost"):
        budget.charge(usage)
    row = {"arm": "baseline", "score": score({}, [], [], 502, {}), "usage": usage}
    result = summarize([row])["baseline"]
    assert result["unknown_cost_calls"] == 1
    assert budget.spent > result["billed_cost_usd"]


@pytest.mark.django_db
def test_all_canonical_states_are_stable_isolated_and_reach_the_real_planner(monkeypatch, settings):
    """All fixture outcomes and IDs stay independent of request order and repetitions."""
    settings.LLM_API_KEY = "evaluation-test-key"
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    cases = json.loads(CASES.read_text())
    assert len({case["id"] for case in cases}) == len(cases)
    original = copy.deepcopy(cases)
    implicit_add = service.apply_implicit_add
    calls = []
    for repetition, arm in itertools.product(range(2), ("baseline", "implicit_add_off")):
        monkeypatch.setattr(
            service, "apply_implicit_add",
            implicit_add if arm == "baseline" else lambda text, _messages: text,
        )
        for case in cases:

            async def complete(**kwargs):
                calls.append((case["id"], arm, repetition, copy.deepcopy(kwargs)))
                actions = []
                for spec in case["expected"].get("add", []):
                    title = spec["title"][0] if isinstance(spec["title"], list) else spec["title"]
                    actions.append({"type": "add", "category": "other", **spec, "title": title})
                for spec in case["expected"].get("update", []):
                    # Each snapshot creates its report as the first block, so parse the context.
                    target = int(re.search(r"id=(\d+)", kwargs["messages"][1]["content"])[1])
                    actions.append({"type": "update", "task_id": target, "changes": {
                        key: value for key, value in spec.items() if key != "id"
                    }})
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content=json.dumps({"actions": actions, "explanation": "Done.", "ask": None})
                ))])

            monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=complete))
            ))
            result = run_case(case)
            assert result["score"]["passed"], (case["id"], result)
            assert not User.objects.filter(username="r11_evaluation").exists()
            assert not TimeBlock.objects.exists()
    assert cases == original
    for case in cases:
        for arm in ("baseline", "implicit_add_off"):
            assert len({
                digest(request) for case_id, variant, _, request in calls
                if case_id == case["id"] and variant == arm
            }) == 1
        paired = [request for case_id, _, run, request in calls
                  if case_id == case["id"] and run == 0]
        # Within a pair, only the latest user message can change. State/history is shared.
        assert paired[0]["messages"][:-1] == paired[1]["messages"][:-1]


@pytest.mark.django_db
def test_saved_live_responses_replay_through_the_view_and_planner_without_network(
    monkeypatch, settings,
):
    evidence = Path(__file__).resolve().parents[2] / (
        "docs/evaluations/r11-live-v2-2026-10-17.json.gz"
    )
    report = json.loads(gzip.decompress(evidence.read_bytes()))
    cases = json.loads(CASES.read_text())
    assert digest(cases) == report["fixture_sha256"]
    case_map = {case["id"]: case for case in cases}
    settings.LLM_API_KEY = "captured-evaluation-test-key"
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    original = service.apply_implicit_add
    for captured in report["rows"]:
        monkeypatch.setattr(
            service, "apply_implicit_add",
            original if captured["arm"] == "baseline" else lambda text, _messages: text,
        )

        async def complete(**kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=captured["raw_response"],
            ))])

        monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=complete))
        ))
        observed = run_case(case_map[captured["case"]])
        label = (captured["case"], captured["arm"], captured["repetition"])
        assert observed["input"] == captured["input"], label
        assert observed["score"] == captured["score"], label
        assert observed["after"] == captured["after"], label
