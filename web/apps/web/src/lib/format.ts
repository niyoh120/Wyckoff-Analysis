export function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function formatSignedPercent(value: number | null | undefined, digits = 2, fallback = '--'): string {
  if (!isFiniteNumber(value)) return fallback
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`
}

/** Normalizes `YYYYMMDD` strings and epoch seconds/milliseconds to `YYYY-MM-DD` (UTC+8). */
export function formatTimestampDate(value: unknown): string {
  const raw = String(value || '').trim()
  if (/^\d{8}$/.test(raw)) return raw.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')
  const numeric = Number(raw)
  if (Number.isFinite(numeric) && numeric > 0) {
    const milliseconds = numeric < 1_000_000_000_000 ? numeric * 1000 : numeric
    return new Date(milliseconds + 8 * 3600_000).toISOString().slice(0, 10)
  }
  return raw.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3').slice(0, 10)
}
