"""WHOOP day Markdown formatter (feature 0107, step 10)."""

import copy
import datetime
import json
import zoneinfo
from pathlib import Path

import pytest
from whoop_sync.day import WhoopDay
from whoop_sync.formatting import format_whoop_day

SYNTHETIC = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "whoop" / "synthetic_2026-11-23.json")
    .read_text()
)
ALMATY = zoneinfo.ZoneInfo("Asia/Almaty")
NOT_SCORED = [("PENDING_SCORE", "pending"), ("UNSCORABLE", "unscorable")]

# The plan's MVP example (docs/features/0107_PLAN.md), byte for byte.
PLAN_EXAMPLE = (
    "## whoop · 2026-11-23\n"
    "recovery: 73% · RHR 56 · HRV 31.1 · SpO2 95%\n"
    "sleep: 21:49–06:57 · asleep 7:43 / need 8:16 · deep 1:16 · REM 1:18 · eff 97%"
    " · disturbances 9\n"
    "strain (prev day): 16.4 · workouts: HIIT 15.2, walk 4.6\n"
)


def _day(**overrides):
    data = copy.deepcopy(SYNTHETIC)
    fields = dict(
        date=datetime.date(2026, 11, 23),
        sleep=next(s for s in data["sleeps"] if s["id"] == "sleep-main"),
        recovery=data["recovery"],
        previous_cycle=data["cycles_before_sleep"][1],
        workouts=[w for w in reversed(data["workouts"]) if w["id"] != "w-before"],
        tz=ALMATY,
    )
    fields.update(overrides)
    return WhoopDay(**fields)


def test_matches_the_plan_example():
    assert format_whoop_day(_day()) == PLAN_EXAMPLE


def test_plan_document_still_shows_the_same_example():
    plan = (Path(__file__).resolve().parents[2] / "docs" / "features" / "0107_PLAN.md").read_text()
    assert "```\n" + PLAN_EXAMPLE + "```" in plan


def test_bed_and_wake_use_the_records_own_offset():
    sleep = copy.deepcopy(_day().sleep)
    sleep["timezone_offset"] = "+03:00"
    text = format_whoop_day(_day(sleep=sleep))
    assert "sleep: 19:49–04:57" in text


def test_missing_offset_falls_back_to_the_users_zone():
    sleep = copy.deepcopy(_day().sleep)
    del sleep["timezone_offset"]
    assert "sleep: 21:49–06:57" in format_whoop_day(_day(sleep=sleep))


class TestPartialStates:
    def test_no_sleep(self):
        text = format_whoop_day(_day(sleep=None, recovery=None, previous_cycle=None, workouts=[]))
        assert text == (
            "## whoop · 2026-11-23\n"
            "recovery: none recorded\n"
            "sleep: none recorded\n"
            "strain (prev day): none recorded · workouts: none\n"
        )

    @pytest.mark.parametrize("state,word", NOT_SCORED)
    def test_recovery_not_scored(self, state, word):
        recovery = {"cycle_id": 1002, "score_state": state}
        assert f"recovery: {word}\n" in format_whoop_day(_day(recovery=recovery))

    @pytest.mark.parametrize("state,word", NOT_SCORED)
    def test_sleep_not_scored_keeps_its_times(self, state, word):
        sleep = {**_day().sleep, "score_state": state}
        sleep.pop("score")
        assert f"sleep: 21:49–06:57 · {word}\n" in format_whoop_day(_day(sleep=sleep))

    def test_no_recovery_record(self):
        assert "recovery: none recorded\n" in format_whoop_day(_day(recovery=None))

    def test_missing_spo2_is_omitted(self):
        recovery = copy.deepcopy(_day().recovery)
        recovery["score"]["spo2_percentage"] = None
        assert "recovery: 73% · RHR 56 · HRV 31.1\n" in format_whoop_day(_day(recovery=recovery))

    def test_previous_cycle_pending(self):
        cycle = {**_day().previous_cycle, "score_state": "PENDING_SCORE"}
        assert "strain (prev day): pending · " in format_whoop_day(_day(previous_cycle=cycle))

    def test_no_workouts(self):
        assert "· workouts: none\n" in format_whoop_day(_day(workouts=[]))

    def test_unscored_workout_shows_its_name_only(self):
        workouts = [{"sport_name": "HIIT", "score_state": "PENDING_SCORE"}]
        assert "workouts: HIIT\n" in format_whoop_day(_day(workouts=workouts))

    def test_nap_credit_reduces_need(self):
        sleep = copy.deepcopy(_day().sleep)
        sleep["score"]["sleep_needed"]["need_from_recent_nap_milli"] = -960000
        assert "need 8:00" in format_whoop_day(_day(sleep=sleep))
