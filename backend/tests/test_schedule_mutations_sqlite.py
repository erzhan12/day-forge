"""Exercise real SQLite writer reservations on independently opened connections."""

import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from django.db import connection


@pytest.fixture
def copied_database(tmp_path, transactional_db):
    if connection.vendor != "sqlite":
        pytest.skip("SQLite concurrency contract")
    connection.ensure_connection()
    copy_path = tmp_path / "schedule-concurrency.sqlite3"
    destination = sqlite3.connect(copy_path)
    try:
        connection.connection.backup(destination)
    finally:
        destination.close()
    return copy_path


def run_on_copy(database, script):
    setup = """
import sys
from django.conf import settings
settings.DATABASES['default']['NAME'] = sys.argv[1]
settings.DATABASES['default']['OPTIONS'] = {'timeout': 0.1}
import django
django.setup()
settings.ALLOWED_HOSTS = ['testserver']
settings.SECURE_SSL_REDIRECT = False
"""
    environment = os.environ.copy()
    environment["DJANGO_SETTINGS_MODULE"] = "day_forge.settings"
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(setup) + textwrap.dedent(script), str(database)],
        env=environment, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("scenario", [
    "edit_edit", "delete_patch", "empty_create_draft", "absent_create_draft"
])
def test_same_revision_has_one_winner_on_separate_sqlite_connections(copied_database, scenario):
    run_on_copy(copied_database, """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from django.contrib.auth.models import User
from django.db import connections
from schedules.models import Schedule, TimeBlock
from schedules.mutations import execute_schedule_mutation, ScheduleChanged
user = User.objects.create_user(username='sqlite-race')
scenario = SCENARIO
schedule = None
if scenario != 'absent_create_draft':
    schedule = Schedule.objects.create(user=user, date='2026-10-10', status='active')
block = None
if scenario not in ('empty_create_draft', 'absent_create_draft'):
    block = TimeBlock.objects.create(
        schedule=schedule, title='Original', start_time='09:00', end_time='10:00'
    )
barrier = Barrier(2)
mutex = Lock()
handles = []
def worker(index):
    connections.close_all()
    db = connections['default']
    db.ensure_connection()
    with mutex:
        handles.append(id(db.connection))
    barrier.wait(timeout=5)
    def write(context):
        if scenario in ('empty_create_draft', 'absent_create_draft'):
            TimeBlock.objects.create(
                schedule=context.schedule, title='Created-' + str(index),
                start_time='09:00', end_time='10:00'
            )
            context.schedule.status = 'draft' if index else 'active'
            context.schedule.save(update_fields=['status'])
        elif scenario == 'delete_patch' and index == 0:
            context.schedule.time_blocks.filter(pk=block.pk).delete()
        else:
            context.schedule.time_blocks.filter(pk=block.pk).update(title='Edited-' + str(index))
    try:
        result = execute_schedule_mutation(
            user.pk, schedule.pk if schedule else None, 0, write, date='2026-10-10'
        )
        return ('ok', result.snapshot)
    except ScheduleChanged:
        return ('conflict', None)
    finally:
        connections.close_all()
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(worker, [0, 1]))
assert len(set(handles)) == 2, handles
assert sorted(result[0] for result in results) == ['conflict', 'ok'], results
schedule = Schedule.objects.get(user=user, date='2026-10-10')
assert schedule.revision == 1
winner = next(result[1] for result in results if result[0] == 'ok')
assert winner['revision'] == schedule.revision
assert len(winner['blocks']) == schedule.time_blocks.count()
if winner['blocks']:
    assert winner['blocks'][0]['title'] == schedule.time_blocks.get().title
""".replace("SCENARIO", repr(scenario)))


