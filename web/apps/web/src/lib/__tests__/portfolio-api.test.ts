import { describe, expect, it, vi } from 'vitest'
import { requestPortfolio } from '../portfolio-api'

function response(body: unknown, init?: ResponseInit): Response {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), init)
}

describe('requestPortfolio', () => {
  it('returns a validated portfolio', async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ free_cash: 1200, positions: [] }))

    await expect(requestPortfolio('GET', 'token', undefined, fetcher)).resolves.toEqual({
      free_cash: 1200,
      positions: [],
    })
    expect(fetcher).toHaveBeenCalledWith('/api/portfolio', expect.objectContaining({
      method: 'GET',
      headers: { Authorization: 'Bearer token' },
    }))
  })

  it('rejects the Pages SPA fallback instead of returning an empty object', async () => {
    const fetcher = vi.fn().mockResolvedValue(response('<!doctype html><html></html>', {
      headers: { 'content-type': 'text/html' },
    }))

    await expect(requestPortfolio('GET', 'token', undefined, fetcher)).rejects.toThrow('持仓服务返回数据不完整')
  })

  it('rejects successful responses with missing positions', async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ free_cash: 0 }))

    await expect(requestPortfolio('GET', 'token', undefined, fetcher)).rejects.toThrow('持仓服务返回数据不完整')
  })

  it('surfaces API errors', async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ error: 'Whitelist required' }, { status: 403 }))

    await expect(requestPortfolio('GET', 'token', undefined, fetcher)).rejects.toThrow('Whitelist required')
  })
})
