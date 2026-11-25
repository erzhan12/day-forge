"""Draft action cap decoupled from the chat cap (feature 0109, issue #222).

Template validation allows ``MAX_TEMPLATE_BLOCKS`` blocks and a draft emits
one ``add`` per block, so the draft validator must accept at least that many
actions. The endpoint tests patch ``ai.service._get_client`` rather than
``ai.views.run_draft`` so the real ``validate_draft_response`` runs behind the
HTTP endpoint.
"""

import datetime
import json
from types import SimpleNamespace

import pytest
import templates_mgr.api as templates_api
from ai.models import AIInteraction
from ai.prompts import SYSTEM_PROMPT_DRAFT
from ai.schemas import (
    DRAFT_ACTION_HEADROOM,
    MAX_ACTIONS_PER_COMMAND,
    MAX_DRAFT_ACTIONS,
    validate_draft_response,
)
from ai.service import AIParseError
from ai.service import run_draft as _async_run_draft
from ai.views import AI_PARSE_ERROR_DETAIL
from asgiref.sync import async_to_sync
from schedules.models import Schedule, TimeBlock
from templates_mgr.limits import MAX_TEMPLATE_BLOCKS
from templates_mgr.models import Template

URL = "/api/ai/schedules/2026-05-04/generate-draft/"  # a Monday: weekday template
CATEGORIES = {"work", "personal", "health", "learning", "other"}


def _blocks(count, *, start_minutes=6 * 60, length=15):
    """``count`` touching template-shaped blocks from 06:00 in the default window."""
    blocks = []
    minutes = start_minutes
    for i in range(count):
        end = minutes + length
        blocks.append(
            {
                "title": f"Block {i + 1}",
                "start_time": f"{minutes // 60:02d}:{minutes % 60:02d}",
                "end_time": f"{end // 60:02d}:{end % 60:02d}",
                "category": "work",
            }
        )
        minutes = end
    return blocks


def _adds(blocks):
    return [{"type": "add", **block} for block in blocks]


def _reply(actions, explanation="Follows the template."):
    return json.dumps({"actions": actions, "explanation": explanation})


class _FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def provider(monkeypatch, settings):
    """Install a fake provider that returns the given JSON reply."""
    settings.LLM_API_KEY = "test-key"

    def _install(content):
        completions = _FakeCompletions(content)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        monkeypatch.setattr("ai.service._get_client", lambda: client)
        return completions

    return _install


def _post(client, body=""):
    return client.post(URL, body, content_type="application/json")


# --- Constants ---------------------------------------------------------------


def test_draft_cap_derives_from_template_limit():
    assert MAX_DRAFT_ACTIONS == MAX_TEMPLATE_BLOCKS + DRAFT_ACTION_HEADROOM
    assert MAX_DRAFT_ACTIONS >= MAX_TEMPLATE_BLOCKS
    # One source of truth: template validation uses the same constant.
    assert templates_api.MAX_TEMPLATE_BLOCKS is MAX_TEMPLATE_BLOCKS
    # Chat keeps its own, smaller cap.
    assert MAX_ACTIONS_PER_COMMAND == 20


def test_draft_prompt_states_cap_and_keeps_template_blocks():
    assert f"Emit at most {MAX_DRAFT_ACTIONS} add actions" in SYSTEM_PROMPT_DRAFT
    assert "never drop a" in SYSTEM_PROMPT_DRAFT
    assert "template block to stay under it" in SYSTEM_PROMPT_DRAFT


# --- Validator ---------------------------------------------------------------


def test_validator_accepts_draft_at_cap():
    parsed = {"actions": _adds(_blocks(MAX_DRAFT_ACTIONS)), "explanation": "ok"}
    assert validate_draft_response(parsed, CATEGORIES) == []


def test_validator_rejects_one_over_cap():
    parsed = {"actions": _adds(_blocks(MAX_DRAFT_ACTIONS + 1)), "explanation": "ok"}
    assert validate_draft_response(parsed, CATEGORIES) == [
        f"too many actions ({MAX_DRAFT_ACTIONS + 1} > {MAX_DRAFT_ACTIONS})"
    ]


# --- Service -----------------------------------------------------------------


