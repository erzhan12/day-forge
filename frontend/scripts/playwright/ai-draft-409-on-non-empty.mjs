// Feature 0009 follow-up — Playwright coverage for /generate-draft/ 409 guard.
//
// 💸 COST WARNING — this script DOES NOT make an LLM call. The 409
// precondition short-circuits before _consume_rate_limit AND before
// the LLM is contacted (backend/ai/views.py:653-664 precedes the rate
// limit consumption at line 686). Verifying this short-circuit is the
// entire point of the test.
//
// The Regenerate Draft button is hidden on non-empty schedules, so this
// test bypasses the UI entirely and POSTs directly to /generate-draft/
// from inside the browser context (credentials + CSRF auto-attached).
//
// Scenario:
//   1. Seed schedule on 2027-03-29 (weekday) with ONE existing block.
//   2. Seed weekday Template so the precondition that fails is
//      "blocks exist", NOT "no template".
//   3. UI login → navigate to date.
//   4. Snapshot ai_draft_rl counter and AIInteraction count for this
//      schedule BEFORE the request.
//   5. Direct-POST /generate-draft/ with empty body.
//   6. Wire-level: 409, body {errors: {detail: "Schedule already has
//      blocks; delete them before regenerating."}}.
//   7. DB: no new TimeBlock, no new AIInteraction; rate-limit counter
//      unchanged.
//
// Run from frontend/:
//   node scripts/playwright/ai-draft-409-on-non-empty.mjs
//
// Concurrency: run this script SERIALLY with the other ai-*.mjs scripts.
// They share the `playwright` user and the `ai_cmd_rl` / `ai_draft_rl`
// rate-limit counters, so parallel execution will race on the counters
// and may produce false failures in this script's "no consumption"
// assertion (the before/after snapshot would catch a concurrent
// /generate-draft/ call from another script). Different seed dates
// prevent DB conflicts; the shared counters do not.
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const SCHEDULE_DATE = "2027-03-29" // Monday → weekday slot
const SCHEDULE_DATE_PARTS = [2027, 3, 29]
const EXPECTED_DETAIL = "Schedule already has blocks; delete them before regenerating."

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Pre-flight: confirming playwright user exists…")
try {
  const preflight = execSync(
    `uv run python backend/manage.py shell -c "
from django.contrib.auth.models import User
print('EXISTS', User.objects.filter(username='${USERNAME}').exists())
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )
  if (!preflight.includes("EXISTS True")) {
    console.error("\n❌ playwright user is missing. Run:")
    console.error("   uv run python backend/manage.py createsuperuser")
    console.error(`   (use username '${USERNAME}' / password '${PASSWORD}')`)
    process.exit(2)
  }
} catch (err) {
  console.error("\n❌ Pre-flight shell failed:", err.message)
  process.exit(2)
}

console.log("→ Seeding non-empty schedule + weekday Template…")
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Template
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
s, _ = Schedule.objects.update_or_create(
    user=u, date=datetime.date(${SCHEDULE_DATE_PARTS.join(', ')}), defaults={'status': 'draft'}
)
TimeBlock.objects.filter(schedule=s).delete()
TimeBlock.objects.create(
    schedule=s, title='Existing block',
    start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
    category='work',
)
Template.objects.update_or_create(
    user=u, type='weekday',
    defaults={'name': 'Playwright Weekday', 'blocks': [
        {'title': 'Deep work', 'start_time': '09:00', 'end_time': '12:00', 'category': 'work'},
    ]},
)
print('seeded non-empty schedule', s.id, 'with weekday template')
"`,
    { stdio: "inherit", cwd: REPO_ROOT },
  )
} catch (err) {
  console.error("\n❌ Seed failed. Is Django running?")
  console.error(err.message)
  process.exit(2)
}

