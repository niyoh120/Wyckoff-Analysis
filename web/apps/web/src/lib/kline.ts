import { supabase } from './supabase'

export interface KlineData {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface FundamentalMetric {
  symbol?: string
  period_end?: string
  announce_date?: string
  eps_basic?: number
  bps?: number
  ocfps?: number
  roe?: number
  roe_diluted?: number
  revenue_yoy?: number
  net_income_yoy?: number
  gross_margin?: number
  net_margin?: number
  debt_to_asset_ratio?: number
  operating_cash_to_revenue?: number
  inventory_turnover?: number
}

export type ValueSnapshotReason = 'unsupported-market' | 'missing-source' | 'not-found'

export interface ValueSnapshot {
  symbol: string
  source: 'tickflow' | 'tushare' | 'none'
  metrics: FundamentalMetric | null
  reason?: ValueSnapshotReason
}

export const TICKFLOW_PURCHASE = 'https://tickflow.org/auth/register?ref=5N4NKTCPL4'
type Fetcher = typeof globalThis.fetch

export function normalizeCode(code: string | number): string {
  const raw = String(code || '').trim().toUpperCase()
  return /^\d+$/.test(raw) && raw.length < 6 ? raw.padStart(6, '0') : raw
}

export function isCnSymbol(code: string): boolean {
  return /^\d{6}$/.test(code.trim())
}

export function isTickFlowMarketSymbol(code: string): boolean {
  const c = code.trim().toUpperCase()
  return /^\d{5}\.HK$/.test(c) || /^[A-Z][A-Z0-9.-]{0,15}\.US$/.test(c)
}

export function isSupportedKlineCode(code: string): boolean {
  return isCnSymbol(code) || isTickFlowMarketSymbol(code)
}

export function detectMarket(code: string): 'cn' | 'hk' | 'us' {
  const c = code.trim().toUpperCase()
  if (isCnSymbol(c)) return 'cn'
  if (/^\d{5}\.HK$/.test(c)) return 'hk'
  return 'us'
}

export function normalizeTickFlowSymbol(code: string): string {
  const c = code.trim().toUpperCase()
  if (isTickFlowMarketSymbol(c)) return c
  if (!isCnSymbol(c)) return c
  if (c.startsWith('0') || c.startsWith('1') || c.startsWith('2') || c.startsWith('3')) return `${c}.SZ`
  if (c.startsWith('4') || c.startsWith('8') || c.startsWith('9')) return `${c}.BJ`
  return `${c}.SH`
}

export function normalizeTushareCode(code: string): string {
  if (/^\d{6}$/.test(code)) {
    if (code.startsWith('6') || code.startsWith('5')) return `${code}.SH`
    if (code.startsWith('4') || code.startsWith('8') || code.startsWith('9')) return `${code}.BJ`
    return `${code}.SZ`
  }
  return code
}

function formatTimestampDate(value: unknown): string {
  const raw = String(value || '').trim()
  if (/^\d{8}$/.test(raw)) return raw.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')
  const numeric = Number(raw)
  if (Number.isFinite(numeric) && numeric > 0) {
    const milliseconds = numeric < 1_000_000_000_000 ? numeric * 1000 : numeric
    return new Date(milliseconds + 8 * 3600_000).toISOString().slice(0, 10)
  }
  return raw.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3').slice(0, 10)
}

function parseRowArray(rows: unknown[]): KlineData[] {
  return (rows as Record<string, unknown>[])
    .map((r) => ({
      date: String(r.date || r.trade_date || '').replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3'),
      open: Number(r.open || 0),
      high: Number(r.high || 0),
      low: Number(r.low || 0),
      close: Number(r.close || 0),
      volume: Number(r.volume || r.vol || 0),
    }))
    .filter((d) => d.date && d.close > 0)
}

function parseTickFlowTable(table: Record<string, unknown[]>): KlineData[] {
  const timestamps = Array.isArray(table.timestamp) ? table.timestamp : []
  if (timestamps.length === 0) return []
  const open = table.open || [], high = table.high || [], low = table.low || []
  const close = table.close || [], volume = table.volume || []
  return timestamps
    .map((ts, i) => ({
      date: formatTimestampDate(ts),
      open: Number(open[i] || 0),
      high: Number(high[i] || 0),
      low: Number(low[i] || 0),
      close: Number(close[i] || 0),
      volume: Number(volume[i] || 0),
    }))
    .filter((d) => d.date && d.close > 0)
}

function findTickFlowTable(data: unknown, symbol: string): Record<string, unknown[]> | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const obj = data as Record<string, unknown>
  if (Array.isArray(obj.timestamp)) return obj as Record<string, unknown[]>
  const direct = obj[symbol]
  if (direct && typeof direct === 'object' && !Array.isArray(direct)) {
    const table = direct as Record<string, unknown>
    if (Array.isArray(table.timestamp)) return table as Record<string, unknown[]>
  }
  for (const value of Object.values(obj)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const table = value as Record<string, unknown>
      if (Array.isArray(table.timestamp)) return table as Record<string, unknown[]>
    }
  }
  return null
}

