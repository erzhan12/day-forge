import { beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick } from "vue"
import { flushPromises, mount } from "@vue/test-utils"

import type { ApiResult } from "../src/composables/useHttp"

const mocks = vi.hoisted(() => {
  const { ref } = require("vue") as typeof import("vue")
  return {
    pageProps: ref<Record<string, unknown>>({
      ui_preferences: {
        chat_suggestions: ["First prompt", "Second prompt", "Third prompt"],
      },
    }),
    reload: vi.fn(),
    save: vi.fn(),
  }
})

vi.mock("@inertiajs/vue3", () => ({
  usePage: () => ({
    get props() {
      return mocks.pageProps.value
    },
  }),
  router: { reload: mocks.reload },
}))

vi.mock("../src/composables/usePreferences", () => ({
  usePreferences: () => ({ saveChatSuggestions: mocks.save }),
}))

import ChatSuggestionsEditor from "../src/components/settings/ChatSuggestionsEditor.vue"
import {
  DEFAULT_CHAT_SUGGESTIONS,
  MAX_CHAT_SUGGESTIONS,
} from "../src/utils/chatSuggestions"

function mountEditor() {
  return mount(ChatSuggestionsEditor)
}

function inputs(wrapper: ReturnType<typeof mountEditor>) {
  return wrapper.findAll('[data-testid="chat-suggestion-input"]')
}

beforeEach(() => {
  mocks.pageProps.value = {
    ui_preferences: {
      chat_suggestions: ["First prompt", "Second prompt", "Third prompt"],
    },
  }
  mocks.reload.mockReset()
  mocks.save.mockReset()
  mocks.save.mockResolvedValue({ ok: true })
})

