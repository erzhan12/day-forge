// Phase 5 Test 6 reproduction: AI command no-op must NOT flip status
// from draft to active.
//
// 💸 COST WARNING — this script makes a REAL LLM call against the
// configured provider (``LLM_API_KEY`` + ``LLM_BASE_URL`` from .env).
// One run = one billable command-bar request. Don't loop this in CI
// without mocking; for that, prefer the unit-level test in
// ``backend/tests/test_ai_views.py`` which patches ``run_command``.
// The script's value is end-to-end fidelity — verifying the model
// genuinely does the right thing on an irrelevant prompt — which is
// exactly what mocks would hide.
//
// Scenario: a freshly drafted schedule (status=draft, blocks present)
// receives an irrelevant/refusable command via the command bar. The
// expected backend response is HTTP 200 with ``actions: []`` and a
// short explanation. The status MUST remain "draft".
//
// User's doubt: modern LLMs don't always honour "return zero actions"
// — they may hallucinate an action, return ``actions: null``, or fail
// schema validation (502). This script captures the actual response
// shape so we can see what the model really did.
//
// Run from frontend/:
//
//   node scripts/playwright/ai-command-noop.mjs
//
// Pre-reqs:
//   * Django on :8006, Vite on :5173
//   * Test user ``playwright`` (see WARNING below)
//   * ``LLM_API_KEY`` set in .env (this calls the real LLM)
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY (see other playwright scripts
// for the user-creation snippet and rationale).

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// Far-future date, deterministic for this test. Different from the
// double-save script's date so the two don't fight over state.
const SCHEDULE_DATE = "2026-08-19"
const SEED_TITLE = "Existing block"
const COMMAND = "what's the weather like"

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Seeding draft schedule + 1 block via Django shell…")
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
s, _ = Schedule.objects.update_or_create(
    user=u, date=datetime.date(2026, 8, 19), defaults={'status': 'draft'}
)
TimeBlock.objects.filter(schedule=s).delete()
TimeBlock.objects.create(
    schedule=s, title='${SEED_TITLE}', start_time='09:00',
    end_time='10:00', category='work',
)
print('seeded schedule', s.id, 'status=', s.status)
"`,
    { stdio: "inherit", cwd: REPO_ROOT },
  )
} catch (err) {
  console.error("\n❌ Seed failed. Is Django running? Does the playwright user exist?")
  console.error(err.message)
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
})
const page = await context.newPage()

// Capture the AI command request + response in detail
const aiCalls = []
page.on("response", async (resp) => {
  const url = resp.url()
  if (/\/api\/ai\/schedules\/[^/]+\/command\/$/.test(url)) {
    let bodyText = ""
    try {
      bodyText = await resp.text()
    } catch {
      bodyText = "(could not read body)"
    }
    aiCalls.push({
      url,
      status: resp.status(),
      contentType: resp.headers()["content-type"] || "",
      body: bodyText,
    })
  }
})

try {
  console.log("→ Logging in…")
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
  await page.fill("#username", USERNAME)
  await page.fill("#password", PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])

  console.log(`→ Opening /schedule/${SCHEDULE_DATE}/…`)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, {
    waitUntil: "networkidle",
  })

  // Confirm we're starting in draft state with the block visible
  const startBadge = await page.locator(".draft-badge").count()
  const blockExists = await page
    .locator(".title")
    .filter({ hasText: SEED_TITLE })
    .count()
  console.log(
    `→ Initial state: draft badge=${startBadge > 0 ? "yes" : "no"}, block visible=${blockExists > 0 ? "yes" : "no"}`,
  )

  console.log(`→ Submitting command via CommandBar: "${COMMAND}"…`)
  const cmdInput = page.locator(".command-input")
  await cmdInput.waitFor({ timeout: 3000 })
  await cmdInput.fill(COMMAND)

  // Wait for the AI response and the keystroke that triggers it in
  // parallel — ``waitForResponse`` is the idiomatic Playwright way to
  // sync on a specific URL (cleaner than a poll loop on a captured
  // array). The 20s timeout matches LLM_REQUEST_TIMEOUT (default 15s)
  // with headroom for network jitter.
  console.log(`→ Submitting + waiting for /api/ai/schedules/.../command/ response…`)
  await Promise.all([
    page.waitForResponse(
      (resp) => /\/api\/ai\/schedules\/[^/]+\/command\/$/.test(resp.url()),
      { timeout: 20_000 },
    ),
    cmdInput.press("Enter"),
  ])
  // Small grace period for the partial reload + Vue state to settle
  // before we assert on the DB.
  await page.waitForTimeout(500)

  // Re-check status by visiting Django shell (post-mutation)
  const dbStatusOut = execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule
s = Schedule.objects.get(date='${SCHEDULE_DATE}', user__username='${USERNAME}')
print(s.status)
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )
  const dbStatus = dbStatusOut.trim().split("\n").pop().trim()

  console.log("\n=== Captured AI calls ===")
  if (aiCalls.length === 0) {
    console.log("(none — endpoint never responded)")
  }
  for (const call of aiCalls) {
    console.log(`  Status: ${call.status}`)
    console.log(`  Content-Type: ${call.contentType}`)
    console.log(`  Body (first 500 chars):`)
    console.log(`    ${call.body.slice(0, 500)}`)
  }

  console.log(`\n=== DB status after ===`)
  console.log(`  Schedule.status = ${dbStatus}`)

  console.log(`\n=== Verdict ===`)
  let pass = true
  let reasons = []

  if (aiCalls.length !== 1) {
    pass = false
    reasons.push(`expected 1 AI call, got ${aiCalls.length}`)
  } else {
    const call = aiCalls[0]
    if (call.status !== 200) {
      pass = false
      reasons.push(`expected HTTP 200, got ${call.status}`)
    }
    let parsed
    try {
      parsed = JSON.parse(call.body)
    } catch {
      pass = false
      reasons.push(`response body is not JSON`)
    }
    if (parsed) {
      // The endpoint returns { blocks: [...], explanation: "..." } on
      // success. ``actions`` isn't in the response shape — it lives
      // server-side in AIInteraction.actions_json. The user-facing
      // proxy for "no-op" is: blocks unchanged from pre-submit.
      if (!Array.isArray(parsed.blocks)) {
        pass = false
        reasons.push(`response.blocks is not an array (got ${typeof parsed.blocks})`)
      }
      if (typeof parsed.explanation !== "string") {
        pass = false
        reasons.push(
          `response.explanation is not a string (got ${typeof parsed.explanation})`,
        )
      }
      // Diagnostic — print the LLM's actual answer
      if (parsed.explanation) {
        console.log(`  LLM explanation: "${parsed.explanation}"`)
      }
      if (Array.isArray(parsed.blocks)) {
        console.log(`  Returned blocks count: ${parsed.blocks.length} (was 1 pre-submit)`)
      }
    }
  }

  if (dbStatus !== "draft") {
    pass = false
    reasons.push(`Schedule.status is "${dbStatus}", expected "draft"`)
  }

  if (pass) {
    console.log("✅ PASS — command bar no-op preserved status=draft")
  } else {
    console.log("❌ FAIL —")
    for (const r of reasons) console.log(`    • ${r}`)
  }
  process.exitCode = pass ? 0 : 1
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