// Snapshot counters BEFORE the request so we can assert no mutation.
console.log("→ Snapshotting rate-limit + AIInteraction counters…")
let counterBefore = ""
try {
  counterBefore = execSync(
    `uv run python backend/manage.py shell -c "
from django.core.cache import cache
from django.contrib.auth.models import User
from ai.models import AIInteraction
from schedules.models import Schedule
import datetime
u = User.objects.get(username='${USERNAME}')
s = Schedule.objects.get(user=u, date=datetime.date(${SCHEDULE_DATE_PARTS.join(', ')}))
print('RATE_BEFORE', cache.get(f'ai_draft_rl:{u.id}', 0))
print('AI_BEFORE', AIInteraction.objects.filter(schedule=s).count())
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )
} catch (err) {
  console.error("\n❌ Snapshot shell failed:", err.message)
  process.exit(2)
}

const beforeMap = {}
for (const line of counterBefore.trim().split("\n")) {
  const idx = line.indexOf(" ")
  if (idx !== -1) beforeMap[line.slice(0, idx)] = line.slice(idx + 1)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
})
const page = await context.newPage()

const draftCalls = []
page.on("response", async (resp) => {
  const url = resp.url()
  if (/\/api\/ai\/schedules\/[^/]+\/generate-draft\/$/.test(url)) {
    let bodyText = ""
    try {
      bodyText = await resp.text()
    } catch {
      bodyText = "(could not read body)"
    }
    draftCalls.push({
      url,
      status: resp.status(),
      responseBody: bodyText,
    })
  }
})

const failures = []
function fail(msg) {
  failures.push(msg)
}

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

  // Sanity check: the Regenerate Draft button must NOT be visible on a
  // non-empty schedule. If it is, the UI contract has drifted and the
  // test's premise (button hidden → direct-POST required) is invalid.
  const regenBtn = page.locator(".regen-btn")
  if ((await regenBtn.count()) > 0 && (await regenBtn.isVisible())) {
    fail(
      "regen-btn is visible on a non-empty schedule — UI contract drift. " +
        "Update the v-if guard in Schedule.vue or this test's premise.",
    )
  }

  console.log("→ Direct-POST /generate-draft/ on non-empty schedule…")
  const postResult = await page.evaluate(
    async ({ url }) => {
      const match = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
      const csrf = match ? decodeURIComponent(match[1]) : ""
      if (!csrf) return { error: "no XSRF-TOKEN cookie present" }
      const r = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "content-type": "application/json",
          "x-xsrf-token": csrf,
        },
        body: "{}",
      })
      return { status: r.status, body: await r.text() }
    },
    { url: `${BASE}/api/ai/schedules/${SCHEDULE_DATE}/generate-draft/` },
  )
  await page.waitForTimeout(300)

  console.log("→ Wire-level assertions…")
  if (postResult.error) {
    fail(`fetch precondition error: ${postResult.error}`)
  }
  if (postResult.body && postResult.body.includes("SynchronousOnlyOperation")) {
    fail(
      "ASYNC REGRESSION: response body contains 'SynchronousOnlyOperation' — " +
        "missed await request.auser() or sync ORM call in async path",
    )
  }
  if (draftCalls.length !== 1) {
    fail(`expected exactly 1 /generate-draft/ call, got ${draftCalls.length}`)
  }
  const call = draftCalls[0]
  let parsedResp = null
  if (!call) {
    // Skip the rest of the wire-level block if no call was captured;
    // the count assertion above already recorded the failure, and
    // dereferencing `call.*` would crash the aggregator before the
    // verdict line runs.
  } else if (call.status !== 409) {
    fail(`expected 409, got ${call.status}; body=${call.responseBody.slice(0, 400)}`)
  } else {
    try {
      parsedResp = JSON.parse(call.responseBody)
    } catch {
      fail("409 response body is not JSON")
    }
    if (parsedResp) {
      if (!parsedResp.errors || typeof parsedResp.errors !== "object") {
        fail(`response.errors expected object, got ${JSON.stringify(parsedResp.errors)}`)
      } else if (parsedResp.errors.detail !== EXPECTED_DETAIL) {
        fail(
          `response.errors.detail expected exact string ${JSON.stringify(EXPECTED_DETAIL)}, ` +
            `got ${JSON.stringify(parsedResp.errors.detail)}`,
        )
      }
    }
  }

  console.log("→ DB + counter assertions (no mutation, no rate-limit consumption)…")
  const afterOut = execSync(
    `uv run python backend/manage.py shell -c "
from django.core.cache import cache
from django.contrib.auth.models import User
from ai.models import AIInteraction
from schedules.models import Schedule, TimeBlock
import datetime
u = User.objects.get(username='${USERNAME}')
s = Schedule.objects.get(user=u, date=datetime.date(${SCHEDULE_DATE_PARTS.join(', ')}))
print('RATE_AFTER', cache.get(f'ai_draft_rl:{u.id}', 0))
print('AI_AFTER', AIInteraction.objects.filter(schedule=s).count())
print('BLOCKS', TimeBlock.objects.filter(schedule=s).count())
print('STATUS', s.status)
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )

  const afterMap = {}
  for (const line of afterOut.trim().split("\n")) {
    const idx = line.indexOf(" ")
    if (idx !== -1) afterMap[line.slice(0, idx)] = line.slice(idx + 1)
  }

  if (Number(afterMap.BLOCKS || "-1") !== 1) {
    fail(`TimeBlock count expected 1 (the seeded block), got ${afterMap.BLOCKS}`)
  }
  if (afterMap.AI_AFTER !== beforeMap.AI_BEFORE) {
    fail(
      `AIInteraction count changed: before=${beforeMap.AI_BEFORE} after=${afterMap.AI_AFTER}. ` +
        `409 must short-circuit BEFORE _log_interaction (the non-empty ` +
        `schedule check precedes the audit-row write).`,
    )
  }
  if (afterMap.RATE_AFTER !== beforeMap.RATE_BEFORE) {
    fail(
      `ai_draft_rl counter changed: before=${beforeMap.RATE_BEFORE} after=${afterMap.RATE_AFTER}. ` +
        `409 must short-circuit BEFORE _consume_rate_limit (the non-empty ` +
        `schedule check precedes the rate-limit increment).`,
    )
  }
  if (afterMap.STATUS !== "draft") {
    fail(`schedule.status expected "draft" (unchanged), got ${JSON.stringify(afterMap.STATUS)}`)
  }

  console.log("\n=== Captured /generate-draft/ call ===")
  if (call) {
    console.log(`  status=${call.status}`)
    console.log(`  Response body: ${call.responseBody.slice(0, 400)}`)
  }
  console.log("\n=== Counters before → after ===")
  console.log(`  RATE: ${beforeMap.RATE_BEFORE} → ${afterMap.RATE_AFTER}`)
  console.log(`  AI:   ${beforeMap.AI_BEFORE} → ${afterMap.AI_AFTER}`)
  console.log(`  BLOCKS: ${afterMap.BLOCKS}  STATUS: ${afterMap.STATUS}`)

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — /generate-draft/ 409 short-circuit: no DB mutation, no audit row, no rate-limit consumption")
    process.exitCode = 0
  } else {
    console.log("❌ FAIL —")
    for (const r of failures) console.log(`    • ${r}`)
    process.exitCode = 1
  }
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
