import { afterEach, describe, expect, it, vi } from "vitest"
import { flushPromises } from "@vue/test-utils"
import type { TimeBlock } from "../src/types"
import { useBlockCompletion } from "../src/composables/useBlockCompletion"

function makeBlock(overrides: Partial<TimeBlock> = {}): TimeBlock {
  return {
    id: 1,
    title: "Focus",
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: 0,
    ...overrides,
  }
}

function makeDeps(overrides: Record<string, unknown> = {}) {
  return {
    updateBlock: vi.fn().mockResolvedValue({ ok: true }),
    undo: { pushUndo: vi.fn(), snapshotBlocks: vi.fn(() => [] as TimeBlock[]) },
    isDisabled: vi.fn(() => false),
    ...overrides,
  }
}

afterEach(() => {
  vi.useRealTimers()
})

describe("useBlockCompletion", () => {
  it("complete() PATCHes is_completed:true, pushes a silent toggle undo, resolves 'success'", async () => {
    const deps = makeDeps()
    const c = useBlockCompletion(deps)
    const outcome = await c.complete(makeBlock({ id: 7, title: "Deep work" }), "2026-08-12")

    expect(outcome).toBe("success")
    expect(deps.updateBlock).toHaveBeenCalledWith(
      7,
      { is_completed: true },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(deps.undo.pushUndo).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "toggle",
        silent: true,
        description: 'Checked "Deep work"',
      }),
    )
    expect(c.saving.value).toBe(false)
    expect(c.errorState.value).toBe(false)
  })

  it("setCompleted(desired=false) labels the undo 'Unchecked'", async () => {
    const deps = makeDeps()
    const c = useBlockCompletion(deps)
    await c.setCompleted(makeBlock({ title: "Nap" }), "2026-08-12", false)
    expect(deps.undo.pushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ description: 'Unchecked "Nap"' }),
    )
  })

  it("is a no-op resolving 'superseded' when the schedule is disabled", async () => {
    const deps = makeDeps({ isDisabled: vi.fn(() => true) })
    const c = useBlockCompletion(deps)
    const outcome = await c.complete(makeBlock(), "2026-08-12")
    expect(outcome).toBe("superseded")
    expect(deps.updateBlock).not.toHaveBeenCalled()
    expect(c.saving.value).toBe(false)
  })

  it("retries per the backoff, then resolves 'failure' with errorState set and saving cleared", async () => {
    vi.useFakeTimers()
    const deps = makeDeps({ updateBlock: vi.fn().mockResolvedValue({ ok: false }) })
    const c = useBlockCompletion(deps)
    const p = c.complete(makeBlock(), "2026-08-12")
    await flushPromises()
    await vi.advanceTimersByTimeAsync(4300)
    const outcome = await p
    expect(outcome).toBe("failure")
    expect(deps.updateBlock).toHaveBeenCalledTimes(4)
    expect(c.errorState.value).toBe(true)
    expect(c.saving.value).toBe(false)
    expect(deps.undo.pushUndo).not.toHaveBeenCalled()
  })

  it("clears errorState after a failure followed by a success", async () => {
    vi.useFakeTimers()
    const updateBlock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValue({ ok: true })
    const deps = makeDeps({ updateBlock })
    const c = useBlockCompletion(deps)
    const p1 = c.complete(makeBlock(), "2026-08-12")
    await flushPromises()
    await vi.advanceTimersByTimeAsync(4300)
    await p1
    expect(c.errorState.value).toBe(true)

    vi.useRealTimers()
    const outcome = await c.complete(makeBlock(), "2026-08-12")
    expect(outcome).toBe("success")
    expect(c.errorState.value).toBe(false)
  })

  it("a second call aborts the first: first resolves 'superseded', only the second pushes undo", async () => {
    const updateBlock = vi.fn().mockImplementation((_id, _data, opts) => {
      const signal: AbortSignal | undefined = opts?.signal
      return new Promise((resolve, reject) => {
        if (signal?.aborted) {
          reject(new DOMException("Aborted", "AbortError"))
          return
        }
        const onAbort = () => reject(new DOMException("Aborted", "AbortError"))
        signal?.addEventListener("abort", onAbort, { once: true })
        // Resolve ok only for a call whose signal is never aborted.
        setTimeout(() => {
          if (!signal?.aborted) resolve({ ok: true })
        }, 0)
      })
    })
    const deps = makeDeps({ updateBlock })
    const c = useBlockCompletion(deps)
    const first = c.complete(makeBlock(), "2026-08-12")
    const second = c.complete(makeBlock(), "2026-08-12")
    const [o1, o2] = await Promise.all([first, second])
    expect(o1).toBe("superseded")
    expect(o2).toBe("success")
    expect(deps.undo.pushUndo).toHaveBeenCalledTimes(1)
  })

  it("captures the block id at call start (a later mutation cannot retarget the PATCH)", async () => {
    const deps = makeDeps()
    const c = useBlockCompletion(deps)
    const block = makeBlock({ id: 11 })
    const p = c.complete(block, "2026-08-12")
    block.id = 999
    await p
    expect(deps.updateBlock).toHaveBeenCalledWith(11, { is_completed: true }, expect.anything())
  })

  it("reset() clears saving + errorState", async () => {
    vi.useFakeTimers()
    const deps = makeDeps({ updateBlock: vi.fn().mockResolvedValue({ ok: false }) })
    const c = useBlockCompletion(deps)
    const p = c.complete(makeBlock(), "2026-08-12")
    await flushPromises()
    await vi.advanceTimersByTimeAsync(4300)
    await p
    expect(c.errorState.value).toBe(true)
    c.reset()
    expect(c.saving.value).toBe(false)
    expect(c.errorState.value).toBe(false)
  })

  it("dispose() bumps generation so a late resolve bails 'superseded' without pushing undo", async () => {
    let resolveUpdate: ((v: { ok: boolean }) => void) | null = null
    const updateBlock = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpdate = resolve
        }),
    )
    const deps = makeDeps({ updateBlock })
    const c = useBlockCompletion(deps)
    const p = c.complete(makeBlock(), "2026-08-12")
    c.dispose()
    resolveUpdate!({ ok: true })
    const outcome = await p
    expect(outcome).toBe("superseded")
    expect(deps.undo.pushUndo).not.toHaveBeenCalled()
  })

  it("reset() on a freshly constructed instance is a no-op (no throw)", () => {
    const c = useBlockCompletion(makeDeps())
    expect(() => c.reset()).not.toThrow()
    expect(c.saving.value).toBe(false)
    expect(c.errorState.value).toBe(false)
  })

  it("dispose() on a freshly constructed instance is a no-op (no throw)", () => {
    const c = useBlockCompletion(makeDeps())
    expect(() => c.dispose()).not.toThrow()
    expect(c.saving.value).toBe(false)
    expect(c.errorState.value).toBe(false)
  })

  it("keeps two instances isolated: failing A leaves B untouched", async () => {
    vi.useFakeTimers()
    const a = useBlockCompletion(makeDeps({ updateBlock: vi.fn().mockResolvedValue({ ok: false }) }))
    const b = useBlockCompletion(makeDeps())
    const pa = a.complete(makeBlock(), "2026-08-12")
    await flushPromises()
    await vi.advanceTimersByTimeAsync(4300)
    await pa
    expect(a.errorState.value).toBe(true)
    expect(b.errorState.value).toBe(false)
    expect(b.saving.value).toBe(false)
    // Resetting A must not touch B.
    a.reset()
    expect(b.errorState.value).toBe(false)
  })
})