def test_category_delete_serializes_against_schedule_edit(copied_database):
    run_on_copy(copied_database, """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth.models import User
from django.db import connections
from schedules.categories import ordered_categories, delete_category, validate_slug
from schedules.models import Schedule, TimeBlock
from schedules.mutations import execute_schedule_mutation, ScheduleChanged, MutationRejected
from django.http import JsonResponse
user = User.objects.create_user(username='category-race')
catalog = ordered_categories(user)
target = next(row for row in catalog if row.slug == 'work')
schedule = Schedule.objects.create(user=user, date='2026-10-10', status='active')
block = TimeBlock.objects.create(
    schedule=schedule, title='Work', start_time='09:00', end_time='10:00', category='work'
)
barrier = Barrier(2)
def delete():
    connections.close_all()
    barrier.wait(timeout=5)
    try:
        delete_category(user, target)
        return 'deleted'
    finally:
        connections.close_all()
def edit():
    connections.close_all()
    barrier.wait(timeout=5)
    def write(context):
        try:
            validate_slug('work', ordered_categories(user))
        except ValueError:
            return JsonResponse({}, status=400)
        context.schedule.time_blocks.filter(pk=block.pk).update(title='Edited')
    try:
        execute_schedule_mutation(user.pk, schedule.pk, 0, write)
        return 'edited'
    except (ScheduleChanged, MutationRejected):
        return 'conflict'
    finally:
        connections.close_all()
with ThreadPoolExecutor(max_workers=2) as pool:
    first = pool.submit(delete)
    second = pool.submit(edit)
    results = [first.result(), second.result()]
assert results[0] == 'deleted'
schedule.refresh_from_db()
block.refresh_from_db()
assert block.category == 'other'
assert schedule.revision == (2 if results[1] == 'edited' else 1)
assert block.title == ('Edited' if results[1] == 'edited' else 'Work')
""")


def test_revision_migration_preserves_a_copied_database(copied_database):
    run_on_copy(copied_database, """
import datetime
from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from schedules.models import Schedule, TimeBlock, UserScheduleSettings
from templates_mgr.models import Template
from analytics.models import DailyReview
from ai.models import AIInteraction
user = User.objects.create_user(username='copied-migration')
schedule = Schedule.objects.create(user=user, date='2026-10-10', status='reviewed')
block = TimeBlock.objects.create(
    schedule=schedule, title='Preserved', start_time='08:00', end_time='09:00',
    category='work', is_completed=True, sort_order=4
)
policy = UserScheduleSettings.objects.create(
    user=user, day_start=datetime.time(8), day_end=datetime.time(20), time_zone='Asia/Qatar'
)
template = Template.objects.create(user=user, type='weekday', name='Preserved', blocks=[])
review = DailyReview.objects.create(
    schedule=schedule, notes='Preserved notes', planned_count=1, completed_count=1,
    planned_minutes_by_category={'work': 60}, completed_minutes_by_category={'work': 60}
)
audit = AIInteraction.objects.create(
    schedule=schedule, kind='command', success=True,
    user_command='Preserved command', ai_response='{}', actions_json=[]
)
executor = MigrationExecutor(connection)
old_target = [('schedules', '0007_userschedulesettings_time_zone')]
new_target = [('schedules', '0008_schedule_revision')]
try:
    executor.migrate(old_target)
    with connection.cursor() as cursor:
        cursor.execute('SELECT id, user_id, date, status FROM schedules_schedule')
        before_days = cursor.fetchall()
        cursor.execute('SELECT * FROM schedules_timeblock')
        before_blocks = cursor.fetchall()
        cursor.execute('SELECT * FROM schedules_userschedulesettings')
        before_policy = cursor.fetchall()
        cursor.execute('SELECT * FROM templates_mgr_template')
        before_templates = cursor.fetchall()
        cursor.execute('SELECT * FROM analytics_dailyreview')
        before_reviews = cursor.fetchall()
        cursor.execute('SELECT * FROM ai_aiinteraction')
        before_audit = cursor.fetchall()
    target_executor = MigrationExecutor(connection)
    target_executor.migrate(new_target)
    with connection.cursor() as cursor:
        cursor.execute('SELECT id, user_id, date, status FROM schedules_schedule')
        assert cursor.fetchall() == before_days
        cursor.execute('SELECT * FROM schedules_timeblock')
        assert cursor.fetchall() == before_blocks
        cursor.execute('SELECT * FROM schedules_userschedulesettings')
        assert cursor.fetchall() == before_policy
        cursor.execute('SELECT * FROM templates_mgr_template')
        assert cursor.fetchall() == before_templates
        cursor.execute('SELECT * FROM analytics_dailyreview')
        assert cursor.fetchall() == before_reviews
        cursor.execute('SELECT * FROM ai_aiinteraction')
        assert cursor.fetchall() == before_audit
    target_apps = target_executor.loader.project_state(new_target).apps
    migrated_schedule = target_apps.get_model('schedules', 'Schedule').objects.get(pk=schedule.pk)
    migrated_block = target_apps.get_model('schedules', 'TimeBlock').objects.get(pk=block.pk)
    assert migrated_schedule.revision == 0
    assert migrated_schedule.status == 'reviewed'
    assert migrated_block.schedule_id == schedule.pk
finally:
    restore_executor = MigrationExecutor(connection)
    restore_executor.migrate(restore_executor.loader.graph.leaf_nodes())
""")


