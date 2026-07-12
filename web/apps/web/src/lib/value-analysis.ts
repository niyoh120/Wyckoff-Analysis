import type { FundamentalMetric, ValueScore, ValueSignal, ValueSnapshot, ValueTone } from '@wyckoff/shared'
import { formatPromptPercent, sourceLabel } from '@wyckoff/shared'

import type { TranslationKey } from './preferences'

export type ValueView = 'quality' | 'risk'

export type Translate = (key: TranslationKey, vars?: Record<string, string | number | null | undefined>) => string

function applyBaseRules(
  metrics: FundamentalMetric,
  addStrength: (code: string, condition: boolean, labelKey: TranslationKey, explanation: string, value?: number, threshold?: number, points?: number) => void,
  addRisk: (code: string, condition: boolean, labelKey: TranslationKey, explanation: string, value?: number, threshold?: number, points?: number) => void
) {
  // 1. ROE Rules
  const roe = metrics.roe
  if (roe !== undefined && roe !== null) {
    addStrength('ROE_STRONG', roe >= 10, 'analysis.valueSignalRoeStrong', 'ROE 较强', roe, 10, 2)
    addRisk('ROE_LOSS', roe < 0, 'analysis.valueRiskRoeLoss', 'ROE 为负', roe, 0, 2)
  }

  // 2. Net Income YoY
  const netIncomeYoY = metrics.net_income_yoy
  if (netIncomeYoY !== undefined && netIncomeYoY !== null) {
    addStrength('NET_INCOME_GROWTH', netIncomeYoY > 0, 'analysis.valueSignalProfitGrowth', '净利润正增长', netIncomeYoY, 0, 1)
    addRisk('NET_INCOME_DECLINE', netIncomeYoY < 0, 'analysis.valueRiskProfitDrop', '净利润下滑', netIncomeYoY, 0, 1)
  }

  // 3. Revenue YoY
  const revenueYoY = metrics.revenue_yoy
  if (revenueYoY !== undefined && revenueYoY !== null) {
    addStrength('REVENUE_GROWTH', revenueYoY > 0, 'analysis.valueSignalRevenueGrowth', '营收正增长', revenueYoY, 0, 1)
    addRisk('REVENUE_DECLINE', revenueYoY < 0, 'analysis.valueRiskRevenueDrop', '营收下滑', revenueYoY, 0, 1)
  }

  // 4. Gross Margin
  const grossMargin = metrics.gross_margin
  if (grossMargin !== undefined && grossMargin !== null) {
    addStrength('GROSS_MARGIN_HIGH', grossMargin >= 30, 'analysis.valueSignalGrossMargin', '毛利率较高', grossMargin, 30, 1)
    addRisk('GROSS_MARGIN_LOW', grossMargin < 15, 'analysis.valueRiskGrossMarginLow', '毛利率偏低', grossMargin, 15, 1)
  }

  // 5. Debt to Asset Ratio (Leverage)
  const debtRatio = metrics.debt_to_asset_ratio
  if (debtRatio !== undefined && debtRatio !== null) {
    addStrength('LOW_DEBT', debtRatio <= 55, 'analysis.valueSignalLowDebt', '杠杆较低', debtRatio, 55, 1)
    addRisk('HIGH_LEVERAGE', debtRatio >= 70, 'analysis.valueRiskHighDebt', '资产负债率偏高', debtRatio, 70, 2)
  }

  // 6. Cash Flow
  const cashToRev = metrics.operating_cash_to_revenue
  if (cashToRev !== undefined && cashToRev !== null) {
    addStrength('CASH_FLOW_MATCH', cashToRev >= 5, 'analysis.valueSignalCashHealthy', '现金流匹配收入', cashToRev, 5, 1)
    addRisk('CASH_FLOW_WEAK', cashToRev < 0, 'analysis.valueRiskCashWeak', '经营现金流偏弱', cashToRev, 0, 1)
  }
}

function applyCompoundRules(
  metrics: FundamentalMetric,
  addRisk: (code: string, condition: boolean, labelKey: TranslationKey, explanation: string, value?: number, threshold?: number, points?: number) => void
) {
  const roe = metrics.roe
  const netIncomeYoY = metrics.net_income_yoy
  const cashToRev = metrics.operating_cash_to_revenue

  if (netIncomeYoY !== undefined && netIncomeYoY !== null && cashToRev !== undefined && cashToRev !== null) {
    addRisk(
      'PROFIT_CASH_FLOW_DIVERGENCE',
      netIncomeYoY > 0 && cashToRev < 0,
      'analysis.valueRiskProfitCashFlowDivergence',
      '净利润增长但经营现金流负',
      netIncomeYoY,
      0,
      0
    )
  }

  if (roe !== undefined && roe !== null && roe > 0 && cashToRev !== undefined && cashToRev !== null) {
    addRisk(
      'WEAK_CASH_EARNINGS',
      cashToRev < 0,
      'analysis.valueRiskWeakCashEarnings',
      '利润现金含量偏弱',
      cashToRev,
      0,
      0
    )
  }
}

