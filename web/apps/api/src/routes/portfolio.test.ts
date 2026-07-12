import { describe, expect, it } from 'vitest'
import { parsePortfolioInput } from './portfolio'

describe('portfolio API input', () => {
  it('accepts a valid user portfolio', () => {
    const result = parsePortfolioInput({
      free_cash: 1000,
      positions: [{ code: '600519', name: '贵州茅台', shares: 100, cost_price: 1500, buy_dt: '2026-07-01' }],
    })

    expect('data' in result).toBe(true)
  })

  it('rejects duplicate symbols and invalid quantities', () => {
    const duplicate = parsePortfolioInput({
      free_cash: 0,
      positions: [
        { code: 'aapl.us', name: null, shares: 1, cost_price: 100, buy_dt: null },
        { code: 'AAPL.US', name: null, shares: 2, cost_price: 110, buy_dt: null },
      ],
    })
    const fractional = parsePortfolioInput({
      free_cash: 0,
      positions: [{ code: '600519', name: null, shares: 1.5, cost_price: 100, buy_dt: null }],
    })

    expect(duplicate).toEqual({ error: 'Duplicate position code' })
    expect(fractional).toHaveProperty('error', 'Invalid portfolio')
  })
})