def test_busy_retry_exhaustion_is_a_controlled_conflict_without_writes(copied_database):
    run_on_copy(copied_database, """
import sqlite3
from django.contrib.auth.models import User
from django.db import connection
from schedules.models import Schedule
from schedules.mutations import execute_schedule_mutation, ScheduleChanged
user = User.objects.create_user(username='busy-retry')
schedule = Schedule.objects.create(user=user, date='2026-10-10')
holder = sqlite3.connect(sys.argv[1], timeout=0.1, isolation_level=None)
holder.execute('BEGIN IMMEDIATE')
attempts = []
def capture(execute, sql, params, many, context):
    if sql.startswith('UPDATE "auth_user"'):
        attempts.append(sql)
    return execute(sql, params, many, context)
def never_called(context):
    raise AssertionError('A busy reservation must not reach the callback')
try:
    with connection.execute_wrapper(capture):
        try:
            execute_schedule_mutation(user.pk, schedule.pk, 0, never_called)
        except ScheduleChanged:
            pass
        else:
            raise AssertionError('Expected controlled conflict after bounded retries')
    assert len(attempts) == 3, attempts
finally:
    holder.rollback()
    holder.close()
schedule.refresh_from_db()
assert schedule.revision == 0
assert schedule.status == 'draft'
assert not schedule.time_blocks.exists()
""")


def test_first_policy_reads_share_the_user_lock_on_separate_connections(copied_database):
    run_on_copy(copied_database, """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from django.contrib.auth.models import User
from django.db import connections
from schedules.models import UserScheduleSettings
from schedules.window import get_schedule_settings
user = User.objects.create_user(username='first-policy')
barrier = Barrier(2)
mutex = Lock()
handles = []
def worker(index):
    connections.close_all()
    db = connections['default']
    db.ensure_connection()
    with mutex:
        handles.append(id(db.connection))
    barrier.wait(timeout=5)
    try:
        settings = get_schedule_settings(user)
        return settings.window.start_str, settings.window.end_str, settings.time_zone
    finally:
        connections.close_all()
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(worker, [0, 1]))
assert len(set(handles)) == 2, handles
assert results == [('06:00', '23:00', 'UTC'), ('06:00', '23:00', 'UTC')]
assert UserScheduleSettings.objects.filter(user=user).count() == 1
""")


