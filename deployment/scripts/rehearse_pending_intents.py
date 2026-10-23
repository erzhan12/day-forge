"""Rehearse ai.0008, retained pending scopes and safe image rollback on a local copy.

Uses real ASGI/Redis with a fixed provider on an internal network. The final
start-only regression probe intentionally fails against the unpatched PR262 image.
"""

import json
import sqlite3
import uuid

from rehearse_chat_requests import ChatRehearsal, main
from rehearse_release import DAY, USERNAME, database_snapshot, digest, document_page


class PendingIntentRehearsal(ChatRehearsal):
    def query(self, sql):
        # Read through the container's SQLite view, including its live journal.
        code = (
            "import json,sqlite3; "
            "db=sqlite3.connect('file:/app/db/day_forge.db?mode=ro',uri=True); "
            "db.row_factory=sqlite3.Row; "
            f"rows=[dict(row) for row in db.execute({sql!r})]; "
            "db.close(); print(json.dumps(rows))"
        )
        return json.loads(self.compose("exec", "-T", "web", "python", "-c", code, capture=True))

    def assert_migrated(self):
        assert self.query(
            "SELECT count(*) AS n FROM django_migrations "
            "WHERE app='ai' AND name='0008_pendingintent'"
        ) == [{"n": 1}]
        assert self.query("PRAGMA integrity_check") == [{"integrity_check": "ok"}]

    def intents(self):
        return self.query(
            "SELECT * FROM ai_pendingintent WHERE user_id="
            f"(SELECT id FROM auth_user WHERE username='{USERNAME}') ORDER BY created_at"
        )

    def receipts(self):
        return self.query(
            "SELECT request_id,body_hash,completed_at,response_status,response_body "
            "FROM ai_chatrequest WHERE user_id="
            f"(SELECT id FROM auth_user WHERE username='{USERNAME}') ORDER BY request_id"
        )

    def receipt_snapshot(self):
        return digest(self.receipts())

    def chat(self, version, text, ref=None, action="continue", history=()):
        payload = {
            "request_id": str(uuid.uuid4()),
            "expected_revision": self.page(version)["schedule"]["revision"],
            "messages": [*history, {"role": "user", "content": text}],
        }
        if ref:
            payload.update(pending_intent_id=ref["id"], pending_intent_version=ref["version"],
                           intent_action=action)
        status, _, body = self.request(f"/api/ai/schedules/{DAY}/chat/", data=payload,
                                       headers=self.headers(version))
        self.events.append({"stage": "chat", "message": text, "status": status,
                            "code": json.loads(body).get("code")})
        return status, json.loads(body), payload, body

    def replay(self, version, payload, body):
        before = self.page(version)
        calls = self.provider_calls()
        status, _, replay = self.request(f"/api/ai/schedules/{DAY}/chat/", data=payload,
                                         headers=self.headers(version))
        assert status == 200 and replay == body
        assert self.page(version)["blocks"] == before["blocks"]
        assert self.page(version)["schedule"]["revision"] == before["schedule"]["revision"]
        assert self.provider_calls() == calls

    def pause_and_rollback(self, image, version):
        intents, receipts = digest(self.intents()), self.receipt_snapshot()
        retained = self.receipts()
        calls = self.provider_calls()
        self.enable_ai(False)
        self.start(image, version)
        self.assert_migrated()
        assert digest(self.intents()) == intents and self.receipt_snapshot() == receipts
        status, _, _ = self.request(f"/api/ai/schedules/{DAY}/chat/", data={
            "request_id": str(uuid.uuid4()),
            "expected_revision": self.page(version)["schedule"]["revision"],
            "messages": [{"role": "user", "content": "Add at 21:00"}],
        }, headers=self.headers(version))
        assert status == 503 and self.provider_calls() == calls
        assert digest(self.intents()) == intents
        after = self.receipts()
        assert all(row in after for row in retained)
        assert len(after) == len(retained) + 1
        assert sum(row["response_status"] == 503 for row in after) == (
            sum(row["response_status"] == 503 for row in retained) + 1
        )
        self.events.append({"stage": "rollback", "intents_and_receipts_retained": True,
                            "ai_paused_status": status, "paused_request_receipted": True})

    def run(self, old_image, old_version, new_image, new_version):
        self.environment["REHEARSAL_IMAGE"] = new_image
        self.ownership(self.root / "data")
        self.ownership(self.root / "staticfiles")
        with sqlite3.connect(self.root / "data/day_forge.db") as db:
            present = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_pendingintent'"
            ).fetchone()
            if present:
                assert db.execute("SELECT count(*) FROM ai_pendingintent").fetchone() == (0,), (
                    "Use a pre-0008 source or a copy without retained pending intents"
                )
        if present:
            self.compose("run", "--rm", "--no-deps", "web", "python", "manage.py",
                         "migrate", "ai", "0007", "--noinput", capture=True)
        self.start(old_image, old_version)
        self.seed()
        self.login(old_version)
        self.add(old_version, "Before upgrade", "11")
        self.compose("stop", "web", capture=True)
        before = database_snapshot(self.root / "data/day_forge.db")
        self.start(new_image, new_version)
        self.assert_migrated()
        after = database_snapshot(self.root / "data/day_forge.db")
        for table, hashes in before.items():
            if table != "django_migrations":
                assert set(hashes).issubset(set(after[table])), table
        self.events.append({"stage": "ai_0007_to_0008", "existing_rows_preserved": True})
        status, asked, ask_payload, ask_body = self.chat(
            new_version, "Add Container pending; ask time"
        )
        assert status == 200 and asked["pending_intent"] and not asked["applied"]
        saved = digest(self.intents())
        self.compose("restart", "web", capture=True)
        self.start(new_image, new_version)
        assert digest(self.intents()) == saved
        self.replay(new_version, ask_payload, ask_body)
        self.pause_and_rollback(old_image, old_version)
        self.enable_ai(True)
        self.start(new_image, new_version)
        assert digest(self.intents()) == saved
        self.replay(new_version, ask_payload, ask_body)
        status, applied, answer_payload, answer_body = self.chat(
            new_version, "14:00", asked["pending_intent"]
        )
        assert status == 200 and applied["applied"] and applied["pending_intent"] is None
        self.replay(new_version, answer_payload, answer_body)
        assert self.intents()[-1]["state"] == "resolved"
        self.events.append({"stage": "restart_and_reupgrade", "open_scope_retained": True,
                            "continuation_and_exact_replay": True})
        status, partial, partial_payload, partial_body = self.chat(
            new_version, "Add Container partial; apply accepted and ask unresolved time"
        )
        assert status == 200 and partial["partial"] and partial["pending_intent"]
        row = self.intents()[-1]
        accepted = next(b for b in partial["blocks"] if b["title"] == "Container accepted")
        assert json.loads(row["accepted_changes"])[0]["block_id"] == accepted["id"]
        calls = self.provider_calls()
        self.pause_and_rollback(old_image, old_version)
        self.add(old_version, "During rollback", "18")
        self.enable_ai(True)
        self.start(new_image, new_version)
        self.replay(new_version, partial_payload, partial_body)
        status, stale, _, _ = self.chat(new_version, "15:00", partial["pending_intent"])
        assert status == 409 and stale["code"] == "pending_intent_stale"
        assert self.provider_calls() == calls and self.intents()[-1]["state"] == "stale"
        status, fresh, _, _ = self.chat(new_version, "Add Container unresolved; ask time")
        assert status == 200 and fresh["pending_intent"]
        status, finished, _, _ = self.chat(new_version, "15:00", fresh["pending_intent"])
        assert status == 200 and finished["applied"]
        titles = [b["title"] for b in self.page(new_version)["blocks"]]
        assert titles.count("Container accepted") == titles.count("Container unresolved") == 1
        assert "During rollback" in titles
        self.events.append({"stage": "partial_rollback_write", "accepted_id_preserved": True,
                            "stale_without_provider": True, "no_sibling_replay": True})
        status, cancel, _, _ = self.chat(new_version, "Add Container cancel; ask time")
        assert status == 200
        calls = self.provider_calls()
        status, cancelled, cancel_payload, cancel_body = self.chat(
            new_version, "Cancel pending request.", cancel["pending_intent"], "cancel"
        )
        assert status == 200 and cancelled["pending_intent"] is None
        assert self.intents()[-1]["state"] == "cancelled" and self.provider_calls() == calls
        self.replay(new_version, cancel_payload, cancel_body)
        status, narrow, _, _ = self.chat(new_version, "Add Container narrow; ask start only")
        assert status == 200 and narrow["pending_intent"]
        status, narrowed, _, _ = self.chat(new_version, "20:00", narrow["pending_intent"])
        self.events.append({"stage": "start_only_derived_end", "status": status,
                            "applied": narrowed.get("applied", False)})
        assert status == 200 and narrowed["applied"], "start-only continuation regression"
        status, omitted, _, _ = self.chat(new_version, "Add Container partial-omitted; ask time")
        assert status == 200 and omitted["partial"] and omitted["pending_intent"]
        status, completed, _, _ = self.chat(new_version, "19:00", omitted["pending_intent"])
        assert status == 200 and completed["applied"] and completed["pending_intent"] is None
        titles = [b["title"] for b in self.page(new_version)["blocks"]]
        assert titles.count("Container accepted omitted") == 1
        assert titles.count("Container unresolved omitted") == 1
        self.events.append({"stage": "omitted_question", "structured_scope_retained": True,
                            "accepted_sibling_once": True})
        for title, suffix, answers in [
            ("Container procedural", "ask start time before adding it", [("21:00", True)]),
            ("Container anchored", "after Container baseline", [("08:00", False), ("10:00", True)]),
        ]:
            text = f"Add {title}; {suffix}"
            status, pending, _, _ = self.chat(new_version, text)
            assert status == 200 and pending["pending_intent"]
            history = [{"role": "user", "content": text},
                       {"role": "assistant", "content": pending["ask"], "is_ask": True}]
            for answer, applies in answers:
                status, pending, _, _ = self.chat(
                    new_version, answer, pending["pending_intent"], history=history
                )
                assert status == 200 and pending["applied"] is applies
                if not applies:
                    assert json.loads(self.intents()[-1]["items"])
        self.events.append({"stage": "relative_guard", "procedural_before_resolved": True,
                            "real_anchor_retained_until_corrected": True})
        self.compose("exec", "-T", "web", "python", "manage.py", "check", capture=True)
        self.compose("exec", "-T", "web", "python", "manage.py", "makemigrations",
                     "--check", "--dry-run", capture=True)
        status, _, _ = self.request("/accounts/logout/", data={}, headers=self.headers(new_version))
        assert status == 200
        status, _, body = self.request(f"/schedule/{DAY}/")
        assert status == 200 and document_page(body)["component"] == "Login"


if __name__ == "__main__":
    main(PendingIntentRehearsal, provider_model="rehearsal-pending-fixture", description=__doc__)
