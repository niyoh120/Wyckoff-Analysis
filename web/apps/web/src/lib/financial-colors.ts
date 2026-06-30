export const FINANCIAL_UP_CLASS = 'text-up'
export const FINANCIAL_DOWN_CLASS = 'text-down'

export function financialValueClass(value: number | null | undefined, neutralClass = 'text-muted-foreground'): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return neutralClass
  if (value > 0) return FINANCIAL_UP_CLASS
  if (value < 0) return FINANCIAL_DOWN_CLASS
  return neutralClass
}
