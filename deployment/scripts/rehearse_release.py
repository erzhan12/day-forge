"""Run real release containers against a private SQLite backup, never production.

Build/pull the images first. The internal Docker network blocks provider egress.
Only the local reverse proxy is published, on loopback. See deployment/README.md.
"""

import argparse
import base64
import hashlib
import html
import http.cookiejar
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

USERNAME = "deployment-rehearsal"
PASSWORD = "container-rehearsal-local-only"
DAY = "2027-07-20"


def database_snapshot(path, *, omit_origin=False):
    """Persist only hashes and counts, never schedule content or credentials."""
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        result = {}
        for (table,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ):
            quoted = '"' + table.replace('"', '""') + '"'
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({quoted})")]
            if omit_origin and table == "schedules_timeblock" and "origin" in columns:
                columns.remove("origin")
            selection = ",".join('"' + c.replace('"', '""') + '"' for c in columns)
            hashes = sorted(
                hashlib.sha256(repr(row).encode()).hexdigest()
                for row in db.execute(f"SELECT {selection} FROM {quoted}")
            )
            result[table] = hashes
        return result


def digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def document_page(body):
    return json.loads(html.unescape(re.search(r'data-page="([^"]+)"', body).group(1)))


class LocalCookies(http.cookiejar.DefaultCookiePolicy):
    def return_ok_secure(self, cookie, request):
        # The sandbox proxy represents HTTPS termination on localhost only.
        local = request.host.startswith(("localhost:", "127.0.0.1:"))
        return local or super().return_ok_secure(cookie, request)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        return None


