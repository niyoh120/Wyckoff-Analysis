import { describe, expect, it } from 'vitest'
import { buildStockAnalysisContextPack, formatAnalysisContextPack } from '@wyckoff/shared'

describe('analysis context pack', () => {
  it('summarizes technical data and provenance for the same analysis input', () => {
    const pack = buildStockAnalysisContextPack({
      symbol: '600519',
      name: '贵州茅台',
      kline: [
        { date: '2026-07-10', open: 100, high: 105, low: 99, close: 104, volume: 1000 },
        { date: '2026-07-13', open: 104, high: 108, low: 103, close: 106, volume: 1200 },
      ],
      dataQuality: {
        source: 'tickflow',
        latestTradingDate: '2026-07-13',
        coverageStart: '2026-07-10',
        coverageEnd: '2026-07-13',
        requestedRows: 320,
        returnedRows: 2,
        isComplete: false,
        fallbackUsed: false,
      },
      valueSnapshot: {
        symbol: '600519.SH',
        source: 'tickflow',
        metrics: { period_end: '2026-03-31', roe: 18.2 },
      },
    })

    expect(pack.technical.latestClose).toBe(106)
    expect(pack.technical.changePct).toBeCloseTo(1.923, 2)
    expect(pack.technical.ma20).toBe(105)
    expect(pack.evidence).toHaveLength(2)
    expect(formatAnalysisContextPack(pack)).toContain('market_data | tickflow | 600519 | 2026-07-13')
    expect(formatAnalysisContextPack(pack)).toContain('fundamental_data | tickflow | 600519 | 2026-03-31')
  })
})
