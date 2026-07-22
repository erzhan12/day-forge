import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from habitica_sync import service
from habitica_sync.models import HabiticaAccount

FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _habitica_settings(settings):
    settings.HABITICA_ENCRYPTION_KEY = FERNET_KEY
    settings.HABITICA_CLIENT_ID = "maintainer-user"
    settings.HABITICA_BASE_URL = "https://habitica.test/api/v3"
    settings.HABITICA_REQUEST_TIMEOUT = 5
    settings.HABITICA_CACHE_TTL_SECONDS = 300


def _response(status_code=200, data=None, success=True):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = {"success": success, "data": [] if data is None else data}
    return resp


@pytest.fixture
def account(db):
    user = User.objects.create_user(username="habitica-user", password="x")
    acc = HabiticaAccount(user=user, api_user_id="habitica-id")
    acc.set_token("habitica-token")
    acc.save()
    return acc


def test_headers_include_habitica_auth_and_x_client():
    headers = service._headers("user-id", "secret-token")
    assert headers["x-api-user"] == "user-id"
    assert headers["x-api-key"] == "secret-token"
    assert headers["x-client"] == "maintainer-user-DayForge"
    assert headers["Content-Type"] == "application/json"


def test_fetch_filters_todos_and_due_dailies_for_client_today(account):
    target = datetime.date(2026, 7, 22)
    todos = [
        {"id": "today", "text": "Today", "date": "2026-07-22", "completed": False},
        {"id": "overdue", "text": "Overdue", "date": "2026-07-21", "completed": False},
        {"id": "undated", "text": "Undated", "date": None, "completed": False},
        {"id": "done", "text": "Done", "date": "2026-07-22", "completed": True},
        {"id": "future", "text": "Future", "date": "2026-07-23", "completed": False},
    ]
    dailies = [
        {"id": "daily-due", "text": "Due daily", "isDue": True, "completed": False},
        {"id": "daily-later", "text": "Not due", "isDue": False, "completed": False},
    ]

    with patch("habitica_sync.service.django_tz.localdate", return_value=target):
        with patch("habitica_sync.service.requests.get") as get:
            get.side_effect = [_response(data=todos), _response(data=dailies)]
            tasks = service.fetch_tasks_for_date(account, target)

    assert [(t.id, t.type) for t in tasks] == [
        ("daily-due", "daily"),
        ("overdue", "todo"),
        ("today", "todo"),
        ("undated", "todo"),
    ]
    assert get.call_args_list[1].kwargs["params"] == {"type": "dailys"}


def test_future_exact_date_skips_dailies_and_undated_overdue(account):
    target = datetime.date(2026, 7, 23)
    project_today = datetime.date(2026, 7, 22)
    todos = [
        {"id": "target", "text": "Target", "date": "2026-07-23", "completed": False},
        {"id": "overdue", "text": "Overdue", "date": "2026-07-22", "completed": False},
        {"id": "undated", "text": "Undated", "date": None, "completed": False},
    ]

    with patch("habitica_sync.service.django_tz.localdate", return_value=project_today):
        with patch("habitica_sync.service.requests.get") as get:
            get.return_value = _response(data=todos)
            tasks = service.fetch_tasks_for_date(account, target)

    assert [t.id for t in tasks] == ["target"]
    assert get.call_count == 1
    assert get.call_args.kwargs["params"] == {"type": "todos"}


def test_client_today_carryover_uses_target_date_boundary_for_todos_and_dailies(account):
    project_today = datetime.date(2026, 7, 22)
    browser_today = datetime.date(2026, 7, 23)
    todos = [
        {
            "id": "server-day-overdue",
            "text": "Server day",
            "date": "2026-07-22",
            "completed": False,
        }
    ]
    dailies = [
        {"id": "daily-due", "text": "Due daily", "isDue": True, "completed": False}
    ]

    with patch("habitica_sync.service.django_tz.localdate", return_value=project_today):
        with patch("habitica_sync.service.requests.get") as get:
            get.side_effect = [_response(data=todos), _response(data=dailies)]
            tasks = service.fetch_tasks_for_date(
                account,
                browser_today,
                include_overdue_carryover=True,
            )

    assert [t.id for t in tasks] == ["daily-due", "server-day-overdue"]


def test_success_false_or_non_list_data_raises_provider(account):
    with patch("habitica_sync.service.requests.get") as get:
        get.return_value = _response(success=False)
        with pytest.raises(service.HabiticaProviderError):
            service.fetch_tasks_for_date(account, datetime.date(2026, 7, 22))

    with patch("habitica_sync.service.requests.get") as get:
        get.return_value = _response(data={"not": "a list"})
        with pytest.raises(service.HabiticaProviderError):
            service.fetch_tasks_for_date(account, datetime.date(2026, 7, 22))


def test_complete_task_scores_up_with_empty_json_body(account):
    with patch("habitica_sync.service.requests.post") as post:
        post.return_value = _response(data={"delta": 1})
        service.complete_task(account, "daily-id")

    _, kwargs = post.call_args
    assert post.call_args.args[0] == "https://habitica.test/api/v3/tasks/daily-id/score/up"
    assert kwargs["json"] == {}
    assert kwargs["headers"]["x-client"] == "maintainer-user-DayForge"


def test_timeout_maps_to_typed_error(account):
    with patch("habitica_sync.service.requests.get") as get:
        get.side_effect = requests.Timeout("slow")
        with pytest.raises(service.HabiticaTimeoutError):
            service.fetch_tasks_for_date(account, datetime.date(2026, 7, 22))


def test_every_outbound_call_disables_redirects(account):
    """No call carrying ``x-api-key`` may follow a redirect.

    ``requests`` strips ``Authorization`` when a redirect crosses hosts, but
    Habitica authenticates with the CUSTOM ``x-api-key`` header, which is
    forwarded verbatim instead — so the token would leak to the redirect
    target. Asserting per-call-site individually is what let this regress
    once already (only ``verify_credentials`` was covered), so this sweeps
    ALL outbound calls: a newly added one is caught the moment it appears.
    """
    with (
        patch("habitica_sync.service.requests.get") as get,
        patch("habitica_sync.service.requests.post") as post,
    ):
        get.return_value = _response(data=[])
        post.return_value = _response(data={"delta": 1})

        service.verify_credentials("user-id", "token")
        service.fetch_tasks_for_date(account, datetime.date(2026, 7, 22))
        service.complete_task(account, "task-id")

        calls = list(get.call_args_list) + list(post.call_args_list)

    assert len(calls) >= 3, "expected verify + fetch + complete to have run"
    for call in calls:
        assert call.kwargs.get("allow_redirects") is False, (
            f"outbound call {call.args[0]!r} may follow redirects and would "
            f"forward the x-api-key token to the redirect target"
        )