class Rehearsal:
    def __init__(self, root, port):
        self.root = root
        self.base = f"http://127.0.0.1:{port}"
        self.environment = dict(os.environ)
        self.events = []
        self.jar = http.cookiejar.CookieJar(policy=LocalCookies())
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def compose(self, *args, capture=False):
        return subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                self.root.name,
                "-f",
                str(self.root / "compose.json"),
                *args,
            ],
            env=self.environment,
            check=True,
            text=True,
            capture_output=capture,
        ).stdout

    def request(self, path, *, data=None, headers=None, follow=True):
        request_headers = {"Origin": self.base, **(headers or {})}
        if data is not None:
            request_headers["Content-Type"] = "application/json"
            request_headers["X-XSRF-TOKEN"] = next(
                cookie.value for cookie in self.jar if cookie.name == "XSRF-TOKEN"
            )
        request = urllib.request.Request(
            self.base + path,
            data=None if data is None else json.dumps(data).encode(),
            headers=request_headers,
        )
        try:
            client = (
                self.client
                if follow
                else urllib.request.build_opener(
                    urllib.request.HTTPCookieProcessor(self.jar), NoRedirect()
                )
            )
            response = client.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read().decode()
            return response.status, dict(response.headers), body

    def start(self, image, version):
        self.environment["REHEARSAL_IMAGE"] = image
        self.compose("up", "-d", "--wait", "--wait-timeout", "120")
        status, _, body = self.request("/accounts/login/")
        assert status == 200, status
        if version != "1.0":
            assert f'content="{version}"' in body
        assets = re.findall(r'(?:src|href)="(/static/assets/[^\"]+)"', body)
        assert assets
        for asset in assets:
            code, headers, _ = self.request(asset)
            assert code == 200, (asset, code)
            if version != "1.0":
                assert "immutable" in headers.get("Cache-Control", "")
        self.events.append(
            {
                "stage": "start",
                "image": image,
                "version": version,
                "assets": assets,
                "status": status,
            }
        )

    def seed(self):
        code = f"""
import datetime
from django.contrib.auth import get_user_model
from django.core.management import call_command
from schedules.models import Schedule, TimeBlock
User = get_user_model()
assert not User.objects.filter(username={USERNAME!r}).exists()
user = User.objects.create_user(username={USERNAME!r}, password={PASSWORD!r})
call_command('seed_templates', user=user.username, verbosity=0)
for date in [datetime.date.today(), datetime.date.fromisoformat({DAY!r})]:
    schedule = Schedule.objects.create(user=user, date=date, status='active')
    TimeBlock.objects.create(schedule=schedule, title='Container baseline',
        start_time='09:00', end_time='10:00', category='work', sort_order=0)
"""
        self.compose("exec", "-T", "web", "python", "manage.py", "shell", "-c", code, capture=True)

    def ownership(self, directory):
        self.compose(
            "run",
            "--rm",
            "--no-deps",
            "--user",
            "0",
            "--entrypoint",
            "python",
            "--volume",
            f"{directory}:/rehearsal-owned",
            "web",
            "-c",
            "import os; from pathlib import Path; root=Path('/rehearsal-owned'); "
            "[os.chown(p,1000,1000) for p in [root,*root.rglob('*')]]",
            capture=True,
        )

    def page(self, version):
        status, _, body = self.request(
            f"/schedule/{DAY}/",
            headers={
                "X-Inertia": "true",
                "X-Inertia-Version": version,
            },
        )
        assert status == 200, (status, body[:200])
        page = json.loads(body)
        assert page["version"] == version
        return page["props"]

    def login(self, version):
        self.request("/accounts/login/")
        status, _, body = self.request(
            "/accounts/login/",
            data={
                "username": USERNAME,
                "password": PASSWORD,
            },
        )
        assert status == 200 and document_page(body)["component"] == "Schedule"
        return self.page(version)

    def exercise(self, version, *, stale=None, title="Container saved block"):
        props = self.login(version)
        headers = {"X-Frontend-Version": version, "X-Schedule-User": str(props["auth_user_id"])}
        path = f"/api/schedules/{DAY}/blocks/"
        hour = "12" if stale and stale != "1.0" else "11"
        payload = {
            "title": title,
            "start_time": f"{hour}:00",
            "end_time": f"{hour}:30",
            "category": "work",
            "expected_revision": props["schedule"]["revision"],
        }
        if stale:
            before = digest(database_snapshot(self.root / "data/day_forge.db"))
            for supplied in [stale, None]:
                test_headers = {**headers}
                if supplied is None:
                    del test_headers["X-Frontend-Version"]
                else:
                    test_headers["X-Frontend-Version"] = supplied
                status, response_headers, body = self.request(
                    path, data=payload, headers=test_headers
                )
                assert status == 409 and json.loads(body)["code"] == "frontend_outdated"
                assert response_headers.get("Cache-Control") == "no-store"
            assert before == digest(database_snapshot(self.root / "data/day_forge.db"))
            status, response_headers, _ = self.request(
                "/settings/",
                headers={
                    "X-Inertia": "true",
                    "X-Inertia-Version": stale,
                },
            )
            assert status == 409 and response_headers["X-Inertia-Location"].endswith("/settings/")
            self.events.append(
                {
                    "stage": "stale_denied",
                    "server": version,
                    "client": stale,
                    "database_unchanged": True,
                }
            )
        status, _, body = self.request(path, data=payload, headers=headers)
        assert status == 201, (status, body[:200])
        saved = json.loads(body)
        assert saved["revision"] == payload["expected_revision"] + 1
        current = self.page(version)
        assert any(block["title"] == title for block in current["blocks"])
        status, response_headers, _ = self.request(
            "/accounts/logout/",
            data={},
            headers={
                "X-Inertia": "true",
                "X-Inertia-Version": stale or version,
            },
            follow=False,
        )
        assert status in {302, 303} and response_headers["Location"] == "/accounts/login/"
        status, _, body = self.request("/accounts/login/")
        assert status == 200
        page = document_page(body)
        assert page["component"] == "Login" and page["props"]["auth_user_id"] is None
        assert page["clearHistory"] is True
        self.events.append(
            {
                "stage": "authenticated_write_logout",
                "version": version,
                "saved_revision": saved["revision"],
            }
        )

    def preserve_originals(self, baseline):
        current = database_snapshot(self.root / "data/day_forge.db")
        for table, hashes in baseline.items():
            assert set(hashes).issubset(set(current[table])), table
        self.events.append(
            {
                "stage": "original_rows_preserved",
                "tables": len(baseline),
                "source_snapshot_sha256": digest(baseline),
            }
        )

    def migrations(self, image):
        directory = self.root / "migration-data"
        directory.mkdir()
        shutil.copyfile(self.root / "source.sqlite3", directory / "day_forge.db")
        self.environment["REHEARSAL_IMAGE"] = image
        self.ownership(directory)
        run = [
            "run",
            "--rm",
            "--no-deps",
            "--volume",
            f"{directory}:/app/db",
            "--entrypoint",
            "python",
            "web",
            "manage.py",
        ]
        # A separate copy rehearses a real pending migration. PR245 itself
        # introduces no schema change; normal image rollback must NOT reverse it.
        self.compose(*run, "migrate", "schedules", "0009", "--noinput", capture=True)
        before = database_snapshot(directory / "day_forge.db", omit_origin=True)
        migrate = [
            "run",
            "--rm",
            "--no-deps",
            "--volume",
            f"{directory}:/app/db",
            "web",
            "python",
            "manage.py",
            "showmigrations",
            "--plan",
        ]
        self.compose(*migrate, capture=True)
        after = database_snapshot(directory / "day_forge.db", omit_origin=True)
        for table in before:
            if table != "django_migrations":
                assert before[table] == after[table], table
        with sqlite3.connect(directory / "day_forge.db") as db:
            assert db.execute(
                "SELECT COUNT(*) FROM schedules_timeblock WHERE origin != 'unknown'"
            ).fetchone() == (0,)
        once = digest(database_snapshot(directory / "day_forge.db"))
        self.compose(*migrate, capture=True)
        assert once == digest(database_snapshot(directory / "day_forge.db"))
        self.events.append(
            {
                "stage": "migration_0009_to_0010",
                "data_preserved": True,
                "legacy_origin": "unknown",
                "second_start_noop": True,
            }
        )


