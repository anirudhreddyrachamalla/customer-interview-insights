import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Format a past timestamp as a human-readable relative string
 * ("2 hours ago", "3 days ago"). Uses the platform's
 * `Intl.RelativeTimeFormat` — no new dependency.
 *
 * Returns `""` (empty string) for an invalid input so the caller can
 * fall back to a placeholder. The unit is auto-selected based on the
 * size of the delta:
 *
 *   < 60s   -> seconds
 *   < 60m   -> minutes
 *   < 24h   -> hours
 *   < 30d   -> days
 *   < 12mo  -> months
 *   else    -> years
 *
 * Note: this runs both on the server (during the initial render) and
 * on the client. Hydration mismatches can occur if the user keeps the
 * page open across a unit boundary, but for v0's near-static project
 * list that's acceptable.
 */
/**
 * Format a duration in seconds as `mm:ss` (or `hh:mm:ss` for ≥ 1 hour).
 *
 * Used by the transcript pane and pain-points panel to render segment
 * timestamps. The backend hands us floats (e.g. `6.5`), which we floor
 * before formatting — sub-second precision isn't useful in the UI.
 *
 * Returns `"00:00"` for invalid / negative / NaN input so the UI never
 * shows `NaN:NaN`.
 */
export function formatTimestamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00"
  const total = Math.floor(seconds)
  const s = total % 60
  const m = Math.floor(total / 60) % 60
  const h = Math.floor(total / 3600)
  const pad = (n: number) => n.toString().padStart(2, "0")
  if (h > 0) return `${pad(h)}:${pad(m)}:${pad(s)}`
  return `${pad(m)}:${pad(s)}`
}

export function formatRelativeTime(input: string | Date, now: Date = new Date()): string {
  const date = typeof input === "string" ? new Date(input) : input
  const ts = date.getTime()
  if (Number.isNaN(ts)) return ""

  const deltaSec = Math.round((ts - now.getTime()) / 1000)
  const abs = Math.abs(deltaSec)
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" })

  if (abs < 60) return rtf.format(deltaSec, "second")
  if (abs < 3600) return rtf.format(Math.round(deltaSec / 60), "minute")
  if (abs < 86_400) return rtf.format(Math.round(deltaSec / 3600), "hour")
  if (abs < 2_592_000) return rtf.format(Math.round(deltaSec / 86_400), "day")
  if (abs < 31_536_000)
    return rtf.format(Math.round(deltaSec / 2_592_000), "month")
  return rtf.format(Math.round(deltaSec / 31_536_000), "year")
}
