import { describe, expect, it, vi } from "vitest"
import { flushPromises } from "@vue/test-utils"
import type { TimeBlock } from "../src/types"
import type { ApiResult } from "../src/composables/useSchedule"
import { useBlockCompletion } from "../src/composables/useBlockCompletion"
import { acceptedMutation } from "./helpers/mutation"

function makeBlock(overrides: Partial<TimeBlock> = {}): TimeBlock {
  return { id: 1, title: "Focus", start_time: "09:00", end_time: "10:00", category: "work", is_completed: false, sort_order: 0, ...overrides }
}
function makeDeps() {
  return {
    updateBlock: vi.fn().mockResolvedValue(acceptedMutation([makeBlock()], "2026-08-12")),
    undo: { pushUndo: vi.fn(), snapshotBlocks: vi.fn(() => [] as TimeBlock[]) },
    isDisabled: vi.fn(() => false),
  }
}
function deferred() {
  let resolve!: (result: ApiResult) => void
  const promise = new Promise<ApiResult>((r) => { resolve = r })
  return { promise, resolve }
}

describe("useBlockCompletion", () => {
  it("registers confirmed snapshot and returned revision, without a request abort signal", async () => {
    const deps = makeDeps()
    const completion = useBlockCompletion(deps)
    expect(await completion.complete(makeBlock({ id: 7, title: "Deep work" }), "2026-08-12")).toBe("success")
    expect(deps.updateBlock).toHaveBeenCalledWith(7, { is_completed: true }, { scheduleDate: "2026-08-12" })
    expect(deps.undo.pushUndo).toHaveBeenCalledWith(expect.objectContaining({
      type: "toggle", silent: true, description: 'Checked "Deep work"', previousBlocks: [makeBlock()],
      previous_revision: 3, expected_revision: 4, scheduleDate: "2026-08-12",
    }))
    expect(deps.undo.snapshotBlocks).not.toHaveBeenCalled()
    expect(completion.saving.value).toBe(false)
  })

  it.each([400, 401, 403, 404, 409, 500, 502, 503, undefined])("never retries status %s or registers undo", async (status) => {
    const deps = makeDeps()
    deps.updateBlock.mockResolvedValue({ ok: false, status })
    const completion = useBlockCompletion(deps)
    expect(await completion.complete(makeBlock(), "2026-08-12")).toBe("failure")
    expect(deps.updateBlock).toHaveBeenCalledOnce()
    expect(deps.undo.pushUndo).not.toHaveBeenCalled()
    expect(completion.errorState.value).toBe(true)
    expect(completion.saving.value).toBe(false)
  })

  it.each([new TypeError("lost response body"), new DOMException("Aborted", "AbortError")])("settles thrown transport failure without replaying PATCH", async (error) => {
    const deps = makeDeps()
    deps.updateBlock.mockRejectedValue(error)
    const completion = useBlockCompletion(deps)
    expect(await completion.complete(makeBlock(), "2026-08-12")).toBe("failure")
    expect(deps.updateBlock).toHaveBeenCalledOnce()
    expect(completion.saving.value).toBe(false)
  })

  it("serializes rapid intents and preserves both confirmed operations in history", async () => {
    const firstWrite = deferred()
    const secondWrite = deferred()
    const deps = makeDeps()
    deps.updateBlock.mockReturnValueOnce(firstWrite.promise).mockReturnValueOnce(secondWrite.promise)
    const completion = useBlockCompletion(deps)
    const first = completion.complete(makeBlock(), "2026-08-12")
    deps.isDisabled.mockReturnValue(true) // Shared controller is busy on this row's write.
    const second = completion.setCompleted(makeBlock(), "2026-08-12", false)
    expect(deps.updateBlock).toHaveBeenCalledOnce()
    firstWrite.resolve(acceptedMutation([makeBlock()], "2026-08-12", 3))
    expect(await first).toBe("superseded")
    await flushPromises()
    expect(deps.updateBlock).toHaveBeenCalledTimes(2)
    expect(completion.saving.value).toBe(true)
    expect(deps.updateBlock.mock.calls[1][1]).toEqual({ is_completed: false })
    secondWrite.resolve(acceptedMutation([makeBlock({ is_completed: true })], "2026-08-12", 4))
    expect(await second).toBe("success")
    expect(deps.undo.pushUndo).toHaveBeenCalledTimes(2)
    expect(deps.undo.pushUndo.mock.calls[1][0]).toMatchObject({ description: 'Unchecked "Focus"', previous_revision: 4, expected_revision: 5 })
    expect(completion.saving.value).toBe(false)
  })

  it.each([
    { ok: false, status: 409, code: "schedule_changed" },
    { ok: false, errors: { detail: "Network error" } },
    { ok: true },
    { ok: true, code: "schedule_reconciled" },
    { ok: true, code: "schedule_sync_failed" },
  ])("cancels pre-conflict queued intent for %j, then permits a fresh user intent", async (failedResult) => {
    const write = deferred()
    const deps = makeDeps()
    deps.updateBlock.mockReturnValueOnce(write.promise)
    const completion = useBlockCompletion(deps)
    const first = completion.complete(makeBlock(), "2026-08-12")
    const queued = completion.setCompleted(makeBlock(), "2026-08-12", false)
    write.resolve(failedResult)
    expect(await first).toBe(failedResult.ok ? "superseded" : "failure")
    expect(await queued).toBe("superseded")
    expect(deps.updateBlock).toHaveBeenCalledOnce()
    expect(deps.undo.pushUndo).not.toHaveBeenCalled()
    expect(completion.saving.value).toBe(false)
    expect(await completion.complete(makeBlock(), "2026-08-12")).toBe("success")
    expect(deps.updateBlock).toHaveBeenCalledTimes(2)
  })

  it("does not create undo for a no-op or success without accepted metadata", async () => {
    const deps = makeDeps()
    deps.updateBlock.mockResolvedValueOnce(acceptedMutation([], "2026-08-12", 3, false)).mockResolvedValueOnce({ ok: true })
    const completion = useBlockCompletion(deps)
    expect(await completion.complete(makeBlock(), "2026-08-12")).toBe("success")
    expect(await completion.complete(makeBlock(), "2026-08-12")).toBe("success")
    expect(deps.undo.pushUndo).not.toHaveBeenCalled()
  })

  it.each(["reset", "dispose"] as const)("%s detaches row UI, cancels unsent work and retains history for the accepted write", async (method) => {
    const write = deferred()
    const deps = makeDeps()
    deps.updateBlock.mockReturnValueOnce(write.promise)
    const completion = useBlockCompletion(deps)
    const first = completion.complete(makeBlock(), "2026-08-12")
    const second = completion.setCompleted(makeBlock(), "2026-08-12", false)
    completion[method]()
    expect(completion.saving.value).toBe(false)
    write.resolve(acceptedMutation([makeBlock()], "2026-08-12"))
    expect(await first).toBe("superseded")
    expect(await second).toBe("superseded")
    expect(deps.updateBlock).toHaveBeenCalledOnce()
    expect(deps.undo.pushUndo).toHaveBeenCalledOnce()
    expect(completion.errorState.value).toBe(false)
  })

  it("does not register history after navigation when the controller omits mutation metadata", async () => {
    const write = deferred()
    const deps = makeDeps()
    deps.updateBlock.mockReturnValueOnce(write.promise)
    const completion = useBlockCompletion(deps)
    const operation = completion.complete(makeBlock(), "2026-08-12")
    completion.reset()
    write.resolve({ ok: true })
    expect(await operation).toBe("superseded")
    expect(deps.undo.pushUndo).not.toHaveBeenCalled()
  })

  it("captures the original identity before mutable block props change", async () => {
    const deps = makeDeps()
    const block = makeBlock({ id: 11 })
    const completion = useBlockCompletion(deps)
    const operation = completion.complete(block, "2026-08-12")
    block.id = 999
    await operation
    expect(deps.updateBlock.mock.calls[0][0]).toBe(11)
  })

  it("rejects new completion when disabled and clears errors after a later accepted request", async () => {
    const deps = makeDeps()
    const completion = useBlockCompletion(deps)
    deps.isDisabled.mockReturnValue(true)
    expect(await completion.complete(makeBlock(), "2026-08-12")).toBe("superseded")
    expect(deps.updateBlock).not.toHaveBeenCalled()
    deps.isDisabled.mockReturnValue(false)
    deps.updateBlock.mockResolvedValueOnce({ ok: false })
    await completion.complete(makeBlock(), "2026-08-12")
    expect(completion.errorState.value).toBe(true)
    await completion.complete(makeBlock(), "2026-08-12")
    expect(completion.errorState.value).toBe(false)
  })
})
