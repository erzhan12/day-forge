import { ref, type Ref } from "vue"
import {
  readExternalCalendarPlacement,
  writeExternalCalendarPlacement,
  type ExternalCalendarPlacement,
} from "../utils/externalCalendarPlacementStorage"

// Module-level ref so Settings + Schedule stay in sync within one SPA
// session without a storage-event listener.
let sharedPlacement: Ref<ExternalCalendarPlacement> | null = null

export function useExternalCalendarPlacement(): {
  placement: Ref<ExternalCalendarPlacement>
  setPlacement: (v: ExternalCalendarPlacement) => void
} {
  if (!sharedPlacement) {
    sharedPlacement = ref(readExternalCalendarPlacement())
  }

  function setPlacement(v: ExternalCalendarPlacement): void {
    writeExternalCalendarPlacement(v)
    sharedPlacement!.value = v
  }

  return { placement: sharedPlacement, setPlacement }
}