export function buildValueScore(metrics: FundamentalMetric | null, t?: Translate): ValueScore {
  const tr = (key: TranslationKey, fallback: string) => t ? t(key) : fallback
  if (!metrics) return { label: tr('analysis.valueNoSource', '暂无'), tone: 'neutral', score: -99, strengths: [], risks: [] }

  let score = 0
  const strengths: ValueSignal[] = []
  const risks: ValueSignal[] = []

  const addStrength = (code: string, condition: boolean, labelKey: TranslationKey, explanation: string, value?: number, threshold?: number, points = 1) => {
    if (!condition) return
    const label = tr(labelKey, explanation)
    strengths.push({ code, label, tone: 'good', value, threshold, explanation })
    score += points
  }

  const addRisk = (code: string, condition: boolean, labelKey: TranslationKey, explanation: string, value?: number, threshold?: number, points = 1) => {
    if (!condition) return
    const label = tr(labelKey, explanation)
    risks.push({ code, label, tone: 'bad', value, threshold, explanation })
    score -= points
  }

  applyBaseRules(metrics, addStrength, addRisk)
  applyCompoundRules(metrics, addRisk)

  const tone: ValueTone = score >= 3 ? 'good' : score < 0 ? 'bad' : 'neutral'
  const label = tone === 'good'
    ? tr('analysis.valueScoreStrong', '稳健')
    : tone === 'bad'
      ? tr('analysis.valueScoreWeak', '承压')
      : tr('analysis.valueScoreNeutral', '中性')
  return { label, tone, score, strengths, risks }
}

export function calculateInputSnapshotHash(
  symbol: string,
  klineData: { date: string }[],
  valueSnapshot: ValueSnapshot
): string {
  const start = klineData[0]?.date || ''
  const end = klineData[klineData.length - 1]?.date || ''
  const len = klineData.length
  const metricsJson = valueSnapshot.metrics ? JSON.stringify(valueSnapshot.metrics) : 'none'
  const source = valueSnapshot.source
  const raw = `${symbol}:${start}:${end}:${len}:${source}:${metricsJson}`

  let hash = 2166136261
  for (let i = 0; i < raw.length; i++) {
    hash = Math.imul(hash ^ raw.charCodeAt(i), 16777619)
  }
  return (hash >>> 0).toString(16)
}


export function valueUnavailableText(reason: ValueSnapshot['reason'], t: Translate): string {
  if (reason === 'unsupported-market') return t('analysis.valueUnsupported')
  if (reason === 'missing-source') return t('analysis.valueMissingSource')
  return t('analysis.valueUnavailable')
}

export function formatValuePercent(value: number | undefined): string {
  if (!Number.isFinite(value)) return '--'
  const numeric = value as number
  const digits = Math.abs(numeric) >= 100 ? 1 : 2
  return `${numeric.toFixed(digits)}%`
}

export function numberTone(value: number | undefined, goodAt: number, badBelow: number): ValueTone {
  if (!Number.isFinite(value)) return 'neutral'
  const numeric = value as number
  if (numeric >= goodAt) return 'good'
  if (numeric < badBelow) return 'bad'
  return 'neutral'
}

export function reverseNumberTone(value: number | undefined, goodAtOrBelow: number, badAtOrAbove: number): ValueTone {
  if (!Number.isFinite(value)) return 'neutral'
  const numeric = value as number
  if (numeric <= goodAtOrBelow) return 'good'
  if (numeric >= badAtOrAbove) return 'bad'
  return 'neutral'
}

export function metricToneClass(tone: ValueTone): string {
  if (tone === 'good') return 'text-down'
  if (tone === 'bad') return 'text-up'
  return 'text-foreground'
}

export function valueScoreClass(tone: ValueTone): string {
  if (tone === 'good') return 'bg-down/10 text-down'
  if (tone === 'bad') return 'bg-up/10 text-up'
  return 'bg-muted text-muted-foreground'
}

export function signalClass(tone: ValueTone): string {
  if (tone === 'good') return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
  if (tone === 'bad') return 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200'
  return 'border-border text-muted-foreground'
}

export function buildValueDigest(snapshot: ValueSnapshot): string {
  const metrics = snapshot.metrics
  if (!metrics) return 'value: 暂无可用价值面指标'
  return [
    `valueSource=${sourceLabel(snapshot)} period=${metrics.period_end || metrics.announce_date || 'unknown'}`,
    `valueMetrics roe=${formatPromptPercent(metrics.roe)} netProfitYoY=${formatPromptPercent(metrics.net_income_yoy)} revenueYoY=${formatPromptPercent(metrics.revenue_yoy)} grossMargin=${formatPromptPercent(metrics.gross_margin)} netMargin=${formatPromptPercent(metrics.net_margin)} debtRatio=${formatPromptPercent(metrics.debt_to_asset_ratio)} cashToRevenue=${formatPromptPercent(metrics.operating_cash_to_revenue)}`,
  ].join('\n')
}
