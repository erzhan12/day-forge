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
import {
  BASE,
  USERNAME,
  WAIT_FOR_SHORT_SETTLE_MS,
  cleanupSchedules,
  djangoToday,
  login,
  makeFailAggregator,
  postWithCsrf,
  preflight,
  preflightUser,
  seed,
} from "./test-utils.mjs"

const SCHEDULE_DATE = "2027-03-29" // Monday → weekday slot
const EXPECTED_DETAIL = "Schedule already has blocks; delete them before regenerating."

await preflight()
const LOGIN_DATE = djangoToday()
const cleanupDates = [SCHEDULE_DATE]

console.log("→ Pre-flight: confirming playwright user exists…")
preflightUser()

console.log("→ Seeding non-empty schedule + weekday Template…")
try {
  seed("seed_schedule", {
    SEED_MODE: "schedules",
    SEED_USERNAME: USERNAME,
    SEED_SCHEDULES_JSON: JSON.stringify([
      {
        date: SCHEDULE_DATE,
        status: "draft",
        blocks: [{ title: "Existing block", start_time: "09:00", end_time: "10:00", category: "work" }],
      },
    ]),
    SEED_TEMPLATE_JSON: JSON.stringify({
      type: "weekday",
      name: "Playwright Weekday",
      blocks: [{ title: "Deep work", start_time: "09:00", end_time: "12:00", category: "work" }],
    }),
    SEED_MARKER: "seeded non-empty schedule {id} with weekday template",
  })
} catch (err) {
  console.error("\n❌ Seed failed. Is Django running?")
  console.error(err.message)
  process.exit(2)
}

// Login redirects to today. Ensure that row already exists so the redirect
// cannot independently auto-draft and consume the counter this test snapshots.
const loginScheduleOut = seed(
  "seed_schedule",
  {
    SEED_MODE: "ensure_exists",
    SEED_USERNAME: USERNAME,
    SEED_DATE: LOGIN_DATE,
  },
  { encoding: "utf8" },
)
if (loginScheduleOut.includes("CREATED True")) cleanupDates.push(LOGIN_DATE)

// Snapshot counters BEFORE the request so we can assert no mutation.
console.log("→ Snapshotting rate-limit + AIInteraction counters…")
let counterBefore = ""
try {
  counterBefore = seed(
    "seed_schedule",
    {
      SEED_MODE: "snapshot",
      SEED_USERNAME: USERNAME,
      SEED_DATE: SCHEDULE_DATE,
      SEED_SNAPSHOT: "rate_before",
    },
    { encoding: "utf8" },
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

const { failures, fail } = makeFailAggregator()

try {
  console.log("→ Logging in…")
  await login(page)

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
  const postResult = await postWithCsrf(
    page,
    `${BASE}/api/ai/schedules/${SCHEDULE_DATE}/generate-draft/`,
    {},
  )
  await page.waitForTimeout(WAIT_FOR_SHORT_SETTLE_MS)

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
  const afterOut = seed(
    "seed_schedule",
    {
      SEED_MODE: "snapshot",
      SEED_USERNAME: USERNAME,
      SEED_DATE: SCHEDULE_DATE,
      SEED_SNAPSHOT: "rate_after",
    },
    { encoding: "utf8" },
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
  cleanupSchedules(cleanupDates)
}