function parseKlinePayload(payload: unknown, symbol: string): KlineData[] {
  if (!payload || typeof payload !== 'object') return []
  const root = payload as Record<string, unknown>
  const data = root.data
  if (Array.isArray(data)) return parseRowArray(data)
  if (Array.isArray(root.records)) return parseRowArray(root.records)
  const table = findTickFlowTable(data, symbol)
  return table ? parseTickFlowTable(table) : []
}

async function readTickFlowError(resp: Response): Promise<string> {
  const text = await resp.text().catch(() => '')
  try {
    const json = JSON.parse(text)
    return String(json?.error?.message || json?.message || json?.error || '').trim()
  } catch {
    return text.slice(0, 160).trim()
  }
}

function tickFlowUpgradeError(status: number, detail: string): Error {
  const reason = detail ? `：${detail}` : ''
  return new Error(`TickFlow 数据源返回 ${status}${reason}。可能是数据权限、额度或并发限制，请升级数据源后重试：${TICKFLOW_PURCHASE}`)
}

function normalizeReportDate(value: unknown): string | undefined {
  const raw = String(value || '').trim()
  if (!raw) return undefined
  if (/^\d{8}$/.test(raw)) return raw.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10)
  if (/^\d{13}$/.test(raw)) return new Date(Number(raw)).toISOString().slice(0, 10)
  return raw.slice(0, 10)
}

function finiteNumber(value: unknown): number | undefined {
  if (value == null || value === '') return undefined
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : undefined
}

function pickMetricValue(row: Record<string, unknown>, aliases: string[]): unknown {
  for (const alias of aliases) {
    if (Object.prototype.hasOwnProperty.call(row, alias)) return row[alias]
    const upper = alias.toUpperCase()
    if (Object.prototype.hasOwnProperty.call(row, upper)) return row[upper]
    const lower = alias.toLowerCase()
    if (Object.prototype.hasOwnProperty.call(row, lower)) return row[lower]
  }
  return undefined
}

