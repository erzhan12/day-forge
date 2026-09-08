"""Public ``/privacy/`` and ``/terms/`` pages.

These two routes are the only page routes in the project that are *not*
``@login_required`` besides ``root_redirect``. The Google OAuth consent
screen for the ``dayforge.habitreward.org`` deployment links to them, so
an anonymous fetch must return the document itself — not a 302 to the
login page, which is what Google's reviewer would otherwise see.

The disclosure assertions are deliberately coarse (a handful of load-bearing
phrases, not the full prose): they exist so that rewording the pages cannot
silently drop a statement the consent-screen review depends on, while
leaving normal copy edits free.
"""

import re

import pytest
from django.test import override_settings
from django.urls import reverse

LEGAL_URLS = ["/privacy/", "/terms/"]


def _text(response):
    return response.content.decode()


def _prose(response):
    """Body with runs of whitespace collapsed to single spaces.

    The templates hard-wrap their paragraphs, so a phrase assertion against
    the raw body breaks on wherever the line happens to end. Collapsing
    first keeps the assertions about wording rather than line width.
    """
    return re.sub(r"\s+", " ", _text(response))


class TestPublicAccess:
    # Only the authenticated case carries ``django_db``. The anonymous cases
    # deliberately do not: these views touch no model, and an unmarked test
    # makes pytest-django fail loudly the moment one starts issuing queries
    # (a login gate reintroduced, a template that reads ``request.user``).
    # Marking them for consistency would trade that canary for nothing.

    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_anonymous_get_returns_200(self, client, url):
        # The whole point of the feature: no session, no redirect.
        response = client.get(url)
        assert response.status_code == 200

    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_anonymous_get_does_not_redirect_to_login(self, client, url):
        response = client.get(url, follow=False)
        # The page itself, not a bounce to /accounts/login/. Checking the
        # Location header (``in response`` looks at response headers) as well
        # as the status catches a redirect issued with any other 3xx, which a
        # bare ``!= 302`` would wave through.
        assert response.status_code == 200
        assert "Location" not in response

    @pytest.mark.parametrize("url", LEGAL_URLS)
    @pytest.mark.django_db
    def test_authenticated_get_returns_200(self, auth_client, url):
        # Signed-in users reach the same page (e.g. via the footer links).
        assert auth_client.get(url).status_code == 200

    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_head_is_allowed(self, client, url):
        # Crawlers and link checkers probe with HEAD; Django's
        # require_http_methods does not fold HEAD into GET, so it has to be
        # listed explicitly on the view.
        assert client.head(url).status_code == 200

    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_post_is_rejected(self, client, url):
        assert client.post(url).status_code == 405

    def test_reverse_names_resolve(self):
        assert reverse("privacy") == "/privacy/"
        assert reverse("terms") == "/terms/"


class TestRendering:
    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_renders_a_standalone_html_document(self, client, url):
        # Not an Inertia page: no data-page payload, no app bundle. A
        # regression to inertia_render here would make the page depend on a
        # frontend build and render blank without JS.
        body = _text(client.get(url))
        assert body.lstrip().startswith("<!DOCTYPE html>")
        assert "data-page" not in body
        assert "/src/app.ts" not in body

    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_maintainer_comments_never_reach_the_rendered_page(self, client, url):
        # Django's ``{# … #}`` is single-line only: a multi-line note written
        # that way is not parsed as a comment and renders verbatim into a
        # public page (it did, once — hence this test). Multi-line notes must
        # use ``{% comment %}``. Unrendered tag markers would betray either
        # mistake, as would the settings names those notes cite.
        body = _text(client.get(url))
        assert "{#" not in body
        assert "{%" not in body
        for internal in ("settings.py", "CACHE_TTL_SECONDS", "STATICFILES_DIRS", "INERTIA_LAYOUT"):
            assert internal not in body

    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_pages_cross_link_and_link_home(self, client, url):
        body = _text(client.get(url))
        assert 'href="/privacy/"' in body
        assert 'href="/terms/"' in body
        assert 'href="/"' in body

    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_shows_the_revision_date(self, client, url):
        from schedules.legal_views import LEGAL_LAST_UPDATED

        assert LEGAL_LAST_UPDATED in _text(client.get(url))

    def test_titles_are_distinct(self, client):
        assert "<title>Privacy Policy — Day Forge</title>" in _text(client.get("/privacy/"))
        assert "<title>Terms of Service — Day Forge</title>" in _text(client.get("/terms/"))


class TestContactAddress:
    @override_settings(LEGAL_CONTACT_EMAIL="ops@example.com")
    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_configured_address_renders_as_a_mailto(self, client, url):
        assert 'href="mailto:ops@example.com"' in _text(client.get(url))

    @override_settings(LEGAL_CONTACT_EMAIL="")
    @pytest.mark.parametrize("url", LEGAL_URLS)
    def test_unset_address_falls_back_without_a_blank_mailto(self, client, url):
        # An unconfigured deploy must not publish `mailto:` with nothing
        # after it — the fallback sentence points at the consent screen.
        response = client.get(url)
        assert "mailto:" not in _text(response)
        assert "Google OAuth consent screen" in _prose(response)


class TestPrivacyDisclosures:
    """Statements the Google review (and the CLAUDE.md privacy notes) rely on."""

    @pytest.fixture
    def body(self, client):
        return _prose(client.get("/privacy/"))

    def test_names_every_stored_credential_integration(self, body):
        for provider in ("CalDAV", "Todoist", "Habitica", "Google Calendar"):
            assert provider in body

    def test_states_credentials_are_encrypted_at_rest(self, body):
        assert "encrypted at rest" in body

    def test_discloses_llm_egress_of_the_whole_transcript(self, body):
        # CLAUDE.md's chat privacy note: every turn re-sends the full prior
        # transcript to the provider, and the mitigation is clearing it.
        assert "entire visible conversation" in body
        assert "clear the thread" in body.lower()

    def test_discloses_draft_history_egress(self, body):
        assert "Draft generation" in body

    def test_states_task_and_event_text_never_reaches_the_llm(self, body):
        # The counterpart invariant: Todoist/Habitica/calendar text is
        # display-only and must never be described as AI input.
        assert "never" in body
        assert "included in AI prompts" in body

    def test_states_ai_messages_are_logged_verbatim(self, body):
        assert "verbatim" in body

    def test_carries_the_google_limited_use_disclosure(self, body):
        assert "Google API Services User Data Policy" in body
        assert "Limited Use" in body

    def test_declares_google_scopes_and_read_only_access(self, body):
        assert "calendar.readonly" in body
        assert "userinfo.email" in body

    def test_explains_how_to_revoke_google_access(self, body):
        assert "myaccount.google.com/permissions" in body

    def test_covers_deletion(self, body):
        assert "Retention and deletion" in body


class TestTermsDisclosures:
    @pytest.fixture
    def body(self, client):
        return _prose(client.get("/terms/"))

    def test_disclaims_ai_output(self, body):
        assert "AI-generated content" in body

    def test_disclaims_warranties(self, body):
        assert "without warranties" in body

    def test_links_to_the_privacy_policy(self, body):
        assert "Privacy Policy" in body
