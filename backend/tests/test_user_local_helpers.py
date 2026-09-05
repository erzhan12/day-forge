"""Tests for the user-local now/date helpers in ``schedules.window``.

DB-backed (needs ``User`` + ``UserScheduleSettings`` rows), so this is a
dedicated file rather than ``test_schedule_window.py`` (which declares a
strict no-ORM contract). Time is frozen by patching ``window.timezone.now``
to a fixed aware-UTC instant, so the real ``timezone.localtime(now, tz)``
conversion is exercised end-to-end.
"""
import datetime

import pytest
from django.contrib.auth.models import User
from schedules import window
from schedules.models import UserScheduleSettings


def _freeze(monkeypatch, fixed_utc):
    monkeypatch.setattr(window.timezone, "now", lambda: fixed_utc)


@pytest.mark.django_db
class TestUserLocalHelpers:
    def test_user_local_now_uses_persisted_zone(self, monkeypatch):
        user = User.objects.create_user(username="almaty", password="pw")
        UserScheduleSettings.objects.create(user=user, time_zone="Asia/Almaty")
        _freeze(monkeypatch, datetime.datetime(2026, 5, 3, 20, 0, tzinfo=datetime.UTC))

        now_local = window.user_local_now(user)
        assert now_local.date() == datetime.date(2026, 5, 4)
        assert now_local.hour == 1

    def test_user_local_date_west_of_utc(self, monkeypatch):
        user = User.objects.create_user(username="la", password="pw")
        UserScheduleSettings.objects.create(user=user, time_zone="America/Los_Angeles")
        _freeze(monkeypatch, datetime.datetime(2026, 5, 4, 3, 0, tzinfo=datetime.UTC))

        assert window.user_local_date(user) == datetime.date(2026, 5, 3)

    def test_user_local_now_falls_back_to_utc_on_corrupt_setting(self, monkeypatch):
        user = User.objects.create_user(username="corrupt", password="pw")
        # Bypass model validation to persist an invalid IANA zone.
        UserScheduleSettings.objects.create(user=user)
        UserScheduleSettings.objects.filter(user=user).update(time_zone="Not/AZone")
        _freeze(monkeypatch, datetime.datetime(2026, 5, 3, 23, 30, tzinfo=datetime.UTC))

        assert window.user_local_date(user) == datetime.date(2026, 5, 3)

    def test_user_local_now_defaults_utc_when_no_settings_row(self, monkeypatch):
        user = User.objects.create_user(username="norow", password="pw")
        _freeze(monkeypatch, datetime.datetime(2026, 5, 3, 23, 30, tzinfo=datetime.UTC))

        assert window.user_local_date(user) == datetime.date(2026, 5, 3)
