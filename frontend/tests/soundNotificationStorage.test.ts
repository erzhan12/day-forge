// Strict-only-on-true semantics for the sound-notification localStorage key.
// See docs/features/0019_PLAN.md Phase 1 / Phase 5. Mirrors
// tests/chatSidebarStorage.test.ts but with the inverse safe default
// (silence): only the literal boolean `true` enables.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  SOUND_NOTIFICATIONS_KEY,
  readSoundNotificationsEnabled,
  writeSoundNotificationsEnabled,
} from "../src/utils/soundNotificationStorage"

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

describe("readSoundNotificationsEnabled — strict-only-on-true", () => {
  it("missing key → false (default off)", () => {
    expect(readSoundNotificationsEnabled()).toBe(false)
  })

  it("stored 'true' → true", () => {
    storage.store[SOUND_NOTIFICATIONS_KEY] = "true"
    expect(readSoundNotificationsEnabled()).toBe(true)
  })

  it("stored 'false' → false", () => {
    storage.store[SOUND_NOTIFICATIONS_KEY] = "false"
    expect(readSoundNotificationsEnabled()).toBe(false)
  })

  it("malformed JSON → false (fallback)", () => {
    storage.store[SOUND_NOTIFICATIONS_KEY] = "not-json"
    expect(readSoundNotificationsEnabled()).toBe(false)
  })

  it.each([
    ["null", "null"],
    ["123", "123"],
    ['"true"', '"true"'],
    ["[]", "[]"],
    ["{}", "{}"],
  ])("valid non-true payload %s → false", (_label, raw) => {
    storage.store[SOUND_NOTIFICATIONS_KEY] = raw
    expect(readSoundNotificationsEnabled()).toBe(false)
  })
})

describe("writeSoundNotificationsEnabled", () => {
  it("writes true then reads back true", () => {
    writeSoundNotificationsEnabled(true)
    expect(readSoundNotificationsEnabled()).toBe(true)
  })

  it("writes false then reads back false", () => {
    writeSoundNotificationsEnabled(false)
    expect(readSoundNotificationsEnabled()).toBe(false)
  })

  it("swallows storage errors (private-mode browsers)", () => {
    storage.setItem.mockImplementation(() => {
      throw new Error("QuotaExceededError")
    })
    expect(() => writeSoundNotificationsEnabled(true)).not.toThrow()
  })
})