function normalizeFinancialRecord(record: Record<string, unknown>, fallbackSymbol: string): FundamentalMetric | null {
  const metrics: FundamentalMetric = {
    symbol: String(pickMetricValue(record, ['symbol', 'ts_code', 'code']) || fallbackSymbol),
    period_end: normalizeReportDate(pickMetricValue(record, ['period_end', 'end_date', 'report_date'])),
    announce_date: normalizeReportDate(pickMetricValue(record, ['announce_date', 'ann_date'])),
    eps_basic: finiteNumber(pickMetricValue(record, ['eps_basic', 'eps', 'basic_eps'])),
    bps: finiteNumber(pickMetricValue(record, ['bps'])),
    ocfps: finiteNumber(pickMetricValue(record, ['ocfps', 'cfps'])),
    roe: finiteNumber(pickMetricValue(record, ['roe', 'roe_weighted'])),
    roe_diluted: finiteNumber(pickMetricValue(record, ['roe_diluted', 'roe_dt'])),
    revenue_yoy: finiteNumber(pickMetricValue(record, ['revenue_yoy', 'or_yoy'])),
    net_income_yoy: finiteNumber(pickMetricValue(record, ['net_income_yoy', 'netprofit_yoy'])),
    gross_margin: finiteNumber(pickMetricValue(record, ['gross_margin', 'grossprofit_margin'])),
    net_margin: finiteNumber(pickMetricValue(record, ['net_margin', 'netprofit_margin'])),
    debt_to_asset_ratio: finiteNumber(pickMetricValue(record, ['debt_to_asset_ratio', 'debt_to_assets', 'debt_ratio'])),
    operating_cash_to_revenue: finiteNumber(pickMetricValue(record, ['operating_cash_to_revenue', 'ocf_to_or'])),
    inventory_turnover: finiteNumber(pickMetricValue(record, ['inventory_turnover', 'inv_turn'])),
  }
  const hasNumbers = Object.entries(metrics).some(([key, value]) => key !== 'symbol' && key !== 'period_end' && key !== 'announce_date' && typeof value === 'number')
  return hasNumbers ? metrics : null
}

function firstFinancialObject(value: unknown): Record<string, unknown> | null {
  if (!value) return null
  if (Array.isArray(value)) return value.find((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object' && !Array.isArray(row)) ?? null
  if (typeof value === 'object') return value as Record<string, unknown>
  return null
}

function looksLikeFinancialRecord(row: Record<string, unknown>): boolean {
  return [
    'roe', 'ROE', 'roe_weighted', 'ROE_WEIGHTED',
    'net_income_yoy', 'NET_INCOME_YOY', 'netprofit_yoy',
    'gross_margin', 'GROSS_MARGIN', 'grossprofit_margin',
    'debt_to_asset_ratio', 'DEBT_TO_ASSET_RATIO', 'debt_to_assets',
  ].some((field) => Object.prototype.hasOwnProperty.call(row, field))
}

function findFinancialRecord(payload: unknown, symbol: string): Record<string, unknown> | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  const root = payload as Record<string, unknown>
  const data = root.data ?? root
  const direct = firstFinancialObject(data)
  if (direct && (Array.isArray(data) || looksLikeFinancialRecord(direct))) return direct
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const table = data as Record<string, unknown>
  const directBySymbol = firstFinancialObject(table[symbol])
  if (directBySymbol) return directBySymbol
  for (const value of Object.values(table)) {
    const row = firstFinancialObject(value)
    if (row) return row
  }
  return null
}

async function tusharePostWithFetch(fetcher: Fetcher, token: string, api_name: string, params: Record<string, string>, fields: string) {
  const resp = await fetcher('/api/llm-proxy/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Target-URL': 'https://api.tushare.pro' },
    body: JSON.stringify({ api_name, token, params, fields }),
  })
  if (!resp.ok) return null
  return (await resp.json()) as { data?: { fields?: string[]; items?: unknown[][] } }
}

async function tusharePost(token: string, api_name: string, params: Record<string, string>, fields: string) {
  return tusharePostWithFetch(globalThis.fetch, token, api_name, params, fields)
}

async function fetchFundamentalsViaTickFlow(fetcher: Fetcher, code: string, apiKey: string): Promise<FundamentalMetric | null> {
  const symbol = normalizeTickFlowSymbol(code)
  const params = new URLSearchParams({ symbols: symbol, latest: 'true' })
  const resp = await fetcher(`/api/llm-proxy/v1/financials/metrics?${params}`, {
    headers: { 'x-api-key': apiKey, 'X-Target-URL': 'https://api.tickflow.org' },
  })
  if (!resp.ok) throw tickFlowUpgradeError(resp.status, await readTickFlowError(resp))
  const record = findFinancialRecord(await resp.json(), symbol)
  return record ? normalizeFinancialRecord(record, symbol) : null
}

