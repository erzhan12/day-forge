/**
 * Date source that can be either a static string or a lazy getter.
 *
 * Use the **function variant** when the date comes from a reactive prop
 * that may change during the component's lifetime (e.g. Schedule.vue's
 * in-place date navigation — `useDrag(() => props.date, ...)`). The
 * captured closure resolves the current value at the point of use,
 * avoiding stale-capture bugs where mutations target the setup-time date.
 *
 * Use the **string variant** for static dates (tests, one-shot calls,
 * code paths that genuinely don't observe date changes).
 */
export type DateSource = string | (() => string)

export function readDate(date: DateSource): string {
  return typeof date === "function" ? date() : date
}
