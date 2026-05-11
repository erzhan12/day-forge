export function clearLocalStorage(): void {
  globalThis.localStorage?.clear?.()
}
