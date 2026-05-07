// Phase 6 Test 7: AI draft prompt includes per-day completion ratios.
//
// 💸 COST WARNING — one real LLM_DRAFT_MODEL call (gpt-4o by default).
//
// Strategy: backend/ai/service.py:run_draft writes the rendered user_message
// to settings.LLM_DRAFT_CAPTURE_PROMPT_PATH when that setting is non-empty.
// We set it to /tmp/draft_prompt_test7.txt via .env, drive the auto-draft
// flow via Playwright (genuine end-to-end: real LLM call, real view query,
// real prompt builder), and assert the captured prompt's suffix invariants.
//
// Setup (one-time per machine):
//   1. Add to .env:  LLM_DRAFT_CAPTURE_PROMPT_PATH=/tmp/draft_prompt_test7.txt
//   2. Restart Django so settings.py picks up the new value.
//   3. Run this script. The capture file is overwritten on every draft.
//   4. Optionally remove the line from .env when done — capture is opt-in.
//
// Pre-reqs:
//   * Django :8006 with LLM_DRAFT_CAPTURE_PROMPT_PATH set + restarted.
//   * Vite :5173.
//   * Test user `playwright`.
//   * LLM_API_KEY set.
//
// Dates (target weekday + 2 history days) are computed from Django's
// `timezone.localdate()` at run time, and the script seeds the weekday
// template + history days inline. Idempotent across re-runs.
//
// Run from frontend/:
//   node scripts/playwright/draft-prompt-history-suffix.mjs

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { readFileSync, existsSync, unlinkSync } from "node:fs"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"
const CAPTURE_PATH = "/tmp/draft_prompt_test7.txt"

const REPO_ROOT = resolve(process.cwd(), "..")

function djangoToday() {
  const out = execSync(
    `uv run python backend/manage.py shell -c "from django.utils import timezone; print(timezone.localdate().isoformat())"`,
    { cwd: REPO_ROOT },
  ).toString()
  const match = out.match(/^\d{4}-\d{2}-\d{2}$/m)
  if (!match) throw new Error(`could not parse Django date from:\n${out}`)
  return match[0]
}

