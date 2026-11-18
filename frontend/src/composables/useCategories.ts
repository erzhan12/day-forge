import { router } from "@inertiajs/vue3"
import { requestJson } from "./useHttp"

export function useCategories() {
  // After ordinary mutations only the catalog changes; after a delete the
  // remap also touches templates and travel-rule overrides, so reload those.
  // A partial reload filters shared props too, so request auth_user_id with
  // every catalogue: the root PiP owner trusts a new catalogue only together
  // with the current identity (see refreshSchedule in useScheduleRevision).
  const refresh = (afterDelete = false) =>
    router.reload({
      only: afterDelete
        ? ["categories", "templates", "travel_rules", "auth_user_id"]
        : ["categories", "auth_user_id"],
    })

  return {
    create: (label: string, color_id: string) =>
      requestJson("/api/user/categories/", "POST", { label, color_id }),
    update: (id: number, data: Record<string, unknown>) =>
      requestJson(`/api/user/categories/${id}/`, "PATCH", data),
    remove: (id: number) => requestJson(`/api/user/categories/${id}/`, "DELETE"),
    swap: (a: number, b: number) =>
      requestJson("/api/user/categories/swap/", "POST", { a, b }),
    refresh,
  }
}
