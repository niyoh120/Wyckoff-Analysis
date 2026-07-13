import { z } from 'zod'
import type { ValueSnapshot } from './agent-market'
import type { KlineDataQuality, KlineRow } from './chat-tools'

export const CONTEXT_EVIDENCE_SCHEMA = z.object({
  id: z.string(),
  kind: z.enum(['market_data', 'fundamental_data', 'strategy', 'portfolio', 'model']),
  source: z.string(),
  identifier: z.string(),
  asOf: z.string().nullable(),
  summary: z.string(),
})

export const ANALYSIS_CONTEXT_PACK_SCHEMA = z.object({
  version: z.literal('v1'),
  symbol: z.string(),
  name: z.string().nullable(),
  generatedAt: z.string(),
  dataQuality: z.object({
    source: z.enum(['tickflow', 'tushare', 'mixed', 'none']),
    latestTradingDate: z.string().nullable(),
    coverageStart: z.string().nullable(),
    coverageEnd: z.string().nullable(),
    requestedRows: z.number(),
    returnedRows: z.number(),
    isComplete: z.boolean(),
    fallbackUsed: z.boolean(),
  }),
  technical: z.object({
    rows: z.number(),
    latestClose: z.number().nullable(),
    changePct: z.number().nullable(),
    ma20: z.number().nullable(),
    ma50: z.number().nullable(),
    recentHigh: z.number().nullable(),
    recentLow: z.number().nullable(),
  }),
  value: z.object({
    source: z.string(),
    asOf: z.string().nullable(),
    metricsAvailable: z.boolean(),
  }),
  evidence: z.array(CONTEXT_EVIDENCE_SCHEMA),
})

export type ContextEvidence = z.infer<typeof CONTEXT_EVIDENCE_SCHEMA>
export type AnalysisContextPack = z.infer<typeof ANALYSIS_CONTEXT_PACK_SCHEMA>

export function buildStockAnalysisContextPack(args: {
  symbol: string
  name?: string | null
  kline: KlineRow[]
  dataQuality: KlineDataQuality
  valueSnapshot: ValueSnapshot
}): AnalysisContextPack {
  const { symbol, name = null, kline, dataQuality, valueSnapshot } = args
  const latest = kline.at(-1) || null
  const previous = kline.at(-2) || null
  const recent20 = kline.slice(-20)
  const average = (rows: KlineRow[]) => rows.length > 0 ? rows.reduce((sum, row) => sum + row.close, 0) / rows.length : null
  const valueAsOf = valueSnapshot.metrics?.period_end || valueSnapshot.metrics?.announce_date || null

  return {
    version: 'v1',
    symbol,
    name,
    generatedAt: new Date().toISOString(),
    dataQuality,
    technical: {
      rows: kline.length,
      latestClose: latest?.close ?? null,
      changePct: latest && previous && previous.close > 0 ? ((latest.close / previous.close) - 1) * 100 : null,
      ma20: average(kline.slice(-20)),
      ma50: average(kline.slice(-50)),
      recentHigh: recent20.length > 0 ? Math.max(...recent20.map((row) => row.high)) : null,
      recentLow: recent20.length > 0 ? Math.min(...recent20.map((row) => row.low)) : null,
    },
    value: {
      source: valueSnapshot.source,
      asOf: valueAsOf,
      metricsAvailable: Boolean(valueSnapshot.metrics),
    },
    evidence: [
      {
        id: `market_data:${symbol}:${dataQuality.latestTradingDate || 'unknown'}`,
        kind: 'market_data',
        source: dataQuality.source,
        identifier: symbol,
        asOf: dataQuality.latestTradingDate,
        summary: `日线K线 ${dataQuality.returnedRows}/${dataQuality.requestedRows} 根，覆盖 ${dataQuality.coverageStart || '未知'} 至 ${dataQuality.coverageEnd || '未知'}${dataQuality.fallbackUsed ? '，发生数据源回退' : ''}`,
      },
      {
        id: `fundamental_data:${symbol}:${valueAsOf || 'unknown'}`,
        kind: 'fundamental_data',
        source: valueSnapshot.source,
        identifier: symbol,
        asOf: valueAsOf,
        summary: valueSnapshot.metrics ? '已取得价值面指标，用于质量、风险和置信度校准' : '暂无可用价值面指标，结论只依据技术面和量价数据',
      },
    ],
  }
}

export function formatAnalysisContextPack(pack: AnalysisContextPack): string {
  return [
    `分析上下文包 ${pack.version}：${pack.symbol}${pack.name ? ` ${pack.name}` : ''}`,
    `行情依据：${pack.dataQuality.source}；最新交易日 ${pack.dataQuality.latestTradingDate || '未知'}；样本 ${pack.technical.rows} 根`,
    `技术摘要：最新收盘 ${formatNumber(pack.technical.latestClose)}；单日涨跌 ${formatPercent(pack.technical.changePct)}；MA20 ${formatNumber(pack.technical.ma20)}；MA50 ${formatNumber(pack.technical.ma50)}；近20日高低 ${formatNumber(pack.technical.recentHigh)} / ${formatNumber(pack.technical.recentLow)}`,
    `价值面：${pack.value.source}；报告期 ${pack.value.asOf || '未知'}；指标${pack.value.metricsAvailable ? '可用' : '不可用'}`,
    '证据：',
    ...pack.evidence.map((item) => `- ${item.kind} | ${item.source} | ${item.identifier} | ${item.asOf || '未知'} | ${item.summary}`),
  ].join('\n')
}

function formatNumber(value: number | null): string {
  return value == null ? '未知' : value.toFixed(2)
}

function formatPercent(value: number | null): string {
  return value == null ? '未知' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}
