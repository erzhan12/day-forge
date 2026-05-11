#!/usr/bin/env python3
"""
Test 9 — Independent rate-limit bucket from command + draft.

Pre-conditions:
  - LLM_CHAT_RATE_LIMIT_PER_HOUR=2 set in .env
  - Django restarted
  - admin user exists, schedules exist for 2026-05-10
  - no schedule for 2026-11-01 (used for draft)
"""

import sys
import requests

BASE = "http://localhost:8006"
CHAT_DATE = "2026-05-10"
CMD_DATE  = "2026-05-10"
DRAFT_DATE = "2026-10-05"  # empty Monday — weekday template exists

PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"

def check(label, actual, expected):
    ok = actual == expected
    symbol = PASS if ok else FAIL
    print(f"  {symbol}  {label}: got {actual}, expected {expected}")
    return ok

session = requests.Session()

# ── 1. Login ──────────────────────────────────────────────────────────────────
print("\n── Login ──")
session.get(f"{BASE}/accounts/login/")
csrf = session.cookies.get("XSRF-TOKEN")
r = session.post(
    f"{BASE}/accounts/login/",
    json={"username": "admin", "password": "admin"},
    headers={
        "X-XSRF-TOKEN": csrf,
        "Content-Type": "application/json",
        "Referer": f"{BASE}/",
    },
    allow_redirects=False,
)
location = r.headers.get("Location", "")
print(f"  login → {r.status_code} {location}")
# Django rotates XSRF-TOKEN on login — pick it up from the Set-Cookie header
csrf = session.cookies.get("XSRF-TOKEN") or csrf
print(f"  sessionid: {session.cookies.get('sessionid')}")
# Follow the redirect so the session is fully established
if location:
    session.get(f"{BASE}{location}")
    csrf = session.cookies.get("XSRF-TOKEN") or csrf
print(f"  csrf after login: {csrf[:12]}...")
if r.status_code != 302:
    print("  !! Login failed — check credentials")
    sys.exit(1)

csrf = session.cookies.get("XSRF-TOKEN")
headers = {"X-XSRF-TOKEN": csrf, "Content-Type": "application/json"}
MSGS = {"messages": [{"role": "user", "content": "hello"}]}

# ── 2. Two valid chat turns → 200 each ───────────────────────────────────────
print("\n── Chat turn 1 (expect 200) ──")
r1 = session.post(f"{BASE}/api/ai/schedules/{CHAT_DATE}/chat/",
                  json=MSGS, headers=headers)
check("turn 1", r1.status_code, 200)

print("\n── Chat turn 2 (expect 200) ──")
r2 = session.post(f"{BASE}/api/ai/schedules/{CHAT_DATE}/chat/",
                  json=MSGS, headers=headers)
check("turn 2", r2.status_code, 200)

# ── 3. Third chat turn → 429 ─────────────────────────────────────────────────
print("\n── Chat turn 3 (expect 429) ──")
r3 = session.post(f"{BASE}/api/ai/schedules/{CHAT_DATE}/chat/",
                  json=MSGS, headers=headers)
check("turn 3 status", r3.status_code, 429)
try:
    body = r3.json()
    expected_msg = "Rate limit exceeded. Try again later."
    got_msg = body.get("errors", {}).get("detail", "")
    check("turn 3 body", got_msg, expected_msg)
except Exception:
    print(f"  {FAIL}  Could not parse 429 body: {r3.text[:200]}")

# ── 4. Command endpoint → 200 (independent bucket) ───────────────────────────
print("\n── Command endpoint (expect 200, independent bucket) ──")
cmd_headers = {"X-XSRF-TOKEN": csrf, "Content-Type": "application/json"}
r4 = session.post(f"{BASE}/api/ai/schedules/{CMD_DATE}/command/",
                  json={"command": "add a 15-min break at 23:30"},
                  headers=cmd_headers)
check("command endpoint", r4.status_code, 200)

# ── 5. Draft endpoint → 200 (independent bucket) ─────────────────────────────
print("\n── Draft endpoint (expect 200, independent bucket) ──")
r5 = session.post(f"{BASE}/api/ai/schedules/{DRAFT_DATE}/generate-draft/",
                  headers={"X-XSRF-TOKEN": csrf})
check("draft endpoint", r5.status_code, 200)

# ── 6. Verify cache counters ─────────────────────────────────────────────────
print("\n── Cache state ──")
import subprocess, json as jsonlib

result = subprocess.run(
    ["uv", "run", "python", "backend/manage.py", "shell", "-c",
     """
from django.core.cache import cache
from django.contrib.auth.models import User
uid = User.objects.get(username='admin').id
chat  = cache.get(f'ai_chat_rl:{uid}')
cmd   = cache.get(f'ai_cmd_rl:{uid}')
draft = cache.get(f'ai_draft_rl:{uid}')
import json
print(json.dumps({'chat': chat, 'cmd': cmd, 'draft': draft}))
"""],
    capture_output=True, text=True,
    cwd="/Users/erzhan/DATA/PROJ/day-forge"
)
raw = result.stdout.strip().splitlines()
data = {}
for line in raw:
    try:
        data = jsonlib.loads(line)
        break
    except Exception:
        pass

print(f"  cache raw: {data}")
check("ai_chat_rl  (expect 3)", data.get("chat"), 3)
check("ai_cmd_rl   (expect 1)", data.get("cmd"),  1)
check("ai_draft_rl (expect 1)", data.get("draft"), 1)

print("\n── Done ──\n")
