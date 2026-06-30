import { describe, expect, it } from 'vitest'
import { FINANCIAL_DOWN_CLASS, FINANCIAL_UP_CLASS, financialValueClass } from '../financial-colors'

describe('financialValueClass', () => {
  it('uses China market colors: red for up and green for down', () => {
    expect(FINANCIAL_UP_CLASS).toBe('text-up')
    expect(FINANCIAL_DOWN_CLASS).toBe('text-down')
    expect(financialValueClass(1)).toBe('text-up')
    expect(financialValueClass(-1)).toBe('text-down')
  })

  it('uses neutral class for zero or invalid values', () => {
    expect(financialValueClass(0)).toBe('text-muted-foreground')
    expect(financialValueClass(null)).toBe('text-muted-foreground')
    expect(financialValueClass(Number.NaN, '')).toBe('')
  })
})
