"""Rehearse ai.0007 upgrade and image rollback on a private local SQLite copy.

Uses production entrypoints, ASGI and Redis. AI replies come from an isolated
fixture provider; this runner never connects to production or a paid provider.
"""

import argparse
import json
import re
import sqlite3
import subprocess
import uuid
from pathlib import Path

from rehearse_release import (
    DAY,
    USERNAME,
    Rehearsal,
    database_snapshot,
    digest,
    document_page,
    prepare,
)


class ChatRehearsal(Rehearsal):
    def headers(self, version):
        props = self.page(version)
        return {"X-Frontend-Version": version, "X-Schedule-User": str(props["auth_user_id"])}

    def add(self, version, title, hour):
        props = self.page(version)
        status, _, body = self.request(
            f"/api/schedules/{DAY}/blocks/",
            data={"title": title, "category": "work", "start_time": f"{hour}:00",
                  "end_time": f"{hour}:30", "expected_revision": props["schedule"]["revision"]},
            headers=self.headers(version),
        )
        assert status == 201, (status, body[:200])
        return json.loads(body)

    def provider_calls(self):
        return int(self.compose(
            "exec", "-T", "provider", "python", "-c",
            "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/calls')"
            ".read().decode())", capture=True,
        ).strip())

    def enable_ai(self, enabled):
        path = self.root / "sandbox.env"
        before, after = "LLM_API_KEY=\n", "LLM_API_KEY=rehearsal-local-only\n"
        if not enabled:
            before, after = after, before
        text = path.read_text()
        assert text.count(before) == 1
        path.write_text(text.replace(before, after))

    def receipt_snapshot(self):
        with sqlite3.connect(self.root / "data/day_forge.db") as db:
            rows = db.execute(
                "SELECT request_id, body_hash, completed_at, response_status, response_body "
                "FROM ai_chatrequest WHERE user_id=(SELECT id FROM auth_user WHERE username=?)",
                (USERNAME,),
            ).fetchall()
        return digest(rows)

    def assert_migrated(self):
        with sqlite3.connect(self.root / "data/day_forge.db") as db:
            assert db.execute(
                "SELECT count(*) FROM django_migrations WHERE app='ai' AND name='0007_chatrequest'"
            ).fetchone() == (1,)
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    def run(self, old_image, old_version, new_image, new_version):
        self.environment["REHEARSAL_IMAGE"] = new_image
        self.ownership(self.root / "data")
        self.ownership(self.root / "staticfiles")
        # The working source may already have 0007. Reverse it only on this
        # empty private copy to create a real pending migration for the old image.
        with sqlite3.connect(self.root / "data/day_forge.db") as db:
            table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_chatrequest'"
            ).fetchone()
            if table:
                assert db.execute("SELECT count(*) FROM ai_chatrequest").fetchone() == (0,), (
                    "Use a pre-0007 source or a copy without existing request identities"
                )
        if table:
            self.compose("run", "--rm", "--no-deps", "web", "python", "manage.py",
                         "migrate", "ai", "0006", "--noinput", capture=True)
        self.start(old_image, old_version)
        self.seed()
        self.login(old_version)
        self.add(old_version, "Before upgrade", "11")
        before = database_snapshot(self.root / "data/day_forge.db")
        self.start(new_image, new_version)
        self.assert_migrated()
        after = database_snapshot(self.root / "data/day_forge.db")
        for table, hashes in before.items():
            if table != "django_migrations":
                assert set(hashes).issubset(set(after[table])), table
        self.events.append({"stage": "ai_0006_to_0007", "existing_rows_preserved": True})
        props = self.page(new_version)  # Existing login survives the image update.
        payload = {
            "request_id": str(uuid.uuid4()), "expected_revision": props["schedule"]["revision"],
            "messages": [{"role": "user", "content": "Add Container AI at 14:00 for 30 minutes"}],
        }
        path = f"/api/ai/schedules/{DAY}/chat/"
        status, _, body = self.request(path, data=payload, headers=self.headers(new_version))
        receipt = json.loads(body)
        assert status == 200 and receipt["request_completed"] is True, (status, body[:200])
        assert receipt["request_id"] == payload["request_id"] and receipt["applied"] is True
        assert len([b for b in receipt["blocks"] if b["title"] == "Container AI"]) == 1
        replay = self.request(path, data=payload, headers=self.headers(new_version))
        assert replay[0] == status and replay[2] == body
        conflict = self.request(path, data={**payload, "extra": "changed"},
                                headers=self.headers(new_version))
        assert conflict[0] == 409 and json.loads(conflict[2])["code"] == "request_id_conflict"
        assert self.provider_calls() == 1
        self.add(new_version, "After receipt", "16")
        saved_receipt = self.receipt_snapshot()
        self.events.append({"stage": "durable_http_replay", "same_response": True,
                            "provider_calls": 1, "different_body_status": 409})
        self.enable_ai(False)
        self.start(old_image, old_version)
        self.assert_migrated()  # Image rollback never reverses 0007.
        assert self.receipt_snapshot() == saved_receipt
        # The old image has no durable-chat protocol. A new bundle cannot write
        # through it; do not send an old-protocol AI request as an alleged replay.
        denied = self.request(path, data=payload, headers={"X-Frontend-Version": new_version})
        assert denied[0] == 409 and json.loads(denied[2])["code"] == "frontend_outdated"
        current = self.page(old_version)
        assert {"Before upgrade", "Container AI", "After receipt"}.issubset(
            {b["title"] for b in current["blocks"]}
        )
        paused = self.request(path, data={
            "expected_revision": current["schedule"]["revision"],
            "messages": [{"role": "user", "content": "Add a block at 20:00"}],
        }, headers=self.headers(old_version))
        assert paused[0] == 503 and self.page(old_version)["blocks"] == current["blocks"]
        self.add(old_version, "During rollback", "18")
        assert self.receipt_snapshot() == saved_receipt and self.provider_calls() == 1
        self.events.append({"stage": "image_rollback", "receipt_retained": True,
                            "writes_preserved": True, "stale_chat_denied": True,
                            "old_protocol_ai_disabled_status": paused[0]})
        self.enable_ai(True)
        self.start(new_image, new_version)
        self.assert_migrated()
        current = self.page(new_version)
        assert current["schedule"]["revision"] > receipt["revision"]
        replay = self.request(path, data=payload, headers=self.headers(new_version))
        assert replay[0] == status and replay[2] == body
        assert self.receipt_snapshot() == saved_receipt and self.provider_calls() == 1
        assert self.page(new_version)["blocks"] == current["blocks"]
        assert any(b["title"] == "During rollback" for b in current["blocks"])
        self.events.append({"stage": "reupgrade_replay", "same_response": True,
                            "newer_writes_preserved": True, "provider_calls": 1})
        status, _, _ = self.request("/accounts/logout/", data={}, headers=self.headers(new_version))
        assert status == 200
        status, _, body = self.request(f"/schedule/{DAY}/")
        assert status == 200 and document_page(body)["component"] == "Login"
        self.compose("exec", "-T", "web", "python", "manage.py", "check", capture=True)
        self.compose("exec", "-T", "web", "python", "manage.py", "makemigrations",
                     "--check", "--dry-run", capture=True)


