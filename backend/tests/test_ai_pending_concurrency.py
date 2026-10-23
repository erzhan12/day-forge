"""A separate request UUID cannot reuse a permission claimed by another process."""

from pathlib import Path

import pytest

from tests.test_schedule_mutations_sqlite import copied_database, run_on_copy  # noqa: F401


@pytest.mark.parametrize("mode", ["apply", "ask"])
def test_two_processes_answer_one_intent(copied_database, mode):  # noqa: F811
    worker = Path(__file__).parent / "helpers" / "parallel_intent_worker.py"
    script = r"""
import json, subprocess, sys, uuid
from django.conf import settings
settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
from django.contrib.auth.models import User
from django.test import RequestFactory
from ai import views
from ai.models import ChatRequest, PendingIntent
from ai.service import AIChatResult
from schedules.models import Schedule, TimeBlock
from asgiref.sync import async_to_sync
user = User.objects.create_user(username='parallel-intent')
scope = {'type':'add','task_id':None,'target_ids':[],
         'known_fields':{'title':'Parallel','category':'work'},
         'missing_fields':['start_time','end_time']}
async def provider(*args):
    return AIChatResult('{}', [], 'Need a time.', 'When?',
                        intent_decision='new', pending_actions=[scope])
views.run_chat = provider
async def auser():
    return user
request = RequestFactory().post('/api/ai/schedules/2027-01-15/chat/',
    json.dumps({'request_id':str(uuid.uuid4()), 'expected_revision':0,
                'messages':[{'role':'user','content':'Add Parallel'}]}),
    content_type='application/json')
request.user, request.auser = user, auser
response = async_to_sync(views.ai_chat)(request, '2027-01-15')
assert response.status_code == 200, response.content
ref = json.loads(response.content)['pending_intent']
processes = [subprocess.Popen([sys.executable, WORKER, sys.argv[1], str(user.pk),
              ref['id'], str(ref['version']), MODE],
              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
statuses = []
for process in processes:
    out, err = process.communicate(timeout=15)
    assert process.returncode == 0, err
    statuses.append(int(out.strip()))
assert sorted(statuses) == [200, 409], statuses
row = PendingIntent.objects.get()
schedule = Schedule.objects.get()
assert ChatRequest.objects.filter(completed_at__isnull=False).count() == 3
if MODE == 'apply':
    assert schedule.revision == 1 and TimeBlock.objects.count() == 1
    assert row.state == 'resolved'
else:
    assert schedule.revision == 0 and TimeBlock.objects.count() == 0
    assert row.version == 2 and row.state == 'open'
"""
    run_on_copy(
        copied_database, script.replace("WORKER", repr(str(worker))).replace("MODE", repr(mode))
    )
