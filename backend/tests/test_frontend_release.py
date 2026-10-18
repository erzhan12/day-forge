"""A release swap must refresh navigation and reject writes before execution."""

import json

import pytest
from common.middleware import FrontendVersionMiddleware
from day_forge.frontend_release import DEVELOPMENT_VERSION, load_frontend_release
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory, override_settings


def test_release_reads_only_packaged_assets(tmp_path):
    (tmp_path / ".vite").mkdir()
    (tmp_path / "assets").mkdir()
    for name in ["app-abcd1234.js", "app-abcd1234.css"]:
        (tmp_path / "assets" / name).write_text("build")
    file = tmp_path / ".vite/release.json"
    data = {
        "version": "release-a",
        "script": "assets/app-abcd1234.js",
        "styles": ["assets/app-abcd1234.css"],
    }
    file.write_text(json.dumps(data))
    release = load_frontend_release(tmp_path)
    assert release.version == "release-a"
    assert release.styles == ("assets/app-abcd1234.css",)
    data["script"] = "../outside.js"
    file.write_text(json.dumps(data))
    with pytest.raises(ImproperlyConfigured):
        load_frontend_release(tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        None,
        "{}",
        "[]",
        "null",
        "bad json",
        '{"version":"a","script":"assets/missing.js","styles":[]}',
    ],
)
def test_missing_or_invalid_build_fails_closed(tmp_path, content):
    if content is not None:
        (tmp_path / ".vite").mkdir()
        (tmp_path / ".vite/release.json").write_text(content)
    with pytest.raises(ImproperlyConfigured, match="Frontend build"):
        load_frontend_release(tmp_path)


@pytest.mark.parametrize("server,client", [("release-b", "release-a"), ("release-a", "release-b")])
@pytest.mark.parametrize("method", ["post", "patch", "put", "delete"])
def test_upgrade_and_rollback_refuse_stale_writes_before_view(server, client, method):
    calls = []
    middleware = FrontendVersionMiddleware(lambda request: calls.append(request) or HttpResponse())
    request = getattr(RequestFactory(), method)("/api/blocks/1/", HTTP_X_FRONTEND_VERSION=client)
    with override_settings(INERTIA_VERSION=server):
        response = middleware(request)
    assert response.status_code == 409
    assert json.loads(response.content)["code"] == "frontend_outdated"
    assert response["Cache-Control"] == "no-store"
    assert calls == []


def test_legacy_missing_identity_refuses_writes_but_allows_reads():
    middleware = FrontendVersionMiddleware(lambda request: HttpResponse(status=204))
    with override_settings(INERTIA_VERSION="release-b"):
        assert middleware(RequestFactory().post("/api/templates/")).status_code == 409
        assert middleware(RequestFactory().get("/api/templates/")).status_code == 204
        assert middleware(RequestFactory().post("/accounts/logout/")).status_code == 204
        assert (
            middleware(
                RequestFactory().post("/api/templates/", HTTP_X_FRONTEND_VERSION="release-b")
            ).status_code
            == 204
        )


@pytest.mark.parametrize(
    "server,client", [("release-b", "release-a"), ("release-a", "release-b"), ("release-b", "1.0")]
)
def test_stale_inertia_visit_does_not_execute_page_bootstrap(server, client):
    calls = []
    middleware = FrontendVersionMiddleware(lambda request: calls.append(request) or HttpResponse())
    request = RequestFactory().get(
        "/schedule/2027-07-11/", HTTP_X_INERTIA="true", HTTP_X_INERTIA_VERSION=client
    )
    with override_settings(INERTIA_VERSION=server):
        response = middleware(request)
    assert response.status_code == 409
    assert response["X-Inertia-Location"] == "http://testserver/schedule/2027-07-11/"
    assert calls == []


@pytest.mark.django_db
def test_stale_real_api_write_leaves_database_unchanged(auth_client, user):
    from templates_mgr.models import Rule

    with override_settings(INERTIA_VERSION="release-b"):
        response = auth_client.post(
            "/api/rules/",
            data=json.dumps({"text": "Must not save", "priority": 1}),
            content_type="application/json",
            HTTP_X_FRONTEND_VERSION="release-a",
        )
    assert response.status_code == 409
    assert not Rule.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_stale_inertia_visit_with_full_middleware_stack(auth_client):
    # inertia-django preserves flash messages on a version mismatch. Its outer
    # response middleware needs MessageMiddleware even for a short-circuited GET.
    with override_settings(INERTIA_VERSION="release-a"):
        response = auth_client.get(
            "/settings/",
            HTTP_X_INERTIA="true",
            HTTP_X_INERTIA_VERSION="release-b",
        )
    assert response.status_code == 409
    assert response["X-Inertia-Location"].endswith("/settings/")


@pytest.mark.django_db
def test_stale_inertia_logout_redirects_to_login_not_post_only_logout(auth_client):
    with override_settings(INERTIA_VERSION="release-a"):
        response = auth_client.post(
            "/accounts/logout/",
            HTTP_X_INERTIA="true",
            HTTP_X_INERTIA_VERSION="release-b",
        )
    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/"
    assert "_auth_user_id" not in auth_client.session


@pytest.mark.django_db
def test_html_assets_and_inertia_page_share_the_packaged_identity(client):
    from day_forge.frontend_release import FrontendRelease

    release = FrontendRelease("release-a", "assets/app-abcdefgh.js", ("assets/app-abcdefgh.css",))
    with override_settings(DEBUG=False, FRONTEND_RELEASE=release, INERTIA_VERSION=release.version):
        response = client.get("/accounts/login/")
        assert response.status_code == 200
        assert b'name="frontend-version" content="release-a"' in response.content
        assert b"/static/assets/app-abcdefgh.js" in response.content
        assert b"/static/assets/app-abcdefgh.css" in response.content
        page = client.get(
            "/accounts/login/",
            HTTP_X_INERTIA="true",
            HTTP_X_INERTIA_VERSION="release-a",
        )
    assert page.status_code == 200
    assert page.json()["version"] == release.version


@pytest.mark.parametrize("supplied", [None, "previous-release", DEVELOPMENT_VERSION])
def test_development_allows_api_writes_without_a_release_handshake(supplied):
    headers = {} if supplied is None else {"HTTP_X_FRONTEND_VERSION": supplied}
    request = RequestFactory().post("/api/rules/", **headers)
    with override_settings(INERTIA_VERSION=DEVELOPMENT_VERSION):
        response = FrontendVersionMiddleware(lambda request: HttpResponse())(request)
    assert response.status_code == 200
