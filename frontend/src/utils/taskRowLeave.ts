// Completed external-task rows play a short leave animation (feature 0105).
// The panel checkboxes are unbound, so a leaving row keeps its native
// checked state. Disable its controls for the leave so a keyboard Space or
// click cannot emit `complete` twice; a row the parent restores after a
// failed completion is a fresh element, never this one revived.
export function lockLeavingTaskRow(el: Element): void {
  el.setAttribute("aria-hidden", "true")
  for (const control of el.querySelectorAll<HTMLInputElement | HTMLButtonElement>("input, button")) {
    control.disabled = true
  }
}