@pytest.mark.django_db
def test_run_draft_uses_draft_timeout_and_accepts_cap(user, provider, settings):
    settings.LLM_DRAFT_REQUEST_TIMEOUT = 42.0
    completions = provider(_reply(_adds(_blocks(MAX_DRAFT_ACTIONS))))
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 5, 4))
    template = Template.objects.create(user=user, name="WD", type="weekday", blocks=[])

    result = async_to_sync(_async_run_draft)(
        schedule, template, [], [], datetime.datetime(2026, 5, 4, 5, 0)
    )

    assert len(result.parsed_actions) == MAX_DRAFT_ACTIONS
    assert completions.calls[0]["timeout"] == 42.0
    assert completions.calls[0]["timeout"] != settings.LLM_REQUEST_TIMEOUT


@pytest.mark.django_db
def test_run_draft_rejects_one_over_cap(user, provider):
    raw = _reply(_adds(_blocks(MAX_DRAFT_ACTIONS + 1)))
    provider(raw)
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 5, 4))
    template = Template.objects.create(user=user, name="WD", type="weekday", blocks=[])

    with pytest.raises(AIParseError) as exc:
        async_to_sync(_async_run_draft)(
            schedule, template, [], [], datetime.datetime(2026, 5, 4, 5, 0)
        )

    assert exc.value.raw_response_text == raw
    assert "too many actions" in str(exc.value)


# --- Endpoint ----------------------------------------------------------------


@pytest.mark.django_db
class TestDraftEndpointCap:
    def test_full_template_generates_complete_draft(self, auth_client, user, provider):
        template_blocks = _blocks(MAX_TEMPLATE_BLOCKS)
        Template.objects.create(user=user, name="WD", type="weekday", blocks=template_blocks)
        # A faithful model returns every template block.
        provider(_reply(_adds(template_blocks)))

        resp = _post(auth_client)

        assert resp.status_code == 200, resp.content
        schedule = Schedule.objects.get(user=user, date="2026-05-04")
        saved = [
            {
                "title": block.title,
                "start_time": block.start_time.strftime("%H:%M"),
                "end_time": block.end_time.strftime("%H:%M"),
                "category": block.category,
            }
            for block in TimeBlock.objects.filter(schedule=schedule).order_by("start_time")
        ]
        assert saved == template_blocks
        assert len(resp.json()["blocks"]) == MAX_TEMPLATE_BLOCKS

    def test_draft_at_cap_is_applied_in_one_revision(self, auth_client, user, provider):
        Template.objects.create(
            user=user, name="WD", type="weekday", blocks=_blocks(MAX_TEMPLATE_BLOCKS)
        )
        provider(_reply(_adds(_blocks(MAX_DRAFT_ACTIONS))))

        resp = _post(auth_client, json.dumps({"expected_revision": 0}))

        assert resp.status_code == 200, resp.content
        schedule = Schedule.objects.get(user=user, date="2026-05-04")
        assert TimeBlock.objects.filter(schedule=schedule).count() == MAX_DRAFT_ACTIONS
        # One mutation: every add lands in a single revision bump.
        assert schedule.revision == 1
        assert resp.json()["revision"] == 1
        assert schedule.status == Schedule.Status.DRAFT

    def test_draft_one_over_cap_returns_502_without_writes(self, auth_client, user, provider):
        Template.objects.create(
            user=user, name="WD", type="weekday", blocks=_blocks(MAX_TEMPLATE_BLOCKS)
        )
        provider(_reply(_adds(_blocks(MAX_DRAFT_ACTIONS + 1))))

        resp = _post(auth_client)

        assert resp.status_code == 502
        assert resp.json() == {"errors": {"detail": AI_PARSE_ERROR_DETAIL}}
        schedule = Schedule.objects.get(user=user, date="2026-05-04")
        assert not TimeBlock.objects.filter(schedule=schedule).exists()
        assert schedule.revision == 0
        log = AIInteraction.objects.get(schedule=schedule)
        assert log.kind == AIInteraction.Kind.DRAFT
        assert log.success is False

    def test_draft_at_cap_with_overlap_writes_nothing(self, auth_client, user, provider):
        Template.objects.create(
            user=user, name="WD", type="weekday", blocks=_blocks(MAX_TEMPLATE_BLOCKS)
        )
        actions = _adds(_blocks(MAX_DRAFT_ACTIONS))
        # The last add overlaps the one before it; the whole draft must roll back.
        actions[-1]["start_time"] = actions[-2]["start_time"]
        provider(_reply(actions))

        resp = _post(auth_client)

        assert resp.status_code == 400
        assert resp.json()["errors"]["detail"] == "Blocks would overlap."
        schedule = Schedule.objects.get(user=user, date="2026-05-04")
        assert not TimeBlock.objects.filter(schedule=schedule).exists()
        assert schedule.revision == 0