def test_first_policy_read_retries_busy_reservation_without_creating_a_row(copied_database):
    run_on_copy(copied_database, """
import sqlite3
from django.contrib.auth.models import User
from django.db import connection
from schedules.models import UserScheduleSettings
from schedules.mutations import ScheduleChanged
from schedules.window import get_schedule_settings
user = User.objects.create_user(username='first-policy-busy')
holder = sqlite3.connect(sys.argv[1], timeout=0.1, isolation_level=None)
holder.execute('BEGIN IMMEDIATE')
attempts = []
def capture(execute, sql, params, many, context):
    if sql.startswith('UPDATE "auth_user"'):
        attempts.append(sql)
    return execute(sql, params, many, context)
try:
    with connection.execute_wrapper(capture):
        try:
            get_schedule_settings(user)
        except ScheduleChanged:
            pass
        else:
            raise AssertionError('First-use policy creation must reserve the shared writer lock')
    assert len(attempts) == 3, attempts
finally:
    holder.rollback()
    holder.close()
assert not UserScheduleSettings.objects.filter(user=user).exists()
settings = get_schedule_settings(user)
assert settings.time_zone == 'UTC'
assert UserScheduleSettings.objects.filter(user=user).count() == 1
""")


def test_existing_schedule_get_reads_during_independent_writer(copied_database):
    run_on_copy(copied_database, """
import sqlite3
from django.contrib.auth.models import User
from django.test import Client
from schedules.categories import ordered_categories
from schedules.models import Schedule, TimeBlock
from schedules.window import get_schedule_settings
from templates_mgr.preferences import get_user_preferences
user = User.objects.create_user(username='page-reader')
schedule = Schedule.objects.create(user=user, date='2026-10-10')
TimeBlock.objects.create(
    schedule=schedule, title='Existing', start_time='09:00', end_time='10:00'
)
ordered_categories(user)
get_schedule_settings(user)
get_user_preferences(user)
client = Client()
client.force_login(user)
holder = sqlite3.connect(sys.argv[1], timeout=0.1, isolation_level=None)
holder.execute('BEGIN IMMEDIATE')
try:
    response = client.get('/schedule/2026-10-10/', HTTP_X_INERTIA='true')
    assert response.status_code == 200, response.content
    props = response.json()['props']
    assert props['schedule']['revision'] == 0
    assert [block['title'] for block in props['blocks']] == ['Existing']
finally:
    holder.rollback()
    holder.close()
""")


def test_schedule_get_snapshot_stays_coherent_across_concurrent_commit(copied_database):
    run_on_copy(copied_database, """
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from django.contrib.auth.models import User
from django.db import connection
from django.db.models import QuerySet
from django.test import Client
from schedules.categories import ordered_categories
from schedules.models import Schedule, TimeBlock
from schedules.window import get_schedule_settings
from templates_mgr.preferences import get_user_preferences
from unittest.mock import patch
with connection.cursor() as cursor:
    cursor.execute('PRAGMA journal_mode=WAL')
user = User.objects.create_user(username='page-snapshot')
schedule = Schedule.objects.create(user=user, date='2026-10-10')
TimeBlock.objects.create(
    schedule=schedule, title='Old', start_time='09:00', end_time='10:00'
)
ordered_categories(user)
get_schedule_settings(user)
get_user_preferences(user)
client = Client()
client.force_login(user)
start = Event()
prepared = Event()
commit_started = Event()
committed = Event()
def writer():
    db = sqlite3.connect(sys.argv[1], timeout=2, isolation_level=None)
    try:
        assert start.wait(5)
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE schedules_schedule SET revision = 1 WHERE id = ?', (schedule.pk,))
        db.execute(
            'UPDATE schedules_timeblock SET title = ? WHERE schedule_id = ?',
            ('New', schedule.pk),
        )
        prepared.set()
        commit_started.set()
        db.commit()
        committed.set()
    finally:
        db.close()
seen = False
original_first = QuerySet.first
def pause_after_schedule(self):
    global seen
    result = original_first(self)
    if not seen and self.model is Schedule:
        seen = True
        start.set()
        assert prepared.wait(5)
        assert commit_started.wait(5)
        time.sleep(0.1)
        assert committed.is_set()
    return result
with ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(writer)
    with patch.object(QuerySet, 'first', pause_after_schedule):
        response = client.get('/schedule/2026-10-10/', HTTP_X_INERTIA='true')
    assert response.status_code == 200, response.content
    props = response.json()['props']
    assert props['schedule']['revision'] == 0, props
    assert [block['title'] for block in props['blocks']] == ['Old'], props
    future.result(timeout=5)
assert committed.is_set()
schedule.refresh_from_db()
assert schedule.revision == 1
assert list(schedule.time_blocks.values_list('title', flat=True)) == ['New']
""")


