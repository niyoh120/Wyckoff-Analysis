import type { FundamentalMetric, ValueSnapshot } from '@wyckoff/shared'
import { buildValuePrompt as _sharedBuildValuePrompt, formatPromptPercent, sourceLabel } from '@wyckoff/shared'

export { sourceLabel }
import type { TranslationKey } from './preferences'

export type ValueTone = 'good' | 'bad' | 'neutral'
export type ValueView = 'quality' | 'risk'

export interface ValueSignal {
  label: string
  tone: ValueTone
}

export interface ValueScore {
  label: string
  tone: ValueTone
  score: number
  strengths: ValueSignal[]
  risks: ValueSignal[]
}

export type Translate = (key: TranslationKey, vars?: Record<string, string | number | null | undefined>) => string

export function buildValueScore(metrics: FundamentalMetric | null, t?: Translate): ValueScore {
  const tr = (key: TranslationKey, fallback: string) => t ? t(key) : fallback
  if (!metrics) return { label: tr('analysis.valueNoSource', '暂无'), tone: 'neutral', score: -99, strengths: [], risks: [] }

  let score = 0
  const strengths: ValueSignal[] = []
  const risks: ValueSignal[] = []
  const addStrength = (condition: boolean, label: string, points = 1) => {
    if (condition) {
      strengths.push({ label, tone: 'good' })
      score += points
    }
  }
  const addRisk = (condition: boolean, label: string, points = 1) => {
    if (condition) {
      risks.push({ label, tone: 'bad' })
      score -= points
    }
  }

  addStrength((metrics.roe ?? -Infinity) >= 10, tr('analysis.valueSignalRoeStrong', 'ROE 较强'), 2)
  addRisk((metrics.roe ?? Infinity) < 0, tr('analysis.valueRiskRoeLoss', 'ROE 为负'), 2)
  addStrength((metrics.net_income_yoy ?? -Infinity) > 0, tr('analysis.valueSignalProfitGrowth', '净利润正增长'))
  addRisk((metrics.net_income_yoy ?? Infinity) < 0, tr('analysis.valueRiskProfitDrop', '净利润下滑'))
  addStrength((metrics.revenue_yoy ?? -Infinity) > 0, tr('analysis.valueSignalRevenueGrowth', '营收正增长'))
  addRisk((metrics.revenue_yoy ?? Infinity) < 0, tr('analysis.valueRiskRevenueDrop', '营收下滑'))
  addStrength((metrics.gross_margin ?? -Infinity) >= 30, tr('analysis.valueSignalGrossMargin', '毛利率较高'))
  addRisk((metrics.gross_margin ?? Infinity) < 15, tr('analysis.valueRiskGrossMarginLow', '毛利率偏低'))
  addStrength((metrics.debt_to_asset_ratio ?? Infinity) <= 55, tr('analysis.valueSignalLowDebt', '杠杆较低'))
  addRisk((metrics.debt_to_asset_ratio ?? -Infinity) >= 70, tr('analysis.valueRiskHighDebt', '资产负债率偏高'), 2)
  addStrength((metrics.operating_cash_to_revenue ?? -Infinity) >= 5, tr('analysis.valueSignalCashHealthy', '现金流匹配收入'))
  addRisk((metrics.operating_cash_to_revenue ?? Infinity) < 0, tr('analysis.valueRiskCashWeak', '经营现金流偏弱'))

  const tone: ValueTone = score >= 3 ? 'good' : score < 0 ? 'bad' : 'neutral'
  const label = tone === 'good'
    ? tr('analysis.valueScoreStrong', '稳健')
    : tone === 'bad'
      ? tr('analysis.valueScoreWeak', '承压')
      : tr('analysis.valueScoreNeutral', '中性')
  return { label, tone, score, strengths, risks }
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

export function buildValuePrompt(snapshot: ValueSnapshot): string {
  return _sharedBuildValuePrompt(snapshot)
}

export function buildValueDigest(snapshot: ValueSnapshot): string {
  const metrics = snapshot.metrics
  if (!metrics) return 'value: 暂无可用价值面指标'
  return [
    `valueSource=${sourceLabel(snapshot)} period=${metrics.period_end || metrics.announce_date || 'unknown'}`,
    `valueMetrics roe=${formatPromptPercent(metrics.roe)} netProfitYoY=${formatPromptPercent(metrics.net_income_yoy)} revenueYoY=${formatPromptPercent(metrics.revenue_yoy)} grossMargin=${formatPromptPercent(metrics.gross_margin)} netMargin=${formatPromptPercent(metrics.net_margin)} debtRatio=${formatPromptPercent(metrics.debt_to_asset_ratio)} cashToRevenue=${formatPromptPercent(metrics.operating_cash_to_revenue)}`,
  ].join('\n')
}
