// Issue #226: a follow-up must refine the existing block or finish a pending
// add, depending on the real provider's first response. Both branches must
// end with exactly one Work block at 14:00–15:00. Two real provider calls.
import assert from "node:assert/strict"
import { chromium } from "@playwright/test"
import {
  BASE,
  CAPTURE_RESPONSE_TIMEOUT_MS,
  CHAT_INPUT_TIMEOUT_MS,
  USERNAME,
  cleanupSchedules,
  login,
  preflight,
  seed,
} from "./test-utils.mjs"

const SCHEDULE_DATE = "2026-09-21"
await preflight()
let browser
try {
  seed("seed_schedule", {
    SEED_MODE: "schedules",
    SEED_USERNAME: USERNAME,
    SEED_SCHEDULES_JSON: JSON.stringify([
      { date: SCHEDULE_DATE, status: "draft", blocks: [] },
    ]),
  })
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await login(page)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, { waitUntil: "networkidle" })

  async function snapshot() {
    const response = await page.request.get(`${BASE}/schedule/${SCHEDULE_DATE}/`, {
      headers: { "X-Inertia": "true", "X-Requested-With": "XMLHttpRequest" },
    })
    assert.equal(response.status(), 200)
    return (await response.json()).props.blocks
  }

  async function submit(text) {
    // The HTTP response arrives before client reconciliation settles. Wait
    // for the visible processing state rather than a fixed 500 ms delay.
    await page.locator('[aria-label="Processing…"]').waitFor({ state: "hidden" })
    const input = page.getByTestId("chat-input")
    await input.waitFor({ timeout: CHAT_INPUT_TIMEOUT_MS })
    await input.fill(text)
    const [response] = await Promise.all([
      page.waitForResponse(
        r => /\/api\/ai\/schedules\/[^/]+\/chat\/$/.test(r.url()),
        { timeout: CAPTURE_RESPONSE_TIMEOUT_MS },
      ),
      input.press("Enter"),
    ])
    const data = await response.json()
    const request = response.request().postDataJSON()
    assert.equal(response.status(), 200, JSON.stringify(data))
    await page.locator('[aria-label="Processing…"]').waitFor({
      state: "hidden", timeout: CAPTURE_RESPONSE_TIMEOUT_MS,
    })
    console.log(JSON.stringify({ text, request: {
      messages: request.messages, expected_revision: request.expected_revision,
    }, response: {
      applied: data.applied, ask: data.ask, explanation: data.explanation,
      blocks: data.blocks?.map(({ id, title, start_time, end_time, category }) =>
        ({ id, title, start_time, end_time, category })),
      outcomes: data.outcomes,
    } }, null, 2))
    return { data, request }
  }

  const first = await submit("запланируй встречу")
  const before = await snapshot()
  assert.equal(first.request.messages.length, 1)
  if (first.data.applied) {
    assert.equal(first.data.ask, null)
    assert.equal(before.length, 1)
    console.log("Branch: immediate add, then refinement of the same ID")
  } else {
    assert.ok(first.data.ask, "First turn must add or ask")
    assert.equal(before.length, 0)
    console.log("Branch: pending question, then one add")
  }

  const second = await submit("в 14:00 на час, рабочая")
  assert.deepEqual(second.request.messages.map(m => m.role), ["user", "assistant", "user"])
  assert.equal(second.data.applied, true)
  assert.equal(second.data.ask, null)
  const after = await snapshot()
  assert.equal(after.length, 1, "Follow-up must not create a duplicate")
  const block = after[0]
  assert.equal(block.start_time.slice(0, 5), "14:00")
  assert.equal(block.end_time.slice(0, 5), "15:00")
  assert.equal(block.category, "work")
  if (first.data.applied) assert.equal(block.id, before[0].id)
  console.log("Persisted:", JSON.stringify({
    id: block.id, title: block.title, start_time: block.start_time,
    end_time: block.end_time, category: block.category,
  }))
  console.log("PASS: follow-up saved exactly one block with the requested attributes")
} catch (error) {
  console.error(error)
  process.exitCode = 1
} finally {
  await browser?.close()
  cleanupSchedules([SCHEDULE_DATE])
}
