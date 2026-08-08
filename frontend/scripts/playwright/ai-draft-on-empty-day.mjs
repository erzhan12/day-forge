// Feature 0009 follow-up — Playwright coverage for /generate-draft/ happy path.
//
// 💸 COST WARNING — one real LLM call per run (uses LLM_DRAFT_MODEL,
// typically 5–10× the cost of LLM_MODEL). Don't loop in CI.
//
// /generate-draft/ has a UI driver (RegenerateDraftButton, .regen-btn),
// visible only when schedule.status='draft' AND blocks.length===0 AND
// the user has a matching template. This script seeds all three and
// clicks the real button.
//
// Scenario:
//   1. Seed empty draft schedule on 2027-03-22 (weekday).
//   2. Seed/refresh a weekday Template for the playwright user with a
//      minimal blocks list (the LLM uses it as context).
//   3. UI login → navigate to date.
//   4. Wait for .regen-btn enabled, click it.
//   5. Wait for /generate-draft/ response.
//   6. Wire-level: 200, body {blocks: [...], explanation: string},
//      blocks.length >= 1.
//   7. DB: ≥1 TimeBlock; latest AIInteraction has kind=draft,
//      success=True, user_command='[DRAFT]'; schedule.status
//      STAYS 'draft' (drafts NEVER promote to active).
//
// Run from frontend/:
//   node scripts/playwright/ai-draft-on-empty-day.mjs
//
// Concurrency: run this script SERIALLY with the other ai-*.mjs scripts.
// They share the `playwright` user and the `ai_cmd_rl` / `ai_draft_rl`
// rate-limit counters, so parallel execution will race on the counters
// and may produce false failures in the 409 script's "no consumption"
// assertion. Different seed dates prevent DB conflicts; the shared
// counters do not.
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY.

import { chromium } from "@playwright/test"
import {
  BASE,
  DRAFT_RESPONSE_TIMEOUT_MS,
  ELEMENT_TIMEOUT_MS,
  USERNAME,
  WAIT_FOR_DRAFT_OVERLAY_MS,
  cleanupSchedules,
  login,
  makeFailAggregator,
  preflight,
  preflightUser,
  seed,
} from "./test-utils.mjs"

const SCHEDULE_DATE = "2027-03-22" // Monday → weekday slot
await preflight()

console.log("→ Pre-flight: confirming playwright user exists…")
preflightUser()

const { failures, fail } = makeFailAggregator()

