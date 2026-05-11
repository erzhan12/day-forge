#!/usr/bin/env python3
"""
Test 10 — Audit envelope: success carries hash, failure carries error_class.

Usage:
  Phase A (success path, Django running normally):
    uv run python scripts/test10_audit_envelope.py success

  Phase B (failure path, Django pointing at bad LLM URL):
    uv run python scripts/test10_audit_envelope.py failure

The script handles .env editing and Django restart automatically when
the --auto-restart flag is given. Without the flag it pauses and waits
for you to restart manually.
"""

import sys
import os
import json
import subprocess
import time
import requests

BASE = "http://localhost:8006"
CHAT_DATE = "2026-05-10"
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")

PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
INFO = "\033[34m[INFO]\033[0m"

def check(label, actual, expected):
    ok = actual == expected
    print(f"  {PASS if ok else FAIL}  {label}: got {actual!r}, expected {expected!r}")
    return ok

def check_in(label, actual, options):
    ok = actual in options
    print(f"  {PASS if ok else FAIL}  {label}: got {actual!r}, expected one of {options!r}")
    return ok

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.get(f"{BASE}/accounts/login/")
    csrf = s.cookies.get("XSRF-TOKEN")
    r = s.post(f"{BASE}/accounts/login/",
               json={"username": "admin", "password": "admin"},
               headers={"X-XSRF-TOKEN": csrf, "Content-Type": "application/json",
                        "Referer": f"{BASE}/"},
               allow_redirects=False)
    if r.status_code != 302:
        print(f"  {FAIL}  Login failed ({r.status_code})")
        sys.exit(1)
    location = r.headers.get("Location", "")
    if location:
        s.get(f"{BASE}{location}")
    csrf = s.cookies.get("XSRF-TOKEN")
    print(f"  {INFO}  Logged in, sessionid={s.cookies.get('sessionid')[:8]}...")
    return s, csrf

