export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

export function sanitizeText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function normalizeStockCode(value: unknown): string {
  return sanitizeText(value).toUpperCase()
}

export function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function readBooleanStorage(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  try {
    const value = window.localStorage.getItem(key)
    if (value === 'true') return true
    if (value === 'false') return false
  } catch {
    return fallback
  }
  return fallback
}

export function writeBooleanStorage(key: string, value: boolean) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, value ? 'true' : 'false')
  } catch {
    // localStorage may be unavailable; the in-memory UI state still works.
  }
}
