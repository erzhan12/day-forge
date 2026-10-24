"""Guard the rehearsal's schema projection and its refusal to reverse migrations."""

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def rehearsal_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deployment/scripts"))
    import rehearse_block_gap
    import rehearse_release
    return rehearse_block_gap, rehearse_release


def test_gap_snapshot_preserves_legacy_fields_and_unrelated_tables(tmp_path, rehearsal_modules):
    gap, release = rehearsal_modules
    path = tmp_path / "source.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE templates_mgr_userpreferences (id INTEGER PRIMARY KEY, theme TEXT);
            INSERT INTO templates_mgr_userpreferences VALUES (1, 'strategic');
            CREATE TABLE schedules_timeblock (id INTEGER PRIMARY KEY, title TEXT);
            INSERT INTO schedules_timeblock VALUES (1, 'Keep');
        """)
    before = gap.legacy_snapshot(path)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE templates_mgr_userpreferences ADD COLUMN "
                   "default_block_gap_minutes INTEGER NOT NULL DEFAULT 10")
        db.execute("UPDATE templates_mgr_userpreferences SET default_block_gap_minutes=0")
    assert gap.legacy_snapshot(path) == before
    assert release.database_snapshot(path) != before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE templates_mgr_userpreferences SET theme='classic'")
    changed = gap.legacy_snapshot(path)
    assert changed["templates_mgr_userpreferences"] != before["templates_mgr_userpreferences"]
    assert changed["schedules_timeblock"] == before["schedules_timeblock"]


def test_rehearsal_requires_pre_gap_backup_without_reversing_it(tmp_path, rehearsal_modules):
    gap, _ = rehearsal_modules
    path = tmp_path / "source.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE templates_mgr_userpreferences (id INTEGER PRIMARY KEY);
            CREATE TABLE django_migrations (app TEXT, name TEXT);
            INSERT INTO django_migrations VALUES
                ('templates_mgr', '0005_userpreferences_chat_suggestions');
        """)
    gap.require_legacy_source(path)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE templates_mgr_userpreferences ADD COLUMN "
                   "default_block_gap_minutes INTEGER NOT NULL DEFAULT 10")
        db.execute("INSERT INTO templates_mgr_userpreferences VALUES (1, 20)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="never reverses a gap migration"):
        gap.require_legacy_source(path)
    assert path.read_bytes() == before