describe("ChatSuggestionsEditor", () => {
  it("renders the saved prompts as ordered labeled inputs", () => {
    const wrapper = mountEditor()
    expect(inputs(wrapper).map((input) => input.element.value)).toEqual([
      "First prompt",
      "Second prompt",
      "Third prompt",
    ])
    expect(inputs(wrapper).map((input) => input.attributes("aria-label"))).toEqual([
      "Suggestion 1",
      "Suggestion 2",
      "Suggestion 3",
    ])
  })

  it("falls back safely when Inertia supplies no props object", () => {
    mocks.pageProps.value = undefined as unknown as Record<string, unknown>
    const wrapper = mountEditor()
    expect(inputs(wrapper).map((input) => input.element.value))
      .toEqual(DEFAULT_CHAT_SUGGESTIONS)
  })

  it("adds, edits, deletes, and reorders rows with stable identities", async () => {
    const wrapper = mountEditor()
    await wrapper.get('[data-testid="add-chat-suggestion"]').trigger("click")
    expect(inputs(wrapper)).toHaveLength(4)
    await inputs(wrapper)[3].setValue("Typed draft")
    const typedElement = inputs(wrapper)[3].element

    await wrapper.findAll('[aria-label^="Move suggestion up"]')[3].trigger("click")
    expect(inputs(wrapper)[2].element).toBe(typedElement)
    expect(inputs(wrapper)[2].element.value).toBe("Typed draft")

    await wrapper.findAll('[aria-label^="Move suggestion down"]')[2].trigger("click")
    expect(inputs(wrapper)[3].element.value).toBe("Typed draft")
    await wrapper.findAll('[aria-label^="Delete suggestion"]')[1].trigger("click")
    expect(inputs(wrapper).map((input) => input.element.value)).toEqual([
      "First prompt",
      "Third prompt",
      "Typed draft",
    ])
  })

  it("allows deleting all rows and saves the intentional empty list", async () => {
    const wrapper = mountEditor()
    while (inputs(wrapper).length) {
      await wrapper.findAll('[aria-label^="Delete suggestion"]')[0].trigger("click")
    }
    await wrapper.get('[data-testid="save-chat-suggestions"]').trigger("click")
    await flushPromises()
    expect(mocks.save).toHaveBeenCalledWith([])
  })

  it("disables Add at eight rows and exposes the count and character limits", () => {
    mocks.pageProps.value = {
      ui_preferences: {
        chat_suggestions: Array.from(
          { length: MAX_CHAT_SUGGESTIONS },
          (_, index) => `Prompt ${index + 1}`,
        ),
      },
    }
    const wrapper = mountEditor()
    expect(wrapper.get('[data-testid="add-chat-suggestion"]').attributes())
      .toHaveProperty("disabled")
    expect(wrapper.text()).toContain("Up to 8 suggestions")
    expect(wrapper.text()).toContain("120 characters")
  })

  it.each(["", "   ", "x".repeat(121)])(
    "blocks invalid non-empty rows without a request: %j",
    async (value) => {
      const wrapper = mountEditor()
      await inputs(wrapper)[0].setValue(value)
      await wrapper.get('[data-testid="save-chat-suggestions"]').trigger("click")
      await flushPromises()
      expect(mocks.save).not.toHaveBeenCalled()
      expect(wrapper.get('[data-testid="chat-suggestions-error"]').text()).not.toBe("")
    },
  )

  it("accepts 120 emoji by counting code points", async () => {
    const wrapper = mountEditor()
    const emoji = "😀".repeat(120)
    await inputs(wrapper)[0].setValue(emoji)
    await wrapper.get('[data-testid="save-chat-suggestions"]').trigger("click")
    await flushPromises()
    expect(mocks.save).toHaveBeenCalledWith([
      emoji,
      "Second prompt",
      "Third prompt",
    ])
  })

  it("refreshes only ui_preferences and synchronizes on success", async () => {
    const wrapper = mountEditor()
    await inputs(wrapper)[0].setValue("Saved prompt")
    await wrapper.get('[data-testid="save-chat-suggestions"]').trigger("click")
    await flushPromises()

    expect(mocks.reload).toHaveBeenCalledWith(expect.objectContaining({
      only: ["ui_preferences"],
      onSuccess: expect.any(Function),
      onError: expect.any(Function),
      onFinish: expect.any(Function),
    }))
    const options = mocks.reload.mock.calls[0][0]
    options.onSuccess()
    options.onFinish()
    await nextTick()
    expect(wrapper.get('[data-testid="save-chat-suggestions"]').attributes())
      .toHaveProperty("disabled")
    expect(wrapper.text()).toContain("Suggestions saved.")
  })

  it("retains the draft and surfaces PATCH errors", async () => {
    mocks.save.mockResolvedValueOnce({
      ok: false,
      errors: { chat_suggestions: "Choose shorter suggestions." },
    })
    const wrapper = mountEditor()
    await inputs(wrapper)[0].setValue("Unsaved draft")
    await wrapper.get('[data-testid="save-chat-suggestions"]').trigger("click")
    await flushPromises()
    expect(inputs(wrapper)[0].element.value).toBe("Unsaved draft")
    expect(wrapper.text()).toContain("Choose shorter suggestions.")
    expect(mocks.reload).not.toHaveBeenCalled()
  })

  it("clears busy but keeps the saved draft dirty when reload errors", async () => {
    const wrapper = mountEditor()
    await inputs(wrapper)[0].setValue("Saved, reload failed")
    await wrapper.get('[data-testid="save-chat-suggestions"]').trigger("click")
    await flushPromises()
    const options = mocks.reload.mock.calls[0][0]
    options.onFinish()
    await nextTick()

    expect(inputs(wrapper)[0].element.value).toBe("Saved, reload failed")
    expect(wrapper.text()).toContain(
      "Suggestions were saved, but the page could not refresh.",
    )
    expect(wrapper.get('[data-testid="save-chat-suggestions"]').attributes("disabled"))
      .toBeUndefined()
  })

  it("does not overwrite a dirty draft on unrelated preference reloads", async () => {
    const wrapper = mountEditor()
    await inputs(wrapper)[0].setValue("Unsaved local draft")
    mocks.pageProps.value = {
      ui_preferences: {
        theme: "strategic",
        chat_suggestions: ["Server value"],
      },
    }
    await nextTick()
    expect(inputs(wrapper)[0].element.value).toBe("Unsaved local draft")
  })

  it("restores by replacing with exactly one copy of the defaults", async () => {
    const wrapper = mountEditor()
    const restore = wrapper.get('[data-testid="restore-chat-suggestions"]')
    await restore.trigger("click")
    await flushPromises()
    expect(mocks.save).toHaveBeenLastCalledWith([...DEFAULT_CHAT_SUGGESTIONS])
    expect(inputs(wrapper).map((input) => input.element.value))
      .toEqual(DEFAULT_CHAT_SUGGESTIONS)

    const firstReload = mocks.reload.mock.calls[0][0]
    firstReload.onSuccess()
    firstReload.onFinish()
    await nextTick()
    await restore.trigger("click")
    await flushPromises()
    expect(mocks.save).toHaveBeenCalledTimes(2)
    expect(mocks.save).toHaveBeenLastCalledWith([...DEFAULT_CHAT_SUGGESTIONS])
    expect(inputs(wrapper).map((input) => input.element.value))
      .toEqual(DEFAULT_CHAT_SUGGESTIONS)
  })

  it("keeps controls disabled while PATCH is pending", async () => {
    let resolveSave: ((result: ApiResult) => void) | undefined
    mocks.save.mockImplementationOnce(
      () => new Promise<ApiResult>((resolve) => { resolveSave = resolve }),
    )
    const wrapper = mountEditor()
    await inputs(wrapper)[0].setValue("Pending")
    await wrapper.get('[data-testid="save-chat-suggestions"]').trigger("click")
    await nextTick()
    expect(wrapper.get('[data-testid="save-chat-suggestions"]').attributes())
      .toHaveProperty("disabled")
    expect(wrapper.get('[data-testid="restore-chat-suggestions"]').attributes())
      .toHaveProperty("disabled")
    resolveSave!({ ok: false, errors: { detail: "Nope" } })
    await flushPromises()
  })
})
