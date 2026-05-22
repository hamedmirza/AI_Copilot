/** True when an ISO string already includes a UTC offset or Z suffix. */
function hasTimezoneSuffix(value: string): boolean {
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value.trim())
}

/**
 * Parse API ISO datetimes. SQLite-backed fields are stored as UTC but may omit
 * a timezone suffix; treat those values as UTC instead of local time.
 */
export function parseApiDateTime(value?: string | null): Date | null {
  if (!value) return null
  const trimmed = value.trim()
  if (!trimmed) return null
  const normalized = hasTimezoneSuffix(trimmed) ? trimmed : `${trimmed}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}