async function fetchFundamentalsViaTushare(fetcher: Fetcher, code: string, token: string): Promise<FundamentalMetric | null> {
  const tsCode = normalizeTushareCode(code)
  const fields = 'ts_code,end_date,ann_date,eps,bps,cfps,roe,roe_dt,or_yoy,netprofit_yoy,grossprofit_margin,netprofit_margin,debt_to_assets,ocf_to_or,inv_turn'
  const json = await tusharePostWithFetch(fetcher, token, 'fina_indicator', { ts_code: tsCode }, fields)
  const items = json?.data?.items
  const fieldNames = json?.data?.fields
  if (!Array.isArray(items) || !Array.isArray(fieldNames) || items.length === 0) return null
  const row = items[0]!
  const record = Object.fromEntries(fieldNames.map((field, index) => [field, row[index]]))
  return normalizeFinancialRecord(record, tsCode)
}

export async function fetchValueSnapshotWithFetch(fetcher: Fetcher, code: string, keys: { tickflow: string | null; tushare: string | null }): Promise<ValueSnapshot> {
  const symbol = isCnSymbol(code) ? normalizeTickFlowSymbol(code) : code.trim().toUpperCase()
  if (!isCnSymbol(code)) return { symbol, source: 'none', metrics: null, reason: 'unsupported-market' }
  if (!keys.tickflow && !keys.tushare) return { symbol, source: 'none', metrics: null, reason: 'missing-source' }

  if (keys.tickflow) {
    try {
      const metrics = await fetchFundamentalsViaTickFlow(fetcher, code, keys.tickflow)
      if (metrics) return { symbol, source: 'tickflow', metrics }
    } catch { /* fall back to Tushare */ }
  }
  if (keys.tushare) {
    try {
      const metrics = await fetchFundamentalsViaTushare(fetcher, code, keys.tushare)
      if (metrics) return { symbol, source: 'tushare', metrics }
    } catch { /* fall through */ }
  }
  return { symbol, source: 'none', metrics: null, reason: 'not-found' }
}

export async function fetchValueSnapshot(code: string, keys: { tickflow: string | null; tushare: string | null }): Promise<ValueSnapshot> {
  return fetchValueSnapshotWithFetch(globalThis.fetch, code, keys)
}

export async function fetchKlineViaTushare(code: string, token: string, startDate: string, endDate: string): Promise<KlineData[]> {
  const tsCode = normalizeTushareCode(code)
  const [dailyJson, adjJson] = await Promise.all([
    tusharePost(token, 'daily', { ts_code: tsCode, start_date: startDate, end_date: endDate }, 'trade_date,open,high,low,close,vol'),
    tusharePost(token, 'adj_factor', { ts_code: tsCode, start_date: startDate, end_date: endDate }, 'trade_date,adj_factor'),
  ])
  const items = dailyJson?.data?.items
  if (!Array.isArray(items) || items.length === 0) return []

  const adjItems = adjJson?.data?.items
  if (!Array.isArray(adjItems) || adjItems.length === 0) return []
  const adjMap = new Map<string, number>()
  let latestDate = ''
  for (const row of adjItems) {
    const dt = String(row[0])
    adjMap.set(dt, Number(row[1]))
    if (dt > latestDate) latestDate = dt
  }
  const latestFactor = adjMap.get(latestDate) || 1

  return items.map(row => {
    const dt = String(row[0] || '')
    const factor = adjMap.get(dt) || latestFactor
    const ratio = factor / latestFactor
    return {
      date: dt.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3'),
      open: Number(row[1] || 0) * ratio, high: Number(row[2] || 0) * ratio,
      low: Number(row[3] || 0) * ratio, close: Number(row[4] || 0) * ratio,
      volume: Number(row[5] || 0),
    }
  }).filter(d => d.date && d.close > 0)
}