def configure_provider(root, image):
    provider = Path(__file__).with_name("rehearsal_chat_provider.py").resolve()
    compose_path = root / "compose.json"
    compose = json.loads(compose_path.read_text())
    compose["services"]["provider"] = {
        "image": image, "entrypoint": ["python", "/fixture_provider.py"],
        "volumes": [f"{provider}:/fixture_provider.py:ro"],
        "healthcheck": {
            "test": ["CMD", "python", "-c", "import urllib.request; "
                     "urllib.request.urlopen('http://127.0.0.1:8000/calls').read()"],
            "interval": "2s", "timeout": "2s", "retries": 5, "start_period": "2s",
        },
    }
    compose["services"]["web"]["depends_on"]["provider"] = {"condition": "service_healthy"}
    compose_path.write_text(json.dumps(compose, indent=2) + "\n")
    path = root / "sandbox.env"
    text = path.read_text()
    if text.count("LLM_API_KEY=\n") != 1:
        raise ValueError("sandbox.env missing a single expected LLM_API_KEY= line")
    text = text.replace("LLM_API_KEY=\n", "LLM_API_KEY=rehearsal-local-only\n")
    path.write_text(text + "LLM_BASE_URL=http://provider:8000/v1\n"
                    "LLM_MODEL=rehearsal-fixture\nLLM_DRAFT_MODEL=rehearsal-fixture\n")


def finalize_rehearsal(runner, evidence):
    """Stop the sandbox and report artifact or cleanup failures as failures."""
    try:
        logs = runner.compose("logs", "--no-color", capture=True)
        (runner.root / "containers.log").write_text(logs)
    except BaseException:
        evidence["success"] = False
        raise
    finally:
        evidence["cleanup_completed"] = False
        try:
            runner.compose("down")
            evidence["cleanup_completed"] = True
        except BaseException:
            evidence["success"] = False
            raise
        finally:
            (runner.root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--old-image", required=True)
    parser.add_argument("--old-version", required=True)
    parser.add_argument("--new-image", required=True)
    parser.add_argument("--new-version", required=True)
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    root, source = args.output_dir.resolve(), args.source_db.resolve()
    if not root.is_relative_to(Path("/tmp").resolve()) or root.exists():
        parser.error("Use a NEW directory under /tmp")
    if not source.is_file() or not 1024 <= args.port <= 65535:
        parser.error("A local source database and unprivileged port are required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]+", root.name):
        parser.error("Use a lowercase Docker project name")
    for image in [args.old_image, args.new_image]:
        # Match Compose's fully qualified lookup for short local image names.
        reference = image if "/" in image else f"docker.io/library/{image}"
        subprocess.run(["docker", "image", "inspect", reference], check=True, capture_output=True)
    for resource in ["container", "network"]:
        command = ["docker", resource, "ls", "--quiet", "--filter",
                   f"label=com.docker.compose.project={root.name}"]
        if resource == "container":
            command.append("--all")
        if subprocess.check_output(command, text=True).strip():
            parser.error("Docker project already exists")
    source_before = database_snapshot(source)
    prepare(root, source, args.port)
    configure_provider(root, args.new_image)
    runner = ChatRehearsal(root, args.port)
    success = False
    try:
        runner.run(args.old_image, args.old_version, args.new_image, args.new_version)
        final = database_snapshot(root / "data/day_forge.db")
        for table, hashes in source_before.items():
            if table != "django_migrations":
                assert set(hashes).issubset(set(final[table])), table
        assert source_before == database_snapshot(source), "Working source database changed"
        success = True
    finally:
        evidence = {"success": success, "source_snapshot_sha256": digest(source_before),
                    "source_tables": len(source_before),
                    "source_rows": sum(map(len, source_before.values())),
                    "old_version": args.old_version, "new_version": args.new_version,
                    "provider": "isolated fixture; no paid calls", "events": runner.events}
        finalize_rehearsal(runner, evidence)
    print(f"PASS: {root / 'evidence.json'}")


if __name__ == "__main__":
    main()
