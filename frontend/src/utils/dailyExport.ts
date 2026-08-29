import {
  formatDurationMinutes,
  sortBlocksByStart,
  timeToMinutes,
} from "./scheduleTime"

export interface DailyExportBlock {
  title: string
  start_time: string
  end_time: string
  category: string
  is_completed: boolean
  sort_order?: number
}

export interface DailyExportArgs {
  date: string
  blocks: DailyExportBlock[]
  note?: string
}

/**
 * Compact human duration between two `"HH:MM"` times (NOT a minute count):
 * `("09:00","09:15") → "15m"`, `("09:00","10:30") → "1h 30m"`. Delegates the
 * hour/minute formatting to the shared `formatDurationMinutes`.
 */
export function formatBlockDuration(start_time: string, end_time: string): string {
  return formatDurationMinutes(timeToMinutes(end_time) - timeToMinutes(start_time))
}

function normalizeNote(note: string | undefined): string {
  return (note ?? "").trim().replace(/\s+/g, " ")
}

/**
 * Pure formatter producing the locked daily-export markdown: a `## day-forge · DATE`
 * header, a `blocks: <done>/<planned> done` summary, one `- [x] HH:MM title (slug) 45m`
 * list item per block (sorted by start then `sort_order`; the `other` category omits its
 * parens), and an optional trailing `note: <text>` line. Never mutates the `blocks` array.
 */
export function formatDailyExport({ date, blocks, note }: DailyExportArgs): string {
  const completed = blocks.filter((block) => block.is_completed).length
  const sections = [
    `## day-forge · ${date}`,
    `blocks: ${completed}/${blocks.length} done`,
  ]

  if (blocks.length) {
    sections.push(
      sortBlocksByStart(blocks)
        .map((block) => {
          const checkbox = block.is_completed ? "[x]" : "[ ]"
          const category = block.category === "other" ? "" : ` (${block.category})`
          return `- ${checkbox} ${block.start_time} ${block.title}${category} ${formatBlockDuration(block.start_time, block.end_time)}`
        })
        .join("\n"),
    )
  }

  const normalizedNote = normalizeNote(note)
  if (normalizedNote) sections.push(`note: ${normalizedNote}`)

  return sections.join("\n\n")
}
