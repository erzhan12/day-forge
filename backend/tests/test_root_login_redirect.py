"""Root + login redirects use the user's persisted timezone for "today".

Both authenticated paths (`root_redirect`, the POST-auth `login_view`
redirect) must resolve "today" from `UserScheduleSettings.time_zone`, not
the host/UTC clock. Time is frozen by patching `schedules.window.timezone.now`
(the module every changed path resolves "now" through).

The `schedule` route is `path("schedule/<str:date>/", …)`, so the redirect
target is `/schedule/<date>/`.
"""
import datetime

import pytest
from django.contrib.auth.models import User
from schedules import window
from schedules.models import UserScheduleSettings


def _freeze(monkeypatch, fixed_utc):
    monkeypatch.setattr(window.timezone, "now", lambda: fixed_utc)


@pytest.mark.django_db
class TestRootLoginRedirect:
    def test_root_redirect_uses_user_local_date_east_of_utc(self, auth_client, user, monkeypatch):
        UserScheduleSettings.objects.create(user=user, time_zone="Asia/Almaty")
        _freeze(monkeypatch, datetime.datetime(2026, 5, 3, 20, 0, tzinfo=datetime.UTC))

        resp = auth_client.get("/", follow=False)
        assert resp.status_code == 302
        assert resp.url == "/schedule/2026-05-04/"

    def test_root_redirect_west_of_utc(self, auth_client, user, monkeypatch):
        UserScheduleSettings.objects.create(user=user, time_zone="America/Los_Angeles")
        _freeze(monkeypatch, datetime.datetime(2026, 5, 4, 3, 0, tzinfo=datetime.UTC))

        resp = auth_client.get("/", follow=False)
        assert resp.status_code == 302
        assert resp.url == "/schedule/2026-05-03/"

    def test_login_post_redirects_to_user_local_date(self, client, monkeypatch):
        user = User.objects.create_user(username="testuser", password="testpass123")
        UserScheduleSettings.objects.create(user=user, time_zone="Asia/Almaty")
        _freeze(monkeypatch, datetime.datetime(2026, 5, 3, 20, 0, tzinfo=datetime.UTC))

        resp = client.post(
            "/accounts/login/",
            data={"username": "testuser", "password": "testpass123"},
            follow=False,
        )
        assert resp.status_code == 302
        assert resp.url == "/schedule/2026-05-04/"

    def test_login_get_unaffected(self, client):
        # Unauthenticated GET renders Login (200) and never looks up a
        # settings row — no crash absent one.
        resp = client.get("/accounts/login/")
        assert resp.status_code == 200

    def test_root_redirect_anonymous_does_not_resolve_user_settings(self, client):
        # `root_redirect` is undecorated (no login_required / no
        # LoginRequiredMiddleware), so an anonymous request reaches it.
        # It must NOT resolve per-user settings for AnonymousUser (which
        # has no DB row → TypeError on get_or_create); it stays on the
        # host clock and redirects, exactly as before this feature.
        resp = client.get("/", follow=False)
        assert resp.status_code == 302
        assert resp.url.startswith("/schedule/")
