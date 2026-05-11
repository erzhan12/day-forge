// Strict-only-on-false semantics for the chat-sidebar localStorage key.
// See docs/features/0008_PLAN.md Phase 4.1 / Phase 5.4.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  CHAT_SIDEBAR_OPEN_KEY,
  readChatSidebarOpen,
  writeChatSidebarOpen,
} from "../src/utils/chatSidebarStorage"

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

describe("readChatSidebarOpen — strict-only-on-false", () => {
  it("missing key → true (default open)", () => {
    expect(readChatSidebarOpen()).toBe(true)
  })

  it("stored 'false' → false", () => {
    storage.store[CHAT_SIDEBAR_OPEN_KEY] = "false"
    expect(readChatSidebarOpen()).toBe(false)
  })

  it("stored 'true' → true", () => {
    storage.store[CHAT_SIDEBAR_OPEN_KEY] = "true"
    expect(readChatSidebarOpen()).toBe(true)
  })

  it("malformed JSON → true (fallback)", () => {
    storage.store[CHAT_SIDEBAR_OPEN_KEY] = "not-json"
    expect(readChatSidebarOpen()).toBe(true)
  })

  it.each([
    ["null", "null"],
    ["123", "123"],
    ['"false"', '"false"'],
    ["[]", "[]"],
    ["{}", "{}"],
  ])("valid non-boolean payload %s → true", (_label, raw) => {
    storage.store[CHAT_SIDEBAR_OPEN_KEY] = raw
    expect(readChatSidebarOpen()).toBe(true)
  })
})

describe("writeChatSidebarOpen", () => {
  it("writes false then reads back false", () => {
    writeChatSidebarOpen(false)
    expect(readChatSidebarOpen()).toBe(false)
  })

  it("writes true then reads back true", () => {
    writeChatSidebarOpen(true)
    expect(readChatSidebarOpen()).toBe(true)
  })

  it("swallows storage errors (private-mode browsers)", () => {
    storage.setItem.mockImplementation(() => {
      throw new Error("QuotaExceededError")
    })
    expect(() => writeChatSidebarOpen(false)).not.toThrow()
  })
})
