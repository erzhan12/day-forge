// Thin wrapper over the `/api/user/preferences/` endpoint.
//
// Public surface:
//   - `savePreference({ theme })`: PATCH the user's prefs. Returns an ApiResult.
//     The Settings selector layers `router.reload({ only: ["ui_preferences"] })`
//     on success and surfaces the error otherwise.
//
// Why we do NOT mutate a local theme ref here:
//   The selector's "checked" state reads from `page.props.ui_preferences.theme`
//   (single source of truth). Mutating a parallel local ref reintroduces the
//   source-of-truth divergence the Phase 5 design eliminated.

import { type ApiResult, requestJson } from "./useHttp"
import type { ThemeId } from "../types"

export function usePreferences() {
  async function saveTheme(theme: ThemeId): Promise<ApiResult> {
    return requestJson("/api/user/preferences/", "PATCH", { theme })
  }

  return { saveTheme }
}