def latest_interaction():
    """Return the most-recent AIInteraction that carries a chat audit envelope
    (identified by transcript_sha256 in the JSON payload)."""
    result = subprocess.run(
        ["uv", "run", "python", "backend/manage.py", "shell", "-c",
         """
import json
from ai.models import AIInteraction
# Chat rows are stored with kind='command' (no Kind.CHAT choice yet).
# Distinguish them by the presence of 'transcript_sha256' in ai_response.
found = None
for r in AIInteraction.objects.order_by('-created_at').iterator():
    try:
        payload = json.loads(r.ai_response)
        if 'transcript_sha256' in payload or 'turn_count' in payload:
            found = (r, payload)
            break
    except Exception:
        pass
if found is None:
    print(json.dumps({"found": False}))
else:
    r, payload = found
    print(json.dumps({
        "found": True,
        "keys": sorted(payload.keys()),
        "turn_count": payload.get("turn_count"),
        "hash_prefix": (payload.get("transcript_sha256") or "")[:12],
        "error_class": payload.get("error_class"),
        "actions_json": r.actions_json,
        "success": r.success,
    }))
"""],
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    for line in result.stdout.strip().splitlines():
        try:
            return json.loads(line)
        except Exception:
            pass
    return {}

def wait_for_server(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(f"{BASE}/accounts/login/", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False

def restart_django(bad_url=False):
    """Edit .env to toggle LLM_BASE_URL, kill & restart Django."""
    env_path = os.path.realpath(ENV_FILE)
    with open(env_path) as f:
        content = f.read()

    if bad_url:
        # point at an unreachable URL
        if "LLM_BASE_URL_REAL=" not in content:
            content = content.replace(
                "LLM_BASE_URL=",
                "LLM_BASE_URL_REAL=__SAVED__\nLLM_BASE_URL=",
            )
        content = content.replace(
            "LLM_BASE_URL=https://openrouter.ai/api/v1",
            "LLM_BASE_URL=http://127.0.0.1:19999/unreachable",
        )
        print(f"  {INFO}  .env: LLM_BASE_URL → unreachable")
    else:
        # restore
        content = content.replace(
            "LLM_BASE_URL=http://127.0.0.1:19999/unreachable",
            "LLM_BASE_URL=https://openrouter.ai/api/v1",
        )
        content = content.replace("LLM_BASE_URL_REAL=__SAVED__\n", "")
        print(f"  {INFO}  .env: LLM_BASE_URL restored")

    with open(env_path, "w") as f:
        f.write(content)

    # kill existing Django dev server
    subprocess.run(["pkill", "-f", "manage.py runserver"], capture_output=True)
    time.sleep(1)
    # restart in background
    log = open("/tmp/django_test10.log", "w")
    subprocess.Popen(
        ["uv", "run", "python", "backend/manage.py", "runserver", "8006"],
        stdout=log, stderr=log,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    print(f"  {INFO}  Django restarting...", end="", flush=True)
    if wait_for_server(30):
        print(" ready.")
    else:
        print(" TIMEOUT — is something wrong?")


# ── Phase A: Success path ──────────────────────────────────────────────────────

def run_success():
    print("\n══ Test 10A — Success path ══")
    s, csrf = make_session()
    headers = {"X-XSRF-TOKEN": csrf, "Content-Type": "application/json"}
    msgs = {"messages": [{"role": "user", "content": "what's on my schedule today?"}]}

    print("\n── Send valid chat turn ──")
    r = s.post(f"{BASE}/api/ai/schedules/{CHAT_DATE}/chat/",
               json=msgs, headers=headers)
    check("HTTP status", r.status_code, 200)

    print("\n── Inspect AIInteraction row ──")
    row = latest_interaction()
    print(f"  {INFO}  keys: {row.get('keys')}")
    print(f"  {INFO}  turn_count: {row.get('turn_count')}")
    print(f"  {INFO}  hash_prefix: {row.get('hash_prefix')}")
    print(f"  {INFO}  error_class: {row.get('error_class')}")
    print(f"  {INFO}  success: {row.get('success')}")

    ok = True
    ok &= check("keys == ['raw','transcript_sha256','turn_count']",
                row.get("keys"), ["raw", "transcript_sha256", "turn_count"])
    ok &= check("error_class is None", row.get("error_class"), None)
    ok &= check("success is True", row.get("success"), True)
    ok &= check("hash_prefix non-empty", bool(row.get("hash_prefix")), True)
    ok &= check("turn_count >= 1", (row.get("turn_count") or 0) >= 1, True)

    print(f"\n{'  All checks PASS ✓' if ok else '  Some checks FAILED ✗'}")
    return ok


# ── Phase B: Failure path ──────────────────────────────────────────────────────

def run_failure(auto_restart=False):
    print("\n══ Test 10B — Failure path ══")

    if auto_restart:
        restart_django(bad_url=True)
    else:
        print(f"  {INFO}  Manually set LLM_BASE_URL to an unreachable URL in .env")
        print(f"  {INFO}  then restart Django, then press Enter here.")
        input("  >> Ready? [Enter] ")

    s, csrf = make_session()
    headers = {"X-XSRF-TOKEN": csrf, "Content-Type": "application/json"}
    msgs = {"messages": [{"role": "user", "content": "hello"}]}

    print("\n── Send chat turn (LLM unreachable, expect 5xx) ──")
    r = s.post(f"{BASE}/api/ai/schedules/{CHAT_DATE}/chat/",
               json=msgs, headers=headers, timeout=20)
    check_in("HTTP status (503=key missing, 502=provider error)", r.status_code, [502, 503])
    try:
        body = r.json()
        detail = body.get("errors", {}).get("detail", "")
        print(f"  {INFO}  errors.detail: {detail!r}")
        ok_503 = "AI" in detail or "disabled" in detail.lower() or "unavailable" in detail.lower()
        print(f"  {PASS if ok_503 else FAIL}  errors.detail contains AI error message")
    except Exception:
        print(f"  {FAIL}  Could not parse 503 body: {r.text[:200]}")

    print("\n── Inspect AIInteraction row ──")
    row = latest_interaction()
    print(f"  {INFO}  keys: {row.get('keys')}")
    print(f"  {INFO}  error_class: {row.get('error_class')}")
    print(f"  {INFO}  actions_json: {row.get('actions_json')}")
    print(f"  {INFO}  success: {row.get('success')}")

    ok = True
    ok &= check("success is False", row.get("success"), False)
    ok &= check_in("error_class in known AI errors",
                   row.get("error_class"),
                   ["AIUnavailableError", "AIProviderError", "AITimeoutError"])
    ok &= check("actions_json == []", row.get("actions_json"), [])
    ok &= check("'error_class' key present in envelope",
                "error_class" in (row.get("keys") or []), True)
    ok &= check("'transcript_sha256' key present",
                "transcript_sha256" in (row.get("keys") or []), True)

    if auto_restart:
        print(f"\n  {INFO}  Restoring .env and restarting Django...")
        restart_django(bad_url=False)
    else:
        print(f"\n  {INFO}  Restore LLM_BASE_URL in .env and restart Django.")

    print(f"\n{'  All checks PASS ✓' if ok else '  Some checks FAILED ✗'}")
    return ok


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "both"
    auto = "--auto-restart" in sys.argv

    if phase in ("success", "both"):
        run_success()

    if phase in ("failure", "both"):
        run_failure(auto_restart=auto)