function daysBefore(isoDate, n) {
  const d = new Date(isoDate + "T00:00:00Z")
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

function nextWeekday(isoDate, minDelta) {
  const d = new Date(isoDate + "T00:00:00Z")
  d.setUTCDate(d.getUTCDate() + minDelta)
  while (d.getUTCDay() === 0 || d.getUTCDay() === 6) {
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return d.toISOString().slice(0, 10)
}

function weekdayName(isoDate) {
  return new Date(isoDate + "T00:00:00Z").toLocaleDateString("en-US", {
    weekday: "long",
    timeZone: "UTC",
  })
}

const TODAY = djangoToday()
// "Fresh future weekday" — far enough out that history-window covers our
// seeded history days. With LLM_HISTORY_DAYS=7, history range is
// [TARGET-7, TARGET); TODAY-2 and TODAY-1 must fit. TARGET = next-weekday-at-+3
// keeps TARGET ≤ TODAY+5, so TARGET-7 ≤ TODAY-2.
const TARGET_DATE = nextWeekday(TODAY, 3)
const HIST_WITH_REVIEW = daysBefore(TODAY, 1)
const HIST_NO_REVIEW = daysBefore(TODAY, 2)

if (existsSync(CAPTURE_PATH)) unlinkSync(CAPTURE_PATH)

console.log(
  `-> Seeding weekday template + history (with-review=${HIST_WITH_REVIEW}, no-review=${HIST_NO_REVIEW}) and clearing target=${TARGET_DATE}...`,
)
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from analytics.services import recompute_review_from_schedule
from analytics.models import DailyReview
from templates_mgr.models import Template
from django.contrib.auth.models import User
import datetime as dt
u = User.objects.get(username='${USERNAME}')

# Weekday template — required for auto-draft to fire on the target date
if not Template.objects.filter(user=u, type='weekday').exists():
    Template.objects.create(user=u, type='weekday', name='Auto-test weekday', blocks=[
        {'title': 'Standup', 'start_time': '09:00', 'end_time': '09:30', 'category': 'work'},
    ])

# History day WITH DailyReview (suffix expected: 'completed: 3/4')
hw = dt.date.fromisoformat('${HIST_WITH_REVIEW}')
s_w, _ = Schedule.objects.update_or_create(user=u, date=hw, defaults={'status': 'active'})
s_w.time_blocks.all().delete()
TimeBlock.objects.create(schedule=s_w, title='Standup',   start_time='09:00', end_time='09:30', category='work',     is_completed=True,  sort_order=0)
TimeBlock.objects.create(schedule=s_w, title='Deep work', start_time='10:00', end_time='12:00', category='work',     is_completed=True,  sort_order=1)
TimeBlock.objects.create(schedule=s_w, title='Lunch',     start_time='12:30', end_time='13:30', category='personal', is_completed=True,  sort_order=2)
TimeBlock.objects.create(schedule=s_w, title='Email',     start_time='14:00', end_time='15:00', category='work',     is_completed=False, sort_order=3)
recompute_review_from_schedule(s_w)

# History day WITHOUT DailyReview (no suffix expected)
hn = dt.date.fromisoformat('${HIST_NO_REVIEW}')
s_n, _ = Schedule.objects.update_or_create(user=u, date=hn, defaults={'status': 'active'})
s_n.time_blocks.all().delete()
TimeBlock.objects.create(schedule=s_n, title='Sunday run', start_time='09:00', end_time='10:00', category='health',  is_completed=True,  sort_order=0)
TimeBlock.objects.create(schedule=s_n, title='Plan week',  start_time='11:00', end_time='12:00', category='personal', is_completed=False, sort_order=1)
DailyReview.objects.filter(schedule=s_n).delete()  # ensure no review row

# Clear target date so auto-draft fires on a never-visited day
target = dt.date.fromisoformat('${TARGET_DATE}')
Schedule.objects.filter(user=u, date=target).delete()
print(f'seeded with-review={hw} no-review={hn} target={target}')
"`,
    { stdio: "inherit", cwd: REPO_ROOT },
  )
} catch (err) {
  console.error("\nSeed failed (Django running? user 'playwright' exists?)")
  console.error(err.message)
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()

function fail(msg) {
  console.error(`\n FAIL  ${msg}`)
  throw new Error(msg)
}

try {
  console.log("-> Login...")
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
  await page.fill("#username", USERNAME)
  await page.fill("#password", PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])

  console.log(`-> Navigate to /schedule/${TARGET_DATE}/ (auto-draft trigger)...`)
  const draftRespP = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().includes(`/api/ai/schedules/${TARGET_DATE}/generate-draft/`),
    { timeout: 120_000 },
  )
  await page.goto(`${BASE}/schedule/${TARGET_DATE}/`, { waitUntil: "domcontentloaded" })
  const draftResp = await draftRespP
  console.log(`   POST /generate-draft/ -> ${draftResp.status()}`)
  if (draftResp.status() !== 200) {
    fail(`expected 200 from generate-draft, got ${draftResp.status()}`)
  }

  console.log("-> Reading captured prompt...")
  if (!existsSync(CAPTURE_PATH)) {
    fail(
      `capture file ${CAPTURE_PATH} not written - is LLM_DRAFT_CAPTURE_PROMPT_PATH=${CAPTURE_PATH} ` +
      `set in .env and Django restarted? See script header for setup.`,
    )
  }
  const prompt = readFileSync(CAPTURE_PATH, "utf-8")

  console.log("\n========== Recent history section ==========")
  const histStart = prompt.indexOf("Recent history (last days):")
  const histEnd = prompt.indexOf("\n\nActive rules")
  if (histStart < 0 || histEnd < 0) fail("Recent history section markers not found")
  const histSection = prompt.slice(histStart, histEnd)
  console.log(histSection)
  console.log("=============================================\n")

  // Assertions on Recent history content. Date + weekday name are computed
  // dynamically so the script doesn't rot when the calendar advances.
  const wWeekday = weekdayName(HIST_WITH_REVIEW)
  const nWeekday = weekdayName(HIST_NO_REVIEW)
  const checks = [
    {
      name: `${HIST_WITH_REVIEW} (${wWeekday}) has suffix (completed: 3/4)`,
      pass: new RegExp(
        `^# ${HIST_WITH_REVIEW} \\(${wWeekday}\\) \\(completed: 3/4\\)$`,
        "m",
      ).test(histSection),
    },
    {
      name: `${HIST_NO_REVIEW} (${nWeekday}) has NO suffix`,
      pass: new RegExp(
        `^# ${HIST_NO_REVIEW} \\(${nWeekday}\\)$`,
        "m",
      ).test(histSection),
    },
    {
      name: `${HIST_NO_REVIEW} line does NOT contain '(completed:'`,
      pass: !new RegExp(
        `^# ${HIST_NO_REVIEW} \\(${nWeekday}\\) \\(completed:`,
        "m",
      ).test(histSection),
    },
  ]
  let passed = 0
  for (const c of checks) {
    console.log(`   ${c.pass ? "OK  " : "FAIL"} ${c.name}`)
    if (c.pass) passed++
  }
  if (passed !== checks.length) {
    fail(`${checks.length - passed}/${checks.length} assertion(s) failed`)
  }

  console.log(`\nPASS - all ${checks.length} prompt-shape invariants hold.`)
  process.exitCode = 0
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
