// Phase 6 Test 7: AI draft prompt includes per-day completion ratios.
//
// 💸 COST WARNING — one real LLM_DRAFT_MODEL call (gpt-4o by default).
//
// Strategy: relies on a TEMPORARY patch in backend/ai/service.py:run_draft
// that writes the rendered user_message to /tmp/draft_prompt_test7.txt
// right before the LLM call. Auto-driving the auto-draft flow via
// Playwright gets us the genuine end-to-end path (real LLM call, real
// view query, real prompt builder); the captured file lets us assert
// the suffix invariants the spec pins.
//
// Patch to apply (revert after the run):
//
//   user_message = build_draft_user_message(
//       schedule, template, history_schedules, rules, now
//   )
//   # TEST7-CAPTURE: temporary, revert after Test 7 manual verification.
//   try:
//       with open("/tmp/draft_prompt_test7.txt", "w") as _f:
//           _f.write(user_message)
//   except OSError:
//       pass
//
//   client = _get_client()
//
// Pre-reqs:
//   * Django :8006 with the TEST7-CAPTURE patch applied + autoreloaded.
//   * Vite :5173.
//   * Test user `playwright` with weekday template and history days
//     seeded (2026-05-03 active no DailyReview, 2026-05-04 active with
//     DailyReview 3/4, 2026-05-05 active with DailyReview 2/4).
//   * LLM_API_KEY set.
//   * /schedule/2026-05-08/ MUST NOT exist for `playwright` (auto-draft
//     fires only on never-visited days).
//
// Run from frontend/:
//   node scripts/playwright/draft-prompt-history-suffix.mjs

import { chromium } from "@playwright/test"
import { readFileSync, existsSync, unlinkSync } from "node:fs"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"
const TARGET_DATE = "2026-05-08"
const CAPTURE_PATH = "/tmp/draft_prompt_test7.txt"

if (existsSync(CAPTURE_PATH)) unlinkSync(CAPTURE_PATH)

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
    fail(`capture file ${CAPTURE_PATH} not written - is the TEST7-CAPTURE patch applied & autoreloaded?`)
  }
  const prompt = readFileSync(CAPTURE_PATH, "utf-8")

  console.log("\n========== Recent history section ==========")
  const histStart = prompt.indexOf("Recent history (last days):")
  const histEnd = prompt.indexOf("\n\nActive rules")
  if (histStart < 0 || histEnd < 0) fail("Recent history section markers not found")
  const histSection = prompt.slice(histStart, histEnd)
  console.log(histSection)
  console.log("=============================================\n")

  // Assertions on Recent history content.
  const checks = [
    {
      name: "2026-05-04 (Monday) has suffix (completed: 3/4)",
      pass: /^# 2026-05-04 \(Monday\) \(completed: 3\/4\)$/m.test(histSection),
    },
    {
      name: "2026-05-05 (Tuesday) has suffix (completed: 2/4)",
      pass: /^# 2026-05-05 \(Tuesday\) \(completed: 2\/4\)$/m.test(histSection),
    },
    {
      name: "2026-05-03 (Sunday) has NO suffix",
      pass: /^# 2026-05-03 \(Sunday\)$/m.test(histSection),
    },
    {
      name: "2026-05-03 line does NOT contain '(completed:'",
      pass: !/^# 2026-05-03 \(Sunday\) \(completed:/m.test(histSection),
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