def prepare(root, source, port):
    root.mkdir(mode=0o700)
    (root / "data").mkdir()
    (root / "staticfiles").mkdir()
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(root / "source.sqlite3") as dst:
            src.backup(dst)
    shutil.copyfile(root / "source.sqlite3", root / "data/day_forge.db")
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    environment = {
        "DEBUG": "0",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(48),
        "ALLOWED_HOSTS": "localhost,127.0.0.1,dayforge.habitreward.org",
        "CSRF_TRUSTED_ORIGINS": f"http://localhost:{port},http://127.0.0.1:{port}",
        "CALDAV_ENCRYPTION_KEY": key,
        "TODOIST_ENCRYPTION_KEY": key,
        "HABITICA_ENCRYPTION_KEY": key,
        "HABITICA_CLIENT_ID": "rehearsal",
        "GOOGLE_OAUTH_TOKEN_KEY": key,
        "GOOGLE_OAUTH_CLIENT_ID": "rehearsal",
        "GOOGLE_OAUTH_CLIENT_SECRET": "rehearsal",
        "GOOGLE_OAUTH_REDIRECT_URI": f"http://localhost:{port}/api/calendar/google/callback/",
        "EXTERNAL_TASKS_POLL_INTERVAL_SECONDS": "0",
        "LLM_API_KEY": "",
        "REDIS_URL": "redis://redis:6379/0",
    }
    (root / "sandbox.env").write_text("".join(f"{k}={v}\n" for k, v in environment.items()))
    (root / "sandbox.env").chmod(0o600)
    (root / "Caddyfile").write_text(
        ":8080 {\n reverse_proxy web:8006 {\n header_up X-Forwarded-Proto https\n }\n}\n"
    )
    compose = {
        "services": {
            "web": {
                "image": "${REHEARSAL_IMAGE:?Set REHEARSAL_IMAGE}",
                "env_file": [str(root / "sandbox.env")],
                "volumes": [f"{root / 'data'}:/app/db", f"{root / 'staticfiles'}:/app/staticfiles"],
                "depends_on": {"redis": {"condition": "service_healthy"}},
                "mem_limit": "250m",
                "memswap_limit": "500m",
                "healthcheck": {"interval": "2s", "start_period": "2s"},
            },
            "redis": {
                "image": "redis:7-alpine",
                "healthcheck": {
                    "test": ["CMD", "redis-cli", "ping"],
                    "interval": "2s",
                    "retries": 10,
                },
            },
            "proxy": {
                "image": "caddy:2-alpine",
                "ports": [f"127.0.0.1:{port}:8080"],
                "volumes": [f"{root / 'Caddyfile'}:/etc/caddy/Caddyfile:ro"],
                "networks": ["default", "edge"],
            },
        },
        "networks": {"default": {"internal": True}, "edge": {}},
    }
    (root / "compose.json").write_text(json.dumps(compose, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--old-image", required=True)
    parser.add_argument("--new-image", required=True)
    parser.add_argument("--new-version", required=True)
    parser.add_argument("--compatible-image", required=True)
    parser.add_argument("--compatible-version", required=True)
    parser.add_argument("--port", type=int, default=8009)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()
    root, source = args.output_dir.resolve(), args.source_db.resolve()
    if not root.is_relative_to(Path("/tmp").resolve()) or root.exists():
        parser.error("Use a NEW directory under /tmp; existing directories are never overwritten")
    if not source.is_file() or not 1024 <= args.port <= 65535:
        parser.error("A source database and an unprivileged port are required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]+", root.name):
        parser.error("Use a lowercase Docker project name for the output directory")
    project_label = f"label=com.docker.compose.project={root.name}"
    for resource in ["container", "network"]:
        existing = subprocess.check_output(
            ["docker", resource, "ls", "--quiet", "--filter", project_label]
            + (["--all"] if resource == "container" else []),
            text=True,
        )
        if existing.strip():
            parser.error("Docker resources already use that project name; choose another directory")
    prepare(root, source, args.port)
    rehearsal = Rehearsal(root, args.port)
    baseline = database_snapshot(root / "source.sqlite3")
    success = False
    try:
        rehearsal.environment["REHEARSAL_IMAGE"] = args.new_image
        rehearsal.ownership(root / "data")
        rehearsal.ownership(root / "staticfiles")
        rehearsal.start(args.old_image, "1.0")
        rehearsal.seed()
        rehearsal.login("1.0")
        rehearsal.start(args.new_image, args.new_version)
        rehearsal.exercise(args.new_version, stale="1.0")
        rehearsal.start(args.compatible_image, args.compatible_version)
        rehearsal.login(args.compatible_version)
        # Keep the saved write across both sides of a compatible rollback.
        rehearsal.start(args.new_image, args.new_version)
        rehearsal.exercise(
            args.new_version, stale=args.compatible_version, title="Rollback saved block"
        )
        rehearsal.start(args.old_image, "1.0")
        props = rehearsal.login("1.0")
        assert {"Container saved block", "Rollback saved block"}.issubset(
            {row["title"] for row in props["blocks"]}
        )
        rehearsal.events.append(
            {
                "stage": "legacy_image_rollback",
                "saved_writes_preserved": True,
                "reload_required": True,
            }
        )
        rehearsal.start(args.new_image, args.new_version)
        rehearsal.preserve_originals(baseline)
        rehearsal.migrations(args.new_image)
        rehearsal.compose(
            "exec", "-T", "web", "python", "manage.py", "check", "--deploy", capture=True
        )
        rehearsal.compose(
            "exec",
            "-T",
            "web",
            "python",
            "manage.py",
            "makemigrations",
            "--check",
            "--dry-run",
            capture=True,
        )
        success = True
    finally:
        try:
            report = {
                "success": success,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source_snapshot_sha256": digest(baseline),
                "events": rehearsal.events,
            }
            (root / "evidence.json").write_text(json.dumps(report, indent=2) + "\n")
            (root / "containers.log").write_text(
                rehearsal.compose("logs", "--no-color", capture=True)
            )
        except BaseException:
            success = False
            raise
        finally:
            if not (success and args.keep_running):
                rehearsal.compose("down")
    print(f"PASS: evidence in {root / 'evidence.json'}")
    if args.keep_running:
        print(f"Sandbox running at {rehearsal.base}; login {USERNAME} / {PASSWORD}")
        print(
            f"Stop: REHEARSAL_IMAGE={args.new_image} docker compose -p {root.name} "
            f"-f {root / 'compose.json'} down"
        )


if __name__ == "__main__":
    main()
