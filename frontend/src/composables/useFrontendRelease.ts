import { readonly, ref } from "vue"

// HTML and hashed entry assets belong to one build. Inertia history/prop
// changes must not change the identity of the JavaScript already running.
const version = __FRONTEND_RELEASE__ ?? document.querySelector<HTMLMetaElement>('meta[name="frontend-version"]')?.content
const outdated = ref(false)

export function frontendVersionHeader(): Record<string, string> {
  return version ? { "X-Frontend-Version": version } : {}
}

export function markFrontendOutdated(): void {
  outdated.value = true
}

export function useFrontendRelease() {
  return { outdated: readonly(outdated), reload: () => window.location.reload() }
}
