import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchKlineViaTickFlow, isWhitelistEntryActive } from '../kline'

describe('whitelist expiry', () => {
  it('treats null and blank expiry as permanent', () => {
    expect(isWhitelistEntryActive(null, '20260630')).toBe(true)
    expect(isWhitelistEntryActive('', '20260630')).toBe(true)
    expect(isWhitelistEntryActive('   ', '20260630')).toBe(true)
  })

  it('keeps entries active through their expiry date', () => {
    expect(isWhitelistEntryActive('20260630', '20260630')).toBe(true)
    expect(isWhitelistEntryActive('20260701', '20260630')).toBe(true)
  })

  it('rejects expired or malformed expiry values', () => {
    expect(isWhitelistEntryActive('20260629', '20260630')).toBe(false)
    expect(isWhitelistEntryActive('2026-06-30', '20260630')).toBe(false)
    expect(isWhitelistEntryActive('20261301', '20260630')).toBe(false)
    expect(isWhitelistEntryActive('20260230', '20260630')).toBe(false)
  })
})

describe('kline TickFlow parsing', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('normalizes Unix second timestamps into trading dates', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        data: {
          '603039.SH': {
            timestamp: [1704067200, 1704153600],
            open: [10, 11],
            high: [11, 12],
            low: [9, 10],
            close: [10.5, 11.5],
            volume: [1000, 1200],
          },
        },
      }),
    }))

    const rows = await fetchKlineViaTickFlow('603039', 'tf-test')

    expect(rows.map((row) => row.date)).toEqual(['2024-01-01', '2024-01-02'])
    expect(rows[0]).toMatchObject({ open: 10, close: 10.5, volume: 1000 })
  })
})
