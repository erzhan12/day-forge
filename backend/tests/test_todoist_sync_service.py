"""Service-layer tests for ``todoist_sync.service``.

Mock the ``requests`` HTTP layer at the boundary (never a live Todoist
call) so tests are deterministic and offline. Cover ``verify_credentials``
success + each typed-error mapping, the date→filter query selection, the
priority mapping, ``due`` normalisation, pagination, the deterministic
null-safe sort, and the no-token-in-logs check.

Mirrors ``test_calendar_sync_service.py`` structure/fixtures/style.
"""

import datetime
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from todoist_sync import service
from todoist_sync.models import TodoistAccount

FERNET_KEY = Fernet.generate_key().decode()

TOKEN_PLAIN = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def _fernet_key(settings):
    settings.TODOIST_ENCRYPTION_KEY = FERNET_KEY
    settings.TODOIST_BASE_URL = "https://api.todoist.com/api/v1"
    settings.TODOIST_REQUEST_TIMEOUT = 5
    settings.TODOIST_CACHE_TTL_SECONDS = 300


def _raw_task(
    *,
    id="t1",
    content="A task",
    priority=1,
    due=None,
):
    """Build a raw Todoist task dict as the filter endpoint returns it.

    The raw field for the title is ``content`` (the normaliser maps it to
    ``title`` on the wire); ``due`` is either ``None`` or a dict with a
    polymorphic ``date`` key.
    """
    return {"id": id, "content": content, "priority": priority, "due": due}


