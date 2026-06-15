// Module-level singleton AudioContext for the sound-notification feature
// (issue #56 / docs/features/0019_PLAN.md Phase 2).
//
// Why a singleton and not a per-composable context: the opt-in toggle lives
// on the Settings page and the boundary detector runs on the Schedule page.
// A user gesture (the toggle click) is required to lift the browser autoplay
// policy and resume the context. If each surface owned its own context, the
// gesture would unlock a DIFFERENT context than the one the detector later
// plays through, so the detector's context would still be `suspended` — the
// "first boundary dropped" bug would hit EVERY enable-via-Settings session
// (the common path). Sharing one context across page navigations means the
// Settings-toggle gesture unlocks the exact context the Schedule detector
// uses.
//
// Lifetime: the context is created lazily on first use and NEVER closed
// during normal operation. A single suspended/running AudioContext for the
// app lifetime is cheap, and closing it on a page unmount would re-suspend
// or destroy exactly the context the next page needs (closing on the
// Settings unmount during Settings→Schedule navigation would re-introduce
// the dropped-first-boundary bug above). `closeAudioContext` exists only for
// test teardown and a hypothetical full app teardown.

let ctx: AudioContext | null = null

function resolveConstructor(): typeof AudioContext | null {
  const g = globalThis as unknown as {
    AudioContext?: typeof AudioContext
    webkitAudioContext?: typeof AudioContext
  }
  return g.AudioContext ?? g.webkitAudioContext ?? null
}

/**
 * Lazily construct and cache the shared AudioContext. Returns `null` when
 * Web Audio is unavailable (constructor missing or construction throws), so
 * every caller can no-op gracefully. Construction is deferred to first call
 * — never at module load, where it can throw or auto-suspend before any
 * user gesture.
 */
export function getAudioContext(): AudioContext | null {
  if (ctx !== null) return ctx
  try {
    const Ctor = resolveConstructor()
    if (Ctor === null) return null
    ctx = new Ctor()
    return ctx
  } catch {
    ctx = null
    return null
  }
}

/**
 * Resume the shared context. MUST be called from inside a user-gesture
 * handler (the Settings toggle click) to satisfy the browser autoplay
 * policy. Idempotent; a rejected `resume()` is swallowed.
 */
export function unlockAudioContext(): void {
  try {
    const c = getAudioContext()
    void c?.resume().catch(() => {})
  } catch {
    // resume() returns a promise per spec; guard a non-conformant stack that
    // throws synchronously so nothing escapes the toggle's click handler
    // (mirrors playSound's try/catch).
  }
}

/**
 * Close and forget the cached context. Not used on per-component unmount —
 * see the lifetime note above. Present for test teardown and full app
 * teardown so a later `getAudioContext()` rebuilds a fresh handle.
 */
export function closeAudioContext(): void {
  const c = ctx
  ctx = null
  void c?.close().catch(() => {})
}