let browser
try {
  console.log("→ Seeding empty draft schedule + weekday Template…")
  seed("seed_schedule", {
    SEED_MODE: "schedules",
    SEED_USERNAME: USERNAME,
    SEED_SCHEDULES_JSON: JSON.stringify([
      { date: SCHEDULE_DATE, status: "draft", blocks: [] },
    ]),
    SEED_TEMPLATE_JSON: JSON.stringify({
      type: "weekday",
      name: "Playwright Weekday",
      blocks: [
        { title: "Morning routine", start_time: "07:00", end_time: "07:30", category: "health" },
        { title: "Deep work", start_time: "09:00", end_time: "12:00", category: "work" },
        { title: "Lunch", start_time: "12:00", end_time: "13:00", category: "personal" },
        { title: "Afternoon work", start_time: "13:00", end_time: "17:00", category: "work" },
      ],
    }),
    SEED_MARKER: "seeded empty schedule {id} with weekday template",
  })

  browser = await chromium.launch({ headless: true })
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
      let requestBody = ""
      try {
        requestBody = resp.request().postData() || ""
      } catch {
        requestBody = "(could not read request body)"
      }
      draftCalls.push({
        url,
        status: resp.status(),
        requestBody,
        responseBody: bodyText,
      })
    }
  })

  console.log("→ Logging in…")
  await login(page)

  console.log(`→ Opening /schedule/${SCHEDULE_DATE}/…`)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, {
    waitUntil: "networkidle",
  })

  console.log("→ Waiting for .regen-btn to be visible and enabled…")
  const regenBtn = page.locator(".regen-btn")
  await regenBtn.waitFor({ state: "visible", timeout: ELEMENT_TIMEOUT_MS })
  const initiallyDisabled = await regenBtn.isDisabled()
  if (initiallyDisabled) {
    fail("regen-btn was disabled — template not configured or API unhealthy?")
  }

  console.log("→ Clicking .regen-btn and awaiting /generate-draft/ response…")
  await Promise.all([
    page.waitForResponse(
      (resp) => /\/api\/ai\/schedules\/[^/]+\/generate-draft\/$/.test(resp.url()),
      { timeout: DRAFT_RESPONSE_TIMEOUT_MS }, // draft model is heavier; allow more time
    ),
    regenBtn.click(),
  ])
  // Give Inertia partial reload time to settle and the overlay to dismiss.
  await page.waitForTimeout(WAIT_FOR_DRAFT_OVERLAY_MS)

  console.log("→ Wire-level assertions…")
  if (draftCalls.length !== 1) {
    fail(`expected exactly 1 /generate-draft/ call, got ${draftCalls.length}`)
  }
  const call = draftCalls[0]
  if (!call) {
    // Skip the rest of the wire-level block if no call was captured;
    // the count assertion above already recorded the failure, and
    // dereferencing `call.*` would crash the aggregator before the
    // verdict line runs.
  } else {
    if (call.responseBody && call.responseBody.includes("SynchronousOnlyOperation")) {
      fail(
        "ASYNC REGRESSION: response body contains 'SynchronousOnlyOperation' — " +
          "missed await request.auser() or sync ORM call in async path",
      )
    }
    if (call.status !== 200) {
      fail(`response expected 200, got ${call.status}; body=${call.responseBody.slice(0, 400)}`)
    } else {
      let parsedResp = null
      try {
        parsedResp = JSON.parse(call.responseBody)
      } catch {
        fail("response body is not JSON")
      }
      if (parsedResp) {
        if (!Array.isArray(parsedResp.blocks) || parsedResp.blocks.length < 1) {
          fail(`response.blocks expected array with ≥1 entry, got ${JSON.stringify(parsedResp.blocks).slice(0, 200)}`)
        }
        if (typeof parsedResp.explanation !== "string") {
          fail(`response.explanation expected string, got ${typeof parsedResp.explanation}`)
        }
      }
    }
  }

  console.log("→ DB assertions…")
  const dbStateOut = seed(
    "seed_schedule",
    {
      SEED_MODE: "snapshot",
      SEED_USERNAME: USERNAME,
      SEED_DATE: SCHEDULE_DATE,
      SEED_SNAPSHOT: "draft",
    },
    { encoding: "utf8" },
  )

  const dbLines = dbStateOut.trim().split("\n").filter((l) => l.trim() !== "")
  const dbMap = {}
  for (const line of dbLines) {
    const idx = line.indexOf(" ")
    if (idx === -1) {
      dbMap[line] = ""
    } else {
      dbMap[line.slice(0, idx)] = line.slice(idx + 1)
    }
  }

  if (dbMap.STATUS !== "draft") {
    fail(
      `NON-PROMOTION REGRESSION: schedule.status expected to stay "draft" ` +
        `after a successful draft generation (drafts NEVER promote to ` +
        `active — only /command/ does, gated on non-empty actions), got ` +
        `${JSON.stringify(dbMap.STATUS)}.`,
    )
  }
  const blockCount = Number(dbMap.BLOCKS || "0")
  if (blockCount < 1) {
    fail(`expected ≥1 TimeBlock after draft, got ${blockCount}`)
  }
  if ("NO_AI_ROW" in dbMap) {
    fail("no AIInteraction row created for this schedule")
  } else {
    if (dbMap.KIND !== "draft") {
      fail(`AIInteraction.kind expected "draft", got ${JSON.stringify(dbMap.KIND)}`)
    }
    if (dbMap.SUCCESS !== "True") {
      fail(`AIInteraction.success expected True, got ${JSON.stringify(dbMap.SUCCESS)}`)
    }
    if (dbMap.USER_COMMAND !== "[DRAFT]") {
      fail(`AIInteraction.user_command expected "[DRAFT]", got ${JSON.stringify(dbMap.USER_COMMAND)}`)
    }
    if (Number(dbMap.ACTIONS_LEN || "0") < 1) {
      fail(`AIInteraction.actions_json expected ≥1 entry, got ${dbMap.ACTIONS_LEN}`)
    }
  }

  // The history DailyReview eager-load is guarded by
  // backend/tests/test_ai_views_draft_nplus1.py.

  console.log("\n=== Captured /generate-draft/ call ===")
  if (call) {
    console.log(`  status=${call.status}`)
    console.log(`  Response body: ${call.responseBody.slice(0, 500)}`)
  }
  console.log("\n=== DB after ===")
  console.log(dbStateOut.trim())

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — /generate-draft/ happy path: blocks generated, status stays draft, audit row correct")
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
  await browser?.close()
  cleanupSchedules([SCHEDULE_DATE])
}