export async function fetchKlineViaTickFlow(code: string, apiKey: string): Promise<KlineData[]> {
  const symbol = normalizeTickFlowSymbol(code)
  const params = new URLSearchParams({
    symbol, period: '1d', count: '320', adjust: 'forward',
  })
  let apiError: Error | null = null
  const resp = await fetch(`/api/llm-proxy/v1/klines?${params}`, {
    headers: { 'x-api-key': apiKey, 'X-Target-URL': 'https://api.tickflow.org' },
  })
  if (resp.ok) {
    const rows = parseKlinePayload(await resp.json(), symbol)
    if (rows.length) return rows.sort((a, b) => a.date.localeCompare(b.date)).slice(-320)
  } else {
    apiError = tickFlowUpgradeError(resp.status, await readTickFlowError(resp))
  }
  const batchParams = new URLSearchParams({ symbols: symbol, period: '1d', count: '320', adjust: 'forward' })
  const batchResp = await fetch(`/api/llm-proxy/v1/klines/batch?${batchParams}`, {
    headers: { 'x-api-key': apiKey, 'X-Target-URL': 'https://api.tickflow.org' },
  })
  if (!batchResp.ok) throw tickFlowUpgradeError(batchResp.status, await readTickFlowError(batchResp))
  const batchRows = parseKlinePayload(await batchResp.json(), symbol).sort((a, b) => a.date.localeCompare(b.date)).slice(-320)
  if (batchRows.length) return batchRows
  if (apiError) throw apiError
  return []
}


export async function getUserDataKeys(userId: string): Promise<{ tickflow: string | null; tushare: string | null }> {
  const { data } = await supabase
    .from('user_settings')
    .select('tickflow_api_key, tushare_token')
    .eq('user_id', userId)
    .single()
  return {
    tickflow: String(data?.tickflow_api_key || '').trim() || null,
    tushare: String(data?.tushare_token || '').trim() || null,
  }
}

export async function checkWhitelist(userId: string): Promise<boolean> {
  const { data } = await supabase
    .from('whitelist')
    .select('user_id')
    .eq('user_id', userId)
    .limit(1)
  return Array.isArray(data) && data.length > 0
}

export async function fetchKline(
  code: string,
  keys: { tickflow: string | null; tushare: string | null },
  _userId: string,
): Promise<KlineData[]> {
  const end = new Date(); end.setDate(end.getDate() - 1)
  const start = new Date(); start.setDate(start.getDate() - 500)
  const fmtCompact = (d: Date) => d.toISOString().slice(0, 10).replace(/-/g, '')
  const isCn = isCnSymbol(code)
  let tickflowError: Error | null = null

  if (keys.tickflow) {
    try { const r = await fetchKlineViaTickFlow(code, keys.tickflow); if (r.length) return r } catch (err) { tickflowError = err instanceof Error ? err : new Error(String(err)) }
  }
  if (isCn && keys.tushare) {
    if (tickflowError) console.warn(`[kline] TickFlow failed for ${code}, falling back to Tushare:`, tickflowError.message)
    try {
      const r = await fetchKlineViaTushare(code, keys.tushare, fmtCompact(start), fmtCompact(end))
      if (r.length) return r.sort((a, b) => a.date.localeCompare(b.date)).slice(-320)
    } catch { /* fallthrough */ }
  }
  if (tickflowError) throw tickflowError
  const suffixHint = isCn ? '' : '美股/港股请使用 TickFlow 标准代码（如 AAPL.US / 00700.HK）。'
  throw new Error(`无法获取K线数据。${suffixHint}请检查股票代码、TickFlow Key 或稍后重试：${TICKFLOW_PURCHASE}`)
}