def _fake_response(*, status_code=200, json_payload=None):
    """Build a fake ``requests.Response``-like object."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_payload if json_payload is not None else {}
    return resp


def _fake_page(results, next_cursor=None):
    """One page of the cursor-paginated ``{results, next_cursor}`` envelope."""
    return {"results": results, "next_cursor": next_cursor}


@pytest.fixture
def account(db):
    user = User.objects.create_user(username="todoist-user", password="x")
    acc = TodoistAccount(user=user)
    acc.set_token(TOKEN_PLAIN)
    acc.save()
    return acc


@pytest.fixture
def patched_get():
    """Patch ``requests.get`` used by ``service``."""
    with patch("todoist_sync.service.requests.get") as mock_get:
        yield mock_get


class TestVerifyCredentials:
    def test_success_returns_none(self, patched_get):
        patched_get.return_value = _fake_response(status_code=200)
        assert service.verify_credentials(TOKEN_PLAIN) is None

    def test_401_raises_auth(self, patched_get):
        patched_get.return_value = _fake_response(status_code=401)
        with pytest.raises(service.TodoistAuthError):
            service.verify_credentials(TOKEN_PLAIN)

    def test_403_raises_auth(self, patched_get):
        patched_get.return_value = _fake_response(status_code=403)
        with pytest.raises(service.TodoistAuthError):
            service.verify_credentials(TOKEN_PLAIN)

    def test_timeout_raises_timeout(self, patched_get):
        patched_get.side_effect = requests.Timeout("timed out")
        with pytest.raises(service.TodoistTimeoutError):
            service.verify_credentials(TOKEN_PLAIN)

    def test_500_raises_provider(self, patched_get):
        patched_get.return_value = _fake_response(status_code=500)
        with pytest.raises(service.TodoistProviderError):
            service.verify_credentials(TOKEN_PLAIN)

    def test_connection_error_raises_provider(self, patched_get):
        patched_get.side_effect = requests.ConnectionError("no route")
        with pytest.raises(service.TodoistProviderError):
            service.verify_credentials(TOKEN_PLAIN)


class TestFilterQuerySelection:
    """The date→filter algorithm: assert the EXACT generated ``query``
    string passed to the filter endpoint for today vs. a past/future date.
    The today branch is pinned by mocking ``timezone.localdate()`` so the
    ``selected_date == today`` comparison is deterministic.
    """

    def _query_for(self, patched_get, target_date):
        patched_get.return_value = _fake_response(
            json_payload=_fake_page([], next_cursor=None)
        )
        service.fetch_tasks_for_date(_make_account_stub(), target_date)
        # The first positional/keyword call carries the query param.
        _, kwargs = patched_get.call_args
        return kwargs["params"]["query"]

    def test_today_uses_date_overdue(self, patched_get):
        today = datetime.date(2026, 6, 17)
        with patch(
            "todoist_sync.service.django_tz.localdate", return_value=today
        ):
            assert self._query_for(patched_get, today) == "2026-06-17 | overdue"

    def test_carry_overdue_flag_when_not_project_today(self, patched_get):
        today = datetime.date(2026, 6, 17)
        browser_today = datetime.date(2026, 6, 18)
        with patch(
            "todoist_sync.service.django_tz.localdate", return_value=today
        ):
            patched_get.return_value = _fake_response(
                json_payload=_fake_page([], next_cursor=None)
            )
            service.fetch_tasks_for_date(
                _make_account_stub(),
                browser_today,
                include_overdue_carryover=True,
            )
        _, kwargs = patched_get.call_args
        assert kwargs["params"]["query"] == "2026-06-18 | overdue"

    def test_past_date_uses_literal_date_token(self, patched_get):
        today = datetime.date(2026, 6, 17)
        past = datetime.date(2025, 2, 12)
        with patch(
            "todoist_sync.service.django_tz.localdate", return_value=today
        ):
            assert self._query_for(patched_get, past) == "2025-02-12"

    def test_future_date_uses_literal_date_token(self, patched_get):
        today = datetime.date(2026, 6, 17)
        future = datetime.date(2027, 12, 31)
        with patch(
            "todoist_sync.service.django_tz.localdate", return_value=today
        ):
            assert self._query_for(patched_get, future) == "2027-12-31"

    def test_filter_uses_max_page_limit(self, patched_get):
        today = datetime.date(2026, 6, 17)
        with patch(
            "todoist_sync.service.django_tz.localdate", return_value=today
        ):
            patched_get.return_value = _fake_response(
                json_payload=_fake_page([], next_cursor=None)
            )
            service.fetch_tasks_for_date(_make_account_stub(), today)
        _, kwargs = patched_get.call_args
        assert kwargs["params"]["limit"] == 200


def _make_account_stub(token=TOKEN_PLAIN):
    """A lightweight stand-in for ``TodoistAccount`` whose ``get_token``
    returns a known plaintext — avoids a DB round-trip where the row itself
    is not under test (the query-string / pagination / sort cases)."""
    acc = MagicMock()
    acc.get_token.return_value = token
    return acc


class TestPriorityMapping:
    """``ui_priority = "P" + str(5 - priority)``: 4→P1 (highest) … 1→P4."""

    @pytest.mark.parametrize(
        "priority,expected_ui",
        [(4, "P1"), (3, "P2"), (2, "P3"), (1, "P4")],
    )
    def test_priority_maps_to_ui_flag(self, patched_get, priority, expected_ui):
        patched_get.return_value = _fake_response(
            json_payload=_fake_page(
                [_raw_task(id="x", content="t", priority=priority)],
                next_cursor=None,
            )
        )
        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2025, 2, 12)
        )
        assert len(tasks) == 1
        assert tasks[0].priority == priority
        assert tasks[0].ui_priority == expected_ui


class TestDueNormalisation:
    def test_full_day_due_keeps_date(self, patched_get):
        patched_get.return_value = _fake_response(
            json_payload=_fake_page(
                [_raw_task(due={"date": "2025-02-12"})], next_cursor=None
            )
        )
        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2025, 2, 12)
        )
        assert tasks[0].due_date == "2025-02-12"

    def test_timed_due_drops_time_no_raise(self, patched_get):
        patched_get.return_value = _fake_response(
            json_payload=_fake_page(
                [_raw_task(due={"date": "2018-11-15T12:00:00.000000"})],
                next_cursor=None,
            )
        )
        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2018, 11, 15)
        )
        assert tasks[0].due_date == "2018-11-15"

    @pytest.mark.parametrize(
        "raw_date",
        [
            "2018-11-15T12:00:00Z",
            "2018-11-15T12:00:00+00:00",
            "2018-11-15T12:00:00.000000Z",
            "2018-11-15T23:30:00+05:00",
        ],
    )
    def test_timed_due_with_tz_suffix_drops_time_no_raise(self, patched_get, raw_date):
        # The ``raw[:10]`` date slice is suffix-agnostic — a fixed-offset or
        # ``Z`` UTC suffix must still yield the correct YYYY-MM-DD without a
        # parse raise (date.fromisoformat rejects a bare ``Z`` on older
        # Pythons, so the impl must not call it on the full value).
        patched_get.return_value = _fake_response(
            json_payload=_fake_page(
                [_raw_task(due={"date": raw_date})], next_cursor=None
            )
        )
        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2018, 11, 15)
        )
        assert tasks[0].due_date == "2018-11-15"

    def test_null_due_maps_to_none(self, patched_get):
        patched_get.return_value = _fake_response(
            json_payload=_fake_page([_raw_task(due=None)], next_cursor=None)
        )
        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2025, 2, 12)
        )
        assert tasks[0].due_date is None


class TestTitleMapping:
    def test_content_maps_to_title(self, patched_get):
        patched_get.return_value = _fake_response(
            json_payload=_fake_page(
                [_raw_task(content="Buy milk")], next_cursor=None
            )
        )
        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2025, 2, 12)
        )
        assert tasks[0].title == "Buy milk"


class TestPagination:
    def test_pages_are_concatenated(self, patched_get):
        """A first page with a non-null ``next_cursor`` followed by a
        ``next_cursor: null`` page must be fully concatenated — a single
        un-paginated call would silently drop tasks."""
        page1 = _fake_response(
            json_payload=_fake_page(
                [
                    _raw_task(id="a", content="A", priority=1),
                    _raw_task(id="b", content="B", priority=1),
                ],
                next_cursor="CURSOR_2",
            )
        )
        page2 = _fake_response(
            json_payload=_fake_page(
                [_raw_task(id="c", content="C", priority=1)],
                next_cursor=None,
            )
        )
        patched_get.side_effect = [page1, page2]

        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2025, 2, 12)
        )

        assert {t.id for t in tasks} == {"a", "b", "c"}
        assert patched_get.call_count == 2
        # Second call carries the cursor returned by the first page.
        _, kwargs = patched_get.call_args
        assert kwargs["params"]["cursor"] == "CURSOR_2"


class TestDeterministicSort:
    def test_sort_is_priority_desc_then_due_then_title(self, patched_get):
        patched_get.return_value = _fake_response(
            json_payload=_fake_page(
                [
                    _raw_task(
                        id="low", content="zzz", priority=1,
                        due={"date": "2025-02-12"},
                    ),
                    _raw_task(
                        id="high", content="aaa", priority=4,
                        due={"date": "2025-02-12"},
                    ),
                ],
                next_cursor=None,
            )
        )
        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2025, 2, 12)
        )
        # priority 4 (P1, highest) sorts before priority 1 (P4).
        assert [t.id for t in tasks] == ["high", "low"]

    def test_none_due_task_does_not_raise(self, patched_get):
        """A task with ``due == null`` (``due_date = None``) must sort
        without a TypeError — the null-safe key coerces ``None`` to ``""``.
        """
        patched_get.return_value = _fake_response(
            json_payload=_fake_page(
                [
                    _raw_task(
                        id="dated", content="b", priority=2,
                        due={"date": "2025-02-12"},
                    ),
                    _raw_task(id="nodue", content="a", priority=2, due=None),
                ],
                next_cursor=None,
            )
        )
        # Must not raise TypeError comparing None against a str date.
        tasks = service.fetch_tasks_for_date(
            _make_account_stub(), datetime.date(2025, 2, 12)
        )
        assert len(tasks) == 2
        # None due sorts as "" (before the dated task) at equal priority.
        assert [t.id for t in tasks] == ["nodue", "dated"]


class TestMalformedTaskSkipped:
    def test_malformed_task_skipped_not_crash(self, patched_get, caplog):
        """A single malformed task (missing required field) is skipped with
        a logged warning rather than failing the whole fetch."""
        good = _raw_task(id="ok", content="fine", priority=2)
        bad = {"id": "broken"}  # no priority/content → KeyError in normaliser
        patched_get.return_value = _fake_response(
            json_payload=_fake_page([good, bad], next_cursor=None)
        )

        with caplog.at_level(logging.WARNING):
            tasks = service.fetch_tasks_for_date(
                _make_account_stub(), datetime.date(2025, 2, 12)
            )

        assert [t.id for t in tasks] == ["ok"]
        assert any(
            "Failed to normalize task" in r.getMessage()
            for r in caplog.records
        )


class TestProviderErrorMapping:
    def test_fetch_401_raises_auth(self, patched_get):
        patched_get.return_value = _fake_response(status_code=401)
        with pytest.raises(service.TodoistAuthError):
            service.fetch_tasks_for_date(
                _make_account_stub(), datetime.date(2025, 2, 12)
            )

    def test_fetch_timeout_raises_timeout(self, patched_get):
        patched_get.side_effect = requests.Timeout("timed out")
        with pytest.raises(service.TodoistTimeoutError):
            service.fetch_tasks_for_date(
                _make_account_stub(), datetime.date(2025, 2, 12)
            )

    def test_fetch_500_raises_provider(self, patched_get):
        patched_get.return_value = _fake_response(status_code=502)
        with pytest.raises(service.TodoistProviderError):
            service.fetch_tasks_for_date(
                _make_account_stub(), datetime.date(2025, 2, 12)
            )


class TestDecryptionPropagation:
    """``account.get_token()`` is called BEFORE the broad provider ``try`` in
    ``fetch_tasks_for_date`` (service.py), so a key-rotation decryption
    failure must propagate as ``ImproperlyConfigured`` — letting the view map
    it to a config-shaped 500 — and must NOT be swallowed/wrapped as
    ``TodoistProviderError`` (a 502 that would wrongly point ops at Todoist).
    A future refactor that slid ``get_token()`` inside the ``try`` would
    silently regress this; these tests pin the line-ordering invariant.
    """

    def test_get_token_improperly_configured_propagates(self, patched_get):
        acc = _make_account_stub()
        acc.get_token.side_effect = ImproperlyConfigured("undecryptable token")
        with pytest.raises(ImproperlyConfigured):
            service.fetch_tasks_for_date(acc, datetime.date(2025, 2, 12))
        # Decryption fails first, so the provider is never hit and the token
        # is never sent over the wire.
        patched_get.assert_not_called()

    def test_key_rotation_surfaces_as_improperly_configured(
        self, account, patched_get, settings
    ):
        # Realistic path: the row was encrypted with FERNET_KEY (autouse),
        # then the encryption key rotates. ``crypto.decrypt_token`` raises
        # ``InvalidToken`` which ``crypto`` translates to
        # ``ImproperlyConfigured`` — it must propagate unwrapped.
        settings.TODOIST_ENCRYPTION_KEY = Fernet.generate_key().decode()
        with pytest.raises(ImproperlyConfigured):
            service.fetch_tasks_for_date(account, datetime.date(2025, 2, 12))
        patched_get.assert_not_called()


class TestTokenBoundary:
    def test_get_token_called_only_in_fetch(self, account, patched_get):
        """``account.get_token()`` is the only decryption call site and it
        lives inside ``fetch_tasks_for_date``."""
        patched_get.return_value = _fake_response(
            json_payload=_fake_page([], next_cursor=None)
        )
        with patch.object(
            account, "get_token", wraps=account.get_token
        ) as spy:
            service.fetch_tasks_for_date(account, datetime.date(2025, 2, 12))
        assert spy.call_count == 1
        # The Bearer header carries the decrypted plaintext.
        _, kwargs = patched_get.call_args
        assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN_PLAIN}"


class TestCredentialsNeverLogged:
    """Mirror ``test_calendar_sync_service.py::TestCredentialsNeverLogged``:
    neither the plaintext token NOR the stored ciphertext hex may appear in
    captured logs, across both the success and failure paths."""

    def test_token_never_appears_in_logs(self, account, patched_get, caplog):
        # Success path (one malformed task to exercise the warning logger).
        patched_get.return_value = _fake_response(
            json_payload=_fake_page(
                [_raw_task(id="ok", content="fine", priority=2), {"id": "x"}],
                next_cursor=None,
            )
        )
        with caplog.at_level(logging.DEBUG):
            service.fetch_tasks_for_date(account, datetime.date(2025, 2, 12))

        # Failure path.
        patched_get.return_value = _fake_response(status_code=502)
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(service.TodoistProviderError):
                service.fetch_tasks_for_date(
                    account, datetime.date(2025, 2, 12)
                )

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert TOKEN_PLAIN not in joined
        # Defence-in-depth: the *ciphertext* must also never appear in logs.
        ciphertext_hex = bytes(account.token_encrypted).hex()
        assert ciphertext_hex not in joined
