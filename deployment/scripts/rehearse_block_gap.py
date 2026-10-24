"""Rehearse gap migration, restart and image rollback on a pre-0006 SQLite backup.

Uses production entrypoints and real ASGI/Redis with AI and polling disabled.
The original database is only read. Schema migrations run forward on its private
copy; an image rollback never reverses migrations or discards customized gaps.
"""

import json
import sqlite3
import uuid

from rehearse_chat_requests import main
from rehearse_release import DAY, PASSWORD, Rehearsal, database_snapshot, digest

GAP_COLUMN = "default_block_gap_minutes"
PREFERENCES_TABLE = "templates_mgr_userpreferences"


def legacy_snapshot(path):
    # Compare old columns across AddField while retaining hashes for every
    # original row. Gap values are checked separately, including valid zero.
    return database_snapshot(path, omit_columns={PREFERENCES_TABLE: {GAP_COLUMN}})


def require_legacy_source(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({PREFERENCES_TABLE})")]
        if not columns or GAP_COLUMN in columns:
            raise ValueError("Use a pre-0006 backup; this runner never reverses a gap migration")
        if db.execute(
            "SELECT count(*) FROM django_migrations WHERE app='templates_mgr' "
            "AND name='0005_userpreferences_chat_suggestions'"
        ).fetchone() != (1,):
            raise ValueError("Source must have templates_mgr.0005 applied")


class GapRehearsal(Rehearsal):
    def query(self, sql, parameters=()):
        code = (
            "import json,sqlite3; "
            "db=sqlite3.connect('file:/app/db/day_forge.db?mode=ro',uri=True); "
            "db.row_factory=sqlite3.Row; "
            f"print(json.dumps([dict(r) for r in db.execute({sql!r}, {parameters!r})]))"
        )
        return json.loads(self.compose("exec", "-T", "web", "python", "-c", code, capture=True))

    def seed_fixtures(self):
        prefix = "gap-rehearsal-" + uuid.uuid4().hex[:10]
        code = f"""
import datetime,json
from django.contrib.auth import get_user_model
from django.core.management import call_command
from schedules.models import Schedule,TimeBlock
from templates_mgr.models import UserPreferences
fixtures=[]
for gap,theme in [(0,'classic'),(10,'strategic'),(20,'light_premium')]:
    username={prefix!r}+'-'+str(gap)
    user=get_user_model().objects.create_user(username=username,password={PASSWORD!r})
    UserPreferences.objects.create(user=user,theme=theme,chat_suggestions=['Keep '+str(gap)])
    call_command('seed_templates',user=username,verbosity=0)
    for day in {{datetime.date.today(),datetime.date.fromisoformat({DAY!r})}}:
        schedule=Schedule.objects.create(user=user,date=day,status='active')
        TimeBlock.objects.create(schedule=schedule,title='Gap baseline',start_time='09:00',
            end_time='10:00',category='work')
    fixtures.append(dict(user_id=user.pk,username=username,gap=gap,theme=theme,
                         chat_suggestions=['Keep '+str(gap)]))
print('GAP_FIXTURES='+json.dumps(fixtures))
"""
        output = self.compose(
            "exec", "-T", "web", "python", "manage.py", "shell", "-c", code, capture=True,
        )
        self.fixtures = json.loads(output.split("GAP_FIXTURES=", 1)[1])
        self.clients = {}
        for fixture in self.fixtures:
            client = Rehearsal(self.root, int(self.base.rsplit(":", 1)[1]))
            self.sign_in(client, fixture["username"])
            self.clients[fixture["user_id"]] = client
        self.events.append({"stage": "legacy_fixtures", "users": 3, "gaps_to_test": [0, 10, 20]})

    def sign_in(self, client, username):
        assert client.request("/accounts/login/")[0] == 200
        status, _, _ = client.request(
            "/accounts/login/", data={"username": username, "password": PASSWORD}, follow=False,
        )
        assert status in (302, 303), status

    def preferences(self, fixture, version, patch=None):
        status, headers, body = self.clients[fixture["user_id"]].request(
            "/api/user/preferences/", data=patch,
            method="PATCH" if patch is not None else "GET",
            headers={"X-Frontend-Version": version, "X-Schedule-User": str(fixture["user_id"])},
        )
        assert status == 200, ("preferences", fixture["gap"], status)
        assert "no-store" in headers["Cache-Control"]
        return json.loads(body)

    def blocks(self, fixture):
        return self.query(
            "SELECT b.* FROM schedules_timeblock b JOIN schedules_schedule s "
            "ON b.schedule_id=s.id WHERE s.user_id=? ORDER BY b.id", (fixture["user_id"],),
        )

    def matrix(self, version, *, old=False):
        for fixture in self.fixtures:
            row = self.query(
                f"SELECT * FROM {PREFERENCES_TABLE} WHERE user_id=?", (fixture["user_id"],),
            )[0]
            assert row[GAP_COLUMN] == fixture["gap"]
            prefs = self.preferences(fixture, version)
            assert prefs["theme"] == fixture["theme"]
            assert prefs["chat_suggestions"] == fixture["chat_suggestions"]
            if old:
                assert GAP_COLUMN not in prefs
            else:
                assert prefs[GAP_COLUMN] == fixture["gap"]
            assert self.blocks(fixture) == fixture["blocks"], "Schedule blocks changed"

    def run(self, old_image, old_version, new_image, new_version):
        require_legacy_source(self.root / "source.sqlite3")
        self.environment["REHEARSAL_IMAGE"] = old_image
        self.ownership(self.root / "data")
        self.ownership(self.root / "staticfiles")
        self.start(old_image, old_version)
        self.seed_fixtures()
        for fixture in self.fixtures:
            fixture["blocks"] = self.blocks(fixture)
            assert GAP_COLUMN not in self.preferences(fixture, old_version)
        before = legacy_snapshot(self.root / "data/day_forge.db")

        self.start(new_image, new_version)
        after = legacy_snapshot(self.root / "data/day_forge.db")
        assert {k: v for k, v in before.items() if k != "django_migrations"} == {
            k: v for k, v in after.items() if k != "django_migrations"
        }
        assert self.query(
            f"SELECT count(*) AS n FROM {PREFERENCES_TABLE} WHERE {GAP_COLUMN} != 10"
        ) == [{"n": 0}]
        assert self.query(
            "SELECT count(*) AS n FROM django_migrations WHERE app='templates_mgr' "
            "AND name='0006_userpreferences_default_block_gap_minutes'"
        ) == [{"n": 1}]
        self.events.append({"stage": "upgrade_0005_to_0006", "default": 10,
                            "legacy_columns_and_original_rows_preserved": True})
        for fixture in self.fixtures:
            assert self.preferences(fixture, new_version)[GAP_COLUMN] == 10
            saved = self.preferences(fixture, new_version, {GAP_COLUMN: fixture["gap"]})
            assert saved[GAP_COLUMN] == fixture["gap"]
        self.matrix(new_version)
        self.events.append({"stage": "saved_gaps", "values": [0, 10, 20],
                            "themes_suggestions_and_blocks_preserved": True})

        before_restart = digest(database_snapshot(self.root / "data/day_forge.db"))
        self.compose("restart", "web", capture=True)
        self.start(new_image, new_version)
        assert before_restart == digest(database_snapshot(self.root / "data/day_forge.db"))
        self.matrix(new_version)
        self.events.append({"stage": "restart", "values": [0, 10, 20],
                            "database_unchanged": True})

        self.start(old_image, old_version)
        self.matrix(old_version, old=True)
        for fixture in self.fixtures:
            fixture["theme"] = "dark_4a"
            fixture["chat_suggestions"] = ["Changed during rollback " + str(fixture["gap"])]
            self.preferences(fixture, old_version, {
                "theme": fixture["theme"], "chat_suggestions": fixture["chat_suggestions"],
            })
            client = self.clients[fixture["user_id"]]
            props = client.page(old_version)
            status, _, body = client.request(
                f"/api/schedules/{DAY}/blocks/", headers={
                    "X-Frontend-Version": old_version, "X-Schedule-User": str(fixture["user_id"]),
                }, data={"expected_revision": props["schedule"]["revision"],
                         "title": "During gap rollback", "category": "work",
                         "start_time": "12:00", "end_time": "12:25"},
            )
            assert status == 201, ("rollback manual write", status)
            assert json.loads(body)["revision"] == props["schedule"]["revision"] + 1
            after = self.blocks(fixture)
            assert len(after) == len(fixture["blocks"]) + 1
            assert all(block in after for block in fixture["blocks"])
            added = [block for block in after if block["title"] == "During gap rollback"]
            assert len(added) == 1
            assert (added[0]["start_time"], added[0]["end_time"], added[0]["category"]) == (
                "12:00:00", "12:25:00", "work",
            )
            fixture["blocks"] = after
        self.matrix(old_version, old=True)
        self.events.append({"stage": "image_rollback", "stored_gaps": [0, 10, 20],
                            "old_preference_writes_and_manual_writes_succeeded": True,
                            "reverse_migrations": False})

        username = "gap-rollback-new-" + uuid.uuid4().hex[:10]
        code = (
            "from django.contrib.auth import get_user_model; "
            f"get_user_model().objects.create_user(username={username!r},password={PASSWORD!r})"
        )
        self.compose("exec", "-T", "web", "python", "manage.py", "shell", "-c", code, capture=True)
        fresh = Rehearsal(self.root, int(self.base.rsplit(":", 1)[1]))
        self.sign_in(fresh, username)
        status, _, _ = fresh.request("/api/user/preferences/", headers={
            "X-Frontend-Version": old_version,
        })
        self.events.append({"stage": "legacy_first_preferences", "status": status})
        assert status == 200, f"First preferences access on rollback returned {status}"
        rows = self.query(
            f"SELECT p.{GAP_COLUMN} FROM {PREFERENCES_TABLE} p JOIN auth_user u "
            "ON p.user_id=u.id WHERE u.username=?", (username,),
        )
        assert rows == [{GAP_COLUMN: 10}]

        self.start(new_image, new_version)
        self.matrix(new_version)
        status, _, body = fresh.request("/api/user/preferences/", headers={
            "X-Frontend-Version": new_version,
        })
        assert status == 200 and json.loads(body)[GAP_COLUMN] == 10
        self.events.append({"stage": "reupgrade", "values": [0, 10, 20],
                            "rollback_writes_preserved": True, "new_user_default": 10})
        self.compose("exec", "-T", "web", "python", "manage.py", "check", capture=True)
        self.compose("exec", "-T", "web", "python", "manage.py", "makemigrations",
                     "--check", "--dry-run", capture=True)


if __name__ == "__main__":
    main(GapRehearsal, provider_model=None, snapshot=legacy_snapshot, description=__doc__)
