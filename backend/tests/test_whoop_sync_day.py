"""Mapping a calendar date to WHOOP records (feature 0107, step 9).

Synthetic data only; an optional real-day fixture (gitignored, see
``backend/tests/fixtures/whoop/README.md``) is checked when present.
"""

import copy
import datetime
import json
import zoneinfo
from pathlib import Path

import pytest
from whoop_sync import day as whoop_day
from whoop_sync import service

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "whoop"
SYNTHETIC = json.loads((FIXTURES / "synthetic_2026-11-23.json").read_text())
ALMATY = zoneinfo.ZoneInfo("Asia/Almaty")
UTC = datetime.UTC
D = datetime.date(2026, 11, 23)


class FakeWhoop:
    """Stands in for the service fetchers and records every call."""

    def __init__(self, data):
        self.data = copy.deepcopy(data)
        self.calls = []

    def install(self, monkeypatch):
        monkeypatch.setattr(service, "fetch_sleeps", self.fetch_sleeps)
        monkeypatch.setattr(service, "fetch_recovery", self.fetch_recovery)
        monkeypatch.setattr(service, "fetch_cycles_ending_by", self.fetch_cycles_ending_by)
        monkeypatch.setattr(service, "fetch_workouts", self.fetch_workouts)
        return self

    def fetch_sleeps(self, account, start, end):
        self.calls.append(("sleeps", start, end))
        return self.data["sleeps"]

    def fetch_recovery(self, account, cycle_id):
        self.calls.append(("recovery", cycle_id))
        return self.data["recovery"]

    def fetch_cycles_ending_by(self, account, end, *, limit):
        self.calls.append(("cycles", end, limit))
        return self.data["cycles_before_sleep"]

    def fetch_workouts(self, account, start, end):
        self.calls.append(("workouts", start, end))
        return self.data["workouts"]


@pytest.fixture
def fake(monkeypatch):
    return FakeWhoop(SYNTHETIC).install(monkeypatch)


def _utc(text):
    return datetime.datetime.fromisoformat(text).astimezone(UTC)


class TestSleepWindow:
    def test_queries_noon_to_noon_in_the_users_zone(self, fake):
        whoop_day.load_day(object(), D, ALMATY)
        kind, start, end = fake.calls[0]
        assert kind == "sleeps"
        assert start == datetime.datetime(2026, 11, 22, 12, 0, tzinfo=ALMATY)
        assert end == datetime.datetime(2026, 11, 23, 12, 0, tzinfo=ALMATY)

    def test_takes_the_longest_non_nap_sleep(self, fake):
        result = whoop_day.load_day(object(), D, ALMATY)
        assert result.sleep["id"] == "sleep-main"

    def test_only_naps_means_no_sleep_and_no_further_calls(self, fake):
        fake.data["sleeps"] = [s for s in fake.data["sleeps"] if s["nap"]]
        result = whoop_day.load_day(object(), D, ALMATY)
        assert result.sleep is None
        assert result.recovery is None
        assert result.previous_cycle is None
        assert result.workouts == []
        assert [c[0] for c in fake.calls] == ["sleeps"]


class TestRecoveryAndPreviousDay:
    def test_recovery_comes_from_the_sleeps_cycle(self, fake):
        result = whoop_day.load_day(object(), D, ALMATY)
        assert ("recovery", 1002) in fake.calls
        assert result.recovery["score"]["recovery_score"] == 73

    def test_previous_cycle_is_the_one_ending_at_sleep_start(self, fake):
        result = whoop_day.load_day(object(), D, ALMATY)
        assert ("cycles", _utc("2026-11-22T16:49:00Z"), 2) in fake.calls
        assert result.previous_cycle["id"] == 1001

    def test_workouts_are_the_previous_cycles_sorted_oldest_first(self, fake):
        result = whoop_day.load_day(object(), D, ALMATY)
        window = (_utc("2026-11-21T17:30:00Z"), _utc("2026-11-22T16:49:00Z"))
        assert ("workouts", *window) in fake.calls
        assert [w["id"] for w in result.workouts] == ["w-hiit", "w-walk"]

    def test_no_previous_cycle_means_no_strain_and_no_workouts(self, fake):
        fake.data["cycles_before_sleep"] = [fake.data["cycles_before_sleep"][0]]
        result = whoop_day.load_day(object(), D, ALMATY)
        assert result.previous_cycle is None
        assert result.workouts == []
        assert not [c for c in fake.calls if c[0] == "workouts"]

    def test_missing_recovery_is_none(self, fake):
        fake.data["recovery"] = None
        assert whoop_day.load_day(object(), D, ALMATY).recovery is None


class TestMalformedRecords:
    @pytest.mark.parametrize("field,value", [
        ("start", "yesterday"), ("end", None), ("cycle_id", "abc"), ("nap", "no"),
    ])
    def test_bad_sleep_fields_are_provider_errors(self, fake, field, value):
        for sleep in fake.data["sleeps"]:
            sleep[field] = value
        with pytest.raises(service.WhoopProviderError):
            whoop_day.load_day(object(), D, ALMATY)

    def test_bad_cycle_timestamp_is_a_provider_error(self, fake):
        fake.data["cycles_before_sleep"][1]["start"] = 5
        with pytest.raises(service.WhoopProviderError):
            whoop_day.load_day(object(), D, ALMATY)


REAL_FIXTURES = sorted(FIXTURES.glob("real_*.json"))


@pytest.mark.skipif(not REAL_FIXTURES, reason="no local real-day WHOOP fixture (gitignored)")
@pytest.mark.parametrize("path", REAL_FIXTURES, ids=[p.name for p in REAL_FIXTURES])
def test_real_day_fixture_maps(monkeypatch, path):
    data = json.loads(path.read_text())
    FakeWhoop(data).install(monkeypatch)
    result = whoop_day.load_day(object(), datetime.date.fromisoformat(data["date"]), ALMATY)
    assert result.sleep is not None
    expected = data.get("expected_markdown")
    if expected:
        from whoop_sync.formatting import format_whoop_day

        assert format_whoop_day(result) == expected
