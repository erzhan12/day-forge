// Phase 6 Test 7: AI draft prompt includes per-day completion ratios.
//
// 💸 COST WARNING — one real LLM_DRAFT_MODEL call (gpt-4o by default,
// approximately $0.05–$0.10 per run as of 2026-05).
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
import { readFileSync, existsSync, unlinkSync } from "node:fs"
import {
  BASE,
  CAPTURE_RESPONSE_TIMEOUT_MS,
  USERNAME,
  cleanupSchedules,
  djangoToday,
  failFast,
  login,
  preflight,
  seed,
} from "./test-utils.mjs"
const CAPTURE_PATH = "/tmp/draft_prompt_test7.txt"

await preflight()

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

let browser
try {
  if (existsSync(CAPTURE_PATH)) unlinkSync(CAPTURE_PATH)

  console.log(
    `-> Seeding weekday template + history (with-review=${HIST_WITH_REVIEW}, no-review=${HIST_NO_REVIEW}) and clearing target=${TARGET_DATE}...`,
  )
  seed("seed_schedule", {
    SEED_MODE: "history_suffix",
    SEED_USERNAME: USERNAME,
    SEED_DATE: TARGET_DATE,
    SEED_HISTORY_WITH_REVIEW: HIST_WITH_REVIEW,
    SEED_HISTORY_NO_REVIEW: HIST_NO_REVIEW,
  })

  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()

  const fail = failFast

  console.log("-> Login...")
  await login(page)

  console.log(`-> Navigate to /schedule/${TARGET_DATE}/ (auto-draft trigger)...`)
  const draftRespP = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().includes(`/api/ai/schedules/${TARGET_DATE}/generate-draft/`),
    { timeout: CAPTURE_RESPONSE_TIMEOUT_MS },
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
  await browser?.close()
  cleanupSchedules([HIST_WITH_REVIEW, HIST_NO_REVIEW, TARGET_DATE])
}
