import { describe, expect, it } from 'vitest'
import { arrayToCSV, buildEnhancedRows, parseExportSymbols, parseTickFlowToRows } from '../export-data'

describe('export-data', () => {
  it('normalizes mixed batch symbols', () => {
    expect(parseExportSymbols('601318; 510300 000001.SH AAPL.US 00700.HK 601318')).toEqual([
      '601318.SH',
      '510300.SH',
      '000001.SH',
      'AAPL.US',
      '00700.HK',
    ])
  })

  it('parses TickFlow table payloads into export rows', () => {
    const rows = parseTickFlowToRows({
      data: {
        '601318.SH': {
          timestamp: [1779033600000],
          open: [10],
          high: [11],
          low: [9],
          close: [10.5],
          volume: [1000],
        },
      },
    })

    expect(rows).toEqual([
      { date: '2026-05-18', open: 10, high: 11, low: 9, close: 10.5, volume: 1000 },
    ])
  })

  it('builds enhanced OHLCV rows and escaped CSV', () => {
    const enhanced = buildEnhancedRows([{ date: '2026-05-18', open: 10, high: 11, low: 9, close: 10.5, volume: 1000, amount: 10500, sector: '银行,金融' }])

    expect(enhanced[0]).toMatchObject({
      Date: '2026-05-18',
      Open: 10,
      AvgPrice: 10.5,
      Sector: '银行,金融',
    })
    expect(arrayToCSV(enhanced)).toContain('"银行,金融"')
  })
})
