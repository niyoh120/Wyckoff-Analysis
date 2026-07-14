import { describe, expect, it } from 'vitest'
import { normalizeCode } from '@wyckoff/shared'

describe('normalizeCode', () => {
  it('pads numeric strings shorter than 6 digits with leading zeros', () => {
    expect(normalizeCode('1')).toBe('000001')
    expect(normalizeCode('12345')).toBe('012345')
    expect(normalizeCode('000001')).toBe('000001')
  })

  it('pads numeric (non-string) codes, including the falsy value 0', () => {
    expect(normalizeCode(1)).toBe('000001')
    expect(normalizeCode(600519)).toBe('600519')
    // Regression: `code || ''` previously coerced 0 to '', normalizeCode('') -> ''
    // instead of the correct zero-padded '000000'.
    expect(normalizeCode(0)).toBe('000000')
    expect(normalizeCode('0')).toBe('000000')
  })

  it('leaves non-numeric or already-qualified codes unchanged aside from casing', () => {
    expect(normalizeCode('AAPL.US')).toBe('AAPL.US')
    expect(normalizeCode('aapl.us')).toBe('AAPL.US')
    expect(normalizeCode('00700.HK')).toBe('00700.HK')
    expect(normalizeCode('600519.SH')).toBe('600519.SH')
  })

  it('does not pad numeric strings already at or beyond 6 digits', () => {
    expect(normalizeCode('600519')).toBe('600519')
    expect(normalizeCode('1234567')).toBe('1234567')
  })

  it('trims surrounding whitespace before normalizing', () => {
    expect(normalizeCode('  600519  ')).toBe('600519')
  })

  it('returns an empty string for empty input', () => {
    expect(normalizeCode('')).toBe('')
  })
})