def test_two_first_visits_create_once_and_signal_once(copied_database):
    run_on_copy(copied_database, """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.conf import settings
from django.contrib.auth.models import User
from django.db import connections
from django.test import Client
from schedules.models import Category, Schedule, UserScheduleSettings
from templates_mgr.models import Template, UserPreferences
user = User.objects.create_user(username='first-page')
Template.objects.create(user=user, type='weekend', name='Weekend', blocks=[])
settings.LLM_API_KEY = 'test-key'
clients = [Client(), Client()]
for client in clients:
    client.force_login(user)
barrier = Barrier(2)
def visit(index):
    connections.close_all()
    barrier.wait(timeout=5)
    try:
        response = clients[index].get('/schedule/2026-10-10/', HTTP_X_INERTIA='true')
        return response.status_code, response.json()['props']['auto_draft_pending']
    finally:
        connections.close_all()
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(visit, [0, 1]))
assert sorted(results) == [(200, False), (200, True)], results
assert Schedule.objects.filter(user=user, date='2026-10-10').count() == 1
assert UserScheduleSettings.objects.filter(user=user).count() == 1
assert UserPreferences.objects.filter(user=user).count() == 1
assert Category.objects.filter(user=user).count() > 0
""")


def test_schedule_get_creation_contention_returns_controlled_503(copied_database):
    run_on_copy(copied_database, """
import sqlite3
from django.contrib.auth.models import User
from django.test import Client
from schedules.models import Schedule
user = User.objects.create_user(username='first-page-busy')
client = Client()
client.force_login(user)
holder = sqlite3.connect(sys.argv[1], timeout=0.1, isolation_level=None)
holder.execute('BEGIN IMMEDIATE')
try:
    response = client.get('/schedule/2026-10-10/', HTTP_X_INERTIA='true')
    assert response.status_code == 503, response.content
    assert response['Retry-After'] == '1'
finally:
    holder.rollback()
    holder.close()
assert not Schedule.objects.filter(user=user, date='2026-10-10').exists()
""")


def test_existing_day_with_missing_policies_bootstraps_without_autodraft(copied_database):
    run_on_copy(copied_database, """
from django.contrib.auth.models import User
from django.test import Client
from schedules.models import Category, Schedule, UserScheduleSettings
from templates_mgr.models import UserPreferences
user = User.objects.create_user(username='historic-page')
schedule = Schedule.objects.create(user=user, date='2026-10-10')
client = Client()
client.force_login(user)
response = client.get('/schedule/2026-10-10/', HTTP_X_INERTIA='true')
assert response.status_code == 200, response.content
props = response.json()['props']
assert props['schedule']['id'] == schedule.pk
assert props['auto_draft_pending'] is False
assert UserScheduleSettings.objects.filter(user=user).count() == 1
assert UserPreferences.objects.filter(user=user).count() == 1
assert Category.objects.filter(user=user).count() > 0
""")


def test_missing_policy_under_writer_returns_controlled_503(copied_database):
    run_on_copy(copied_database, """
import sqlite3
from django.contrib.auth.models import User
from django.test import Client
from schedules.models import Schedule
from templates_mgr.models import UserPreferences
user = User.objects.create_user(username='historic-page-busy')
schedule = Schedule.objects.create(user=user, date='2026-10-10')
client = Client()
client.force_login(user)
holder = sqlite3.connect(sys.argv[1], timeout=0.1, isolation_level=None)
holder.execute('BEGIN IMMEDIATE')
try:
    response = client.get('/schedule/2026-10-10/', HTTP_X_INERTIA='true')
    assert response.status_code == 503, response.content
finally:
    holder.rollback()
    holder.close()
assert Schedule.objects.get(pk=schedule.pk).revision == 0
assert not UserPreferences.objects.filter(user=user).exists()
""")
