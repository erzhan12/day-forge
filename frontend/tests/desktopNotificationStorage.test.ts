// Strict-only-on-true semantics for the desktop-notification localStorage key.
// See docs/features/0028_PLAN.md Phase 1. Mirrors
// tests/soundNotificationStorage.test.ts — only the literal boolean `true`
// enables (safe default: silence).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  DESKTOP_NOTIFICATIONS_KEY,
  readDesktopNotificationsEnabled,
  writeDesktopNotificationsEnabled,
} from "../src/utils/desktopNotificationStorage"

type StorageMock = {
  store: Record<string, string>
  getItem: ReturnType<typeof vi.fn>
  setItem: ReturnType<typeof vi.fn>
  removeItem: ReturnType<typeof vi.fn>
  clear: ReturnType<typeof vi.fn>
  key: ReturnType<typeof vi.fn>
  length: number
}

function makeStorage(): StorageMock {
  const store: Record<string, string> = {}
  return {
    store,
    getItem: vi.fn((k: string) => (k in store ? store[k] : null)),
    setItem: vi.fn((k: string, v: string) => {
      store[k] = v
    }),
    removeItem: vi.fn((k: string) => {
      delete store[k]
    }),
    clear: vi.fn(() => {
      for (const k of Object.keys(store)) delete store[k]
    }),
    key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
    length: 0,
  }
}

let storage: StorageMock

beforeEach(() => {
  storage = makeStorage()
  vi.stubGlobal("localStorage", storage)
})

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe("readDesktopNotificationsEnabled — strict-only-on-true", () => {
  it("missing key → false (default off)", () => {
    expect(readDesktopNotificationsEnabled()).toBe(false)
  })

  it("stored 'true' → true", () => {
    storage.store[DESKTOP_NOTIFICATIONS_KEY] = "true"
    expect(readDesktopNotificationsEnabled()).toBe(true)
  })

  it("stored 'false' → false", () => {
    storage.store[DESKTOP_NOTIFICATIONS_KEY] = "false"
    expect(readDesktopNotificationsEnabled()).toBe(false)
  })

  it("malformed JSON → false (fallback)", () => {
    storage.store[DESKTOP_NOTIFICATIONS_KEY] = "not-json"
    expect(readDesktopNotificationsEnabled()).toBe(false)
  })

  it.each([
    ["null", "null"],
    ["123", "123"],
    ['"true"', '"true"'],
    ["[]", "[]"],
    ["{}", "{}"],
  ])("valid non-true payload %s → false", (_label, raw) => {
    storage.store[DESKTOP_NOTIFICATIONS_KEY] = raw
    expect(readDesktopNotificationsEnabled()).toBe(false)
  })
})

describe("writeDesktopNotificationsEnabled", () => {
  it("writes true then reads back true", () => {
    writeDesktopNotificationsEnabled(true)
    expect(readDesktopNotificationsEnabled()).toBe(true)
  })

  it("writes false then reads back false", () => {
    writeDesktopNotificationsEnabled(false)
    expect(readDesktopNotificationsEnabled()).toBe(false)
  })

  it("swallows storage errors (private-mode browsers)", () => {
    storage.setItem.mockImplementation(() => {
      throw new Error("QuotaExceededError")
    })
    expect(() => writeDesktopNotificationsEnabled(true)).not.toThrow()
  })
})
