// Uses only the isolated --draft-window server on port 8007, never the shared
// playwright user or the working database. See scripts/playwright/README.md.
import assert from "node:assert/strict"
import { readFile, realpath, rename, writeFile } from "node:fs/promises"
import { isAbsolute, join, relative } from "node:path"
import { chromium, expect } from "@playwright/test"

assert(process.argv[2], "Pass the running --draft-window fixture directory under /tmp")
const root = await realpath(process.argv[2])
const tmpRelative = relative(await realpath("/tmp"), root)
assert(tmpRelative && !tmpRelative.startsWith("..") && !isAbsolute(tmpRelative), "Use a private /tmp fixture")
const controlsPath = join(root, "controls.json")
const originalControls = await readFile(controlsPath, "utf8")
const controls = JSON.parse(originalControls)
assert.equal(controls.draft_window, true, "Start browser_audit_server.py with --draft-window")

async function replaceControls(contents) {
  const temporary = join(root, `controls.wrap-${process.pid}.json`)
  await writeFile(temporary, contents)
  await rename(temporary, controlsPath)
}

const title = "W".repeat(255)
const base = "http://127.0.0.1:8007"
const measurements = []
let browser
try {
  await replaceControls(JSON.stringify({
    ...controls,
    ai: "draft",
    draft_actions: [{
      type: "add", title, start_time: "21:30", end_time: "22:30", category: "work",
    }],
  }))
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto(`${base}/accounts/login/`)
  await page.locator("#username").fill("audit-browser-local")
  await page.locator("#password").fill("audit-browser-local-only")
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.locator('button[type="submit"]').click(),
  ])
  await page.goto(`${base}/schedule/2027-08-06/`, { waitUntil: "networkidle" })
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/generate-draft/") && r.request().method() === "POST"),
    page.locator(".regen-btn").click(),
  ])
  assert.equal(response.status(), 400)
  const error = page.locator(".draft-error")
  await expect(error).toContainText(title)
  await expect(error).toContainText("outside your day window (05:00-22:00)")

  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    const actual = await error.evaluate(el => ({
      scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,
      documentWidth: document.documentElement.scrollWidth, viewport: window.innerWidth,
    }))
    assert(actual.clientWidth > 0, "The message must occupy visible space")
    assert(actual.scrollWidth <= actual.clientWidth, `Draft error overflows at ${width}px: ${JSON.stringify(actual)}`)
    assert(actual.documentWidth <= actual.viewport, `Page overflows at ${width}px`)

    // A negative control proves these layout assertions detect removal of the fix.
    const style = await page.addStyleTag({ content: ".draft-error { overflow-wrap: normal !important; }" })
    const withoutWrap = await error.evaluate(el => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }))
    assert(withoutWrap.scrollWidth > withoutWrap.clientWidth, `Negative control did not overflow at ${width}px`)
    await style.evaluate(el => el.remove())
    measurements.push({ width, actual, withoutWrap })
  }
  const audit = (await readFile(join(root, "audit.jsonl"), "utf8")).trim().split("\n").map(line => JSON.parse(line))
  const sdkCompletions = audit.filter(row => row.kind === "sdk").length
  assert.equal(sdkCompletions, 1, "Run against a fresh fixture with exactly one completion")
  console.log(JSON.stringify({ result: "PASS", sdkCompletions, externalAiCalls: 0, measurements }, null, 2))
} finally {
  try {
    await browser?.close()
  } finally {
    await replaceControls(originalControls)
  }
}
