import { z } from 'zod'

const positionSchema = z.object({
  code: z.union([z.string(), z.number()]),
  name: z.string().nullable(),
  shares: z.number(),
  cost_price: z.number(),
  buy_dt: z.string().nullable(),
})

const portfolioSchema = z.object({
  free_cash: z.number(),
  positions: z.array(positionSchema),
})

const errorSchema = z.object({ error: z.string() })

export type Position = z.infer<typeof positionSchema>
export type Portfolio = z.infer<typeof portfolioSchema>

export const EMPTY_PORTFOLIO: Portfolio = { free_cash: 0, positions: [] }

export async function requestPortfolio(
  method: 'GET' | 'PUT',
  accessToken: string,
  portfolio?: Portfolio,
  fetcher: typeof fetch = fetch,
): Promise<Portfolio> {
  const response = await fetcher('/api/portfolio', {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(portfolio ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(portfolio ? { body: JSON.stringify(portfolio) } : {}),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const message = errorSchema.safeParse(payload)
    throw new Error(message.success ? message.data.error : '持仓服务请求失败')
  }
  const parsed = portfolioSchema.safeParse(payload)
  if (!parsed.success) throw new Error('持仓服务返回数据不完整，请稍后重试')
  return parsed.data
}
