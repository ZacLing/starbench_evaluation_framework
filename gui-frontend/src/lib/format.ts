export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "–"
  const total = Math.max(0, Math.round(Number(seconds)))
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes}m ${total % 60}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "–"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return "–"
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function spanBetween(
  startIso: string | null | undefined,
  endIso: string | null | undefined,
  running: boolean,
): string {
  if (!startIso) return "–"
  const start = new Date(startIso).getTime()
  const end = running ? Date.now() : endIso ? new Date(endIso).getTime() : NaN
  if (Number.isNaN(start) || Number.isNaN(end)) return "–"
  return fmtDuration((end - start) / 1000)
}

/* Compact relative recency ("3d ago") for dense cells; exact timestamps live
   on the linked detail pages. Unparseable input renders as honest absence. */
export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return ""
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ""
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 0) return fmtTime(iso) /* future timestamp: show it, don't invent "ago" */
  if (seconds < 60) return "just now"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(days / 365)}y ago`
}

export function fmtRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "–"
  return `${Math.round(rate * 1000) / 10}%`
}

export function fmtDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "–"
  const value = Math.round(delta * 1000) / 10
  return `${value > 0 ? "+" : ""}${value}%`
}

export function percent(numerator: number, denominator: number): number | null {
  if (!denominator) return null
  return numerator / denominator
}

/* Last two path segments — enough to recognize a folder without the noise of
   an absolute path; callers put the full path in a title attribute. */
export function shortDir(path: string | null | undefined): string {
  if (!path) return ""
  const parts = path.split("/").filter(Boolean)
  return parts.length > 2 ? `…/${parts.slice(-2).join("/")}` : path
}
