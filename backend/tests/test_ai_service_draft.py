"""Unit tests for ``service.run_draft``.

Monkeypatches the OpenAI client so no network call is made. The draft
flavour shares its exception taxonomy with ``run_command`` — covered there
— so this file focuses on the *differences*: model selection, the
``add``-only validator, and the AIUnavailableError gate.
"""
import datetime
import json

import pytest
from ai.service import (
    AIDraftResult,
    AIParseError,
    AIUnavailableError,
    run_draft,
)
from schedules.models import Schedule
from templates_mgr.models import Template


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeChat:
    def __init__(self, captured: dict, content: str):
        self._captured = captured
        self._content = content

    def create(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, captured: dict, content: str):
        completions = _FakeChat(captured, content)
        self.chat = type("C", (), {"completions": completions})()


@pytest.mark.django_db
def test_run_draft_uses_draft_model_and_returns_result(
    user, monkeypatch, settings
):
    settings.LLM_API_KEY = "sk-test"
    settings.LLM_DRAFT_MODEL = "gpt-4o-test"

    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    template = Template.objects.create(
        user=user, name="WD", type="weekday", blocks=[]
    )

    captured: dict = {}
    fake = _FakeClient(
        captured,
        json.dumps(
            {
                "actions": [
                    {
                        "type": "add",
                        "title": "Block",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "category": "work",
                    }
                ],
                "explanation": "fresh draft",
            }
        ),
    )
    monkeypatch.setattr("ai.service._get_client", lambda: fake)

    result = run_draft(
        schedule, template, [], [], datetime.datetime(2026, 5, 4, 8, 0)
    )

    assert isinstance(result, AIDraftResult)
    assert result.explanation == "fresh draft"
    assert len(result.parsed_actions) == 1
    assert captured["model"] == "gpt-4o-test"
    # System message is the draft variant
    assert captured["messages"][0]["role"] == "system"
    assert "draft" in captured["messages"][0]["content"].lower()


@pytest.mark.django_db
def test_run_draft_raises_unavailable_without_key(user, settings):
    settings.LLM_API_KEY = ""
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    template = Template.objects.create(
        user=user, name="WD", type="weekday", blocks=[]
    )
    with pytest.raises(AIUnavailableError):
        run_draft(
            schedule, template, [], [], datetime.datetime(2026, 5, 4, 8, 0)
        )


@pytest.mark.django_db
def test_run_draft_rejects_non_add(user, monkeypatch, settings):
    settings.LLM_API_KEY = "sk-test"
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    template = Template.objects.create(
        user=user, name="WD", type="weekday", blocks=[]
    )

    fake = _FakeClient(
        {},
        json.dumps(
            {
                "actions": [{"type": "remove", "task_id": 99}],
                "explanation": "should fail",
            }
        ),
    )
    monkeypatch.setattr("ai.service._get_client", lambda: fake)

    with pytest.raises(AIParseError) as exc_info:
        run_draft(
            schedule, template, [], [], datetime.datetime(2026, 5, 4, 8, 0)
        )
    assert "only accept 'add'" in str(exc_info.value)
    # Raw response preserved for the audit log.
    assert "remove" in exc_info.value.raw_response_text


def _success_response_client(captured: dict | None = None) -> _FakeClient:
    """Helper: a fake LLM client that returns a single valid 'add' action.

    ``captured`` mirrors ``_FakeClient``'s constructor — when supplied, the
    last ``chat.completions.create`` call's kwargs land in it for tests
    that need to inspect what the service sent (model, messages, etc.).
    Pass ``None`` (the default) when you only care that the call happened
    and don't need the kwargs.
    """
    return _FakeClient(
        captured if captured is not None else {},
        json.dumps(
            {
                "actions": [
                    {
                        "type": "add",
                        "title": "Block",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "category": "work",
                    }
                ],
                "explanation": "fresh draft",
            }
        ),
    )


@pytest.mark.django_db
def test_capture_writes_with_owner_only_perms(
    user, monkeypatch, settings, tmp_path
):
    """LLM_DRAFT_CAPTURE_PROMPT_PATH writes must be 0o600 (owner-only) so a
    permissive umask doesn't expose the user's full schedule history (PII)
    to other accounts on the host. Force ``umask(0o000)`` for the duration
    of the call so the test fails if the explicit ``mode=0o600`` is ever
    dropped — without the umask manipulation, a stricter system umask
    could hide the regression."""
    import os
    import stat

    capture_path = tmp_path / "draft_prompt.txt"
    settings.LLM_API_KEY = "sk-test"
    settings.LLM_DRAFT_CAPTURE_PROMPT_PATH = str(capture_path)

    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    template = Template.objects.create(
        user=user, name="WD", type="weekday", blocks=[]
    )
    monkeypatch.setattr("ai.service._get_client", _success_response_client)

    old_umask = os.umask(0o000)
    try:
        run_draft(
            schedule, template, [], [], datetime.datetime(2026, 5, 4, 8, 0)
        )
    finally:
        os.umask(old_umask)

    assert capture_path.exists()
    mode = stat.S_IMODE(os.stat(capture_path).st_mode)
    assert mode == 0o600, f"expected 0o600 even with umask(0), got {oct(mode)}"


@pytest.mark.django_db
def test_capture_refuses_to_follow_symlink(
    user, monkeypatch, settings, tmp_path, caplog
):
    """The capture write must use O_NOFOLLOW so a pre-existing symlink at
    the configured path can't be exploited to write through it (e.g., a
    local attacker pre-creating /tmp/draft_prompt_test7.txt as a symlink to
    a victim file). The OSError is swallowed-then-logged, not raised, so
    real draft requests still succeed."""
    victim = tmp_path / "victim.txt"
    victim.write_text("victim data")
    symlink_path = tmp_path / "draft_prompt.txt"
    symlink_path.symlink_to(victim)

    settings.LLM_API_KEY = "sk-test"
    settings.LLM_DRAFT_CAPTURE_PROMPT_PATH = str(symlink_path)

    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    template = Template.objects.create(
        user=user, name="WD", type="weekday", blocks=[]
    )
    monkeypatch.setattr("ai.service._get_client", _success_response_client)

    import logging
    with caplog.at_level(logging.WARNING, logger="ai.service"):
        # The draft itself succeeds — capture failure is non-fatal.
        result = run_draft(
            schedule, template, [], [], datetime.datetime(2026, 5, 4, 8, 0)
        )

    assert result.parsed_actions  # draft completed despite capture failure
    assert victim.read_text() == "victim data"  # symlink target untouched
    # The OSError surfaces in logs at WARNING level. Tighten beyond a
    # name-match so an unrelated WARNING that happens to mention the
    # setting can't satisfy this assertion.
    assert any(
        r.levelno == logging.WARNING
        and "LLM_DRAFT_CAPTURE_PROMPT_PATH" in r.message
        for r in caplog.records
    )
