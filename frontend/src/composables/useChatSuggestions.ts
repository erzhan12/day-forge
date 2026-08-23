import { computed, type ComputedRef } from "vue"
import { usePage } from "@inertiajs/vue3"

import { resolveChatSuggestions } from "../utils/chatSuggestions"

export function useChatSuggestions(): ComputedRef<string[]> {
  const page = usePage()
  return computed(() =>
    resolveChatSuggestions(
      page.props?.ui_preferences?.chat_suggestions,
    ),
  )
}
